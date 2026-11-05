"""bundle/의 분석 결과(과거 재생)와 실시간 입력(SQLite, 현재 수신)을 읽어 질의에 답합니다.

Python 기본 기능만 씁니다. 과거 자료는 export_bundle.py가 만든 배열을 메모리에 올려 그대로 돌려주고,
현재 자료는 인증된 수집기(realtime/pipeline.py)가 POST /api/v1/ingest로 보낸 값만 씁니다.
"""

import array
import gzip
import json
import math
import re
import sqlite3
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
GRADES = ["관심", "주의", "경계", "심각"]

# 시각별 상태 코드 (export_bundle.py의 STATE_CODES와 같음)
STATE = {
    0: ("no_condition", "조건 미충족", "선택한 결빙 조건에 해당하지 않음. 안전 판정이 아님"),
    1: ("icing_condition", "결빙 가능 조건", "추정 노면온도·습도·수분 공급이 결빙 가능 조건에 해당"),
    2: ("prediction_only", "모델 예측만", "결빙관련 노면 분류 확률이 임계값 이상이나 결빙 가능 조건은 아님"),
    3: ("condition_and_prediction", "결빙 가능 조건 + 모델 예측", "결빙 가능 조건이고 분류 확률도 임계값 이상"),
}
NO_DATA = ("no_data", "자료 없음", "이 시각의 추정값이 없음")
STALE = ("stale", "정보 부족(오래된 자료)", "마지막 수신 자료가 신선도 기준보다 오래되어 현재 상태로 볼 수 없음")
NO_LIVE = ("no_live_data", "정보 부족(수신 자료 없음)", "현재 시각의 수신 자료가 없음. 상태를 만들어 내지 않음")

# RWIS 노면상태 코드 (제공 데이터 설명자료 PDF)
ROAD_STATE = {
    1: ("dry", "건조(Dry)"), 2: ("wet", "젖음(Wet)"), 3: ("snow", "눈(Snow)"), 4: ("ice", "얼음(Ice)"),
    10: ("low_visibility", "저시정"), 11: ("standing_water", "물 고임"), 12: ("deicer_no_ice", "제빙제 사용, 결빙 안 됨"),
    13: ("deicer_icing_start", "제빙제 사용, 결빙 시작"), 14: ("damp", "습윤(Damp)"), 15: ("indeterminate", "물·얼음 판별 불가"),
}


class ApiError(Exception):
    """HTTP 상태 코드와 함께 사용자에게 보낼 오류."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def parse_time(value, name="시각"):
    """ISO 8601 시각을 KST aware datetime으로. 시간대가 없으면 KST로 본다. 'Z'도 받는다."""
    if value is None or str(value).strip() == "":
        raise ApiError(400, "missing_time", f"{name}이 필요합니다 (예: 2025-01-28T06:00+09:00)")
    text = re.sub(r"(\d{2}:\d{2}(?::\d{2})?) (\d{2}:\d{2})$", r"\1+\2", str(value).strip())  # 주소의 +가 공백으로 풀린 경우
    text = text.replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}", text):
        text += ":00"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        text += "T00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(400, "bad_time", f"{name}을 읽지 못했습니다: {value} (예: 2025-01-28T06:00+09:00)") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def iso(dt):
    return dt.astimezone(KST).isoformat(timespec="minutes") if dt else None


def finite(v):
    return v is not None and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def state_info(code):
    c, label, basis = STATE.get(code, NO_DATA) if code is not None else NO_DATA
    return {"code": c, "label": label, "basis": basis}


def road_state_info(code):
    if code is None:
        return {"code": "no_data", "label": "자료 없음", "value": None}
    c, label = ROAD_STATE.get(code, ("unknown", f"알 수 없는 코드 {code}"))
    return {"code": c, "label": label, "value": code}


def _read_array(path, typecode):
    raw = gzip.decompress(Path(path).read_bytes())
    arr = array.array(typecode)
    arr.frombytes(raw)
    if sys.byteorder == "big" and arr.itemsize > 1:
        arr.byteswap()  # 묶음은 리틀 엔디언으로 저장했다
    return arr


class Bundle:
    """export_bundle.py의 결과를 메모리에 올린다."""

    def __init__(self, path):
        path = Path(path)
        if not (path / "meta.json").exists():
            raise FileNotFoundError(f"{path}/meta.json 이 없습니다. 먼저 export_bundle.py를 실행하세요.")
        read = lambda name: json.loads((path / name).read_text(encoding="utf-8"))
        self.path = path
        self.meta, self.criteria = read("meta.json"), read("criteria.json")
        self.segments = read("segments.geojson")["features"]
        self.facilities = read("facilities.geojson")["features"]
        self.stations = read("stations.json")
        self.vulnerable = read("vulnerable.geojson") if (path / "vulnerable.geojson").exists() else None
        self.vulnerable_meta = read("vulnerable_meta.json") if (path / "vulnerable_meta.json").exists() else None
        self.seg_ids = [f["properties"]["seg_id"] for f in self.segments]
        self.seg_index = {s: i for i, s in enumerate(self.seg_ids)}
        self.stn_index = {s["stn"]: j for j, s in enumerate(self.stations)}
        self.n_seg, self.n_st = len(self.segments), len(self.stations)
        self.n_hours = self.meta["time"]["n_hours"]
        self.periods = [(datetime.fromisoformat(p["start"]).replace(tzinfo=KST), p["hours"]) for p in self.meta["time"]["periods"]]
        a = self.meta["arrays"]
        self.rst = _read_array(path / a["rst"]["file"], "h")
        self.p = _read_array(path / a["p_icing"]["file"], "B")
        self.state = _read_array(path / a["state"]["file"], "B")
        self.srst = _read_array(path / a["station_rst"]["file"], "h")
        self.sstate = _read_array(path / a["station_state"]["file"], "B")
        assert len(self.rst) == self.n_hours * self.n_seg and len(self.srst) == self.n_hours * self.n_st
        self.p_scale = self.meta["scales"]["p_icing"]["multiply"]
        self.label_states = set(self.criteria["model_prediction"]["label_states"])

    # ----- 시간축 -----
    def hour_index(self, dt):
        """KST 시각 → 시각 번호 (정시로 내림). 자료 기간 밖이면 -1."""
        local = dt.astimezone(KST).replace(minute=0, second=0, microsecond=0)
        base = 0
        for start, hours in self.periods:
            k = int((local - start).total_seconds() // 3600)
            if 0 <= k < hours:
                return base + k
            base += hours
        return -1

    def time_of(self, h):
        base = 0
        for start, hours in self.periods:
            if h < base + hours:
                return start + timedelta(hours=h - base)
            base += hours
        raise IndexError(h)

    def period_text(self):
        return [{"start": iso(s), "end": iso(s + timedelta(hours=n - 1)), "hours": n} for s, n in self.periods]

    def require_hour(self, dt):
        h = self.hour_index(dt)
        if h < 0:
            raise ApiError(404, "outside_history", f"{iso(dt)}은 과거 재생 자료 기간 밖입니다: " +
                           ", ".join(f"{p['start'][:10]}~{p['end'][:10]}" for p in self.period_text()))
        return h

    # ----- 값 -----
    def rst_at(self, h, s):
        v = self.rst[h * self.n_seg + s]
        return None if v == -32768 else v / 10

    def p_at(self, h, s):
        v = self.p[h * self.n_seg + s]
        return None if v == 255 else round(v * self.p_scale, 3)

    def state_at(self, h, s):
        v = self.state[h * self.n_seg + s]
        return None if v == 255 else v

    def obs_at(self, h, j):
        r, st = self.srst[h * self.n_st + j], self.sstate[h * self.n_st + j]
        return (None if r == -32768 else r / 10), (None if st == 0 else st)

    def segment_record(self, s, h):
        props = self.segments[s]["properties"]
        code = self.state_at(h, s)
        return {"seg_id": props["seg_id"], "route": props["route"], "grade": props["grade"],
                "rst_est": self.rst_at(h, s), "p_icing": self.p_at(h, s), "state": code,
                "condition": None if code is None else code in (1, 3),
                "prediction": None if code is None else code in (2, 3), "status": state_info(code)}

    def station_record(self, j, h):
        s = self.stations[j]
        rst, st = self.obs_at(h, j)
        return {"stn": s["stn"], "name": s["name"], "seg_id": s["seg_id"], "holdout": s["holdout"],
                "observed_at": iso(self.time_of(h)), "rst": rst, "road_state": road_state_info(st),
                "icing_related_observed": None if st is None else st in self.label_states}


class LiveStore:
    """수집기가 보낸 현재 추정·관측을 SQLite에 둔다. 과거 재생 자료와 섞지 않는다."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY, valid_time TEXT NOT NULL, received_at TEXT NOT NULL, source TEXT NOT NULL,
        quality TEXT NOT NULL, inputs TEXT, model TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS run_segments (
        run_id TEXT NOT NULL, seg_id TEXT NOT NULL, rst_est REAL, p_icing REAL, condition INTEGER, prediction INTEGER,
        PRIMARY KEY (run_id, seg_id));
    CREATE TABLE IF NOT EXISTS run_stations (
        run_id TEXT NOT NULL, stn INTEGER NOT NULL, observed_at TEXT, rst REAL, road_state INTEGER, ta REAL, rh REAL,
        PRIMARY KEY (run_id, stn));
    CREATE TABLE IF NOT EXISTS run_reference (run_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
    """

    def __init__(self, path, bundle, keep_runs=96):
        self.bundle, self.keep_runs = bundle, keep_runs
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(self.SCHEMA)
            self.db.commit()

    def ingest(self, payload, now):
        """입력 계약을 검사하고 저장한다. 하나라도 틀리면 아무것도 저장하지 않는다."""
        b = self.bundle
        if not isinstance(payload, dict):
            raise ApiError(400, "bad_payload", "JSON 객체를 보내야 합니다")
        run_id = str(payload.get("run_id", ""))
        if not re.fullmatch(r"[A-Za-z0-9_.:\-]{1,64}", run_id):
            raise ApiError(400, "bad_run_id", "run_id는 영문·숫자·_.:- 1~64자입니다")
        valid = parse_time(payload.get("valid_time"), "valid_time")
        if valid > now + timedelta(minutes=5):
            raise ApiError(400, "future_time", f"valid_time {iso(valid)}이 서버 시각 {iso(now)}보다 5분 넘게 미래입니다")
        source = str(payload.get("source", ""))[:60]
        if not source:
            raise ApiError(400, "missing_source", "source(자료 출처)가 필요합니다")
        quality = payload.get("quality", "unverified")
        if quality not in ("valid", "unverified"):
            raise ApiError(400, "bad_quality", "quality는 valid(제공자 QC 통과) 또는 unverified입니다")
        segs = payload.get("segments") or []
        if not isinstance(segs, list) or len(segs) > b.n_seg:
            raise ApiError(400, "bad_segments", f"segments는 최대 {b.n_seg}개 목록입니다")
        seg_rows, seen = [], set()
        for k, r in enumerate(segs):
            sid = r.get("seg_id") if isinstance(r, dict) else None
            if sid not in b.seg_index or sid in seen:
                raise ApiError(400, "bad_segment", f"segments[{k}]: 모르는 또는 중복된 seg_id {sid!r}")
            seen.add(sid)
            rst, p = r.get("rst_est"), r.get("p_icing")
            if rst is not None and not (finite(rst) and -40 <= rst <= 70):
                raise ApiError(400, "bad_value", f"segments[{k}].rst_est가 범위(-40~70°C) 밖입니다")
            if p is not None and not (finite(p) and 0 <= p <= 1):
                raise ApiError(400, "bad_value", f"segments[{k}].p_icing은 0~1입니다")
            cond, pred = r.get("condition"), r.get("prediction")
            for name, v in (("condition", cond), ("prediction", pred)):
                if v is not None and not isinstance(v, bool):
                    raise ApiError(400, "bad_value", f"segments[{k}].{name}은 true/false/null입니다")
            seg_rows.append((run_id, sid, rst, p, None if cond is None else int(cond), None if pred is None else int(pred)))
        stn_rows = []
        for k, r in enumerate(payload.get("stations") or []):
            if not isinstance(r, dict) or not isinstance(r.get("stn"), int):
                raise ApiError(400, "bad_station", f"stations[{k}].stn은 정수입니다")
            obs = parse_time(r.get("observed_at"), f"stations[{k}].observed_at")
            if obs > now + timedelta(minutes=5):
                raise ApiError(400, "future_time", f"stations[{k}].observed_at이 미래입니다")
            vals = [r.get(c) for c in ("rst", "ta", "rh")]
            if any(v is not None and not finite(v) for v in vals):
                raise ApiError(400, "bad_value", f"stations[{k}]의 숫자 값이 올바르지 않습니다")
            rs = r.get("road_state")
            if rs is not None and rs not in ROAD_STATE:
                raise ApiError(400, "bad_value", f"stations[{k}].road_state {rs!r}는 설명자료에 없는 코드입니다")
            stn_rows.append((run_id, r["stn"], iso(obs), vals[0], rs, vals[1], vals[2]))
        refs = []
        for kind, items in (payload.get("reference") or {}).items():
            if kind not in ("cctv",) or not isinstance(items, list) or len(items) > 5000:
                raise ApiError(400, "bad_reference", "reference는 {'cctv': [...]} 형식만 받습니다 (최대 5000개)")
            for k, it in enumerate(items):
                if not (isinstance(it, dict) and finite(it.get("lat")) and finite(it.get("lon"))):
                    raise ApiError(400, "bad_reference", f"reference.{kind}[{k}]에 lat·lon이 필요합니다")
            refs.append((run_id, kind, json.dumps(items, ensure_ascii=False)))
        if not seg_rows and not stn_rows:
            raise ApiError(400, "empty_run", "segments 또는 stations 중 하나는 있어야 합니다")
        with self.lock:
            if self.db.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone():
                raise ApiError(409, "duplicate_run", f"run_id {run_id}는 이미 받았습니다")
            with self.db:
                self.db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)", (
                    run_id, iso(valid), iso(now), source, quality, json.dumps(payload.get("inputs") or {}, ensure_ascii=False),
                    json.dumps(payload.get("model") or {}, ensure_ascii=False), str(payload.get("note", ""))[:500]))
                self.db.executemany("INSERT INTO run_segments VALUES (?,?,?,?,?,?)", seg_rows)
                self.db.executemany("INSERT INTO run_stations VALUES (?,?,?,?,?,?,?)", stn_rows)
                self.db.executemany("INSERT INTO run_reference VALUES (?,?,?)", refs)
                old = [r[0] for r in self.db.execute(
                    "SELECT run_id FROM runs ORDER BY valid_time DESC, received_at DESC LIMIT -1 OFFSET ?", (self.keep_runs,))]
                for rid in old:
                    for t in ("runs", "run_segments", "run_stations", "run_reference"):
                        self.db.execute(f"DELETE FROM {t} WHERE run_id = ?", (rid,))
        return {"run_id": run_id, "valid_time": iso(valid), "received_at": iso(now), "segments": len(seg_rows),
                "stations": len(stn_rows), "reference": {k: len(json.loads(p)) for _, k, p in refs}}

    def latest(self, kind=None, not_after=None):
        """가장 최근 valid_time의 실행. kind='cctv'면 참고 자료가 있는 가장 최근 실행.

        not_after(ISO 문자열) 뒤의 실행은 고르지 않는다. 시연 시각을 앞당겨도 DB의 '미래' 실행을 현재로 보이지 않기 위해서다.
        valid_time은 iso()가 만든 같은 형식의 KST 문자열이라 문자열 비교가 곧 시각 비교이다.
        """
        limit = not_after or "9999"
        with self.lock:
            if kind:
                row = self.db.execute("SELECT r.run_id FROM runs r JOIN run_reference f ON f.run_id = r.run_id "
                                      "WHERE f.kind = ? AND r.valid_time <= ? ORDER BY r.valid_time DESC LIMIT 1", (kind, limit)).fetchone()
            else:
                row = self.db.execute("SELECT run_id FROM runs WHERE valid_time <= ? ORDER BY valid_time DESC, received_at DESC LIMIT 1",
                                      (limit,)).fetchone()
            if not row:
                return None
            rid = row[0]
            run = dict(zip(["run_id", "valid_time", "received_at", "source", "quality", "inputs", "model", "note"],
                           self.db.execute("SELECT * FROM runs WHERE run_id = ?", (rid,)).fetchone()))
            run["inputs"], run["model"] = json.loads(run["inputs"]), json.loads(run["model"])
            run["segments"] = {r[0]: {"rst_est": r[1], "p_icing": r[2], "condition": None if r[3] is None else bool(r[3]),
                                      "prediction": None if r[4] is None else bool(r[4])}
                               for r in self.db.execute("SELECT seg_id, rst_est, p_icing, condition, prediction "
                                                        "FROM run_segments WHERE run_id = ?", (rid,))}
            run["stations"] = {r[0]: {"observed_at": r[1], "rst": r[2], "road_state": r[3], "ta": r[4], "rh": r[5]}
                               for r in self.db.execute("SELECT stn, observed_at, rst, road_state, ta, rh FROM run_stations "
                                                        "WHERE run_id = ?", (rid,))}
            run["reference"] = {k: json.loads(p) for k, p in self.db.execute(
                "SELECT kind, payload FROM run_reference WHERE run_id = ?", (rid,))}
            return run

    def count(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


def live_state_code(rec):
    """수신값의 condition·prediction을 상태 코드(0~3)로. 둘 다 없으면 None."""
    c, p = rec.get("condition"), rec.get("prediction")
    if c is None and p is None:
        return None
    return int(bool(c)) + 2 * int(bool(p))
