"""API 검사. 실행: python -m unittest discover -s service -p "test_*.py" -v

실제 서버를 임시 포트에 띄워 HTTP로 확인합니다. 합성 입력은 임시 DB에만 넣습니다.
네이버 Directions 5는 공식 문서의 응답 형식을 따른 가짜 서버로 대체합니다 (실제 키로 호출한 검사가 아닙니다).
"""

import gzip
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import geo  # noqa: E402
import naver  # noqa: E402
import ops  # noqa: E402
from server import Service, make_server  # noqa: E402
from store import KST, ApiError, parse_time  # noqa: E402

BUNDLE = HERE.parent / "bundle"
TOKEN = "test-token"
AT = "2025-02-07T03:00:00+09:00"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 1, 15, 6, 10, tzinfo=KST)

    def __call__(self):
        return self.now


class FakeDirections(BaseHTTPRequestHandler):
    """공식 문서의 Directions 5 응답 구조를 흉내 낸다."""
    path_points = []
    seen = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        FakeDirections.seen.append({"key_id": self.headers.get("x-ncp-apigw-api-key-id"), "key": self.headers.get("x-ncp-apigw-api-key"), "url": self.path})
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if q["start"] == q["goal"]:
            body, status = {"code": 1, "message": "same"}, 400
        else:
            route = {"summary": {"distance": 12000, "duration": 480000}, "path": FakeDirections.path_points,
                     "section": [{"pointIndex": 0, "pointCount": 3, "distance": 12000, "name": "서해안고속도로", "congestion": 1, "speed": 90}]}
            body, status = {"code": 0, "message": "ok", "route": {q["option"][0]: [route]}}, 200
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ApiCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.clock = Clock()
        cls.service = Service(BUNDLE, Path(cls.tmp) / "live.sqlite3", 90, "public-id", TOKEN, cls.clock)
        cls.server = make_server(cls.service, "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.fake = HTTPServer(("127.0.0.1", 0), FakeDirections)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.fake.shutdown()
        cls.fake.server_close()
        cls.service.live.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        live = self.service.live
        with live.lock, live.db:
            for table in ("runs", "run_segments", "run_stations", "run_reference"):
                live.db.execute(f"DELETE FROM {table}")

    def get(self, path, **params):
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        try:
            with urllib.request.urlopen(url) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def post(self, path, body, token=None):
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def raw_state(self, h, s):
        meta = self.service.bundle.meta
        return gzip.decompress((BUNDLE / meta["arrays"]["state"]["file"]).read_bytes())[h * meta["n_segments"] + s]

    def seg_coords(self, ids):
        b = self.service.bundle
        path, first_len = [], 0
        for sid in ids:
            g = b.segments[b.seg_index[sid]]["geometry"]
            line = g["coordinates"] if g["type"] == "LineString" else [c for part in g["coordinates"] for c in part]
            if path:  # 구간 선의 진행 방향이 남북으로 섞일 수 있어 이전 끝점에 가까운 쪽부터 잇는다
                d = lambda c: (c[0] - path[-1][0]) ** 2 + (c[1] - path[-1][1]) ** 2
                if d(line[-1]) < d(line[0]):
                    line = line[::-1]
                if len(path) == first_len and d(line[0]) > (path[0][0] - line[0][0]) ** 2 + (path[0][1] - line[0][1]) ** 2:
                    path.reverse()  # 첫 구간은 둘째 구간이 이어지는 쪽으로 뒤집는다
            path.extend(line)
            first_len = first_len or len(path)
        return path

    def payload(self, run_id, valid, **kw):
        ids = self.service.bundle.seg_ids
        p = {"run_id": run_id, "valid_time": valid, "source": "test", "quality": "valid",
             "segments": [{"seg_id": ids[0], "rst_est": -2.5, "p_icing": 0.9, "condition": True, "prediction": True},
                          {"seg_id": ids[1], "rst_est": 3.0, "p_icing": 0.0, "condition": False, "prediction": False}],
             "stations": [{"stn": 12410, "observed_at": valid, "rst": -1.0, "road_state": 4}]}
        p.update(kw)
        return p

    # ----- 조회 -----
    def test_metadata(self):
        status, m = self.get("/api/v1/metadata")
        self.assertEqual(status, 200)
        self.assertEqual(m["segments"], 233)
        self.assertEqual(m["history"]["n_hours"], 5760)
        self.assertEqual(sum(m["grade_counts"].values()), 233)
        self.assertTrue(m["naver"]["map_key"])

    def test_segments_filter(self):
        _, all_ = self.get("/api/v1/segments")
        self.assertEqual(len(all_["features"]), 233)
        _, td = self.get("/api/v1/segments", route="통영-대전중부선")
        self.assertEqual(len(td["features"]), 47)
        self.assertEqual(self.get("/api/v1/segments", route="경부선")[0], 400)

    def test_segment_detail(self):
        status, d = self.get("/api/v1/segments/TD-014")
        self.assertEqual(status, 200)
        self.assertEqual(d["properties"]["grade"], "심각")
        self.assertEqual(len(d["indicators"]), 8)
        self.assertEqual(self.get("/api/v1/segments/XX-999")[0], 404)

    def test_history_matches_bundle(self):
        status, r = self.get("/api/v1/status", mode="history", at=AT)
        self.assertEqual(status, 200)
        self.assertEqual(r["data_time"], "2025-02-07T03:00+09:00")
        b = self.service.bundle
        h = b.hour_index(parse_time(AT))
        for s in (0, 57, 232):
            self.assertEqual(r["segments"][s]["state"], self.raw_state(h, s))
            self.assertEqual(r["segments"][s]["seg_id"], b.seg_ids[s])
        self.assertEqual(len(r["stations"]), 17)

    def test_history_unencoded_plus(self):
        with urllib.request.urlopen(self.base + "/api/v1/status?mode=history&at=2025-02-07T03:00+09:00") as resp:
            self.assertEqual(json.load(resp)["data_time"], "2025-02-07T03:00+09:00")

    def test_history_outside_period(self):
        status, r = self.get("/api/v1/status", mode="history", at="2025-07-01T00:00+09:00")
        self.assertEqual(status, 404)
        self.assertEqual(r["error"]["code"], "outside_history")

    def test_geojson_status(self):
        _, r = self.get("/api/v1/status", mode="history", at=AT, format="geojson", route="호남선")
        self.assertEqual(r["type"], "FeatureCollection")
        self.assertEqual(len(r["features"]), 86)

    def test_timeseries_with_station(self):
        seg = next(s for s in self.service.bundle.stations if s["stn"] == 12410)["seg_id"]
        status, r = self.get(f"/api/v1/segments/{seg}/timeseries", **{"from": "2025-01-28T00:00+09:00"})
        self.assertEqual(status, 200)
        self.assertEqual(len(r["series"]), 24)
        self.assertEqual(r["stations"][0]["stn"], 12410)
        self.assertEqual(len(r["stations"][0]["observations"]), 24)
        self.assertEqual(self.get(f"/api/v1/segments/{seg}/timeseries", **{"from": "2025-01-01", "to": "2025-02-20"})[0], 400)

    def test_timeseries_skips_summer_gap(self):
        _, r = self.get("/api/v1/segments/SH-001/timeseries", **{"from": "2025-02-28T22:00", "to": "2025-03-02T00:00"})
        self.assertEqual(len(r["series"]), 2)

    def test_nearest_station(self):
        for s in self.service.bundle.stations[:6]:
            status, r = self.get("/api/v1/nearest", lat=s["lat"], lon=s["lon"])
            self.assertEqual(status, 200)
            self.assertEqual(r["seg_id"], s["seg_id"])
        self.assertEqual(self.get("/api/v1/nearest", lat=37.5, lon=127.0)[0], 404)

    # ----- 경로 -----
    def test_route_risk_order_and_eta(self):
        ids = [f"SH-{k:03d}" for k in range(10, 21)]
        status, r = self.post("/api/v1/route-risk", {"path": self.seg_coords(ids), "mode": "history", "at": AT, "duration_s": 480})
        self.assertEqual(status, 200)
        got = [x["seg_id"] for x in r["segments"]]
        self.assertEqual(got, ids)
        etas = [x["eta"] for x in r["segments"]]
        self.assertEqual(etas, sorted(etas))
        self.assertGreater(r["matched_km"], 9)
        self.assertEqual(r["travel"]["basis"], "duration_s")

    def test_route_risk_off_road(self):
        status, r = self.post("/api/v1/route-risk", {"path": [[127.2, 35.5], [127.25, 35.55]], "mode": "history", "at": AT})
        self.assertEqual(status, 200)
        self.assertEqual(r["segments"], [])

    def test_route_risk_rejects_bad_path(self):
        self.assertEqual(self.post("/api/v1/route-risk", {"path": [[35.5, 127.2], [35.6, 127.3]], "at": AT})[0], 400)
        self.assertEqual(self.post("/api/v1/route-risk", {"path": [[127.2, 35.5]], "at": AT})[0], 400)

    def test_stretch_both_directions(self):
        _, up = self.get("/api/v1/route-risk/stretch", route="호남선", from_km=10, to_km=20, at=AT)
        _, down = self.get("/api/v1/route-risk/stretch", route="호남선", from_km=20, to_km=10, at=AT)
        self.assertGreater(len(up["segments"]), 8)
        self.assertEqual([x["seg_id"] for x in up["segments"]], [x["seg_id"] for x in down["segments"]][::-1])
        self.assertLessEqual(up["segments"][0]["eta"], up["segments"][-1]["eta"])
        self.assertLessEqual(down["segments"][0]["eta"], down["segments"][-1]["eta"])

    def test_stretch_clamps_to_route_end(self):
        status, r = self.get("/api/v1/route-risk/stretch", route="통영-대전중부선", from_km=40, to_km=47, at=AT)
        self.assertEqual(status, 200)
        self.assertEqual(r["segments"][-1]["seg_id"], "TD-047")

    def test_naver_requires_keys(self):
        os.environ.pop("NCP_MAPS_KEY_ID", None)
        os.environ.pop("NCP_MAPS_KEY", None)
        status, r = self.get("/api/v1/naver/directions", start="126.8,35.6", goal="126.8,35.7", at=AT)
        self.assertEqual(status, 503)
        self.assertEqual(r["error"]["code"], "naver_not_configured")

    def test_naver_directions_flow(self):
        FakeDirections.path_points = self.seg_coords([f"HN-{k:03d}" for k in range(30, 41)])
        os.environ.update({"NCP_MAPS_KEY_ID": "kid", "NCP_MAPS_KEY": "secret-key",
                           "NCP_MAPS_DIRECTIONS_URL": f"http://127.0.0.1:{self.fake.server_address[1]}/map-direction/v1/driving"})
        try:
            status, r = self.get("/api/v1/naver/directions", start="126.8,35.6", goal="126.9,35.7", at=AT)
            self.assertEqual(status, 200)
            self.assertEqual(r["route"]["duration_s"], 480)  # 밀리초를 초로 바꿨는지
            self.assertEqual(r["segments"][0]["seg_id"], "HN-030")
            self.assertEqual(FakeDirections.seen[-1]["key"], "secret-key")
            self.assertNotIn("secret-key", json.dumps(r))
            status, r = self.get("/api/v1/naver/directions", start="126.8,35.6", goal="126.8,35.6", at=AT)
            self.assertEqual(status, 422)
            self.assertEqual(self.get("/api/v1/naver/directions", start="35.6,126.8", goal="126.8,35.6", at=AT)[0], 400)
            with urllib.request.urlopen(self.base + "/config.js") as resp:
                self.assertNotIn("secret-key", resp.read().decode())
        finally:
            for k in ("NCP_MAPS_KEY_ID", "NCP_MAPS_KEY", "NCP_MAPS_DIRECTIONS_URL"):
                os.environ.pop(k, None)

    # ----- 현재 수신 -----
    def test_live_lifecycle(self):
        self.clock.now = datetime(2026, 1, 15, 6, 10, tzinfo=KST)
        valid = "2026-01-15T06:00+09:00"
        self.assertEqual(self.post("/api/v1/ingest", self.payload("r0", valid))[0], 401)
        self.assertEqual(self.post("/api/v1/ingest", self.payload("r0", valid), "wrong")[0], 401)
        status, r = self.post("/api/v1/ingest", self.payload("r1", valid, reference={"cctv": [{"lat": 35.8, "lon": 127.1, "wh_cd": 31}]}), TOKEN)
        self.assertEqual(status, 201)
        self.assertEqual(r["segments"], 2)
        self.assertEqual(self.post("/api/v1/ingest", self.payload("r1", valid), TOKEN)[0], 409)

        _, cur = self.get("/api/v1/current")
        self.assertEqual(cur["freshness"]["state"], "fresh")
        self.assertEqual(cur["segments"][0]["state"], 3)
        self.assertEqual(cur["segments"][1]["state"], 0)
        self.assertIsNone(cur["segments"][2]["state"])  # 보내지 않은 구간은 자료 없음
        self.assertEqual(cur["segments"][2]["status"]["code"], "no_data")
        st = next(s for s in cur["stations"] if s["stn"] == 12410)
        self.assertEqual(st["observation_label"], "결빙 관측(센서 보고)")
        self.assertEqual(len(self.get("/api/v1/reference/cctv")[1]["items"]), 1)

        self.clock.now = datetime(2026, 1, 15, 7, 45, tzinfo=KST)  # 105분 뒤 → 신선도 90분 초과
        _, cur = self.get("/api/v1/current")
        self.assertEqual(cur["freshness"]["state"], "stale")
        self.assertIsNone(cur["segments"][0]["rst_est"])
        self.assertEqual(cur["segments"][0]["status"]["code"], "stale")
        self.assertEqual(self.get("/api/v1/reference/cctv")[1]["items"], [])
        self.clock.now = datetime(2026, 1, 15, 6, 10, tzinfo=KST)

    def test_ingest_validation(self):
        self.clock.now = datetime(2026, 1, 16, 6, 10, tzinfo=KST)
        valid = "2026-01-16T06:00+09:00"
        bad = [self.payload("b1", "2026-01-16T06:30+09:00"),
               self.payload("b2", valid, segments=[{"seg_id": "XX-001"}]),
               self.payload("b3", valid, segments=[{"seg_id": "SH-001", "rst_est": 200}]),
               self.payload("b4", valid, segments=[{"seg_id": "SH-001", "p_icing": 1.5}]),
               self.payload("b5", valid, stations=[{"stn": 12410, "observed_at": valid, "road_state": 99}]),
               self.payload("b 6", valid), self.payload("b7", valid, quality="good"), self.payload("b8", valid, segments=[], stations=[])]
        for p in bad:
            self.assertEqual(self.post("/api/v1/ingest", p, TOKEN)[0], 400, p["run_id"])
        self.assertEqual(self.service.live.count(), 0)  # 하나라도 틀리면 아무것도 저장하지 않는다

    def test_future_run_hidden_by_clock(self):
        """시연 시각을 앞당겨도 DB의 더 뒤 시각 실행을 현재로 보이지 않는다."""
        self.clock.now = datetime(2026, 1, 20, 6, 10, tzinfo=KST)
        self.post("/api/v1/ingest", self.payload("f1", "2026-01-20T06:00+09:00"), TOKEN)
        self.clock.now = datetime(2025, 1, 28, 6, 30, tzinfo=KST)
        _, cur = self.get("/api/v1/current")
        self.assertEqual(cur["freshness"]["state"], "no_data")
        self.assertEqual(cur["segments"][0]["status"]["code"], "no_live_data")

    def test_unverified_ice_label(self):
        self.clock.now = datetime(2026, 1, 17, 6, 10, tzinfo=KST)
        valid = "2026-01-17T06:00+09:00"
        self.post("/api/v1/ingest", self.payload("u1", valid, quality="unverified"), TOKEN)
        _, cur = self.get("/api/v1/current")
        self.assertEqual(next(s for s in cur["stations"] if s["stn"] == 12410)["observation_label"], "결빙 보고·품질 미확인")

    def test_keep_runs_limit(self):
        live = self.service.live
        keep, live.keep_runs = live.keep_runs, 3
        self.clock.now = datetime(2026, 2, 1, 12, 0, tzinfo=KST)
        for k in range(6):
            t = (self.clock.now - timedelta(minutes=60 - 10 * k)).isoformat()
            self.assertEqual(self.post("/api/v1/ingest", self.payload(f"k{k}", t), TOKEN)[0], 201)
        self.assertLessEqual(live.count(), 3)
        self.assertEqual(live.latest()["run_id"], "k5")
        live.keep_runs = keep

    # ----- 운영 -----
    def test_briefing_history(self):
        status, r = self.get("/api/v1/ops/briefing", start="2025-01-27T18:00+09:00", hours=15, group="sigungu", top=3)
        self.assertEqual(status, 200)
        self.assertEqual(r["window"]["hours"], 15)
        self.assertGreater(r["total"]["alert_segments"], 50)
        counts = [g["alert_segment_hours"] for g in r["groups"]]
        self.assertEqual(counts, sorted(counts, reverse=True))
        top = r["groups"][0]["top"]
        self.assertLessEqual(len(top), 3)
        self.assertGreaterEqual(top[0]["alert_hours"], 1)
        self.assertTrue(top[0]["grade_meaning"])

    def test_briefing_requires_branches(self):
        self.assertEqual(self.get("/api/v1/ops/briefing", start="2025-01-27T18:00+09:00", group="branch")[0], 409)

    def test_briefing_branch_group(self):
        branches = [{"name": "남쪽", "lat": 35.4, "lon": 126.8}, {"name": "북쪽", "lat": 36.0, "lon": 127.4}]
        r = ops.history_briefing(self.service.bundle, parse_time("2025-01-27T18:00+09:00"), 6, "branch", 2, branches)
        self.assertEqual({g["group"] for g in r["groups"]}, {"남쪽", "북쪽"})
        self.assertEqual(sum(g["segments"] for g in r["groups"]), 233)

    def test_load_branches_cp949(self):
        p = Path(self.tmp) / "b.csv"
        p.write_bytes("지사명,위도,경도\n전주지사,35.8,127.1\n".encode("cp949"))
        self.assertEqual(ops.load_branches(p), [{"name": "전주지사", "lat": 35.8, "lon": 127.1}])

    def test_briefing_crosses_period(self):
        with self.assertRaises(ApiError):
            ops.history_briefing(self.service.bundle, parse_time("2025-02-28T20:00+09:00"), 15)

    # ----- 화면·보안 -----
    def test_static(self):
        for path in ("/", "/api-docs", "/static/app.js", "/assets/d3.min.js", "/assets/municipalities.geojson"):
            with urllib.request.urlopen(self.base + path) as r:
                self.assertEqual(r.status, 200, path)
        with urllib.request.urlopen(self.base + "/config.js") as r:
            text = r.read().decode()
        self.assertIn('"naverKeyId": "public-id"', text)
        self.assertNotIn(TOKEN, text)

    def test_path_traversal(self):
        for path in ("/static/../server.py", "/static/%2e%2e/server.py", "/static/../../bundle/meta.json"):
            try:
                with urllib.request.urlopen(self.base + path) as r:
                    self.fail(f"{path} 응답 {r.status}")
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 404, path)

    def test_unknown_route(self):
        self.assertEqual(self.get("/api/v1/nope")[0], 404)


class GeoCase(unittest.TestCase):
    def test_projection_round_trip(self):
        x, y = geo.to_xy(127.2, 35.9)
        lon, lat = geo.to_lonlat(x, y)
        self.assertAlmostEqual(lon, 127.2, places=9)
        self.assertAlmostEqual(lat, 35.9, places=9)

    def test_distance_scale(self):
        x1, y1 = geo.to_xy(127.0, 35.5)
        x2, y2 = geo.to_xy(127.0, 36.0)
        self.assertAlmostEqual(abs(y2 - y1) / 1000, ops.distance_km(35.5, 127.0, 36.0, 127.0), delta=0.2)
        x2, _ = geo.to_xy(127.5, 35.75)
        self.assertAlmostEqual((x2 - x1) / 1000, ops.distance_km(35.75, 127.0, 35.75, 127.5), delta=0.2)

    def test_short_touch_is_ignored(self):
        feature = {"geometry": {"type": "LineString", "coordinates": [[127.0, 35.0], [127.0, 35.1]]}}
        index = geo.SegmentIndex([feature])
        # 구간을 약 30m만 스치는 경로는 지나간 것으로 보지 않는다
        path = [[126.999, 35.05], [127.0, 35.05], [127.0, 35.0503], [126.999, 35.0503]]
        self.assertEqual(geo.match_path(index, path, buffer_m=10)[0], [])

    def test_time_parsing(self):
        self.assertEqual(parse_time("2025-01-28 06:00").hour, 6)
        self.assertEqual(parse_time("2025-01-27T21:00:00Z").hour, 6)
        self.assertEqual(parse_time("2025-01-28T06").hour, 6)
        with self.assertRaises(ApiError):
            parse_time("어제")


class NaverCase(unittest.TestCase):
    def test_coordinate_order(self):
        self.assertEqual(naver.lonlat("127.1,35.8", "start"), (127.1, 35.8))
        with self.assertRaises(ApiError):
            naver.lonlat("35.8,127.1", "start")


if __name__ == "__main__":
    unittest.main()
