"""관측 자료로 구간별 노면온도·결빙관련 확률을 추정합니다. 노트북의 계산을 시간창 하나에 적용하도록 옮겼습니다.

옮겨 온 곳
    02-1  clean_rwis, clean_aws, clean_asos, mask_stuck, hourly_to_10min
    02-2  idw_weights, idw_apply, interpolate_field, sun_position, terrain_shading, rolling_features, build_point_features
    03-2  smooth_weather, ema, surface_inputs, base_map, fingerprint, sk_weights, krige (B3)
    05-1  predict_members, predict_icing     05-2  icing_condition

저장된 모델·계수만 쓰며 다시 학습하지 않습니다. 노트북과 같은 값이 나오는지는 test_realtime.py의 재생 검사로 확인합니다.
노트북과 다른 점: 입력에 결측이 있어도 B3의 지수 이동평균이 끝까지 NaN이 되지 않도록 평균 전에 앞뒤 값으로 채웁니다.
"""

import json
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.signal import lfilter
from scipy.spatial.distance import cdist

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
MODEL_DIR = BASE.parent / "model"

ICE_STATE = 4
SNOW_STATE = 3
VALID_STATES = [1, 2, 3, 4, 10, 11, 12, 13, 14, 15]
WET_STATES = [2, 3, 4, 11, 12, 13, 14, 15]
STUCK_STEPS = 36  # 6시간
LAPSE = {"ta": 0.0065, "tg": 0.0065, "td": 0.002}
N_AZ = 36
SIGMA_SB = 5.670374419e-8
AWS_VARS = ["ta", "td", "rh", "ws", "rain", "pr60", "pr12h", "pr_day"]
ASOS_VARS = ["cloud", "tg", "snow", "sunshine"]
LOOKBACK_HOURS = 78  # 강수 후 경과시간 상한 72시간 + 여유


# ----- 정제 (02-1) -----

def clip_range(df, ranges):
    for col, (lo, hi) in ranges.items():
        df[col] = df[col].where(df[col].between(lo, hi))
    return df


def mask_stuck(df, col, cols_to_mask, steps=STUCK_STEPS):
    """같은 값이 6시간 이상 이어지면 센서 고착으로 보고 결측으로 바꾼다."""
    same = df[col].eq(df.groupby("stn")[col].shift()) & df[col].notna()
    run_len = df.groupby((~same).cumsum())[col].transform("size")
    df.loc[run_len >= steps, cols_to_mask] = np.nan
    return df


def clean_rwis(df):
    """df: stn, time, state, rst, ta, rh, ws, pr_day, vis (이름만 맞춘 원본)."""
    df = df.replace(-999, np.nan).copy()
    df["state"] = df["state"].where(df["state"].isin(VALID_STATES))
    df = clip_range(df, {"rst": (-30, 60), "ta": (-30, 40), "rh": (1, 100), "ws": (0, 60), "pr_day": (0, 300), "vis": (1, 50000)})
    df = df.drop_duplicates(["stn", "time"]).sort_values(["stn", "time"]).reset_index(drop=True)
    return mask_stuck(df, "rst", ["rst", "state"])


def clean_aws(df):
    df = df.copy()
    df[AWS_VARS] = df[AWS_VARS].mask(df[AWS_VARS] <= -99)
    df = clip_range(df, {"ta": (-35, 40), "td": (-50, 35), "rh": (1, 100), "ws": (0, 60), "rain": (0, 1),
                         "pr60": (0, 200), "pr12h": (0, 500), "pr_day": (0, 500)})
    return df[["stn", "time", *AWS_VARS]].drop_duplicates(["stn", "time"])


def clean_asos(df):
    df = df.copy()
    df[["snow", "sunshine"]] = df[["snow", "sunshine"]].fillna(0)  # 빈칸 = 현상 없음
    df = clip_range(df, {"cloud": (0, 10), "tg": (-30, 60), "snow": (0, 200), "sunshine": (0, 1)})
    return df[["stn", "time", *ASOS_VARS]].drop_duplicates(["stn", "time"])


def to_wide(df, col, stns, times):
    return df.pivot(index="time", columns="stn", values=col).reindex(index=times, columns=stns).to_numpy(dtype="float32").T


def hourly_to_10min(df, col, stns, times):
    wide = df.pivot(index="time", columns="stn", values=col).reindex(columns=stns)
    wide = wide.reindex(wide.index.union(times)).loc[times]
    wide = wide.interpolate(limit=5, limit_area="inside").ffill(limit=5)
    return wide.to_numpy(dtype="float32").T


# ----- 공간 보간 (02-2) -----

def idw_weights(tgt_xy, src_xy, k=4, power=2):
    d = cdist(tgt_xy, src_xy)
    w = np.zeros_like(d)
    nearest = np.argsort(d, axis=1)[:, :k]
    rows = np.arange(len(d))[:, None]
    w[rows, nearest] = 1.0 / np.maximum(d[rows, nearest], 50.0) ** power
    return w.astype("float32")


def idw_apply(w, values):
    ok = ~np.isnan(values)
    num = w @ np.where(ok, values, 0)
    den = w @ ok.astype("float32")
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan).astype("float32")


def interpolate_field(w, values, var, src_elev, tgt_elev):
    lapse = LAPSE.get(var)
    if lapse is None:
        return idw_apply(w, values)
    sea_level = values + lapse * src_elev[:, None]
    return idw_apply(w, sea_level) - lapse * tgt_elev[:, None]


# ----- 태양·지형 그늘 (02-2) -----

def sun_position(times, lat, lon):
    doy = times.dayofyear.to_numpy()
    hour = (times.hour + times.minute / 60).to_numpy()
    g = 2 * np.pi / 365 * (doy - 1 + (hour - 12) / 24)
    decl = (0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g) - 0.006758 * np.cos(2 * g)
            + 0.000907 * np.sin(2 * g) - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g))
    eqtime = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g)
                       - 0.014615 * np.cos(2 * g) - 0.040849 * np.sin(2 * g))
    tst = hour * 60 + eqtime + 4 * np.asarray(lon)[:, None] - 60 * 9
    ha = np.radians(tst / 4 - 180)
    lat = np.radians(np.asarray(lat))[:, None]
    cos_z = np.sin(lat) * np.sin(decl) + np.cos(lat) * np.cos(decl) * np.cos(ha)
    elev = 90 - np.degrees(np.arccos(np.clip(cos_z, -1, 1)))
    azim = (np.degrees(np.arctan2(np.sin(ha), np.cos(ha) * np.sin(lat) - np.tan(decl) * np.cos(lat))) + 180) % 360
    return elev.astype("float32"), azim.astype("float32")


def terrain_shading(times, lat, lon, horizon):
    sun_elev, sun_az = sun_position(times, lat, lon)
    az_bin = np.round(sun_az / (360 / N_AZ)).astype(int) % N_AZ
    hz = np.take_along_axis(horizon, az_bin, axis=1)
    return sun_elev, (sun_elev > np.maximum(hz, 0)).astype("float32")


def rolling_features(ta, rh, rain):
    f = lambda a: pd.DataFrame(a.T)  # noqa: E731
    out = {"ta_d3h": f(ta).diff(18), "ta_min12h": f(ta).rolling(72, min_periods=36).min(),
           "rh_mean3h": f(rh).rolling(18, min_periods=9).mean(), "rain_hrs12h": f(rain).rolling(72, min_periods=36).sum() / 6}
    d = f(rain)
    step = np.arange(len(d), dtype="float32")[:, None]
    last = pd.DataFrame(np.where(d.to_numpy() >= 0.5, step, np.nan)).ffill().to_numpy()
    out["hrs_since_rain"] = pd.DataFrame(np.minimum((step - last) / 6, 72.0)).fillna(72.0)
    return {k: v.to_numpy(dtype="float32").T for k, v in out.items()}


class Engine:
    def __init__(self, static_path=HERE / "static" / "inputs.npz", model_dir=MODEL_DIR, bundle_dir=BASE / "bundle"):
        if not Path(static_path).exists():
            raise FileNotFoundError(f"{static_path}이 없습니다. 먼저 realtime/build_static.py를 실행하세요.")
        z = np.load(static_path)
        self.s = {k: z[k] for k in z.files}
        read = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))  # noqa: E731
        self.est_meta, self.cls_meta = read(model_dir / "road_temp_meta.json"), read(model_dir / "icing_meta.json")
        self.b3 = read(model_dir / "road_temp_b3.json")
        cond = read(Path(bundle_dir) / "criteria.json")["icing_condition"]
        self.t_rst, self.t_rh = cond["T_RST"], cond["T_RH"]
        self.booster = lgb.Booster(model_file=str(model_dir / "road_temp_lgbm.txt"))
        self.ridge = joblib.load(model_dir / "road_temp_ridge.joblib")
        self.icing = lgb.Booster(model_file=str(model_dir / self.cls_meta["model_file"]))
        keep = ~np.isin(self.s["aws_stn"], self.b3["air_temperature"]["aws_exclude"])  # B3는 설천봉·섬 AWS를 뺀다
        self.b3_keep, self.b3_xy, self.b3_elev = keep, self.s["aws_xy"][keep], self.s["aws_elev"][keep]
        self.beta = np.array(list(self.b3["beta"].values()))
        self.coef = np.array([self.b3["fingerprint_a0_aR_aS"][str(s)] for s in self.s["src_stn"]])
        self.vg = self.b3["variogram"]
        self.a_s, self.b_s = self.b3["angstrom_prescott"]
        self.lapse_b = self.b3["air_temperature"]["lapse_per_m"]

    # ----- B3 (03-2) -----
    def smooth_weather(self, tgt_xy, tgt_elev, aws, idx=slice(None)):
        w = idw_weights(tgt_xy, self.b3_xy, k=len(self.b3_xy), power=1).astype(float)
        out = {}
        for v, lapse in self.lapse_b.items():
            vals = aws[v][self.b3_keep][:, idx].astype(float)
            a = idw_apply(w, vals + lapse * self.b3_elev[:, None]).astype(float) - lapse * tgt_elev[:, None]
            out[v] = pd.DataFrame(a.T).ffill().bfill().to_numpy().T
        return out

    def ema(self, a, step_h):
        a = pd.DataFrame(a.T).ffill().bfill().to_numpy().T  # 입력 결측이 평균 전체를 NaN으로 만들지 않게 한다
        alpha = 1 - np.exp(-step_h / self.b3["tau_h"])
        return lfilter([alpha], [1, alpha - 1], a, axis=1, zi=(1 - alpha) * a[:, :1])[0]

    def surface_inputs(self, w, cloud, sunshine, sun_elev, sunlit, step_h):
        ta, td, u = w["ta"], w["td"], w["ws"]
        n = np.clip(cloud / 10, 0, 1)
        s_eff = np.sin(np.radians(np.clip(sun_elev, 0, None))) * (self.a_s + self.b_s * sunshine * sunlit)
        e = 6.112 * np.exp(17.62 * td / (243.12 + td))
        tak = ta + 273.15
        eps_clr = 1.24 * (e / tak) ** (1 / 7)
        l_net = -(1 - n) * (1 - eps_clr) * SIGMA_SB * tak ** 4
        night = sun_elev <= 0
        R = night * (1 - n) * np.clip(1 - u / 5, 0, 1)
        S = s_eff / self.b3["s_max"]
        regime = np.select([night & (R > 0.5), night, S > 0.5], [0, 1, 2], 3)
        return {"ta": ta, "u": u, "s_eff": s_eff, "l_net": l_net, "m_s": self.ema(s_eff, step_h), "m_l": self.ema(l_net, step_h),
                "R": R, "S": S, "regime": regime}

    def base_map(self, inp):
        reg = inp["regime"].ravel()
        X = np.column_stack([(reg == k).astype(float) for k in range(4)] + [inp[c].ravel() for c in ["s_eff", "l_net", "m_s", "m_l"]])
        x = X @ self.beta / (1 + self.b3["beta_u"] * inp["u"].ravel())
        return inp["ta"] + x.reshape(inp["ta"].shape)

    def krige(self, E, src_xy, tgt_xy):
        sigma2, nugget, L = self.vg["sigma2"], self.vg["nugget"], self.vg["L"]
        K = sigma2 * np.exp(-cdist(src_xy, src_xy) / 1000 / L) + nugget * np.eye(len(src_xy))
        c = sigma2 * np.exp(-cdist(tgt_xy, src_xy) / 1000 / L)
        avail = ~np.isnan(E)
        out, E0 = np.empty((len(tgt_xy), E.shape[1])), np.nan_to_num(E)
        _, first, inv = np.unique(avail.T, axis=0, return_index=True, return_inverse=True)
        inv = inv.ravel()
        for p, t0 in enumerate(first):
            cols, idx = inv == p, np.flatnonzero(avail[:, t0])
            W = np.zeros_like(c)
            if len(idx):
                W[:, idx] = np.linalg.solve(K[np.ix_(idx, idx)], c[:, idx].T).T
            out[:, cols] = W @ E0[:, cols]
        return out

    # ----- 추정 -----
    def run(self, rwis, aws, asos, targets):
        """정제된 긴 형식 자료로 targets(정시 목록)의 구간별 값을 구한다. 자료는 마지막 target까지만 있어야 한다."""
        s = self.s
        targets = pd.DatetimeIndex(targets)
        times = pd.date_range(targets.min() - pd.Timedelta(hours=LOOKBACK_HOURS), targets.max(), freq="10min")
        t_idx = times.get_indexer(targets)
        AWS = {v: to_wide(aws, v, s["aws_stn"], times) for v in AWS_VARS}
        ASOS = {v: hourly_to_10min(asos, v, s["asos_stn"], times) for v in ASOS_VARS}
        state = to_wide(rwis, "state", s["src_stn"], times)
        src = {"rst": to_wide(rwis, "rst", s["src_stn"], times),
               "ice": np.where(np.isnan(state), np.nan, state == ICE_STATE).astype("float32"),
               "wet": np.where(np.isnan(state), np.nan, np.isin(state, WET_STATES)).astype("float32"),
               "snow": np.where(np.isnan(state), np.nan, state == SNOW_STATE).astype("float32")}
        w_src = idw_weights(s["src_xy"], s["aws_xy"])
        src_ta = interpolate_field(w_src, AWS["ta"], "ta", s["aws_elev"], s["src_elev"])
        src["anom"] = src["rst"] - src_ta

        # 구간 변수 (build_point_features)
        p_xy, p_elev = s["seg_xy"], s["seg_elev"]
        f = {}
        w = idw_weights(p_xy, s["aws_xy"])
        for v in AWS_VARS:
            f[v] = interpolate_field(w, AWS[v], v, s["aws_elev"], p_elev)
        w = idw_weights(p_xy, s["asos_xy"], k=3)
        for v in ASOS_VARS:
            f[v] = interpolate_field(w, ASOS[v], v, s["asos_elev"], p_elev)
        f.update(rolling_features(f["ta"], f["rh"], f["rain"]))
        w = idw_weights(p_xy, s["src_xy"], k=3)
        f["nbr_rst"] = interpolate_field(w, src["rst"], "ta", s["src_elev"], p_elev)
        f["rst_phys"] = f["ta"] + idw_apply(w, src["anom"])
        for v in ["ice", "wet", "snow"]:
            f[f"nbr_{v}"] = idw_apply(w, src[v])
        f["nbr_ice_3h"] = pd.DataFrame(f["nbr_ice"].T).rolling(18, min_periods=1).max().to_numpy("float32").T
        f["sun_elev"], f["sunlit"] = terrain_shading(times, s["seg_lat"], s["seg_lon"], s["seg_horizon"])
        f["solar_eff"] = f["sunshine"] * np.sin(np.radians(np.clip(f["sun_elev"], 0, None))) * f["sunlit"]

        n_p, n_t = len(p_xy), len(targets)
        df = pd.DataFrame({"seg_id": np.repeat(s["seg_id"], n_t), "time": np.tile(targets, n_p)})
        for k, v in f.items():
            df[k] = v[:, t_idx].ravel()
        hour = df["time"].dt.hour + df["time"].dt.minute / 60
        df["hour_sin"] = np.sin(2 * np.pi * hour / 24).astype("float32")
        df["hour_cos"] = np.cos(2 * np.pi * hour / 24).astype("float32")
        year = df["time"].dt.year.where(df["time"].dt.month >= 11, df["time"].dt.year - 1)
        df["season_day"] = (df["time"] - pd.to_datetime(year.astype(str) + "-11-01")).dt.days.astype("int16")

        # B3: 원천은 10분, 구간은 1시간 간격 (03-2의 3-6-7과 같음)
        s_cloud, s_sun = self.station_field(ASOS["cloud"], "cloud"), self.station_field(ASOS["sunshine"], "sunshine")
        s_elev_sun, s_lit = terrain_shading(times, s["src_lat"], s["src_lon"], s["src_horizon"])
        src_inp = self.surface_inputs(self.smooth_weather(s["src_xy"], s["src_elev"], AWS), s_cloud.astype(float), s_sun.astype(float),
                                      s_elev_sun.astype(float), s_lit.astype(float), 1 / 6)
        coef = self.coef
        finger = coef[:, [0]] + coef[:, [1]] * src_inp["R"] + coef[:, [2]] * src_inp["S"]
        E = src["rst"].astype(float) - self.base_map(src_inp) - finger
        hours = np.flatnonzero(times.minute == 0)
        seg_inp = self.surface_inputs(self.smooth_weather(p_xy, p_elev, AWS, hours), f["cloud"][:, hours].astype(float), f["sunshine"][:, hours].astype(float),
                                      f["sun_elev"][:, hours].astype(float), f["sunlit"][:, hours].astype(float), 1.0)
        b3_all = self.base_map(seg_inp) + self.krige(E[:, hours], s["src_xy"], p_xy)
        df["b3"] = b3_all[:, np.searchsorted(hours, t_idx)].ravel()

        feats = self.est_meta["features"]
        members = pd.DataFrame({"LightGBM(핵심)": self.booster.predict(df[feats]), "Ridge(핵심)": self.ridge.predict(df[feats]),
                                "B1 주변 노면온도": df["nbr_rst"].to_numpy(), self.est_meta["b3"]: df["b3"].to_numpy()}, index=df.index)
        df["rst_est"] = members[self.est_meta["ensemble"]].mean(axis=1).astype("float32")
        df["rst_dpd"] = df["rst_est"] - df["td"]
        df["p_icing"] = self.icing.predict(df[self.cls_meta["features"]]).astype("float32")
        moist = (df["rain_hrs12h"] > 0) | (df["snow"] > 0) | (df["rst_dpd"] <= 0)
        df["condition"] = (df["rst_est"] <= self.t_rst) & (df["rh"] >= self.t_rh) & moist
        df["prediction"] = df["p_icing"] >= self.cls_meta["threshold"]
        used = {"rwis_sources": int(np.isfinite(src["rst"][:, t_idx[-1]]).sum()), "aws": int(np.isfinite(AWS["ta"][:, t_idx[-1]]).sum()),
                "asos": int(np.isfinite(ASOS["cloud"][:, t_idx[-1]]).sum())}
        return df, used

    def station_field(self, values, var):
        """학습 지점 위치의 ASOS 보간 값 (운량·일조는 고도 보정 없음)."""
        w = idw_weights(self.s["src_xy"], self.s["asos_xy"], k=3)
        return interpolate_field(w, values, var, self.s["asos_elev"], self.s["src_elev"])
