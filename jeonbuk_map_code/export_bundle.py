"""프로젝트 분석 결과(노트북 02~05)를 지도·API용 묶음(bundle/)으로 내보냅니다.

실행: 프로젝트 conda 환경(haksik)에서 노트북 05-2까지 실행한 뒤
    python jeonbuk_map_code/export_bundle.py

이 단계만 pandas·geopandas가 필요합니다. 묶음을 읽는 build_risk_map.py와 service/는 Python 기본 기능만 씁니다.

출력 (jeonbuk_map_code/bundle/)
    segments.geojson    233개 구간 선(WGS84), 위험 등급·요인 점수·하위 지표·노선 위치(km)
    facilities.geojson  위험도(R1·R2)에 쓴 고속도로 교량·터널 구간 (국토부 경계와 구간 선이 겹치는 부분)
    stations.json       RWIS 17곳 위치·종류·연결 구간·검증 지점 여부
    criteria.json       위험도 기준표(05-2), 등급 의미, 결빙 가능 조건(05-1)
    hourly_*.gz         구간 x 시각(1시간) 추정 노면온도·결빙관련 확률·상태 코드
    station_*.gz        RWIS 정시 관측 노면온도·노면상태 (검증 표시용)
    meta.json           기간·배열 형식·모델과 검증 성능 요약·주요 사례일·원천 파일
"""

import argparse
import gzip
import json
import sys
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from scipy.stats import spearmanr

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402

GRADES = ["관심", "주의", "경계", "심각"]
# 05-2의 grade_table과 같은 등급 의미
GRADE_MEANING = {"관심": "평상시 관리", "주의": "결빙 가능 기상 시 순찰 강화", "경계": "사전 제설·제빙 우선 구간",
                 "심각": "상시 감시·사전 살포 최우선 구간"}
GRADE_RANGE = {"관심": "1.00~1.75", "주의": "1.75~2.50", "경계": "2.50~3.25", "심각": "3.25~4.00"}
WEIGHTS = {"기상": 0.5, "도로": 0.25, "지형": 0.25}  # 05-2의 WEIGHTS

# 시각별 상태 코드 (hourly_state): 결빙 가능 조건(05-1)과 04 모델 예측(확률 ≥ 임계값)의 조합
STATE_CODES = {0: "조건 미충족", 1: "결빙 가능 조건", 2: "모델 예측만", 3: "결빙 가능 조건 + 모델 예측"}
MISSING_I16, MISSING_U8 = -32768, 255
P_SCALE = 200  # 결빙관련 확률을 0~200 정수로 저장 (0.005 단위)


def dumps(obj, indent=None):
    """NaN이 섞이면 표준 JSON이 아니므로 바로 오류를 낸다."""
    return json.dumps(obj, ensure_ascii=False, allow_nan=False, indent=indent,
                      separators=None if indent else (",", ":"))


def write_gz(path, array):
    """배열을 리틀 엔디언 바이트로 gzip 저장한다. 시각이 바뀌어도 같은 결과가 나오게 mtime을 0으로 둔다."""
    raw = np.ascontiguousarray(array).astype(array.dtype.newbyteorder("<")).tobytes()
    with open(path, "wb") as f:
        f.write(gzip.compress(raw, compresslevel=9, mtime=0))
    return {"file": path.name, "dtype": array.dtype.str.replace(">", "<").replace("=", "<"),
            "shape": list(array.shape), "bytes_gz": path.stat().st_size}


def quantize(values, scale, missing, dtype):
    out = np.round(np.asarray(values, dtype="float64") * scale)
    return np.where(np.isfinite(out), out, missing).astype(dtype)


def line_coords(geom, ndigits=5):
    if geom.geom_type == "LineString":
        return [[round(x, ndigits), round(y, ndigits)] for x, y in geom.coords]
    return [[[round(x, ndigits), round(y, ndigits)] for x, y in part.coords] for part in geom.geoms]


def route_positions(segments):
    """노선별 seg_id 순서로 누적 거리(km)를 매긴다. 구간 사이 빈틈(IC 부근 등)도 거리에 넣는다."""
    pos = {}
    for _, g in segments.sort_values("seg_id").groupby("route"):
        km, prev = 0.0, None
        for sid, geom in zip(g["seg_id"], g.geometry):
            if prev is not None:
                ends_a = [shapely.Point(prev.coords[0]), shapely.Point(prev.coords[-1])]
                ends_b = [shapely.Point(geom.coords[0]), shapely.Point(geom.coords[-1])]
                km += min(p.distance(q) for p in ends_a for q in ends_b) / 1000
            pos[sid] = (round(km, 3), round(km + geom.length / 1000, 3))
            km += geom.length / 1000
            prev = geom
    return pos


def sigungu_of(points_ll, geo_path):
    """구간 중간점이 속한 시군구 (2013 경계). 경계 밖이면 가장 가까운 전북 시군구."""
    geo = gpd.read_file(geo_path)
    jb = geo[geo["code"].astype(str).str.startswith("35")].to_crs(5179)
    jb["name"] = jb["name"].replace({"전주시완산구": "전주시", "전주시덕진구": "전주시"})
    pts = points_ll.to_crs(5179)
    idx, _ = jb.sindex.nearest(pts.geometry, return_distance=True, return_all=False)
    return jb["name"].to_numpy()[idx[1]]


def highway_facilities(segments):
    """02-2와 같은 방법으로 고속도로 교량·터널 polygon을 고르고, 구간 선과 겹치는 부분을 선으로 돌려준다."""
    centerline = gpd.read_file(config.RAW_DIR / config.RAW_FILES["centerline"])
    zip_root = f"/vsizip/{config.RAW_DIR / config.RAW_FILES['boundary']}/국토교통부 도로, 교량, 터널, 하천 경계 데이터"
    bbox = tuple(centerline.buffer(5000).total_bounds)

    def read_boundary(path):
        return pyogrio.read_dataframe(f"{zip_root}/{path}", bbox=bbox).to_crs(5179)

    def on_highway(layer, min_ratio):  # 02-2의 on_highway와 같음
        road_buf = gpd.GeoDataFrame(geometry=centerline.buffer(10), crs=5179)
        hit = layer.loc[gpd.sjoin(layer, road_buf, predicate="intersects").index.unique()].copy()
        inside = hit.intersection(centerline.union_all()).length
        keep = inside >= min_ratio * hit["LENG"].where(hit["LENG"] > 0, 40)
        return hit[keep].reset_index(drop=True)

    bridges = on_highway(read_boundary("N3A_A0070000(교량)_국토부_디지털트윈국토/N3A_A0070000.shp"), 0.5)
    tunnels = on_highway(read_boundary("N3A_A0110020(터널)_국토부_디지털트윈국토/N3A_A0110020.shp"), 0.3)
    seg_lines = segments.geometry.union_all()
    rows = []
    for kind, layer, buf in [("bridge", bridges, 5), ("tunnel", tunnels, 0)]:
        for _, r in layer.iterrows():
            piece = seg_lines.intersection(r.geometry.buffer(buf) if buf else r.geometry)
            if piece.geom_type == "GeometryCollection":  # 경계에 닿는 점 등은 버리고 선만 남긴다
                lines = [g for g in piece.geoms if g.geom_type in ("LineString", "MultiLineString")]
                piece = shapely.union_all(lines) if lines else shapely.LineString()
            if piece.geom_type == "MultiLineString":
                piece = shapely.line_merge(piece)
            if piece.is_empty or piece.length < 1 or piece.geom_type not in ("LineString", "MultiLineString"):
                continue
            name = r.get("NAME")
            rows.append({"kind": kind, "name": name if isinstance(name, str) and name.strip() else None,
                         "length_m": round(float(piece.length), 1), "geometry": piece})
    return gpd.GeoDataFrame(rows, crs=5179), len(bridges), len(tunnels)


def icing_state(est, feat, t_rst, t_rh, threshold):
    """05-2의 icing_condition(결빙 가능 조건)과 04 모델 예측을 상태 코드(0~3)로 합친다."""
    moist = (feat["rain_hrs12h"] > 0) | (feat["snow"] > 0) | ((est["rst_est"] - feat["td"]) <= 0)
    cond = (est["rst_est"] <= t_rst) & (feat["rh"] >= t_rh) & moist
    pred = est["p_icing"] >= threshold
    state = cond.astype("uint8") + 2 * pred.astype("uint8")
    return state.where(est["rst_est"].notna() & est["p_icing"].notna(), MISSING_U8).astype("uint8")


def event_days(times, seg_state, n_seg, stn_state, label_states):
    """구간 예측·조건과 RWIS 관측이 많은 날을 고른다 (사례 재생용)."""
    days = pd.DatetimeIndex(times).normalize()
    st = seg_state.reshape(len(times), n_seg)
    pred = (st == 2) | (st == 3)
    cond = (st == 1) | (st == 3)
    df = pd.DataFrame({"day": days, "cond_seghours": cond.sum(axis=1), "pred_seghours": pred.sum(axis=1)})
    by = df.groupby("day").sum()
    by["seg_pred"] = pd.DataFrame(pred, index=days).groupby(level=0).any().sum(axis=1)
    obs = pd.DataFrame(np.isin(stn_state, label_states), index=days)
    ice = pd.DataFrame(stn_state == config.ICE_STATE_CODES[0], index=days)
    by["stn_related"] = obs.groupby(level=0).any().sum(axis=1)
    by["stn_ice"] = ice.groupby(level=0).any().sum(axis=1)
    rank = by.sort_values(["seg_pred", "cond_seghours"], ascending=False)
    picks = list(rank.index[:6])
    second = rank[rank.index >= pd.Timestamp(config.PERIODS[1][0])]
    picks += [d for d in second.index[:2] if d not in picks]
    out = []
    for d in sorted(picks):
        r = by.loc[d]
        out.append({"date": d.strftime("%Y-%m-%d"), "segments_predicted": int(r["seg_pred"]),
                    "condition_segment_hours": int(r["cond_seghours"]), "stations_related_observed": int(r["stn_related"]),
                    "stations_ice_observed": int(r["stn_ice"])})
    return out


def performance_summary():
    est = pd.read_csv(config.RESULT_DIR / "estimation_scores.csv", encoding="utf-8-sig")
    est = est[est["방법"] == "앙상블+B3"]
    ice = pd.read_csv(config.RESULT_DIR / "icing_scores.csv", encoding="utf-8-sig")
    ice = ice[ice["방법"] == "LightGBM(결빙관련 라벨)"]
    rows_e = [{"stn": str(r["stn"]), "name": r["지점명"], "BIAS": r["BIAS"], "MAE": r["MAE"], "RMSE": r["RMSE"]}
              for _, r in est.iterrows()]
    rows_i = [{"stn": str(r["stn"]), "name": r["지점명"], "empty_days": r["빈날처리"], "days": r["평가일수"],
               "ice_days": r["결빙관측일수"], "false_alarm_days": r["오탐일수"], "F1": r["F1"],
               "Precision": r["Precision"], "Recall": r["Recall"]} for _, r in ice.iterrows()]
    return {"road_temperature": {"method": "앙상블+B3", "holdout": rows_e},
            "icing": {"method": "LightGBM(결빙관련 라벨)", "holdout": rows_i}}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=BASE / "bundle")
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    P, R = config.PROCESSED_DIR, config.RESULT_DIR

    # ----- 구간: 정적 위험도 -----
    segments = gpd.read_file(P / "segments.gpkg").sort_values("seg_id").reset_index(drop=True)
    risk = pd.read_csv(R / "segment_risk.csv", encoding="utf-8-sig").set_index("seg_id")
    assert set(risk.index) == set(segments["seg_id"]), "segment_risk.csv와 segments.gpkg의 구간이 다릅니다"
    seg_ids = segments["seg_id"].tolist()
    n_seg = len(seg_ids)
    pos = route_positions(segments)
    ll = segments.to_crs(4326)
    mid_ll = gpd.GeoDataFrame(geometry=gpd.points_from_xy(segments["lon"], segments["lat"]), crs=4326)
    sigungu = sigungu_of(mid_ll, BASE / "assets" / "municipalities.geojson")
    match = pd.read_csv(P / "station_segment_match.csv", encoding="utf-8-sig")
    seg_stations = match.groupby("seg_id")["stn"].apply(lambda s: [int(v) for v in s]).to_dict()

    features = []
    for i, sid in enumerate(seg_ids):
        r = risk.loc[sid]
        geom = ll.geometry.iloc[i].simplify(0.00001)
        props = {
            "seg_id": sid, "route": r["route"], "index": i, "km_from": pos[sid][0], "km_to": pos[sid][1],
            "length_m": float(r["length_m"]), "lon": round(float(r["lon"]), 5), "lat": round(float(r["lat"]), 5),
            "sigungu": str(sigungu[i]),
            "grade": r["등급"], "grade_lv": GRADES.index(r["등급"]) + 1,
            "score": round(float(r["총점"]), 3), "s_meteo": round(float(r["기상"]), 3),
            "s_road": round(float(r["도로"]), 3), "s_terrain": round(float(r["지형"]), 3),
            "levels": {k: int(r[k]) for k in ["M1", "M2", "R1", "R2", "T1", "T2", "T3"]},
            "values": {k: (None if pd.isna(r[k]) else round(float(r[k]), 3)) for k in [
                "icing_cond_hours", "icing_pred_hours", "bridge_ratio", "tunnel_ratio", "seg_dist_tunnel", "elev",
                "tpi", "shade_winter", "dist_river", "rst_mean", "rst_night_mean", "rst_le0_hours"]},
            "elev_max": round(float(segments.loc[i, "elev_max"]), 1),
            "stations": seg_stations.get(sid, []),
        }
        features.append({"type": "Feature", "properties": props,
                         "geometry": {"type": geom.geom_type, "coordinates": line_coords(geom)}})
    (out / "segments.geojson").write_text(dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")

    # ----- 교량·터널 구간 -----
    fac, n_bridge_poly, n_tunnel_poly = highway_facilities(segments)
    fac_ll = fac.to_crs(4326)
    fac_features = [{"type": "Feature",
                     "properties": {"kind": r["kind"], "name": r["name"] if isinstance(r["name"], str) else None,
                                    "length_m": float(r["length_m"])},
                     "geometry": {"type": r.geometry.geom_type, "coordinates": line_coords(r.geometry)}}
                    for _, r in fac_ll.iterrows()]
    (out / "facilities.geojson").write_text(dumps({"type": "FeatureCollection", "features": fac_features}), encoding="utf-8")

    # ----- RWIS 관측소 -----
    stations = pd.read_parquet(P / "stations.parquet")
    stations = stations.merge(match[["stn", "seg_id", "dist_m"]], on="stn", how="left").sort_values("stn")
    stn_ids = stations["stn"].astype(int).tolist()
    stn_rows = [{"stn": int(s["stn"]), "name": s["name"].replace("(도)", ""), "route": s["route"], "kind": s["kind"],
                 "lat": round(float(s["lat"]), 5), "lon": round(float(s["lon"]), 5), "holdout": bool(s["holdout"]),
                 "seg_id": s["seg_id"], "dist_m": round(float(s["dist_m"]), 1), "elev": round(float(s["elev"]), 1)}
                for _, s in stations.iterrows()]
    (out / "stations.json").write_text(dumps(stn_rows, indent=1), encoding="utf-8")

    # ----- 시각별 추정값 (1시간) -----
    est = pd.read_parquet(P / "segment_estimates.parquet")
    feat = pd.read_parquet(P / "segment_features.parquet", columns=["seg_id", "time", "rh", "td", "rain_hrs12h", "snow"])
    est = est.merge(feat, on=["seg_id", "time"], how="left", validate="one_to_one")
    times = pd.DatetimeIndex(sorted(est["time"].unique()))
    periods = []
    for start, end in config.PERIODS:
        hours = pd.date_range(start, pd.Timestamp(end) + pd.Timedelta("23:00:00"), freq="1h")
        assert hours.isin(times).all(), f"{start}~{end} 구간 시각이 빠져 있습니다"
        periods.append({"start": hours[0].strftime("%Y-%m-%dT%H:%M"), "hours": len(hours)})
    assert sum(p["hours"] for p in periods) == len(times)
    est["t_idx"] = times.get_indexer(est["time"])
    est["s_idx"] = pd.Index(seg_ids).get_indexer(est["seg_id"])
    est = est.sort_values(["t_idx", "s_idx"])
    assert len(est) == len(times) * n_seg
    cond_cfg = json.load(open(P / "icing_conditions.json", encoding="utf-8"))
    cls_meta = json.load(open(config.MODEL_DIR / "icing_meta.json", encoding="utf-8"))
    est_meta = json.load(open(config.MODEL_DIR / "road_temp_meta.json", encoding="utf-8"))
    state = icing_state(est, est, cond_cfg["T_RST"], cond_cfg["T_RH"], cls_meta["threshold"]).to_numpy()
    arrays = {
        "rst": write_gz(out / "hourly_rst.i16.gz", quantize(est["rst_est"], 10, MISSING_I16, "int16")),
        "p_icing": write_gz(out / "hourly_p.u8.gz", quantize(est["p_icing"], P_SCALE, MISSING_U8, "uint8")),
        "state": write_gz(out / "hourly_state.u8.gz", state),
    }

    # ----- RWIS 정시 관측 (17곳) -----
    rw = pd.read_parquet(P / "rwis_10min.parquet", columns=["stn", "time", "state", "rst"])
    rw = rw[rw["time"].isin(times)]
    obs_rst = rw.pivot(index="time", columns="stn", values="rst").reindex(index=times, columns=stn_ids)
    obs_state = rw.pivot(index="time", columns="stn", values="state").reindex(index=times, columns=stn_ids)
    arrays["station_rst"] = write_gz(out / "station_rst.i16.gz", quantize(obs_rst.to_numpy(), 10, MISSING_I16, "int16"))
    arrays["station_state"] = write_gz(out / "station_state.u8.gz",
                                       np.nan_to_num(obs_state.to_numpy(), nan=0).astype("uint8"))

    # ----- 기준표·조건 -----
    crit = pd.read_csv(R / "risk_criteria.csv", encoding="utf-8-sig")
    indicators = []
    for _, r in crit.iterrows():
        code, name = r["지표"].split(" ", 1)
        indicators.append({"factor": r["요인"], "code": code, "name": name,
                           "levels": [None if r[f"수준{k}"] == "-" else r[f"수준{k}"] for k in range(1, 5)],
                           "basis": r["기준 설정 근거"]})
    criteria = {
        "indicators": indicators, "weights": WEIGHTS,
        "factor_rule": {"기상": "M1·M2 평균", "도로": "R1·R2 중 큰 값", "지형": "T1·T2·T3 평균"},
        "grades": [{"grade": g, "level": i + 1, "range": GRADE_RANGE[g], "meaning": GRADE_MEANING[g]}
                   for i, g in enumerate(GRADES)],
        "icing_condition": {"T_RST": cond_cfg["T_RST"], "T_RH": cond_cfg["T_RH"],
                            "definition": f"추정 노면온도 ≤ {cond_cfg['T_RST']}°C, 습도 ≥ {cond_cfg['T_RH']:.0f}%, "
                                          "수분 공급(최근 12시간 강수·적설·노면 ≤ 이슬점)",
                            "steps": cond_cfg["conditions"]},
        "model_prediction": {"threshold": cls_meta["threshold"], "label": "결빙관련 노면(Snow·Ice·결빙시작·판별불가)",
                             "label_states": cls_meta["label_states"]},
        "state_codes": STATE_CODES,
    }
    (out / "criteria.json").write_text(dumps(criteria, indent=1), encoding="utf-8")

    # ----- 관측소 검증 (05-2 4장과 같은 방법) -----
    rw_all = pd.read_parquet(P / "rwis_10min.parquet", columns=["stn", "state", "ice", "rst"])
    rw_all = rw_all[rw_all["ice"].notna()]
    stn_stats = rw_all.groupby("stn").agg(ice=("ice", "mean"),
                                          related=("state", lambda s: s.isin(cls_meta["label_states"]).mean()),
                                          le0=("rst", lambda s: (s <= 0).mean()))
    val = match.set_index("stn")[["seg_id"]].join(stn_stats).join(risk["총점"], on="seg_id")
    rho = {k: round(float(spearmanr(val["총점"], val[k])[0]), 2) for k in ["ice", "related", "le0"]}

    meta = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "title": "전북 고속도로 구간별 결빙 위험도",
        "segment_length_m": config.SEGMENT_LENGTH_M, "n_segments": n_seg, "seg_ids": seg_ids,
        "station_ids": stn_ids, "routes": sorted(segments["route"].unique().tolist()),
        "time": {"step": "1h", "timezone": "Asia/Seoul (KST)", "periods": periods, "n_hours": len(times),
                 "layout": "시각 우선: index = 시각 x 구간 수 + 구간 (관측소 배열은 x 관측소 수)"},
        "arrays": arrays,
        "scales": {"rst": {"multiply": 0.1, "missing": MISSING_I16, "unit": "°C"},
                   "p_icing": {"multiply": 1 / P_SCALE, "missing": MISSING_U8},
                   "state": {"codes": STATE_CODES, "missing": MISSING_U8},
                   "station_rst": {"multiply": 0.1, "missing": MISSING_I16, "unit": "°C"},
                   "station_state": {"missing": 0, "note": "노면상태 원본 코드 (데이터 설명자료 PDF)"}},
        "grade_counts": {g: int((risk["등급"] == g).sum()) for g in GRADES},
        "models": {"road_temperature": {"method": est_meta["method"], "ensemble": est_meta["ensemble"]},
                   "icing": {"method": cls_meta["method"], "threshold": cls_meta["threshold"]}},
        "performance": performance_summary(),
        "station_validation_spearman": {"총점-Ice 비율": rho["ice"], "총점-결빙관련 노면 비율": rho["related"],
                                        "총점-노면 0°C 이하 비율": rho["le0"], "n_stations": int(len(val))},
        "event_days": event_days(times, state, n_seg, obs_state.to_numpy(), cls_meta["label_states"]),
        "facilities": {"bridge_polygons": n_bridge_poly, "tunnel_polygons": n_tunnel_poly,
                       "note": "국토부 교량·터널 경계(제공 자료 8번) 중 고속도로 위 객체를 02-2와 같은 방법으로 골라 구간 선과 겹친 부분"},
        "sources": {p.name: datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds") for p in [
            P / "segments.gpkg", R / "segment_risk.csv", R / "risk_criteria.csv", P / "segment_estimates.parquet",
            P / "segment_features.parquet", P / "rwis_10min.parquet", config.MODEL_DIR / "icing_meta.json",
            config.MODEL_DIR / "road_temp_meta.json"]},
    }
    (out / "meta.json").write_text(dumps(meta, indent=1), encoding="utf-8")

    print(f"구간 {n_seg}개, 시각 {len(times):,}개 ({periods[0]['start']} 등 {len(periods)}개 기간)")
    print(f"교량 구간 {int((fac['kind'] == 'bridge').sum())}개·터널 구간 {int((fac['kind'] == 'tunnel').sum())}개 "
          f"(고속도로 교량 polygon {n_bridge_poly}, 터널 polygon {n_tunnel_poly})")
    print("주요 사례일:", ", ".join(d["date"] for d in meta["event_days"]))
    print("관측소 검증 순위상관:", meta["station_validation_spearman"])
    for p in sorted(out.iterdir()):
        print(f"  {p.name:24s} {p.stat().st_size / 1e3:9.1f} KB")


if __name__ == "__main__":
    main()
