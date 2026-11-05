"""결빙 위험도 분석 결과를 JSON·GeoJSON API와 지도 화면으로 제공합니다.

실행: python service/server.py --open
Python 3.9 이상. 추가 패키지는 필요하지 않습니다. 발표·개발용 표준 라이브러리 서버이며 공개 운영 서버가 아닙니다.

환경변수 (모두 선택)
    ICING_INGEST_TOKEN   POST /api/v1/ingest 인증값. 없으면 입력 경로를 닫는다
    NCP_MAPS_KEY_ID, NCP_MAPS_KEY   네이버 Directions 5 인증키. 없으면 경로 조회만 빠진다
네이버 지도 배경의 공개 Client ID는 service/config.local.json의 naver_key_id에 둔다 (config.example.json 참고).
"""

import argparse
import hmac
import json
import mimetypes
import os
import re
import sys
import time
import traceback
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

import geo  # noqa: E402
import naver  # noqa: E402
import ops  # noqa: E402
from store import (KST, NO_LIVE, STALE, ApiError, Bundle, LiveStore, finite, iso, live_state_code, parse_time,  # noqa: E402
                   road_state_info, state_info)

MAX_BODY = 8 * 1024 * 1024
MAX_PATH_POINTS = 20000
MAX_SERIES_DAYS = 31
DEFAULT_SPEED_KMH = 90.0
STATIC_PAGES = {"/": HERE / "static" / "index.html", "/api-docs": HERE / "static" / "api-docs.html",
                "/assets/d3.min.js": BASE / "assets" / "d3.v7.9.0.min.js",
                "/assets/municipalities.geojson": BASE / "assets" / "municipalities.geojson",
                "/atlas": BASE / "output" / "jeonbuk_risk_atlas.html"}
STATUS_NOTE = "이 값은 분석 추정이며 실제 노면 결빙을 확인한 것이 아닙니다. 조건 미충족은 안전 판정이 아닙니다."


def number(q, name, default=None, lo=None, hi=None):
    if name not in q:
        if default is None:
            raise ApiError(400, "missing_parameter", f"{name}이 필요합니다")
        return default
    try:
        v = float(q[name])
    except ValueError:
        raise ApiError(400, "bad_parameter", f"{name}은 숫자입니다") from None
    if not finite(v) or (lo is not None and v < lo) or (hi is not None and v > hi):
        raise ApiError(400, "bad_parameter", f"{name}은 {lo}~{hi} 범위입니다")
    return v


class Service:
    """요청 처리. 모든 메서드는 JSON으로 바꿀 수 있는 값을 돌려준다."""

    def __init__(self, bundle_dir, db_path, ttl_minutes=90, naver_key_id="", ingest_token=None, clock=None, branches=None, simulated=False):
        self.bundle = Bundle(bundle_dir)
        self.live = LiveStore(db_path, self.bundle)
        self.index = geo.SegmentIndex(self.bundle.segments)
        self.ttl = ttl_minutes
        self.naver_key_id = naver_key_id
        self.token = ingest_token
        self.clock = clock or (lambda: datetime.now(KST))
        self.branches = branches
        self.simulated = simulated

    # ----- 공통 -----
    def latest_run(self, kind=None):
        return self.live.latest(kind, not_after=iso(self.clock() + timedelta(minutes=5)))

    def freshness(self, run):
        if run is None:
            return {"state": "no_data", "ttl_minutes": self.ttl, "age_minutes": None, "valid_time": None}
        age = (self.clock() - parse_time(run["valid_time"])).total_seconds() / 60
        return {"state": "fresh" if age <= self.ttl else "stale", "ttl_minutes": self.ttl, "age_minutes": round(age, 1),
                "valid_time": run["valid_time"]}

    def seg(self, seg_id):
        if seg_id not in self.bundle.seg_index:
            raise ApiError(404, "unknown_segment", f"구간 {seg_id}이 없습니다")
        return self.bundle.seg_index[seg_id]

    def route_filter(self, q):
        route = q.get("route")
        if route and route not in self.bundle.meta["routes"]:
            raise ApiError(400, "bad_route", f"route는 {', '.join(self.bundle.meta['routes'])} 중 하나입니다")
        return route

    # ----- 조회 -----
    def metadata(self, q):
        b = self.bundle
        run = self.latest_run()
        return {"service": "전북 고속도로 결빙 위험도 API", "version": "1.0", "now": iso(self.clock()), "simulated_clock": self.simulated,
                "history": {"periods": b.period_text(), "n_hours": b.n_hours, "step": "1h", "timezone": "+09:00"},
                "segments": b.n_seg, "stations": b.n_st, "routes": b.meta["routes"], "segment_length_m": b.meta["segment_length_m"],
                "grade_counts": b.meta["grade_counts"], "grades": b.criteria["grades"], "weights": b.criteria["weights"],
                "icing_condition": b.criteria["icing_condition"], "model_prediction": b.criteria["model_prediction"],
                "models": b.meta["models"], "performance": b.meta["performance"],
                "station_validation_spearman": b.meta["station_validation_spearman"], "event_days": b.meta["event_days"],
                "live": {"freshness": self.freshness(run), "source": run["source"] if run else None, "ingest_enabled": bool(self.token)},
                "naver": {"map_key": bool(self.naver_key_id), "directions": naver.configured()},
                "vulnerable_sections": bool(b.vulnerable), "branches": len(self.branches or []),
                "bundle_generated_at": b.meta["generated_at"], "notes": [STATUS_NOTE]}

    def segments(self, q):
        route = self.route_filter(q)
        feats = [f for f in self.bundle.segments if not route or f["properties"]["route"] == route]
        return {"type": "FeatureCollection", "features": feats}

    def facilities(self, q):
        return {"type": "FeatureCollection", "features": self.bundle.facilities}

    def segment(self, seg_id, q):
        b = self.bundle
        f = b.segments[self.seg(seg_id)]
        p = f["properties"]
        indicators = [{"code": i["code"], "factor": i["factor"], "name": i["name"], "level": p["levels"][i["code"]], "levels": i["levels"],
                       "basis": i["basis"]} for i in b.criteria["indicators"]]
        grade = next(g for g in b.criteria["grades"] if g["grade"] == p["grade"])
        stations = [b.stations[b.stn_index[s]] for s in p["stations"]]
        return {"type": "Feature", "geometry": f["geometry"], "properties": p, "grade": grade, "indicators": indicators, "stations": stations,
                "weights": b.criteria["weights"], "factor_rule": b.criteria["factor_rule"]}

    def timeseries(self, seg_id, q):
        b = self.bundle
        s = self.seg(seg_id)
        start = parse_time(q.get("from"), "from").replace(minute=0, second=0, microsecond=0)
        end = parse_time(q["to"], "to") if q.get("to") else start + timedelta(hours=23)
        if end < start:
            raise ApiError(400, "bad_range", "to가 from보다 앞입니다")
        if end - start > timedelta(days=MAX_SERIES_DAYS):
            raise ApiError(400, "range_too_long", f"한 번에 {MAX_SERIES_DAYS}일까지 조회합니다")
        hours, t = [], start
        while t <= end:
            h = b.hour_index(t)
            if h >= 0:
                hours.append(h)
            t += timedelta(hours=1)
        if not hours:
            raise ApiError(404, "outside_history", "요청한 기간에 과거 재생 자료가 없습니다")
        series = []
        for h in hours:
            r = b.segment_record(s, h)
            series.append({"time": iso(b.time_of(h)), "rst_est": r["rst_est"], "p_icing": r["p_icing"], "state": r["state"],
                           "condition": r["condition"], "prediction": r["prediction"], "status": r["status"]["label"]})
        stations = []
        for stn in b.segments[s]["properties"]["stations"]:
            j = b.stn_index[stn]
            obs = []
            for h in hours:
                rst, st = b.obs_at(h, j)
                obs.append({"time": iso(b.time_of(h)), "rst": rst, "road_state": road_state_info(st)})
            stations.append({"stn": stn, "name": b.stations[j]["name"], "holdout": b.stations[j]["holdout"], "observations": obs})
        return {"seg_id": seg_id, "route": b.segments[s]["properties"]["route"], "grade": b.segments[s]["properties"]["grade"], "step": "1h",
                "series": series, "stations": stations, "notes": [STATUS_NOTE]}

    def status(self, q):
        b = self.bundle
        mode = q.get("mode", "live")
        route = self.route_filter(q)
        if mode == "history":
            at = parse_time(q.get("at"), "at")
            h = b.require_hour(at)
            segs = [b.segment_record(s, h) for s in range(b.n_seg)]
            stations = [b.station_record(j, h) for j in range(b.n_st)]
            head = {"mode": "history", "requested_at": iso(at), "data_time": iso(b.time_of(h)), "source": "제출 분석 결과 (과거 재생)"}
        elif mode == "live":
            head, segs, stations = self.live_snapshot()
        else:
            raise ApiError(400, "bad_mode", "mode는 history 또는 live입니다")
        if route:
            segs = [r for r in segs if r["route"] == route]
        out = {**head, "summary": self.summarize(segs), "notes": [STATUS_NOTE]}
        if q.get("format") == "geojson":
            geom = {f["properties"]["seg_id"]: f["geometry"] for f in b.segments}
            return {"type": "FeatureCollection", **out, "stations": stations,
                    "features": [{"type": "Feature", "geometry": geom[r["seg_id"]], "properties": r} for r in segs]}
        return {**out, "segments": segs, "stations": stations}

    def live_snapshot(self):
        b = self.bundle
        run = self.latest_run()
        fresh = self.freshness(run)
        usable = fresh["state"] == "fresh"
        common = dict(zip(("code", "label", "basis"), STALE if run else NO_LIVE))
        segs = []
        for f in b.segments:
            p = f["properties"]
            rec = run["segments"].get(p["seg_id"], {}) if usable else {}
            code = live_state_code(rec)
            segs.append({"seg_id": p["seg_id"], "route": p["route"], "grade": p["grade"], "rst_est": rec.get("rst_est"),
                         "p_icing": rec.get("p_icing"), "state": code, "condition": rec.get("condition"), "prediction": rec.get("prediction"),
                         "status": state_info(code) if usable else common})
        stations = []
        for s in b.stations:
            rec = run["stations"].get(s["stn"]) if usable else None
            rs = rec.get("road_state") if rec else None
            item = {"stn": s["stn"], "name": s["name"], "seg_id": s["seg_id"], "holdout": s["holdout"],
                    "observed_at": rec.get("observed_at") if rec else None, "rst": rec.get("rst") if rec else None,
                    "road_state": road_state_info(rs), "icing_related_observed": None if rs is None else rs in b.label_states}
            if rs == 4:
                item["observation_label"] = "결빙 관측(센서 보고)" if run["quality"] == "valid" else "결빙 보고·품질 미확인"
            stations.append(item)
        head = {"mode": "live", "now": iso(self.clock()), "simulated_clock": self.simulated, "freshness": fresh,
                "data_time": run["valid_time"] if run else None, "source": run["source"] if run else None,
                "quality": run["quality"] if run else None, "inputs": run["inputs"] if run else None}
        return head, segs, stations

    @staticmethod
    def summarize(segs):
        known = [r for r in segs if r["state"] is not None]
        temps = [r["rst_est"] for r in segs if r["rst_est"] is not None]
        return {"segments": len(segs), "with_data": len(known), "condition": sum(r["state"] in (1, 3) for r in known),
                "prediction": sum(r["state"] in (2, 3) for r in known), "min_rst": min(temps) if temps else None}

    def nearest(self, q):
        lat, lon = number(q, "lat", lo=32, hi=39.5), number(q, "lon", lo=123, hi=132)
        max_m = number(q, "max_m", 2000.0, 1, 20000)
        hit = self.index.nearest(lon, lat, max_m)
        if hit is None:
            raise ApiError(404, "no_segment", f"{max_m:.0f}m 안에 구간이 없습니다")
        s, dist, along = hit
        p = self.bundle.segments[s]["properties"]
        return {"seg_id": p["seg_id"], "route": p["route"], "distance_m": round(dist, 1), "km": round(p["km_from"] + along / 1000, 2),
                "grade": p["grade"], "score": p["score"], "sigungu": p["sigungu"]}

    # ----- 경로 -----
    def risk_context(self, mode, at):
        """모드에 맞는 출발 시각과 현재 수신 자료."""
        if mode == "history":
            return parse_time(at, "at"), None, None
        if mode != "live":
            raise ApiError(400, "bad_mode", "mode는 history 또는 live입니다")
        run = self.latest_run()
        return (parse_time(at, "at") if at else self.clock()), run, self.freshness(run)

    def risk_response(self, visits, total_m, sec_per_m, mode, depart, run, fresh, extra):
        rows, summary = ops.route_rows(self.bundle, visits, depart, sec_per_m, mode, run, fresh)
        notes = [STATUS_NOTE]
        if mode == "live":
            notes.append("현재 모드는 통과 예상 시각이 아니라 마지막 수신 시각의 상태를 보여 줍니다. 앞으로의 예보가 아닙니다.")
        else:
            notes.append("과거 재생 모드는 그 시각에 출발했다면 어땠을지를 분석 결과로 보여 줍니다.")
        return {"mode": mode, "departure": iso(depart), "path_km": round(total_m / 1000, 2), "matched_km": round(sum(e - a for _, a, e in visits) / 1000, 2),
                "freshness": fresh, "summary": summary, "segments": rows, "notes": notes, **extra}

    def route_risk(self, body):
        if not isinstance(body, dict):
            raise ApiError(400, "bad_payload", "JSON 객체를 보내야 합니다")
        path = body.get("path")
        if not isinstance(path, list) or not 2 <= len(path) <= MAX_PATH_POINTS:
            raise ApiError(400, "bad_path", f"path는 [경도, 위도] 좌표 2~{MAX_PATH_POINTS}개입니다")
        for k, c in enumerate(path):
            if not (isinstance(c, list) and len(c) == 2 and finite(c[0]) and finite(c[1]) and 123 <= c[0] <= 132 and 32 <= c[1] <= 39.5):
                raise ApiError(400, "bad_path", f"path[{k}]는 국내 범위의 [경도, 위도]입니다")
        buffer_m = body.get("buffer_m", 60)
        if not (finite(buffer_m) and 5 <= buffer_m <= 300):
            raise ApiError(400, "bad_parameter", "buffer_m은 5~300입니다")
        duration = body.get("duration_s")
        if duration is not None and not (finite(duration) and duration > 0):
            raise ApiError(400, "bad_parameter", "duration_s는 양수입니다")
        mode = body.get("mode", "history")
        depart, run, fresh = self.risk_context(mode, body.get("at"))
        matches, total = geo.match_path(self.index, path, float(buffer_m))
        return self.path_response(matches, total, duration, mode, depart, run, fresh, {})

    def path_response(self, matches, total, duration, mode, depart, run, fresh, extra):
        visits = [(m["seg"], m["enter_m"], m["exit_m"]) for m in matches]
        if duration:
            sec_per_m, extra = duration / total, {**extra, "travel": {"basis": "duration_s", "duration_s": duration}}
        else:
            sec_per_m, extra = 3.6 / DEFAULT_SPEED_KMH, {**extra, "travel": {"basis": "assumed_speed", "speed_kmh": DEFAULT_SPEED_KMH}}
        return self.risk_response(visits, total, sec_per_m, mode, depart, run, fresh, extra)

    def stretch(self, q):
        """네이버 키 없이 노선 위 km 범위의 위험을 본다."""
        route = self.route_filter(q)
        if not route:
            raise ApiError(400, "missing_parameter", "route가 필요합니다")
        rows = [(s, f["properties"]) for s, f in enumerate(self.bundle.segments) if f["properties"]["route"] == route]
        max_km = max(p["km_to"] for _, p in rows)
        km0, km1 = (min(number(q, name, default, 0, 1000), max_km) for name, default in (("from_km", 0.0), ("to_km", max_km)))  # 노선 끝을 넘으면 끝까지
        speed = number(q, "speed_kmh", DEFAULT_SPEED_KMH, 10, 130)
        lo, hi = min(km0, km1), max(km0, km1)
        mode = q.get("mode", "history")
        depart, run, fresh = self.risk_context(mode, q.get("at"))
        picked = sorted((r for r in rows if r[1]["km_to"] > lo and r[1]["km_from"] < hi), key=lambda r: r[1]["km_from"], reverse=km0 > km1)
        visits = []
        for s, p in picked:
            a, e = max(p["km_from"], lo), min(p["km_to"], hi)
            enter, exit_ = (a - lo, e - lo) if km0 <= km1 else (hi - e, hi - a)
            visits.append((s, enter * 1000, exit_ * 1000))
        return self.risk_response(visits, (hi - lo) * 1000, 3.6 / speed, mode, depart, run, fresh,
                                  {"route": route, "from_km": km0, "to_km": km1, "travel": {"basis": "assumed_speed", "speed_kmh": speed}})

    def naver_directions(self, q):
        start, goal = naver.lonlat(q.get("start"), "start"), naver.lonlat(q.get("goal"), "goal")
        waypoints = [naver.lonlat(w, "waypoints") for w in q["waypoints"].split("|")] if q.get("waypoints") else None
        mode = q.get("mode", "history")
        depart, run, fresh = self.risk_context(mode, q.get("at"))
        route = naver.directions(start, goal, q.get("option", "traoptimal"), waypoints)
        matches, total = geo.match_path(self.index, route["path"], number(q, "buffer_m", 60.0, 5, 300))
        extra = {"route": {"distance_m": route["distance_m"], "duration_s": route["duration_s"], "sections": route["sections"]}, "path": route["path"]}
        return self.path_response(matches, total, route["duration_s"], mode, depart, run, fresh, extra)

    # ----- 입력·참고 -----
    def ingest(self, body, authorization):
        if not self.token:
            raise ApiError(403, "ingest_disabled", "서버에 ICING_INGEST_TOKEN이 없어 입력 경로가 닫혀 있습니다")
        given = authorization[7:] if authorization.startswith("Bearer ") else ""
        if not hmac.compare_digest(given.encode(), self.token.encode()):
            raise ApiError(401, "unauthorized", "입력 인증값이 맞지 않습니다")
        return self.live.ingest(body, self.clock())

    def cctv(self, q):
        run = self.latest_run("cctv")
        fresh = self.freshness(run)
        items = run["reference"]["cctv"] if run and fresh["state"] == "fresh" else []
        return {"freshness": fresh, "source": "기상청 CCTV 기반 도로날씨정보", "items": items,
                "notes": ["고속도로 CCTV 특성상 야간 판별 성능이 낮습니다. 주간 정보 위주로 참고하세요."]}

    def briefing(self, q):
        mode = q.get("mode", "history")
        group, top = q.get("group", "sigungu"), int(number(q, "top", 5.0, 1, 50))
        if mode == "live":
            run = self.latest_run()
            return ops.live_briefing(self.bundle, run, self.freshness(run), group, top, self.branches)
        if mode != "history":
            raise ApiError(400, "bad_mode", "mode는 history 또는 live입니다")
        return ops.history_briefing(self.bundle, parse_time(q.get("start"), "start"), int(number(q, "hours", 15.0, 1, 72)), group, top, self.branches)

    def vulnerable(self, q):
        if not self.bundle.vulnerable_meta:
            raise ApiError(404, "no_vulnerable_data", "기존 결빙취약구간 비교 자료가 없습니다. ops/vulnerable_sections.py를 먼저 실행하세요")
        return {**self.bundle.vulnerable_meta, "geojson": self.bundle.vulnerable}

    def config_js(self):
        cfg = {"naverKeyId": self.naver_key_id, "directions": naver.configured(), "ttlMinutes": self.ttl, "simulatedClock": self.simulated}
        return "window.ICING_CONFIG = " + json.dumps(cfg, ensure_ascii=False).replace("<", "\\u003c") + ";\n"


GET_ROUTES = [
    (r"/api/v1/metadata", lambda s, q: s.metadata(q)),
    (r"/api/v1/segments", lambda s, q: s.segments(q)),
    (r"/api/v1/facilities", lambda s, q: s.facilities(q)),
    (r"/api/v1/stations", lambda s, q: {"stations": s.bundle.stations}),
    (r"/api/v1/segments/([A-Z]{2}-\d{3})", lambda s, q, i: s.segment(i, q)),
    (r"/api/v1/segments/([A-Z]{2}-\d{3})/timeseries", lambda s, q, i: s.timeseries(i, q)),
    (r"/api/v1/status", lambda s, q: s.status(q)),
    (r"/api/v1/current", lambda s, q: s.status({**q, "mode": "live"})),
    (r"/api/v1/nearest", lambda s, q: s.nearest(q)),
    (r"/api/v1/route-risk/stretch", lambda s, q: s.stretch(q)),
    (r"/api/v1/naver/directions", lambda s, q: s.naver_directions(q)),
    (r"/api/v1/reference/cctv", lambda s, q: s.cctv(q)),
    (r"/api/v1/ops/briefing", lambda s, q: s.briefing(q)),
    (r"/api/v1/ops/vulnerable", lambda s, q: s.vulnerable(q)),
]
GET_ROUTES = [(re.compile(p + "$"), f) for p, f in GET_ROUTES]


class Handler(BaseHTTPRequestHandler):
    server_version = "IcingRiskAPI/1.0"
    sys_version = ""
    verbose = False

    def log_message(self, fmt, *args):
        if self.verbose:
            super().log_message(fmt, *args)

    def send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, status, obj):
        kind = "application/geo+json" if isinstance(obj, dict) and obj.get("type") == "FeatureCollection" else "application/json"
        self.send(status, json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8"), kind + "; charset=utf-8")

    def guarded(self, work):
        try:
            work()
        except ApiError as exc:
            self.send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:  # 내부 오류 내용은 화면에 보내지 않고 서버 창에만 남긴다
            traceback.print_exc()
            self.send_json(500, {"error": {"code": "internal_error", "message": "서버 내부 오류입니다"}})

    def do_GET(self):
        self.guarded(self.handle_get)

    do_HEAD = do_GET

    def do_POST(self):
        self.guarded(self.handle_post)

    def handle_get(self):
        url = urlsplit(self.path)
        service = self.server.service
        q = {k: v[-1] for k, v in parse_qs(url.query).items()}
        if url.path.startswith("/api/"):
            for pattern, func in GET_ROUTES:
                m = pattern.match(url.path)
                if m:
                    self.send_json(200, func(service, q, *m.groups()))
                    return
            raise ApiError(404, "not_found", f"{url.path} 경로가 없습니다. /api-docs를 보세요")
        if url.path == "/config.js":
            self.send(200, service.config_js().encode("utf-8"), "text/javascript; charset=utf-8")
            return
        self.serve_file(url.path)

    def serve_file(self, path):
        target = STATIC_PAGES.get(path)
        if target is None and path.startswith("/static/"):
            root = (HERE / "static").resolve()
            target = (root / path[len("/static/"):]).resolve()
            if root not in target.parents:
                raise ApiError(404, "not_found", "파일이 없습니다")
        if target is None or not target.is_file():
            if path == "/atlas":
                raise ApiError(404, "not_built", "먼저 python build_risk_map.py로 지도를 만드세요")
            raise ApiError(404, "not_found", "파일이 없습니다")
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".geojson":
            kind = "application/geo+json"
        if kind.startswith("text/") or kind.endswith(("javascript", "json")):
            kind += "; charset=utf-8"
        self.send(200, target.read_bytes(), kind)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise ApiError(411, "length_required", "Content-Length가 필요합니다") from None
        if length > MAX_BODY:
            raise ApiError(413, "too_large", f"본문은 {MAX_BODY // 1024 // 1024}MB까지입니다")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ApiError(400, "bad_json", "본문이 올바른 JSON이 아닙니다") from None

    def handle_post(self):
        path = urlsplit(self.path).path
        service = self.server.service
        if path == "/api/v1/route-risk":
            self.send_json(200, service.route_risk(self.read_json()))
        elif path == "/api/v1/ingest":
            auth = self.headers.get("Authorization", "")
            service_token_ok = service.token and hmac.compare_digest(auth[7:].encode() if auth.startswith("Bearer ") else b"", service.token.encode())
            body = self.read_json() if service_token_ok else None  # 인증 전에는 본문을 해석하지 않는다
            self.send_json(201, service.ingest(body, auth))
        else:
            raise ApiError(404, "not_found", f"{path} 경로가 없습니다")


def make_server(service, host="127.0.0.1", port=8000):
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.service = service
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--bundle", type=Path, default=BASE / "bundle")
    parser.add_argument("--db", type=Path, default=HERE / "data" / "live.sqlite3")
    parser.add_argument("--config", type=Path, default=HERE / "config.local.json")
    parser.add_argument("--branches", type=Path, help="지사 위치 CSV (지사명·위도·경도)")
    parser.add_argument("--sim-clock", help="시연용: 서버 시각을 이 시각에서 시작한다. 재생 입력을 '현재'처럼 볼 때만 쓴다")
    parser.add_argument("--open", action="store_true", help="기본 웹브라우저에서 열기")
    parser.add_argument("--verbose", action="store_true", help="요청 기록 출력")
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8")) if args.config.exists() else {}
    clock = None
    if args.sim_clock:
        base, t0 = parse_time(args.sim_clock, "--sim-clock"), time.monotonic()
        clock = lambda: base + timedelta(seconds=time.monotonic() - t0)  # noqa: E731
    try:
        service = Service(args.bundle, args.db, cfg.get("observation_ttl_minutes", 90), cfg.get("naver_key_id", ""),
                          os.environ.get("ICING_INGEST_TOKEN"), clock, ops.load_branches(args.branches) if args.branches else None,
                          simulated=bool(args.sim_clock))
    except (OSError, ValueError) as exc:
        print(f"실행 오류: {exc}", file=sys.stderr)
        return 1
    Handler.verbose = args.verbose
    server = make_server(service, args.host, args.port)
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    print(f"구간 {service.bundle.n_seg}개, 시각 {service.bundle.n_hours:,}개를 읽었습니다.")
    print(f"화면 {url}  /  API 설명 {url}/api-docs  /  종료 Ctrl+C")
    print(f"네이버 지도 배경 {'켜짐' if service.naver_key_id else '꺼짐(내장 지도 사용)'}, Directions 5 {'켜짐' if naver.configured() else '꺼짐'}, "
          f"입력 경로 {'열림' if service.token else '닫힘'}")
    if args.sim_clock:
        print(f"시연 시각 사용 중: {iso(service.clock())} (실제 시각이 아닙니다)")
    if args.host != "127.0.0.1":
        print("주의: 같은 네트워크의 다른 기기가 접속할 수 있습니다. 공개 운영용 서버가 아닙니다.")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
