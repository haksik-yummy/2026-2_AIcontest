"""실시간 경로 검사. 프로젝트 환경에서 실행: python -m unittest discover -s realtime -p "test_*.py" -v

재생 검사는 제공 원자료를 그 시각까지만 넣어 노트북의 구간 추정(segment_estimates.parquet)과 비교합니다.
API 응답 해석 검사의 입력은 문서와 제공 CSV 열 순서로 만든 예시이며, 실제 API 응답으로 확인한 것이 아닙니다.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(HERE.parent / "service")]

import engine as E  # noqa: E402
import kma_client as K  # noqa: E402
import pipeline as P  # noqa: E402
from replay import ReplaySource  # noqa: E402

ESTIMATES = ROOT / "data" / "processed" / "segment_estimates.parquet"
KST = timezone(timedelta(hours=9))


class Parsers(unittest.TestCase):
    def asos_row(self, tm="202501280600", stn=146, ca=9, ts=-1.2, sd=3.5, ss=-9.0):
        vals = dict.fromkeys(K.ASOS_COLUMNS, "-9")
        vals.update({"TM": tm, "STN": stn, "CA_TOT": ca, "TS": ts, "SD_TOT": sd, "SS": ss})
        return " ".join(str(vals[c]) for c in K.ASOS_COLUMNS)

    def test_asos(self):
        text = "#START7777\n# YYMMDDHHMI STN WD ...\n" + self.asos_row() + "\n" + self.asos_row(stn=140, ca=-9, ts=-99.0, sd=-9.0, ss=0.4) + "\n#7777END\n"
        df = K.parse_asos(text)
        self.assertEqual(df["stn"].tolist(), [146, 140])
        self.assertEqual(df["time"].iloc[0], pd.Timestamp("2025-01-28 06:00"))
        self.assertEqual(df["cloud"].iloc[0], 9)
        self.assertEqual(df["tg"].iloc[0], -1.2)
        self.assertTrue(df[["cloud", "tg", "snow"]].iloc[1].isna().all())  # 결측 표기
        self.assertTrue(np.isnan(df["sunshine"].iloc[0]))
        cleaned = E.clean_asos(df)
        self.assertEqual(cleaned["snow"].iloc[1], 0)  # 빈칸은 눈 없음으로 (02-1과 같음)
        self.assertEqual(cleaned["sunshine"].iloc[0], 0)

    def test_asos_wrong_width(self):
        with self.assertRaises(K.KmaFormatError):
            K.parse_asos("202501280600 146 1 2 3\n")

    def test_aws_csv_and_space(self):
        row = ["202501280600", "300", "77.7", "1.7", "63", "4.8", "70", "1.5", "-3.1", "1", "0.0", "0.5", "2.0", "4.0", "85.0", "1016", "1022", "-5.2"]
        for text in (",".join(row) + ",=\n", " ".join(row) + "\n"):
            df = K.parse_aws("# YYMMDDHHMI STN ...\n" + text)
            self.assertEqual(df["stn"].iloc[0], 300)
            self.assertEqual(df["ta"].iloc[0], -3.1)
            self.assertEqual(df["td"].iloc[0], -5.2)
            self.assertEqual(df["rh"].iloc[0], 85.0)
            self.assertEqual(df["ws"].iloc[0], 1.5)  # 10분 평균 풍속
            self.assertEqual(df["rain"].iloc[0], 1)
            self.assertEqual(df["pr12h"].iloc[0], 2.0)

    def road_csv_rows(self):
        return ["202411010000,12103, 군산휴(도), 서해안, 거점,36.0202,126.7959,33,1,14.6,16550,84.6,0.0,0.0,14.6,313.5,0.0,314.4,0.5,1022,7620,7620,7620,1",
                "202411010000,12209, 서김제(도), 서해안, 기본,35.8347,126.8398,12,2,1.0,16000,90.0,0.0,0.0,1.5,10.0,1.0,20.0,2.0,1021,7620,7620,7620,2",
                "202411010000,33411, 삼봉(도), 통영-대전선, 목표(결빙),35.9,127.6,300,4,-1.2,-999,-999,-999,-999,-999,-999,-999,-999,-999,-999,-999,-999,-999,-999"]

    def test_road_csv_order(self):
        df = K.parse_road("\n".join(self.road_csv_rows()))
        self.assertEqual(df["stn"].tolist(), [12103, 12209, 33411])
        self.assertEqual(df["state"].tolist(), [1, 2, 4])
        self.assertEqual(df["rst"].tolist(), [14.6, 1.0, -1.2])
        self.assertEqual(df["ta"].iloc[0], 14.6)
        self.assertEqual(df["ws"].iloc[1], 1.0)
        self.assertTrue(np.isnan(E.clean_rwis(df)["ta"].iloc[2]))

    def test_road_named_header(self):
        text = "# TM STN SFS SRT VS HM RN_DAY SD TA WD WS\n202501280600,12103,4,-1.5,300,95,1.0,2.0,-2.0,10,1.5\n"
        df = K.parse_road(text)
        self.assertEqual(df["state"].iloc[0], 4)
        self.assertEqual(df["rst"].iloc[0], -1.5)
        self.assertEqual(df["rh"].iloc[0], 95)

    def test_road_wrong_order_stops(self):
        """열 순서가 어긋나 온도가 노면상태 자리에 오면 값을 쓰지 않고 멈춘다."""
        rows = [r.split(",") for r in self.road_csv_rows()]
        for r in rows:
            r[8], r[9] = r[9], r[8]
        with self.assertRaises(K.KmaFormatError):
            K.parse_road("\n".join(",".join(r) for r in rows))

    def test_road_unknown_layout_stops(self):
        with self.assertRaises(K.KmaFormatError):
            K.parse_road("202501280600,12103,1,2,3\n")

    def test_road_overrides(self):
        df = K.parse_road("202501280600,12103,1,2.5,70\n", {"tm": 0, "stn": 1, "state": 2, "rst": 3, "rh": 4})
        self.assertEqual(df["rst"].iloc[0], 2.5)

    def test_cctv(self):
        text = "#START7777\n202501280600,A1,군산휴게소,35.9,126.8,30,31,00,00,31\n202501280600,A2,이름,bad,126.8,30,0,0,0,0\n#7777END"
        items = K.parse_cctv(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["wh_cd"], 31)

    def test_key_required(self):
        with self.assertRaises(K.KmaError):
            K.KmaHub("")

    def test_error_message_hides_key(self):
        hub = K.KmaHub("secret-key", base="http://127.0.0.1:9", timeout=1)
        with self.assertRaises(K.KmaError) as ctx:
            hub.get("api/x", tm=1)
        self.assertNotIn("secret-key", str(ctx.exception))

    def test_valid_time_rule(self):
        self.assertEqual(P.latest_valid_time(pd.Timestamp("2026-01-15 06:20")), pd.Timestamp("2026-01-15 06:00"))
        self.assertEqual(P.latest_valid_time(pd.Timestamp("2026-01-15 06:05")), pd.Timestamp("2026-01-15 05:00"))


class FakeHub:
    """KmaSource의 캐시·조회 방식을 네트워크 없이 확인한다."""

    def __init__(self):
        self.step_calls = self.station_calls = 0

    def frame(self, stn, times):
        return pd.DataFrame({"stn": stn, "time": times, "state": 1.0, "rst": 1.0, "ta": 0.0, "rh": 50.0, "ws": 1.0, "pr_day": 0.0, "vis": 1000.0,
                             "td": -5.0, "rain": 0.0, "pr60": 0.0, "pr12h": 0.0})

    def road_step(self, t, overrides=None):
        self.step_calls += 1
        return self.frame(12103, [t])

    def aws_step(self, t):
        self.step_calls += 1
        return self.frame(300, [t])

    def road_station(self, stn, a, b, overrides=None):
        self.station_calls += 1
        return self.frame(stn, pd.date_range(a, b, freq="1min"))

    def aws_station(self, stn, a, b):
        self.station_calls += 1
        return self.frame(stn, pd.date_range(a, b, freq="1min"))

    def asos(self, a, b):
        return pd.DataFrame({"stn": [146], "time": [b], "cloud": [5.0], "tg": [1.0], "snow": [0.0], "sunshine": [0.0]})


class Cache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_backfill_then_incremental(self):
        hub = FakeHub()
        src = K.KmaSource(hub, [300], [146], [12103], self.tmp)
        end = pd.Timestamp("2026-01-15 06:00")
        start = end - pd.Timedelta(hours=78)
        first = src.collect(start, end)
        self.assertGreater(hub.station_calls, 0)
        self.assertEqual(hub.step_calls, 0)
        self.assertEqual(len(first["rwis"]), 78 * 6 + 1)  # 1분 자료에서 10분 시각만 남긴다
        hub.station_calls = 0
        later = end + pd.Timedelta(minutes=10)
        second = src.collect(start + pd.Timedelta(minutes=10), later)
        self.assertEqual(hub.station_calls, 0)  # 다음 회차는 전체 지점 조회만 쓴다
        self.assertLessEqual(hub.step_calls, 8)
        self.assertEqual(second["rwis"]["time"].max(), later)
        self.assertEqual(second["rwis"]["time"].min(), start + pd.Timedelta(minutes=10))


@unittest.skipUnless(ESTIMATES.exists(), "제공 자료와 노트북 결과가 필요합니다")
class ReplayMatchesNotebook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = E.Engine()
        cls.source = ReplaySource()
        cls.ref = pd.read_parquet(ESTIMATES)

    def run_at(self, t):
        frames = self.source.collect(t - pd.Timedelta(hours=E.LOOKBACK_HOURS), t)
        self.assertLessEqual(frames["rwis"]["time"].max(), t)  # 미래 자료를 쓰지 않는다
        return self.engine.run(E.clean_rwis(frames["rwis"]), E.clean_aws(frames["aws"]), E.clean_asos(frames["asos"]), [t])[0]

    def test_random_hours(self):
        """두 겨울에서 고른 시각의 구간 추정이 노트북 결과와 같다."""
        times = pd.DatetimeIndex(sorted(self.ref["time"].unique()))
        rng = np.random.default_rng(42)
        picks = sorted(rng.choice(len(times), 30, replace=False))
        worst_r, worst_p = 0.0, 0.0
        for k in picks:
            t = times[k]
            m = self.run_at(t).merge(self.ref[self.ref["time"] == t], on="seg_id", suffixes=("", "_ref"))
            self.assertEqual(len(m), 233)
            worst_r = max(worst_r, float((m["rst_est"] - m["rst_est_ref"]).abs().max()))
            worst_p = max(worst_p, float((m["p_icing"] - m["p_icing_ref"]).abs().max()))
        print(f"\n재생 30개 시각: 노면온도 최대 차이 {worst_r:.5f}°C, 결빙관련 확률 최대 차이 {worst_p:.5f}")
        self.assertLess(worst_r, 0.05)
        self.assertLess(worst_p, 0.01)

    def test_missing_sources_still_finite(self):
        """RWIS 일부와 ASOS 한 시각이 비어도 값이 끝까지 NaN이 되지 않는다."""
        t = pd.Timestamp("2025-01-28 06:00")
        fr = self.source.collect(t - pd.Timedelta(hours=E.LOOKBACK_HOURS), t)
        rwis = fr["rwis"][~fr["rwis"]["stn"].isin([12103, 12209, 23202])]
        asos = fr["asos"][fr["asos"]["time"] != t - pd.Timedelta(hours=5)]
        out, used = self.engine.run(E.clean_rwis(rwis), E.clean_aws(fr["aws"]), E.clean_asos(asos), [t])
        self.assertEqual(used["rwis_sources"], 11)
        self.assertTrue(np.isfinite(out["rst_est"]).all())
        self.assertTrue(np.isfinite(out["b3"]).all())

    def test_payload_flows_through_api(self):
        from server import Service, make_server
        tmp = tempfile.mkdtemp()
        t = pd.Timestamp("2025-01-28 06:00")
        svc = Service(HERE.parent / "bundle", Path(tmp) / "live.sqlite3", 90, "", "tok", lambda: datetime(2025, 1, 28, 6, 12, tzinfo=KST))
        server = make_server(svc, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            frames = self.source.collect(t - pd.Timedelta(hours=E.LOOKBACK_HOURS), t)
            payload = P.build_payload(self.engine, "replay", frames, t)
            self.assertEqual(len(payload["segments"]), 233)
            self.assertEqual(len(payload["stations"]), 17)
            self.assertEqual(P.post(base, payload, "tok")["segments"], 233)
            self.assertIn("already_received", P.post(base, payload, "tok"))
            with urllib.request.urlopen(base + "/api/v1/current") as r:
                cur = json.load(r)
            with urllib.request.urlopen(base + "/api/v1/status?mode=history&at=2025-01-28T06:00%2B09:00") as r:
                hist = json.load(r)
            self.assertEqual(cur["freshness"]["state"], "fresh")
            same = sum(a["state"] == b["state"] for a, b in zip(cur["segments"], hist["segments"]))
            diff = max(abs(a["rst_est"] - b["rst_est"]) for a, b in zip(cur["segments"], hist["segments"]))
            self.assertEqual(same, 233)  # 같은 시각의 재생 입력은 제출 결과와 상태까지 같아야 한다
            self.assertLess(diff, 0.06)  # 양쪽 반올림 차이만 남는다
        finally:
            server.shutdown()
            server.server_close()
            svc.live.db.close()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_too_few_inputs_sends_no_segments(self):
        t = pd.Timestamp("2025-01-28 06:00")
        fr = self.source.collect(t - pd.Timedelta(hours=E.LOOKBACK_HOURS), t)
        fr["rwis"] = fr["rwis"][fr["rwis"]["stn"].isin([12103, 12209])]
        payload = P.build_payload(self.engine, "replay", fr, t)
        self.assertEqual(payload["segments"], [])
        self.assertIn("입력 부족", payload["note"])


if __name__ == "__main__":
    unittest.main()
