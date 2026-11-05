"""교량·터널·RWIS CSV로 확대·선택 가능한 전북 위치 지도를 만듭니다.

실행: python build_map.py --open
Python 3.9 이상. 추가 패키지와 인터넷 연결은 필요하지 않습니다.
"""

import argparse
import csv
import io
import json
import math
import re
import sys
import webbrowser
from collections import Counter
from datetime import datetime
from pathlib import Path


BASE = Path(__file__).resolve().parent


def read_csv(path):
    """기상청 CSV의 UTF-8/CP949 인코딩을 자동으로 구분합니다."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"{path.name}: UTF-8/CP949로 읽을 수 없습니다.")

    rows = csv.DictReader(io.StringIO(text))
    if not rows.fieldnames:
        raise ValueError(f"{path.name}: 열 이름이 없습니다.")
    records = [
        {str(k).strip(): (v.strip() if isinstance(v, str) else v)
         for k, v in row.items() if k is not None}
        for row in rows
    ]
    return records, [name.strip() for name in rows.fieldnames]


def normalize(name):
    return re.sub(r"[\s_()（）]", "", name).lower()


def find_column(columns, aliases, required=True):
    """열 이름의 공백 차이는 무시합니다. 위도·경도는 명칭으로 구분합니다."""
    lookup = {normalize(c): c for c in columns}
    for alias in aliases:
        if normalize(alias) in lookup:
            return lookup[normalize(alias)]
    if required:
        raise ValueError(
            f"필요한 열을 찾지 못했습니다: {', '.join(aliases)}\n"
            f"파일의 열: {', '.join(columns)}"
        )
    return None


def coordinate(row, lat_col, lon_col):
    try:
        lat, lon = float(row[lat_col]), float(row[lon_col])
    except (ValueError, TypeError, KeyError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    # 대한민국 주변 범위를 벗어나면 좌표 뒤바뀜·결측 코드 가능성이 있습니다.
    if not (32 <= lat <= 39.5 and 123 <= lon <= 132):
        return None
    return lat, lon


def facility_points(path, kind):
    rows, cols = read_csv(path)
    label = "교량" if kind == "bridge" else "터널"
    lat_col = find_column(cols, [f"{label}시작점위도", "위도", "latitude", "lat"])
    lon_col = find_column(cols, [f"{label}시작점경도", "경도", "longitude", "lon", "lng"])
    road_col = find_column(cols, ["도로노선명", "고속도로", "노선명"], required=False)
    groups = {}
    skipped = 0

    for row in rows:
        xy = coordinate(row, lat_col, lon_col)
        if xy is None:
            skipped += 1
            continue
        if xy not in groups:
            groups[xy] = {"roads": set(), "count": 0}
        group = groups[xy]
        group["count"] += 1
        if road_col and row.get(road_col):
            group["roads"].add(row[road_col])

    if not groups:
        raise ValueError(f"{path.name}: 사용할 수 있는 위경도 행이 없습니다.")

    points = []
    for index, ((lat, lon), group) in enumerate(groups.items(), 1):
        points.append({
            "id": f"{kind}-{index}", "kind": kind,
            "name": f"{label} 대표점 {index:03d}",
            "lat": lat, "lon": lon,
            "road": " · ".join(sorted(group["roads"])) or "노선 미상",
            "count": group["count"],
        })
    return points, {"file": path.name, "input_rows": len(rows),
                    "points": len(points), "invalid_rows": skipped}


def parse_time(value):
    if not value:
        return None
    value = str(value).strip()
    if value.endswith(".0") and value[:-2].isdigit():
        value = value[:-2]
    for fmt in ("%Y%m%d%H%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def rwis_points(path):
    rows, cols = read_csv(path)
    lat_col = find_column(cols, ["관측소 위도", "위도", "latitude", "lat"])
    lon_col = find_column(cols, ["관측소 경도", "경도", "longitude", "lon", "lng"])
    station_col = find_column(cols, ["관측 지점번호", "지점번호", "station_id"])
    name_col = find_column(cols, ["관측 지점명", "지점명", "station_name"], False)
    road_col = find_column(cols, ["고속도로", "도로노선명", "노선명"], False)
    time_col = find_column(cols, ["관측시각 (KST)", "일시", "time"], False)
    groups, times = {}, []
    skipped = moved = 0

    for row in rows:
        if time_col:
            t = parse_time(row.get(time_col))
            if t:
                times.append(t)
        xy = coordinate(row, lat_col, lon_col)
        station_id = row.get(station_col)
        if xy is None or not station_id:
            skipped += 1
            continue
        lat, lon = xy
        # 관측소가 이전했다면 번호가 같아도 다른 위치로 표시합니다.
        key = (station_id, lat, lon)
        if key not in groups:
            groups[key] = {
                "id": f"rwis-{len(groups) + 1}", "kind": "rwis",
                "station_id": station_id,
                "name": row.get(name_col) or station_id,
                "road": row.get(road_col) or "노선 미상",
                "lat": lat, "lon": lon, "count": 1,
            }
    location_counts = Counter(key[0] for key in groups)
    moved = sum(count > 1 for count in location_counts.values())
    if not groups:
        raise ValueError(f"{path.name}: 사용할 수 있는 RWIS 지점이 없습니다.")
    period = (f"{min(times):%Y.%m.%d %H:%M} ~ {max(times):%Y.%m.%d %H:%M}"
              if times else "관측기간 미확인")
    return list(groups.values()), {
        "file": path.name, "input_rows": len(rows), "points": len(groups),
        "invalid_rows": skipped, "multiple_location_station_ids": moved,
        "period": period,
    }


def build(args):
    bridges, bridge_info = facility_points(args.bridges, "bridge")
    tunnels, tunnel_info = facility_points(args.tunnels, "tunnel")
    rwis, rwis_info = rwis_points(args.rwis)
    points = bridges + tunnels + rwis
    geo = json.loads((BASE / "assets" / "municipalities.geojson").read_text(encoding="utf-8"))
    focus = {
        "type": "FeatureCollection",
        "features": [f for f in geo["features"]
                     if str(f["properties"].get("code", "")).startswith("35")],
    }
    if not focus["features"]:
        raise ValueError("배경 지도에서 전북 경계를 찾지 못했습니다.")

    payload = {
        "points": points, "geo": geo, "focus": focus,
        "meta": {"bridge": bridge_info, "tunnel": tunnel_info, "rwis": rwis_info},
    }
    # CSV에 HTML 문자가 들어 있어도 script 태그 밖으로 나가지 않게 합니다.
    data_json = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    data_json = data_json.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = (BASE / "assets" / "map_template.html").read_text(encoding="utf-8")
    d3_source = (BASE / "assets" / "d3.v7.9.0.min.js").read_text(encoding="utf-8")
    page = template.replace("__D3_SOURCE__", d3_source).replace("__MAP_DATA__", data_json)

    output = args.output.resolve()
    inputs = [args.bridges.resolve(), args.tunnels.resolve(), args.rwis.resolve()]
    if output in inputs:
        raise ValueError("출력 경로가 원본 CSV와 같습니다. .html 파일을 지정하세요.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    print(f"교량 대표 위치: {len(bridges)}개 / 원본 {bridge_info['input_rows']}행")
    print(f"터널 대표 위치: {len(tunnels)}개 / 원본 {tunnel_info['input_rows']}행")
    print(f"RWIS 위치: {len(rwis)}개 / 원본 {rwis_info['input_rows']}행")
    print(f"RWIS 관측기간: {rwis_info['period']}")
    for info in (bridge_info, tunnel_info, rwis_info):
        if info["invalid_rows"]:
            print(f"좌표·지점 누락으로 제외: {info['file']} {info['invalid_rows']}행")
    print(f"지도 저장: {output}")
    if args.open:
        webbrowser.open(output.as_uri())
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridges", type=Path, default=BASE / "data" / "bridges.csv")
    parser.add_argument("--tunnels", type=Path, default=BASE / "data" / "tunnels.csv")
    parser.add_argument("--rwis", type=Path, default=BASE / "data" / "rwis.csv")
    parser.add_argument("--output", type=Path, default=BASE / "output" / "jeonbuk_map.html")
    parser.add_argument("--open", action="store_true", help="완료 후 기본 웹브라우저에서 열기")
    args = parser.parse_args()
    try:
        build(args)
    except (OSError, ValueError, csv.Error, KeyError) as exc:
        print(f"실행 오류: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
