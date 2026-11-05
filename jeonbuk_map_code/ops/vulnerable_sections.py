"""행정안전부 상습 결빙구간을 구간별 위험 등급과 비교합니다. 프로젝트 환경에서 실행합니다.

실행: python jeonbuk_map_code/ops/vulnerable_sections.py
입력: data/external/행정안전부_상습 결빙구간_20251107.csv (data.go.kr 15067396, 이용허락범위 제한 없음)
출력
    bundle/vulnerable.geojson, bundle/vulnerable_meta.json   지도·API용 층과 비교 결과
    data/external/vulnerable_sections.csv                    --notebook-input을 줄 때만. 노트북 05-2의 5장 입력 형식

상습 결빙구간은 행정안전부가 공개한 관리 구간이고 위험 등급은 기상·도로·지형으로 계산한 값이라 정답과 예측의 관계가 아닙니다.
05-2가 말하는 전북 기존 결빙취약구간 22개소와 같은 목록인지는 확인되지 않았습니다.
노선마다 등급 분포가 크게 달라, 같은 노선에 같은 길이의 구간을 무작위로 놓았을 때와도 비교합니다.
"""

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402

ROUTES = {"15호선": "서해안", "서해안선": "서해안", "25호선": "호남선", "호남선": "호남선", "35호선": "통영-대전중부선", "통영대전선": "통영-대전중부선"}
COLS = {"id": "구간번호", "agency": "관리청", "area": "대표지역", "road": "도로(노선)명", "length": "총길이(km)", "lat0": "기점 위도(WGS84(4326))",
        "lon0": "기점 경도(WGS84(4326))", "lat1": "종점 위도(WGS84(4326))", "lon1": "종점 경도(WGS84(4326))"}
HIGH = ["경계", "심각"]
MIN_INSIDE_KM = 0.2
SOURCE_NAME = "행정안전부_상습 결빙구간_20251107.csv"
SOURCE_TEXT = ("상습 결빙구간: 행정안전부_상습 결빙구간(공공데이터포털 15067396, 2025-12-08 수정, 이용허락범위 제한 없음) 중 고속국도 15·25·35호선. "
               "기점·종점을 노선에 투영해 지나는 구간을 표시했습니다.")


def locate(point, chain):
    """점을 노선 구간 사슬에 투영한다: (노선 km, 거리 m)."""
    idx, dist = chain.sindex.nearest(point, return_distance=True, return_all=False)
    row = chain.iloc[idx[1][0]]
    return row["km_from"] + row.geometry.project(point) / 1000, float(dist[0])


def overlap_km(chain, lo, hi, grades=HIGH):
    """노선 km 범위 [lo, hi]에서 경계·심각 구간이 차지하는 길이."""
    km0, km1 = chain["km_from"].to_numpy(), chain["km_to"].to_numpy()
    high = chain["등급"].isin(grades).to_numpy()
    return float(np.clip(np.minimum(km1, hi) - np.maximum(km0, lo), 0, None)[high].sum())


def match_section(sec, chain, max_dist):
    """상습 구간이 지나는 구간. 기점~종점을 100m 간격으로 짚어 max_dist 안의 부분만 쓴다 (한쪽 끝이 전북 밖일 수 있다)."""
    a = gpd.GeoSeries([shapely.Point(sec["lon0"], sec["lat0"])], crs=4326).to_crs(5179).iloc[0]
    b = gpd.GeoSeries([shapely.Point(sec["lon1"], sec["lat1"])], crs=4326).to_crs(5179).iloc[0]
    km = []
    for f in np.linspace(0, 1, max(2, int(a.distance(b) / 100) + 1)):
        k, d = locate(shapely.Point(a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f), chain)
        if d <= max_dist:
            km.append(k)
    if not km or max(km) - min(km) < MIN_INSIDE_KM:
        return None  # 전북 노선 구간 끝에 닿기만 하는 구간
    lo, hi = min(km), max(km)
    if hi - lo > 1.5 * sec["length"] + 1:
        # 구간 번호가 남→북 순이라 굽은 곳에서 km가 튄다. 그때는 짚은 점에 가장 가까운 구간만 쓴다
        hits = sorted(km)
        steps = np.diff(hits)
        cut = int(np.argmax(steps)) + 1
        part = hits[:cut] if len(hits[:cut]) >= len(hits[cut:]) else hits[cut:]
        lo, hi = min(part), max(part)
    picked = chain[(chain["km_to"] > lo) & (chain["km_from"] < hi)]
    return {"km_from": lo, "km_to": hi, "segments": picked, "partial": (hi - lo) < 0.7 * sec["length"]}


def random_baseline(chains, sections, rng, n=20000):
    """같은 노선에 같은 길이의 구간을 무작위로 놓았을 때 경계·심각 길이 비율의 분포."""
    high_km = np.zeros(n)
    total = 0.0
    for route, length in sections:
        c = chains[route]
        km0, km1 = c["km_from"].to_numpy(), c["km_to"].to_numpy()
        high = c["등급"].isin(HIGH).to_numpy()
        start = rng.uniform(0, max(km1.max() - length, 1e-6), n)
        for i in np.flatnonzero(high):
            high_km += np.clip(np.minimum(km1[i], start + length) - np.maximum(km0[i], start), 0, None)
        total += length
    return high_km / total


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=config.DATA_DIR / "external" / SOURCE_NAME)
    parser.add_argument("--max-dist", type=float, default=500, help="구간 선에서 이 거리(m) 안이면 같은 도로로 본다")
    parser.add_argument("--notebook-input", action="store_true", help="data/external/vulnerable_sections.csv도 쓴다. 노트북 05-2의 5장이 22개소 대신 이 목록을 읽게 된다")
    args = parser.parse_args()
    if not args.input.exists():
        print(f"{args.input}이 없습니다. 공공데이터포털 15067396에서 받아 data/external/에 두세요.", file=sys.stderr)
        return 1

    raw = pd.read_csv(args.input, encoding="utf-8-sig").rename(columns={v: k for k, v in COLS.items()})
    hw = raw[raw["도로분류"] == "고속국도"].copy()
    hw["route"] = hw["road"].map(ROUTES)
    hw = hw[hw["route"].notna()]

    seg = gpd.read_file(config.PROCESSED_DIR / "segments.gpkg").sort_values("seg_id")
    bundle = {f["properties"]["seg_id"]: f["properties"] for f in json.loads((BASE / "bundle" / "segments.geojson").read_text(encoding="utf-8"))["features"]}
    seg["km_from"] = seg["seg_id"].map(lambda s: bundle[s]["km_from"])
    seg["km_to"] = seg["seg_id"].map(lambda s: bundle[s]["km_to"])
    seg["등급"] = seg["seg_id"].map(lambda s: bundle[s]["grade"])
    seg["총점"] = seg["seg_id"].map(lambda s: bundle[s]["score"])
    chains = {r: g.reset_index(drop=True) for r, g in seg.groupby("route")}

    rows, features = [], []
    for _, sec in hw.iterrows():
        m = match_section(sec, chains[sec["route"]], args.max_dist)
        if m is None:
            continue
        picked = m["segments"]
        grades = picked["등급"].value_counts().reindex(["관심", "주의", "경계", "심각"]).fillna(0).astype(int).to_dict()
        high_share = float(picked["등급"].isin(HIGH).mean())
        lines = gpd.GeoSeries(picked.geometry.to_numpy(), crs=5179).to_crs(4326)
        mid = lines.iloc[len(lines) // 2].interpolate(0.5, normalized=True)
        rows.append({"id": sec["id"], "area": sec["area"], "road": sec["road"], "route": sec["route"], "length_km": float(sec["length"]),
                     "km_from": round(m["km_from"], 2), "km_to": round(m["km_to"], 2), "matched_km": round(m["km_to"] - m["km_from"], 2), "partial": bool(m["partial"]),
                     "segments": picked["seg_id"].tolist(), "grades": grades, "high_share": round(high_share, 3), "max_score": float(picked["총점"].max()),
                     "lat": round(mid.y, 5), "lon": round(mid.x, 5)})
        features.append({"type": "Feature", "properties": {k: rows[-1][k] for k in ("id", "area", "road", "route", "length_km", "partial")},
                         "geometry": {"type": "MultiLineString", "coordinates": [[[round(x, 5), round(y, 5)] for x, y in g.coords] for g in lines]}})
    table = pd.DataFrame(rows).sort_values(["route", "km_from"])

    # 상습 구간에 든 1km 구간과 나머지 구간 비교
    in_vuln = seg["seg_id"].isin({s for r in rows for s in r["segments"]})
    base = float(seg["등급"].isin(HIGH).mean())
    inside = float(seg.loc[in_vuln, "등급"].isin(HIGH).mean())
    by_route = []
    for route, g in seg.groupby("route"):
        v = g["seg_id"].isin({s for r in rows if r["route"] == route for s in r["segments"]})
        by_route.append({"route": route, "sections": int((table["route"] == route).sum()), "segments_in_sections": int(v.sum()), "segments": len(g),
                         "high_share_in": None if not v.any() else round(float(g.loc[v, "등급"].isin(HIGH).mean()), 3),
                         "high_share_route": round(float(g["등급"].isin(HIGH).mean()), 3),
                         "mean_score_in": None if not v.any() else round(float(g.loc[v, "총점"].mean()), 3),
                         "mean_score_route": round(float(g["총점"].mean()), 3)})
    rng = np.random.default_rng(42)
    # 관측값과 무작위 기준을 같은 방식(km 길이)으로 잰다. 1km보다 짧은 구간은 구간 길이에 맞춰 1km로 본다
    spans = []
    for r in rows:
        length = max(r["km_to"] - r["km_from"], 1.0)
        mid = (r["km_from"] + r["km_to"]) / 2
        spans.append((r["route"], mid - length / 2, mid + length / 2))
    observed = sum(overlap_km(chains[route], lo, hi) for route, lo, hi in spans) / sum(hi - lo for _, lo, hi in spans)
    null = random_baseline(chains, [(route, hi - lo) for route, lo, hi in spans], rng)
    stats = {"sections": len(rows), "highway_sections_on_routes": int(len(hw)), "segments_in_sections": int(in_vuln.sum()),
             "section_hit_rate": round(float(np.mean([r["high_share"] > 0 for r in rows])), 3),
             "high_share_in_sections": round(inside, 3), "high_share_all": round(base, 3), "lift": round(inside / base, 2),
             "length_weighted_high_share": round(observed, 3), "random_placement_mean": round(float(null.mean()), 3),
             "random_placement_p": round(float((null >= observed).mean()), 3), "by_route": by_route}
    meta = {"source": SOURCE_TEXT, "stats": stats, "sections": table.to_dict("records"),
            "notes": ["상습 결빙구간은 공개된 관리 구간이고 위험 등급은 기상·도로·지형 계산값이라 서로 정답이 아닙니다.",
                      f"비교 구간이 {len(rows)}개뿐이라 비율의 불확실성이 큽니다.", "partial은 구간의 일부가 전북 노선 구간 밖에 있어 안쪽만 비교했다는 뜻입니다.",
                      "random_placement는 같은 노선에 같은 길이의 구간을 무작위로 놓았을 때의 경계·심각 길이 비율입니다. 노선 구성의 영향을 뺀 비교입니다."]}
    (BASE / "bundle" / "vulnerable.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    (BASE / "bundle" / "vulnerable_meta.json").write_text(json.dumps(meta, ensure_ascii=False, allow_nan=False, indent=1), encoding="utf-8")
    if args.notebook_input:
        nb = table.rename(columns={"id": "name"})[["name", "route", "lat", "lon", "area", "road", "length_km", "km_from", "km_to", "partial"]]
        nb.to_csv(config.DATA_DIR / "external" / "vulnerable_sections.csv", index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 200)
    print(table[["id", "area", "road", "route", "length_km", "matched_km", "partial", "grades", "high_share"]].to_string(index=False))
    print(json.dumps({k: v for k, v in stats.items() if k != "by_route"}, ensure_ascii=False))
    print(pd.DataFrame(by_route).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
