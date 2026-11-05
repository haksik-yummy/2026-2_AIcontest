"""도로 관리자용 우선 구간 목록과 경로 위험 요약을 계산합니다. 서버와 ops/briefing.py가 함께 씁니다.

목록은 등급·결빙 가능 조건·모델 예측 시간을 그대로 정렬해 보여 줄 뿐, 살포 시점이나 작업량을 정하지 않습니다.
"""

import csv
import io
import math
from datetime import timedelta
from pathlib import Path

from store import GRADES, NO_LIVE, STALE, ApiError, iso, live_state_code, state_info

GROUPS = ("sigungu", "route", "branch")
BRANCH_ALIASES = {"name": ("name", "지사명", "지사", "branch"), "lat": ("lat", "위도", "latitude"), "lon": ("lon", "경도", "longitude", "lng")}


def load_branches(path):
    """지사 위치 CSV (지사명·위도·경도). UTF-8과 CP949를 구분한다."""
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"{path}: UTF-8/CP949로 읽을 수 없습니다")
    reader = csv.DictReader(io.StringIO(text))
    cols = {}
    for key, aliases in BRANCH_ALIASES.items():
        cols[key] = next((c for c in reader.fieldnames or [] if c.strip().lower() in aliases), None)
        if cols[key] is None:
            raise ValueError(f"{path}: {key} 열을 찾지 못했습니다 (가능한 이름: {', '.join(aliases)})")
    return [{"name": r[cols["name"]].strip(), "lat": float(r[cols["lat"]]), "lon": float(r[cols["lon"]])} for r in reader]


def distance_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def group_of(props, group, branches):
    if group == "route":
        return props["route"]
    if group == "sigungu":
        return f"{props['sigungu']} ({props['route']})"
    return min(branches, key=lambda b: distance_km(props["lat"], props["lon"], b["lat"], b["lon"]))["name"]


def _item(props, stats):
    return {"seg_id": props["seg_id"], "route": props["route"], "km_from": props["km_from"], "km_to": props["km_to"],
            "sigungu": props["sigungu"], "lat": props["lat"], "lon": props["lon"], "grade": props["grade"],
            "score": props["score"], **stats}


def _rank(item):
    return (-item["prediction_hours"], -item["alert_hours"], -GRADES.index(item["grade"]), item["min_rst"] if item["min_rst"] is not None else 99)


def _assemble(bundle, items, group, top, branches, header):
    meaning = {g["grade"]: g["meaning"] for g in bundle.criteria["grades"]}
    groups = {}
    for props, it in items:
        groups.setdefault(group_of(props, group, branches), []).append(it)
    out = []
    for name, rows in groups.items():
        alert = [r for r in rows if r["alert_hours"] > 0]
        alert.sort(key=_rank)
        out.append({"group": name, "segments": len(rows), "alert_segments": len(alert),
                    "alert_segment_hours": sum(r["alert_hours"] for r in rows),
                    "top": [dict(r, grade_meaning=meaning[r["grade"]]) for r in alert[:top]]})
    out.sort(key=lambda g: (-g["alert_segment_hours"], g["group"]))
    notes = ["우선순위는 모델 예측 시간, 결빙 가능 조건 시간, 위험 등급, 최저 추정 노면온도 순으로 정렬한 것입니다. 실제 결빙 확인이나 작업 지시가 아닙니다.",
             "조건 미충족 구간이 안전하다는 뜻은 아닙니다."]
    if group == "branch":
        notes.append("지사 묶음은 구간 중간점에서 가장 가까운 지사를 직선거리로 고른 것으로 실제 관할과 다를 수 있습니다.")
    return {**header, "group_by": group, "groups": out, "notes": notes,
            "total": {"segments": bundle.n_seg, "alert_segments": sum(g["alert_segments"] for g in out),
                      "alert_segment_hours": sum(g["alert_segment_hours"] for g in out)}}


def check_group(group, branches):
    if group not in GROUPS:
        raise ApiError(400, "bad_group", f"group은 {', '.join(GROUPS)} 중 하나입니다")
    if group == "branch" and not branches:
        raise ApiError(409, "no_branches", "지사 위치 자료가 없습니다. 서버를 --branches 지사.csv 로 실행하세요")


def history_briefing(bundle, start, hours=15, group="sigungu", top=5, branches=None):
    """start부터 hours시간 동안의 과거 재생 자료로 묶음별 우선 구간을 고른다."""
    check_group(group, branches)
    if not 1 <= hours <= 72:
        raise ApiError(400, "bad_hours", "hours는 1~72입니다")
    h0 = bundle.require_hour(start)
    h_last = bundle.require_hour(start + timedelta(hours=hours - 1))
    if h_last - h0 != hours - 1:
        raise ApiError(400, "crosses_period", "기간이 두 겨울 자료의 경계를 넘습니다")
    items = []
    for s, f in enumerate(bundle.segments):
        props = f["properties"]
        cond = pred = alert = 0
        min_rst = min_time = first = None
        for h in range(h0, h_last + 1):
            st, v = bundle.state_at(h, s), bundle.rst_at(h, s)
            if st:
                alert += 1
                cond += st in (1, 3)
                pred += st in (2, 3)
                first = first or bundle.time_of(h)
            if v is not None and (min_rst is None or v < min_rst):
                min_rst, min_time = v, bundle.time_of(h)
        items.append((props, _item(props, {"alert_hours": alert, "condition_hours": cond, "prediction_hours": pred,
                                           "first_alert": iso(first), "min_rst": min_rst, "min_rst_time": iso(min_time)})))
    header = {"mode": "history", "window": {"start": iso(bundle.time_of(h0)), "end": iso(bundle.time_of(h_last)), "hours": hours}}
    return _assemble(bundle, items, group, top, branches, header)


def live_briefing(bundle, run, freshness, group="sigungu", top=5, branches=None):
    """마지막 수신 시각 한 시점의 상태로 고른다. 미래 시각 예보가 아니다."""
    check_group(group, branches)
    if run is None or freshness["state"] != "fresh":
        code, label, basis = STALE if run else NO_LIVE
        return {"mode": "live", "freshness": freshness, "status": {"code": code, "label": label, "basis": basis}, "groups": [],
                "notes": ["최신 수신 자료가 없어 우선 구간을 만들지 않았습니다."]}
    items = []
    for f in bundle.segments:
        props = f["properties"]
        rec = run["segments"].get(props["seg_id"], {})
        st = live_state_code(rec)
        items.append((props, _item(props, {"alert_hours": 1 if st else 0, "condition_hours": 1 if st in (1, 3) else 0,
                                           "prediction_hours": 1 if st in (2, 3) else 0, "first_alert": run["valid_time"] if st else None,
                                           "min_rst": rec.get("rst_est"), "min_rst_time": run["valid_time"]})))
    out = _assemble(bundle, items, group, top, branches, {"mode": "live", "freshness": freshness, "valid_time": run["valid_time"], "source": run["source"]})
    out["notes"].append("마지막 수신 시각 한 시점의 상태입니다. 앞으로의 예보가 아닙니다.")
    return out


# ----- 경로 위험 요약 -----

def _risk_row(bundle, s, enter_m, exit_m, eta, values):
    props = bundle.segments[s]["properties"]
    return {"seg_id": props["seg_id"], "route": props["route"], "km_from": props["km_from"], "km_to": props["km_to"], "sigungu": props["sigungu"],
            "lat": props["lat"], "lon": props["lon"], "grade": props["grade"], "score": props["score"],
            "enter_km": round(enter_m / 1000, 2), "exit_km": round(exit_m / 1000, 2), "eta": iso(eta), **values}


def route_rows(bundle, visits, depart, sec_per_m, mode, run=None, freshness=None):
    """visits: [(구간 번호, 경로상 시작 m, 끝 m)] → 통과 예상 시각의 값과 요약."""
    rows = []
    for s, enter_m, exit_m in visits:
        eta = depart + timedelta(seconds=enter_m * sec_per_m) if depart else None
        if mode == "history":
            h = bundle.hour_index(eta)
            if h < 0:
                values = {"rst_est": None, "p_icing": None, "state": None, "status": state_info(None)}
            else:
                r = bundle.segment_record(s, h)
                values = {k: r[k] for k in ("rst_est", "p_icing", "state", "status")}
                values["data_time"] = iso(bundle.time_of(h))
        else:
            rec = (run or {}).get("segments", {}).get(bundle.seg_ids[s], {})
            fresh = run is not None and freshness["state"] == "fresh"
            code = live_state_code(rec) if fresh else None
            status = state_info(code) if fresh else dict(zip(("code", "label", "basis"), STALE if run else NO_LIVE))
            values = {"rst_est": rec.get("rst_est") if fresh else None, "p_icing": rec.get("p_icing") if fresh else None, "state": code,
                      "status": status, "data_time": run["valid_time"] if run else None}
        rows.append(_risk_row(bundle, s, enter_m, exit_m, eta, values))
    return rows, route_summary(rows)


def route_summary(rows):
    km = {g: 0.0 for g in GRADES}
    for r in rows:
        km[r["grade"]] += r["exit_km"] - r["enter_km"]
    temps = [r for r in rows if r["rst_est"] is not None]
    coldest = min(temps, key=lambda r: r["rst_est"]) if temps else None
    return {"segments": len(rows), "km_by_grade": {g: round(v, 1) for g, v in km.items()},
            "high_grade_segments": sum(r["grade"] in ("경계", "심각") for r in rows),
            "condition_segments": sum(r["state"] in (1, 3) for r in rows), "prediction_segments": sum(r["state"] in (2, 3) for r in rows),
            "coldest": None if coldest is None else {k: coldest[k] for k in ("seg_id", "rst_est", "eta")}}
