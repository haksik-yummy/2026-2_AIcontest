"""도로 관리자용 우선 구간 목록을 인쇄할 수 있는 HTML과 CSV로 만듭니다.

과거 재생: python ops/briefing.py --start 2025-01-27T18:00 --hours 15 --group sigungu
현재 수신: python ops/briefing.py --api http://127.0.0.1:8000
Python 3.9 이상. 추가 패키지는 필요하지 않습니다.

목록은 등급·결빙 가능 조건·모델 예측 시간을 정렬해 보여 줄 뿐, 살포 시점이나 작업량을 정하지 않습니다.
"""

import argparse
import csv
import html
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "service"))

import ops as core  # noqa: E402  (service/ops.py)
from store import ApiError, Bundle, parse_time  # noqa: E402

COLUMNS = [("group", "묶음"), ("seg_id", "구간"), ("route", "노선"), ("km_from", "시작 km"), ("km_to", "끝 km"), ("sigungu", "시군"), ("grade", "등급"), ("score", "총점"),
           ("condition_hours", "결빙 가능 조건(시간)"), ("prediction_hours", "모델 예측(시간)"), ("first_alert", "첫 해당 시각"), ("min_rst", "최저 추정 노면온도(°C)"),
           ("min_rst_time", "최저 시각"), ("grade_meaning", "등급 의미")]


def flat_rows(report):
    return [{"group": g["group"], **r} for g in report["groups"] for r in g["top"]]


def write_csv(report, path):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([label for _, label in COLUMNS])
        for r in flat_rows(report):
            w.writerow([r.get(k, "") for k, _ in COLUMNS])


def title_of(report):
    if report["mode"] == "history":
        w = report["window"]
        return f"우선 구간 목록 · 과거 재생 {w['start'][:16].replace('T', ' ')} ~ {w['end'][:16].replace('T', ' ')} ({w['hours']}시간)"
    return f"우선 구간 목록 · 현재 수신 {str(report.get('valid_time', ''))[:16].replace('T', ' ')} 기준"


def write_html(report, path):
    e = html.escape
    parts = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>우선 구간 목록</title><style>",
             "body{font-family:system-ui,'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',sans-serif;color:#0b0b0b;max-width:980px;margin:24px auto;padding:0 16px;line-height:1.5}",
             "h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:18px 0 4px}table{border-collapse:collapse;width:100%;font-size:12.5px}",
             "th,td{border-bottom:1px solid #e1e0d9;padding:4px 6px;text-align:left;vertical-align:top}th{color:#52514e}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}",
             ".note{font-size:12px;color:#52514e}@media print{body{margin:0;max-width:none}h2{break-after:avoid}table{break-inside:auto}}</style></head><body>",
             f"<h1>{e(title_of(report))}</h1>"]
    total = report.get("total")
    if total:
        parts.append(f"<p class='note'>전체 {total['segments']}개 구간 중 {total['alert_segments']}개 구간에 결빙 가능 조건 또는 모델 예측이 있습니다.</p>")
    for g in report["groups"]:
        if not g["top"]:
            continue
        parts.append(f"<h2>{e(g['group'])} · {g['alert_segments']}/{g['segments']}구간</h2><table><tr><th>구간</th><th>위치</th><th>등급</th><th class='n'>조건(h)</th><th class='n'>예측(h)</th>"
                     "<th>첫 해당</th><th class='n'>최저 노면</th><th>등급 의미</th></tr>")
        for r in g["top"]:
            first = (r["first_alert"] or "")[5:16].replace("T", " ")
            low = "" if r["min_rst"] is None else f"{r['min_rst']:.1f}°C"
            parts.append(f"<tr><td>{e(r['seg_id'])}</td><td>{e(r['route'])} {r['km_from']:.1f}~{r['km_to']:.1f}km</td><td>{e(r['grade'])}</td><td class='n'>{r['condition_hours']}</td>"
                         f"<td class='n'>{r['prediction_hours']}</td><td>{e(first)}</td><td class='n'>{low}</td><td>{e(r['grade_meaning'])}</td></tr>")
        parts.append("</table>")
    parts.extend(f"<p class='note'>{e(n)}</p>" for n in report["notes"])
    parts.append("</body></html>")
    Path(path).write_text("".join(parts), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", help="시작 시각 (과거 재생), 예: 2025-01-27T18:00")
    parser.add_argument("--hours", type=int, default=15)
    parser.add_argument("--group", default="sigungu", choices=core.GROUPS)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--branches", type=Path, help="지사 위치 CSV (지사명·위도·경도)")
    parser.add_argument("--api", help="현재 수신 자료를 읽을 서버 주소")
    parser.add_argument("--bundle", type=Path, default=BASE / "bundle")
    parser.add_argument("--out", type=Path, default=BASE / "output" / "briefing", help="확장자 없는 저장 경로")
    args = parser.parse_args()
    try:
        if args.api:
            query = urllib.parse.urlencode({"mode": "live", "group": args.group, "top": args.top})
            with urllib.request.urlopen(f"{args.api.rstrip('/')}/api/v1/ops/briefing?{query}", timeout=20) as r:
                report = json.load(r)
            if not report["groups"]:
                print(report["notes"][0])
                return 1
        else:
            if not args.start:
                parser.error("--start 또는 --api가 필요합니다")
            branches = core.load_branches(args.branches) if args.branches else None
            report = core.history_briefing(Bundle(args.bundle), parse_time(args.start), args.hours, args.group, args.top, branches)
    except (ApiError, OSError, ValueError) as exc:
        print(f"실행 오류: {exc}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_csv(report, args.out.with_suffix(".csv"))
    write_html(report, args.out.with_suffix(".html"))
    print(f"{title_of(report)}\n묶음 {sum(1 for g in report['groups'] if g['top'])}개, 구간 {len(flat_rows(report))}개 → {args.out.with_suffix('.html')}, {args.out.with_suffix('.csv')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
