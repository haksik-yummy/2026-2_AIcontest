"""bundle/의 분석 결과로 인터넷 없이 열리는 결빙 위험도 지도(HTML 한 파일)를 만듭니다.

실행: python build_risk_map.py --open
Python 3.9 이상. 추가 패키지와 인터넷 연결은 필요하지 않습니다.
bundle/은 export_bundle.py(프로젝트 환경)로 만듭니다. 상습 결빙구간 층은 ops/vulnerable_sections.py를 실행했을 때만 들어갑니다.
"""

import argparse
import base64
import json
import sys
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent
ARRAYS = ["rst", "p_icing", "state", "station_rst", "station_state"]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def build(args):
    bundle = args.bundle
    meta = read_json(bundle / "meta.json")
    payload = {
        "meta": meta,
        "criteria": read_json(bundle / "criteria.json"),
        "segments": read_json(bundle / "segments.geojson"),
        "facilities": read_json(bundle / "facilities.geojson"),
        "stations": read_json(bundle / "stations.json"),
        "geo": read_json(BASE / "assets" / "municipalities.geojson"),
        "arrays": {k: base64.b64encode((bundle / meta["arrays"][k]["file"]).read_bytes()).decode("ascii") for k in ARRAYS},
        "vulnerable": None, "vulnerableMeta": None,
    }
    if (bundle / "vulnerable.geojson").exists():
        payload["vulnerable"] = read_json(bundle / "vulnerable.geojson")
        payload["vulnerableMeta"] = read_json(bundle / "vulnerable_meta.json")

    # 자료에 HTML 문자가 들어 있어도 script 태그 밖으로 나가지 않게 한다 (build_map.py와 같음)
    data_json = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    data_json = data_json.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = (BASE / "assets" / "risk_template.html").read_text(encoding="utf-8")
    d3_source = (BASE / "assets" / "d3.v7.9.0.min.js").read_text(encoding="utf-8")
    page = template.replace("__D3_SOURCE__", d3_source).replace("__ATLAS_DATA__", data_json)

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    n_vuln = len(payload["vulnerable"]["features"]) if payload["vulnerable"] else 0
    print(f"구간 {meta['n_segments']}개, 시각 {meta['time']['n_hours']:,}개, 관측소 {len(payload['stations'])}곳, "
          f"상습 결빙구간 {n_vuln}개")
    print(f"지도 저장: {output} ({output.stat().st_size / 1e6:.1f} MB)")
    if args.open:
        webbrowser.open(output.as_uri())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle", type=Path, default=BASE / "bundle")
    parser.add_argument("--output", type=Path, default=BASE / "output" / "jeonbuk_risk_atlas.html")
    parser.add_argument("--open", action="store_true", help="완료 후 기본 웹브라우저에서 열기")
    args = parser.parse_args()
    try:
        build(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"실행 오류: {exc}", file=sys.stderr)
        print("bundle/이 없다면 먼저 프로젝트 환경에서 python jeonbuk_map_code/export_bundle.py 를 실행하세요.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
