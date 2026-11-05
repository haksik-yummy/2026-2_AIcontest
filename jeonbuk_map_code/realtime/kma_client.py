"""기상청 API허브에서 AWS·ASOS·도로기상·CCTV 자료를 받아 engine.py가 쓰는 표준 이름으로 바꿉니다.

인증키는 환경변수 KMA_APIHUB_KEY로만 받습니다. 요청 주소에 키가 들어가므로 원문 저장과 오류 메시지에는 키를 남기지 않습니다.

응답 형식의 근거
    ASOS kma_sfctm3.php    API허브 문서의 출력 항목 순서
    AWS  nph-aws2_min      제공 AWS CSV의 열 순서 (이 API의 1분 자료와 항목이 같다)
    도로기상 road_stn_obs.php  문서에 출력 항목이 없다. 헤더 이름을 먼저 읽고, 없으면 제공 RWIS CSV의 열 순서로 본다.
                           값이 범위를 벗어나면 잘못 읽은 것으로 보고 멈춘다. 키를 받으면 pipeline.py --check-api로 대조한다
    CCTV cctv_ana_info.php API허브 문서의 출력 항목 순서
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from engine import VALID_STATES

BASE_URL = "https://apihub.kma.go.kr"
ASOS_COLUMNS = ["TM", "STN", "WD", "WS", "GST_WD", "GST_WS", "GST_TM", "PA", "PS", "PT", "PR", "TA", "TD", "HM", "PV", "RN", "RN_DAY", "RN_INT",
                "SD_HR3", "SD_DAY", "SD_TOT", "WC", "WP", "WW", "CA_TOT", "CA_MID", "CH_MIN", "CT", "CT_TOP", "CT_MID", "CT_LOW", "VS", "SS", "SI",
                "ST_GD", "TS", "TE_005", "TE_01", "TE_02", "TE_03", "ST_SEA", "WH", "BF", "IR", "IX", "RN_JUN"]
AWS_COLUMNS = ["TM", "STN", "WD1", "WS1", "WDS", "WSS", "WD10", "WS10", "TA", "RE", "RN_15M", "RN_60M", "RN_12H", "RN_DAY", "HM", "PA", "PS", "TD"]
CCTV_COLUMNS = ["TM", "EQP_ID", "STN_NM", "LAT", "LON", "HT", "WH_CD", "FOG_CD", "RN_CD", "SN_CD"]
# 제공 RWIS CSV의 열 순서. 앞의 지점 정보가 있는 형식과 없는 형식을 모두 본다
ROAD_ELEMENTS = ["state", "rst", "vis", "rh", "pr_day", "snow", "ta", "wd", "ws", "gust_wd", "gust_ws", "pa", "ch1", "ch2", "ch3", "ca"]
ROAD_LAYOUTS = {24: ["tm", "stn", "name", "road", "kind", "lat", "lon", "alt", *ROAD_ELEMENTS], 18: ["tm", "stn", *ROAD_ELEMENTS]}
ROAD_ALIASES = {"tm": ("tm", "yymmddhhmi", "yyyymmddhhmi", "관측시각"), "stn": ("stn", "stn_id", "stnid", "지점", "지점번호"), "state": ("sfs", "노면상태"),
                "rst": ("srt", "sft", "rst", "st", "ts", "노면온도"), "ta": ("ta", "기온"), "rh": ("hm", "rh", "습도"), "ws": ("ws", "ws1", "풍속"),
                "pr_day": ("rn_day", "rn", "일누적강수량"), "vis": ("vs", "vis", "시정")}
ROAD_VARS = ["state", "rst", "ta", "rh", "ws", "pr_day", "vis"]


class KmaError(RuntimeError):
    pass


class KmaFormatError(KmaError):
    """응답 형식이 예상과 다르다. 잘못 읽은 값으로 추정하지 않도록 멈춘다."""


def data_rows(text):
    """주석(#)을 뺀 자료 줄을 나눈다. 쉼표가 있으면 쉼표로, 없으면 공백으로 가른다."""
    rows = []
    for line in text.splitlines():
        s = line.strip().rstrip("=").rstrip(",").strip()
        if not s or s.startswith("#"):
            continue
        rows.append([c.strip() for c in s.split(",")] if "," in s else s.split())
    return rows


def header_tokens(text):
    """주석 줄 가운데 열 이름으로 보이는 마지막 줄."""
    found = None
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("#"):
            continue
        tokens = [t for t in re.split(r"[,\s]+", s.lstrip("#").strip()) if t]
        low = [t.lower() for t in tokens]
        if len(tokens) >= 5 and any(t in ROAD_ALIASES["tm"] for t in low) and any(t in ROAD_ALIASES["stn"] for t in low):
            found = tokens
    return found


def parse_time(values):
    return pd.to_datetime(pd.Series(values).astype(str).str.slice(0, 12), format="%Y%m%d%H%M")


def numeric(df, cols):
    return df[cols].apply(pd.to_numeric, errors="coerce")


def parse_asos(text):
    rows = data_rows(text)
    empty = pd.DataFrame(columns=["stn", "time", "cloud", "tg", "snow", "sunshine"])
    if not rows:
        return empty
    n = len(ASOS_COLUMNS)
    if any(not n - 2 <= len(r) <= n for r in rows):
        raise KmaFormatError(f"ASOS 열 수가 문서와 다릅니다: {sorted({len(r) for r in rows})}개, 기대 {n}개")
    raw = pd.DataFrame([r + [None] * (n - len(r)) for r in rows], columns=ASOS_COLUMNS)
    vals = numeric(raw, ["STN", "CA_TOT", "TS", "SD_TOT", "SS"])
    out = pd.DataFrame({"stn": vals["STN"].astype(int), "time": parse_time(raw["TM"])})
    out["cloud"] = vals["CA_TOT"].where(vals["CA_TOT"] >= 0)
    out["tg"] = vals["TS"].where((vals["TS"] > -90) & (vals["TS"] != -9.0))  # -9.0·-99.0은 결측 표기
    out["snow"] = vals["SD_TOT"].where(vals["SD_TOT"] >= 0)
    out["sunshine"] = vals["SS"].where(vals["SS"] >= 0)
    return out


def parse_aws(text):
    rows = data_rows(text)
    empty = pd.DataFrame(columns=["stn", "time", "ta", "td", "rh", "ws", "rain", "pr60", "pr12h", "pr_day"])
    if not rows:
        return empty
    if any(len(r) != len(AWS_COLUMNS) for r in rows):
        raise KmaFormatError(f"AWS 열 수가 다릅니다: {sorted({len(r) for r in rows})}개, 기대 {len(AWS_COLUMNS)}개")
    raw = pd.DataFrame(rows, columns=AWS_COLUMNS)
    vals = numeric(raw, ["STN", "TA", "TD", "HM", "WS10", "RE", "RN_60M", "RN_12H", "RN_DAY"])
    return pd.DataFrame({"stn": vals["STN"].astype(int), "time": parse_time(raw["TM"]), "ta": vals["TA"], "td": vals["TD"], "rh": vals["HM"], "ws": vals["WS10"],
                         "rain": vals["RE"], "pr60": vals["RN_60M"], "pr12h": vals["RN_12H"], "pr_day": vals["RN_DAY"]})


def road_columns(text, width, overrides=None):
    """도로기상 열 이름을 정한다. 설정 파일 → 응답 헤더 → 제공 CSV 순서로 찾는다."""
    if overrides:
        names = [None] * width
        for key, pos in overrides.items():
            names[pos] = key
        return names, "설정 파일"
    header = header_tokens(text)
    if header and len(header) == width:
        low = [h.lower() for h in header]
        names = [None] * width
        for key, aliases in ROAD_ALIASES.items():
            hit = next((i for i, h in enumerate(low) if h in aliases), None)
            if hit is not None:
                names[hit] = key
        if all(k in names for k in ("tm", "stn", "state", "rst")):
            return names, "응답 헤더"
    if width in ROAD_LAYOUTS:
        return ROAD_LAYOUTS[width], "제공 CSV 순서"
    raise KmaFormatError(f"도로기상 열을 해석하지 못했습니다 (열 {width}개, 헤더 {header}). realtime/road_columns.json으로 위치를 지정하세요")


def parse_road(text, overrides=None):
    rows = data_rows(text)
    if not rows:
        return pd.DataFrame(columns=["stn", "time", *ROAD_VARS])
    widths = {len(r) for r in rows}
    if len(widths) != 1:
        raise KmaFormatError(f"도로기상 행마다 열 수가 다릅니다: {sorted(widths)}")
    names, _ = road_columns(text, widths.pop(), overrides)
    raw = pd.DataFrame(rows, columns=[n or f"_{i}" for i, n in enumerate(names)])
    out = pd.DataFrame({"stn": pd.to_numeric(raw["stn"], errors="coerce").astype("Int64"), "time": parse_time(raw["tm"])})
    for v in ROAD_VARS:
        out[v] = pd.to_numeric(raw[v], errors="coerce") if v in raw else np.nan
    check_road(out)
    out["stn"] = out["stn"].astype(int)
    return out


def check_road(df):
    """읽은 값이 말이 되는지 본다. 열을 잘못 짚으면 노면상태 코드와 온도 범위가 크게 어긋난다."""
    if len(df) < 3:
        return
    state, rst = df["state"].dropna(), df["rst"].dropna()
    state = state[state != -999]
    rst = rst[rst != -999]
    if len(state) and state.isin(VALID_STATES + [0]).mean() < 0.9:
        raise KmaFormatError(f"노면상태 값이 코드표와 맞지 않습니다 (예: {state.head(5).tolist()}). 열 순서를 확인하세요")
    if len(rst) and rst.between(-40, 70).mean() < 0.9:
        raise KmaFormatError(f"노면온도 값이 범위를 벗어납니다 (예: {rst.head(5).tolist()}). 열 순서를 확인하세요")


def parse_cctv(text):
    rows = data_rows(text)
    if not rows:
        return []
    out = []
    for r in rows:
        if len(r) < len(CCTV_COLUMNS):
            raise KmaFormatError(f"CCTV 열 수가 다릅니다: {len(r)}개, 기대 {len(CCTV_COLUMNS)}개")
        rec = dict(zip(CCTV_COLUMNS, r))
        try:
            out.append({"eqp_id": rec["EQP_ID"], "name": rec["STN_NM"], "lat": float(rec["LAT"]), "lon": float(rec["LON"]), "tm": rec["TM"],
                        "wh_cd": int(rec["WH_CD"]), "fog_cd": int(rec["FOG_CD"]), "rn_cd": int(rec["RN_CD"]), "sn_cd": int(rec["SN_CD"])})
        except ValueError:
            continue
    return out


class KmaHub:
    """API허브 요청. 응답 원문을 raw_dir에 저장하면 형식을 나중에 확인할 수 있다."""

    def __init__(self, auth_key, raw_dir=None, timeout=30, base=BASE_URL, pause=0.2):
        if not auth_key:
            raise KmaError("환경변수 KMA_APIHUB_KEY가 없습니다. 기상청 API허브에서 인증키를 받아 설정하세요")
        self.key, self.raw_dir, self.timeout, self.base, self.pause = auth_key, raw_dir, timeout, base, pause
        self.calls = 0

    def get(self, path, **params):
        query = urllib.parse.urlencode({**params, "authKey": self.key})
        self.calls += 1
        try:
            with urllib.request.urlopen(f"{self.base}/{path}?{query}", timeout=self.timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as exc:
            raise KmaError(f"{path}: HTTP {exc.code} {self.message(exc.read())}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise KmaError(f"{path}: 연결 실패 {getattr(exc, 'reason', exc)}") from None
        time.sleep(self.pause)
        for encoding in ("utf-8", "cp949"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise KmaFormatError(f"{path}: 응답 인코딩을 알 수 없습니다")
        if text.lstrip().startswith("{"):
            raise KmaError(f"{path}: {self.message(raw)}")
        if self.raw_dir:
            Path(self.raw_dir).mkdir(parents=True, exist_ok=True)
            name = re.sub(r"\W+", "_", path.rsplit("/", 1)[-1]) + "_" + "_".join(str(v) for v in params.values())
            (Path(self.raw_dir) / f"{name[:120]}.txt").write_text(text, encoding="utf-8")
        return text

    @staticmethod
    def message(raw):
        try:
            return json.loads(raw.decode("utf-8", "replace"))["result"]["message"]
        except (ValueError, KeyError, TypeError):
            return raw[:200].decode("utf-8", "replace")

    def asos(self, start, end):
        return parse_asos(self.get("api/typ01/url/kma_sfctm3.php", tm1=f"{start:%Y%m%d%H%M}", tm2=f"{end:%Y%m%d%H%M}", stn=0, help=0))

    def aws_step(self, t):
        return parse_aws(self.get("api/typ01/cgi-bin/url/nph-aws2_min", tm2=f"{t:%Y%m%d%H%M}", stn=0, disp=1, help=0))

    def aws_station(self, stn, start, end):
        return parse_aws(self.get("api/typ01/cgi-bin/url/nph-aws2_min", tm1=f"{start:%Y%m%d%H%M}", tm2=f"{end:%Y%m%d%H%M}", stn=int(stn), disp=1, help=0))

    def road_step(self, t, overrides=None):
        return parse_road(self.get("api/typ01/url/road_stn_obs.php", mode=1, var=0, tm1=f"{t:%Y%m%d%H%M}", disp=1, help=1), overrides)

    def road_station(self, stn, start, end, overrides=None):
        return parse_road(self.get("api/typ01/url/road_stn_obs.php", mode=1, var=int(stn), tm1=f"{start:%Y%m%d%H%M}", tm2=f"{end:%Y%m%d%H%M}", disp=1, help=1), overrides)

    def cctv(self, start, end):
        return parse_cctv(self.get("api/typ01/url/cctv_ana_info.php", tm1=f"{start:%Y%m%d%H%M}", tm2=f"{end:%Y%m%d%H%M}", eqp=0, disp=0, help=0))


class KmaSource:
    """10분 자료를 캐시에 쌓아 두고 빠진 시각만 받는다. 처음에는 지점별로 며칠 치를 받는다."""

    name = "kma-apihub"
    RECENT_REFETCH = pd.Timedelta("30min")  # 늦게 들어오는 관측을 다시 받는 범위

    def __init__(self, hub, aws_stn, asos_stn, rwis_stn, cache_dir, road_columns_path=None):
        self.hub, self.aws_stn, self.asos_stn, self.rwis_stn = hub, set(map(int, aws_stn)), set(map(int, asos_stn)), set(map(int, rwis_stn))
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        path = Path(road_columns_path) if road_columns_path else None
        self.road_columns = json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else None

    def _load(self, name):
        p = self.cache / f"{name}.parquet"
        return pd.read_parquet(p) if p.exists() else None

    def _store(self, name, df, start):
        df = df[df["time"] >= start].drop_duplicates(["stn", "time"], keep="last")
        df.to_parquet(self.cache / f"{name}.parquet", index=False)
        return df

    def _steps(self, name, start, end, step_fetch, station_fetch, stations):
        old = self._load(name)
        have = set() if old is None else set(old["time"].unique())
        steps = pd.date_range(start, end, freq="10min")
        need = [t for t in steps if t not in have or t > end - self.RECENT_REFETCH]
        frames = [] if old is None else [old]
        if len(need) > 6:  # 처음이거나 오래 멈췄다: 지점별로 하루씩 받는다
            lo = min(need)
            while lo <= end:
                hi = min(lo + pd.Timedelta(hours=23, minutes=50), end)
                for stn in sorted(stations):
                    frames.append(station_fetch(stn, lo, hi))
                lo = hi + pd.Timedelta("10min")
        else:
            frames += [step_fetch(t) for t in need]
        frames = [f for f in frames if len(f)]
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        df = df[df["stn"].isin(stations) & (df["time"].dt.minute % 10 == 0)]
        return self._store(name, df, start)

    def collect(self, start, end):
        road = self._steps("rwis", start, end, lambda t: self.hub.road_step(t, self.road_columns),
                           lambda s, a, b: self.hub.road_station(s, a, b, self.road_columns), self.rwis_stn)
        aws = self._steps("aws", start, end, self.hub.aws_step, self.hub.aws_station, self.aws_stn)
        asos = self.hub.asos(start, end)
        return {"rwis": road, "aws": aws, "asos": asos[asos["stn"].isin(self.asos_stn)]}

    def reference(self, end):
        """전북 고속도로 범위의 CCTV 도로날씨. 없어도 추정은 계속한다."""
        items = self.hub.cctv(end - pd.Timedelta("10min"), end)
        return [c for c in items if 35.2 <= c["lat"] <= 36.25 and 126.4 <= c["lon"] <= 127.9]
