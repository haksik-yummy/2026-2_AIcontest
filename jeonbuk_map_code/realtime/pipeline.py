"""관측 수집 → 정제 → 구간별 추정 → API 전달을 한 번(또는 주기적으로) 실행합니다. 프로젝트 환경에서 실행합니다.

시연 (제공 원자료 재생, 키 불필요)
    python realtime/pipeline.py --source replay --valid-time 2025-01-28T06:00 --post http://127.0.0.1:8000
실제 수집 (환경변수 KMA_APIHUB_KEY, ICING_INGEST_TOKEN 필요)
    python realtime/pipeline.py --source kma --post http://127.0.0.1:8000 --watch 600
API 응답 확인 (키를 받은 뒤 처음 한 번)
    python realtime/pipeline.py --check-api --compare 2025-01-28T06:00

이 추정은 같은 시각의 관측으로 구간 값을 메우는 현재 추정입니다. 앞으로의 시각을 예측하지 않습니다.
"""

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import engine as E  # noqa: E402
from kma_client import KmaError, KmaFormatError, KmaHub, KmaSource  # noqa: E402
from replay import ReplaySource  # noqa: E402

KST = timezone(timedelta(hours=9))
MIN_INPUTS = {"rwis_sources": 5, "aws": 10, "asos": 3}  # 이보다 적으면 구간 추정을 보내지 않는다


def value(v):
    """JSON에 넣을 수 있는 숫자로. 결측은 None."""
    if v is None or (isinstance(v, (float, np.floating)) and not math.isfinite(v)) or v is pd.NA:
        return None
    return float(v) if isinstance(v, (float, np.floating)) else int(v)


def iso(t):
    return pd.Timestamp(t).tz_localize(KST).isoformat(timespec="minutes")


def build_payload(engine, source_name, frames, valid, reference=None):
    """수집 자료로 POST /api/v1/ingest 본문을 만든다."""
    rwis, aws, asos = E.clean_rwis(frames["rwis"]), E.clean_aws(frames["aws"]), E.clean_asos(frames["asos"])
    df, used = engine.run(rwis, aws, asos, [valid])
    enough = all(used[k] >= n for k, n in MIN_INPUTS.items())
    segments = []
    if enough:
        segments = [{"seg_id": r.seg_id, "rst_est": round(float(r.rst_est), 2) if math.isfinite(r.rst_est) else None,
                     "p_icing": round(float(r.p_icing), 4) if math.isfinite(r.p_icing) else None,
                     "condition": bool(r.condition), "prediction": bool(r.prediction)} for r in df.itertuples()]
    now = rwis[(rwis["time"] == valid) & rwis["stn"].isin(engine.s["all_stn"])]
    stations = [{"stn": int(r.stn), "observed_at": iso(r.time), "rst": value(r.rst), "road_state": value(r.state), "ta": value(r.ta), "rh": value(r.rh)}
                for r in now.itertuples()]
    notes = []
    if not enough:
        notes.append(f"입력 부족으로 구간 추정을 보내지 않음: {used}")
    if valid.month not in (11, 12, 1, 2):
        notes.append("모델 학습 기간(11~2월) 밖의 시각입니다")
    return {"run_id": f"{source_name}-{valid:%Y%m%d%H%M}", "valid_time": iso(valid), "source": source_name, "quality": "unverified", "inputs": used,
            "model": {"road_temperature": engine.est_meta["method"], "icing": engine.cls_meta["method"]}, "note": " / ".join(notes),
            "segments": segments, "stations": stations, "reference": {"cctv": reference} if reference else {}}


def post(url, payload, token):
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    req = urllib.request.Request(url.rstrip("/") + "/api/v1/ingest", body, {"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if exc.code == 409:
            return {"already_received": payload["run_id"]}
        raise RuntimeError(f"전달 실패 HTTP {exc.code}: {detail[:300]}") from None


def latest_valid_time(now):
    """ASOS 정시 자료가 올라올 시간을 두고 직전 정시를 고른다."""
    return (pd.Timestamp(now) - pd.Timedelta(minutes=15)).floor("h")


def run_once(engine, source, valid, args):
    start = valid - pd.Timedelta(hours=E.LOOKBACK_HOURS)
    t0 = time.time()
    frames = source.collect(start, valid)
    reference = None
    if hasattr(source, "reference"):
        try:
            reference = source.reference(valid)
        except KmaError as exc:
            print(f"CCTV 참고 자료 없이 진행: {exc}", file=sys.stderr)
    payload = build_payload(engine, source.name, frames, valid, reference)
    cond = sum(s["condition"] for s in payload["segments"])
    pred = sum(s["prediction"] for s in payload["segments"])
    print(f"{valid:%Y-%m-%d %H:%M} 입력 {payload['inputs']} 구간 {len(payload['segments'])}개 (조건 {cond}, 예측 {pred}), "
          f"관측소 {len(payload['stations'])}곳, {time.time() - t0:.1f}초")
    if payload["note"]:
        print("참고:", payload["note"])
    if args.out:
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.post:
        token = os.environ.get("ICING_INGEST_TOKEN")
        if not token:
            raise RuntimeError("환경변수 ICING_INGEST_TOKEN이 없습니다")
        print("전달:", post(args.post, payload, token))
    return payload


def check_api(hub, engine, compare, road_columns):
    """각 API를 한 번씩 불러 해석 결과를 보여 주고, 과거 시각이면 제공 원자료와 값을 대조한다."""
    t = pd.Timestamp(compare) if compare else latest_valid_time(datetime.now(KST).replace(tzinfo=None))
    print(f"기준 시각 {t:%Y-%m-%d %H:%M} KST, 응답 원문은 {hub.raw_dir}에 저장합니다")
    road = hub.road_step(t, road_columns)
    print(f"도로기상: {len(road)}행, 대상 지점 {road['stn'].isin(engine.s['all_stn']).sum()}곳")
    aws = hub.aws_step(t)
    print(f"AWS: {len(aws)}행, 대상 지점 {aws['stn'].isin(engine.s['aws_stn']).sum()}곳")
    asos = hub.asos(t, t)
    print(f"ASOS: {len(asos)}행, 대상 지점 {asos['stn'].isin(engine.s['asos_stn']).sum()}곳")
    print(f"CCTV: {len(hub.cctv(t - pd.Timedelta('10min'), t))}곳")
    if not compare:
        return 0
    ref = ReplaySource().collect(t, t)
    bad = 0
    for name, api, cols in [("도로기상", road, ["state", "rst", "ta", "rh", "ws", "pr_day", "vis"]), ("AWS", aws, ["ta", "td", "rh", "ws", "rain", "pr60", "pr12h", "pr_day"]),
                            ("ASOS", asos, ["cloud", "tg", "snow", "sunshine"])]:
        key = {"도로기상": "rwis", "AWS": "aws", "ASOS": "asos"}[name]
        m = api.merge(ref[key], on=["stn", "time"], suffixes=("", "_csv"))
        if m.empty:
            print(f"{name}: 제공 자료와 겹치는 행이 없습니다")
            bad += 1
            continue
        for c in cols:
            a, b = m[c].astype(float), m[f"{c}_csv"].astype(float)
            both = a.notna() & b.notna() & (a > -90) & (b > -90)
            same = ((a - b).abs() < 1e-6)[both].mean() if both.any() else float("nan")
            print(f"  {name} {c:9s} 비교 {int(both.sum()):3d}행, 일치 {same:.0%}")
            bad += not (same >= 0.98) and both.any()
    print("대조 결과:", "모든 항목이 제공 자료와 일치합니다" if not bad else f"{bad}개 항목이 다릅니다. road_columns.json으로 위치를 지정하세요")
    return 1 if bad else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=["replay", "kma"], default="replay")
    parser.add_argument("--valid-time", help="재생할 시각 (replay에서 필수, 정시)")
    parser.add_argument("--post", help="API 서버 주소")
    parser.add_argument("--out", help="전달 본문을 파일로 저장")
    parser.add_argument("--watch", type=int, help="이 초마다 반복 (kma)")
    parser.add_argument("--raw-dir", default=str(HERE / "cache" / "raw"), help="API 응답 원문 저장 위치")
    parser.add_argument("--check-api", action="store_true", help="API 응답을 해석해 보고 끝낸다")
    parser.add_argument("--compare", help="--check-api와 함께: 이 과거 시각의 API 값을 제공 원자료와 대조")
    args = parser.parse_args()
    engine = E.Engine()
    road_path = HERE / "road_columns.json"
    try:
        if args.check_api:
            hub = KmaHub(os.environ.get("KMA_APIHUB_KEY"), args.raw_dir)
            return check_api(hub, engine, args.compare, json.loads(road_path.read_text(encoding="utf-8")) if road_path.exists() else None)
        if args.source == "replay":
            if not args.valid_time:
                parser.error("--source replay에는 --valid-time이 필요합니다")
            valid = pd.Timestamp(args.valid_time)
            if valid != valid.floor("h"):
                parser.error("--valid-time은 정시여야 합니다")
            run_once(engine, ReplaySource(), valid, args)
            return 0
        hub = KmaHub(os.environ.get("KMA_APIHUB_KEY"), args.raw_dir)
        source = KmaSource(hub, engine.s["aws_stn"], engine.s["asos_stn"], engine.s["all_stn"], HERE / "cache", road_path)
        while True:
            now = datetime.now(KST).replace(tzinfo=None)
            try:
                run_once(engine, source, latest_valid_time(now), args)
            except KmaFormatError:
                raise  # 형식이 다르면 잘못 읽은 값을 보내지 않도록 멈춘다
            except (KmaError, RuntimeError) as exc:
                if not args.watch:
                    raise
                print(f"이번 회차 실패, 다음 회차에 다시 시도: {exc}", file=sys.stderr)
            if not args.watch:
                return 0
            time.sleep(args.watch)
    except (KmaError, RuntimeError, FileNotFoundError) as exc:
        print(f"실행 오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
