"""기존 전북도 결빙취약구간 22개소를 노선 구간에 연결한다.

표는 문제 설명의 [전북도 결빙취약구간 현황]을 옮긴 것이다 (QnA 2026-11-02 1번).
표의 위치는 이정(km)뿐이라 좌표를 아는 기준점을 이용해 도로 위 위치로 바꾼다.

- 기준점의 이정은 노선별 나들목 누적거리(위키백과)와 행정안전부 상습 결빙구간(공공데이터포털 15067396)에서 가져왔다.
- 행정안전부 자료의 구간번호 70100-83~91, 95는 이 표와 연장·순서가 같아서 기점·종점 좌표를 이정의 기준점으로 쓴다.
- 기준점 사이는 중심선을 그래프로 이어 찾은 경로의 길이에 비례해 나눈다.
- 나들목 좌표는 OpenStreetMap(Nominatim, ODbL)에서 찾았다.
"""
import heapq

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree

SECTION_COLUMNS = ["no", "branch", "road", "km_from", "km_to", "length_km", "grade"]
SECTIONS = pd.DataFrame([
    (1, "전주", "호남선", 129.00, 130.00, 1.00, "C"),
    (2, "전주", "호남선", 132.00, 133.00, 1.00, "C"),
    (3, "부안", "서해안선", 97.99, 100.66, 2.67, "A"),
    (4, "부안", "서해안선", 142.42, 144.68, 2.26, "C"),
    (5, "무주", "통영대전선", 125.50, 134.00, 8.50, "B"),
    (6, "무주", "통영대전선", 155.61, 158.11, 2.50, "B"),
    (7, "무주", "통영대전선", 172.58, 173.58, 1.00, "C"),
    (8, "무주", "통영대전선", 174.58, 175.58, 1.00, "C"),
    (9, "무주", "통영대전선", 199.18, 201.06, 1.88, "C"),
    (10, "논산", "호남선", 171.00, 172.00, 1.00, "C"),
    (11, "논산", "호남선", 173.00, 174.00, 1.00, "C"),
    (12, "논산", "호남선", 180.00, 181.00, 1.00, "C"),
    (13, "논산", "호남선", 186.00, 187.00, 1.00, "C"),
    (14, "논산", "호남지선", 13.00, 14.00, 1.00, "C"),
    (15, "논산", "호남지선", 24.00, 27.00, 3.00, "C"),
    (16, "진안", "새만금포항선", 24.36, 26.09, 1.73, "B"),
    (17, "진안", "순천완주선", 94.22, 95.12, 0.90, "B"),
    (18, "진안", "순천완주선", 98.69, 99.82, 1.13, "C"),
    (19, "보령", "서해안선", 166.10, 168.10, 2.00, "C"),
    (20, "보령", "서해안선", 192.83, 193.83, 1.00, "C"),
    (21, "보령", "서해안선", 194.83, 195.83, 1.00, "B"),
    (22, "보령", "서해안선", 221.83, 222.83, 1.00, "C"),
], columns=SECTION_COLUMNS)

ROUTE_OF_ROAD = {"서해안선": "서해안", "호남선": "호남선", "통영대전선": "통영-대전중부선"}
CENTERLINE_NAME = {"서해안": "서해안고속국도", "호남선": "호남고속국도", "통영-대전중부선": "통영-대전고속국도"}

# 노선별 기준점: (이름, 이정 km, 위도, 경도). 이정 순서로 적는다
ANCHORS = {
    "서해안": [
        ("고창분기점", 74.20, 35.42040, 126.65511),
        ("상습결빙 70100-83 기점", 97.99, 35.625627, 126.699494),
        ("상습결빙 70100-83 종점", 100.66, 35.645382, 126.716212),
        ("부안나들목", 110.90, 35.7262656, 126.7688621),
        ("상습결빙 70100-84 기점", 142.42, 35.986749, 126.823463),
        ("상습결빙 70100-84 종점", 144.68, 36.001614, 126.805674),
    ],
    "호남선": [
        ("내장산나들목", 120.25, 35.5065175, 126.8009773),
        ("정읍나들목", 128.71, 35.5781369, 126.8320536),
        ("태인나들목", 141.55, 35.6601519, 126.9244382),
        ("익산분기점", 177.77, 35.93890, 127.08362),
    ],
    "통영-대전중부선": [
        ("장수분기점", 135.09, 35.72446, 127.61086),
        ("덕유산나들목", 149.55, 35.8403146, 127.6466569),
        ("상습결빙 70100-86 기점", 155.61, 35.893329, 127.664117),
        ("상습결빙 70100-86 종점", 158.11, 35.915664, 127.664941),
        ("무주나들목", 165.58, 35.9747788, 127.6481),
        ("상습결빙 70100-87 기점", 172.58, 36.009090, 127.585065),
    ],
}

STEP_M = 50  # 중심선을 짚는 간격


def _dense_points(lines):
    """선을 STEP_M 간격 점으로 바꾸고 선 안의 이웃 점을 잇는다. 반환: 점 좌표, 간선 목록."""
    xy, edges = [], []
    for line in lines:
        n = max(2, int(line.length / STEP_M) + 1)
        pts = shapely.get_coordinates(shapely.line_interpolate_point(line, np.linspace(0, line.length, n)))
        base = len(xy)
        xy.extend(pts)
        edges.extend((base + i, base + i + 1) for i in range(n - 1))
    return np.asarray(xy), edges


def route_axis(centerline, route, link_m=30):
    """노선의 본선 중심선을 점 그래프로 만든다. 끝점끼리 link_m 안이면 잇는다."""
    main = centerline[(centerline["NAME"] == CENTERLINE_NAME[route])
                      & ((centerline["ONSD"] == "ITH002") | (centerline["RDLN"] >= 2))]
    merged = shapely.line_merge(shapely.union_all(main.geometry.to_numpy()))
    xy, edges = _dense_points(list(getattr(merged, "geoms", [merged])))
    tree = cKDTree(xy)
    edges += [tuple(p) for p in tree.query_pairs(link_m)]
    graph = [[] for _ in range(len(xy))]
    for a, b in edges:
        d = float(np.hypot(*(xy[a] - xy[b])))
        graph[a].append((b, d))
        graph[b].append((a, d))
    return xy, graph, tree


def shortest_path(graph, start, goal):
    """다익스트라. 반환: 점 번호 목록."""
    dist, prev, heap = {start: 0.0}, {}, [(0.0, start)]
    while heap:
        d, u = heapq.heappop(heap)
        if u == goal:
            break
        if d > dist.get(u, np.inf):
            continue
        for v, w in graph[u]:
            nd = d + w
            if nd < dist.get(v, np.inf):
                dist[v], prev[v] = nd, u
                heapq.heappush(heap, (nd, v))
    path = [goal]
    while path[-1] != start:
        path.append(prev[path[-1]])
    return path[::-1]


def anchor_xy(anchors, crs):
    pts = gpd.GeoSeries(gpd.points_from_xy([a[3] for a in anchors], [a[2] for a in anchors]), crs=4326).to_crs(crs)
    return np.column_stack([pts.x, pts.y])


def km_path(centerline, route, anchors=None):
    """기준점을 차례로 지나는 경로를 만들고 경로 위 점마다 이정을 매긴다.

    기준점 사이는 경로 길이에 비례해 나누고, 첫 기준점 앞과 마지막 기준점 뒤는 경로를 노선 끝까지 늘려 길이 그대로 이어 간다.
    반환: 점 좌표 (n x 2), 이정 (n).
    """
    anchors = ANCHORS[route] if anchors is None else anchors
    xy, graph, tree = route_axis(centerline, route)
    nodes = tree.query(anchor_xy(anchors, centerline.crs))[1]
    south, north = _route_ends(xy, graph, nodes[0])
    stops = [south, *nodes, north]
    path = [stops[0]]
    marks = []  # 기준점이 경로에서 차지하는 자리
    for a, b in zip(stops[:-1], stops[1:]):
        path += shortest_path(graph, a, b)[1:]
        marks.append(len(path) - 1)
    marks = marks[:-1]
    pts = xy[path]
    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    km_anchor = np.array([a[1] for a in anchors])
    km = np.interp(s, s[marks], km_anchor)
    km[:marks[0]] = km_anchor[0] - (s[marks[0]] - s[:marks[0]]) / 1000
    km[marks[-1] + 1:] = km_anchor[-1] + (s[marks[-1] + 1:] - s[marks[-1]]) / 1000
    return pts, km


def _route_ends(xy, graph, start):
    """기준점에서 닿는 점 가운데 가장 남쪽과 가장 북쪽 점. 세 노선 모두 남에서 북으로 이어진다."""
    seen, stack = {start}, [start]
    while stack:
        for v, _ in graph[stack.pop()]:
            if v not in seen:
                seen.add(v)
                stack.append(v)
    nodes = np.fromiter(seen, int)
    return nodes[np.argmin(xy[nodes, 1])], nodes[np.argmax(xy[nodes, 1])]


def locate_sections(centerline, segments, sections=SECTIONS, max_dist_m=200):
    """22개소를 구간에 연결한다.

    반환: 구간표 (개소별 상태와 연결 구간), 개소의 도로 위 선 (GeoDataFrame).
    상태는 '비교', '일부 비교'(앞뒤 일부가 전북 구간 밖), '구간 밖'(전북 노선 구간 밖), '대상 노선 아님'이다.
    """
    rows, lines = [], []
    paths = {r: km_path(centerline, r) for r in ANCHORS}
    for sec in sections.itertuples():
        route = ROUTE_OF_ROAD.get(sec.road)
        row = {**sec._asdict(), "route": route, "status": "대상 노선 아님", "matched_km": 0.0, "segments": []}
        row.pop("Index")
        if route is not None:
            pts, km = paths[route]
            inside = (km >= sec.km_from) & (km <= sec.km_to)
            seg = segments[segments["route"] == route]
            if inside.sum() >= 2:
                sub = pts[inside]
                near_idx, dist = seg.sindex.nearest(shapely.points(sub), return_distance=True, return_all=False)
                hits = seg.iloc[near_idx[1][dist <= max_dist_m]]["seg_id"].value_counts()
                picked = hits[hits * STEP_M >= 100].index.tolist()  # 끝이 스치기만 하는 구간은 뺀다
                row["matched_km"] = round(float(km[inside].max() - km[inside].min()), 2)
                row["segments"] = sorted(picked)
                row["status"] = "비교" if row["matched_km"] >= 0.9 * sec.length_km else "일부 비교"
                lines.append({"no": sec.no, "geometry": shapely.LineString(sub)})
            else:
                row["status"] = "구간 밖"
        rows.append(row)
    table = pd.DataFrame(rows)
    geo = gpd.GeoDataFrame(pd.DataFrame(lines).merge(sections, on="no"), geometry="geometry", crs=centerline.crs)
    return table, geo
