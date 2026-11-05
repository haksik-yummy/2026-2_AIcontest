"""기존 결빙취약구간 22개소와 위험 등급 비교 결과를 지도·API용 층으로 만듭니다. 프로젝트 환경에서 실행합니다.

실행: python jeonbuk_map_code/ops/vulnerable_sections.py
입력: 노트북 05-2의 결과 (data/results/vulnerable_comparison.csv, vulnerable_summary.json, figures/risk_map_shp/vulnerable_sections.shp)
출력: bundle/vulnerable.geojson, bundle/vulnerable_meta.json

기존 등급은 도로 운영까지 포함한 평가표 점수이고 위험 등급은 기상·도로·지형 계산값이라 서로 정답이 아닙니다.
비교는 22개소 중 대상 노선의 전북 구간에 들어오는 곳만 합니다. 계산은 src/vulnerable.py와 05-2의 5장에 있습니다.
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402

GRADES = ["관심", "주의", "경계", "심각"]
SOURCE_TEXT = ("기존 결빙취약구간: 문제 설명의 전북도 결빙취약구간 현황 22개소. 이정은 노선별 나들목 누적거리와 행정안전부 상습 결빙구간"
               "(공공데이터포털 15067396) 좌표로 도로 위 위치로 바꿨습니다.")


def main():
    table_path = config.RESULT_DIR / "vulnerable_comparison.csv"
    if not table_path.exists():
        print(f"{table_path}이 없습니다. 노트북 05-2를 먼저 실행하세요.", file=sys.stderr)
        return 1
    table = pd.read_csv(table_path, encoding="utf-8-sig")
    summary = json.loads((config.RESULT_DIR / "vulnerable_summary.json").read_text(encoding="utf-8"))
    lines = gpd.read_file(config.FIGURE_DIR / "risk_map_shp" / "vulnerable_sections.shp").to_crs(4326).set_index("no")
    bundle = {f["properties"]["seg_id"]: f["properties"]
              for f in json.loads((BASE / "bundle" / "segments.geojson").read_text(encoding="utf-8"))["features"]}

    rows, features = [], []
    for r in table[table["연결 구간"].notna()].to_dict("records"):
        ids = r["연결 구간"].split()
        grades = pd.Series([bundle[s]["grade"] for s in ids]).value_counts().reindex(GRADES).fillna(0).astype(int).to_dict()
        geom = lines.geometry.loc[r["연번"]]
        mid = geom.interpolate(0.5, normalized=True)
        rows.append({"id": int(r["연번"]), "area": r["관리기관"], "road": r["노선명"], "old_grade": r["기존 등급"],
                     "length_km": float(r["연장(km)"]), "km_from": float(r["시점(km)"]), "km_to": float(r["종점(km)"]),
                     "matched_km": float(r["비교 길이(km)"]), "partial": r["비교 상태"] == "일부 비교", "segments": ids, "grades": grades,
                     "high_share": float(r["경계·심각 비율"]), "max_score": max(float(bundle[s]["score"]) for s in ids),
                     "lat": round(mid.y, 5), "lon": round(mid.x, 5)})
        features.append({"type": "Feature",
                         "properties": {k: rows[-1][k] for k in ("id", "area", "road", "old_grade", "length_km", "partial")},
                         "geometry": {"type": "LineString", "coordinates": [[round(x, 5), round(y, 5)] for x, y in geom.coords]}})

    meta = {"source": SOURCE_TEXT, "stats": {**summary, "listed": int(len(table))}, "sections": rows,
            "notes": ["기존 등급은 도로 운영을 포함한 평가표 점수이고 위험 등급은 기상·도로·지형 계산값이라 서로 정답이 아닙니다.",
                      f"22개소 중 {len(rows)}곳만 대상 노선의 전북 구간에 들어와 비교했습니다.",
                      "partial은 구간의 일부가 전북 노선 구간 밖에 있어 안쪽만 비교했다는 뜻입니다.",
                      "random_placement는 같은 노선에 같은 수의 이어진 구간을 무작위로 골랐을 때의 경계·심각 비율입니다."]}
    (BASE / "bundle" / "vulnerable.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    (BASE / "bundle" / "vulnerable_meta.json").write_text(json.dumps(meta, ensure_ascii=False, allow_nan=False, indent=1), encoding="utf-8")
    print(f"기존 결빙취약구간 {len(rows)}곳 층을 만들었습니다.", json.dumps({k: v for k, v in summary.items() if k != "by_route"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
