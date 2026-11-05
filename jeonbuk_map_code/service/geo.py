"""구간 선과 위경도 경로를 맞추는 계산입니다. Python 기본 기능만 씁니다.

전북 범위(약 150km)에서는 위경도를 한 점 기준의 평면 미터 좌표로 바꿔도 오차가 수 m 수준입니다.
"""

import math
from collections import defaultdict

LAT0, LON0 = 35.75, 127.0
M_PER_DEG_LAT = 110_950.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT0))
CELL_M = 1000.0


def to_xy(lon, lat):
    return (lon - LON0) * M_PER_DEG_LON, (lat - LAT0) * M_PER_DEG_LAT


def to_lonlat(x, y):
    return x / M_PER_DEG_LON + LON0, y / M_PER_DEG_LAT + LAT0


def point_on_piece(px, py, ax, ay, bx, by):
    """선분 ab 위에서 점 p에 가장 가까운 위치: (거리, 0~1 비율)."""
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)), t


def lines_of(geometry):
    return [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]


class SegmentIndex:
    """구간 선을 짧은 조각으로 나눠 격자에 넣고 가까운 구간을 찾는다."""

    def __init__(self, features):
        self.pieces = []  # (구간 번호, ax, ay, bx, by, 구간 시작부터 a까지 거리)
        self.grid = defaultdict(list)
        for s, f in enumerate(features):
            along = 0.0
            for line in lines_of(f["geometry"]):
                pts = [to_xy(*c) for c in line]
                for (ax, ay), (bx, by) in zip(pts[:-1], pts[1:]):
                    k = len(self.pieces)
                    self.pieces.append((s, ax, ay, bx, by, along))
                    along += math.hypot(bx - ax, by - ay)
                    for cx in range(int(min(ax, bx) // CELL_M), int(max(ax, bx) // CELL_M) + 1):
                        for cy in range(int(min(ay, by) // CELL_M), int(max(ay, by) // CELL_M) + 1):
                            self.grid[(cx, cy)].append(k)

    def nearest_xy(self, x, y, max_m):
        """(구간 번호, 거리 m, 구간 시작부터의 거리 m) 또는 None."""
        reach = int(math.ceil(max_m / CELL_M))
        cx, cy = int(x // CELL_M), int(y // CELL_M)
        seen, best = set(), None
        for gx in range(cx - reach, cx + reach + 1):
            for gy in range(cy - reach, cy + reach + 1):
                for k in self.grid.get((gx, gy), ()):
                    if k in seen:
                        continue
                    seen.add(k)
                    s, ax, ay, bx, by, along = self.pieces[k]
                    d, t = point_on_piece(x, y, ax, ay, bx, by)
                    if d <= max_m and (best is None or d < best[1]):
                        best = (s, d, along + t * math.hypot(bx - ax, by - ay))
        return best

    def nearest(self, lon, lat, max_m):
        return self.nearest_xy(*to_xy(lon, lat), max_m)


def densify(points, step_m):
    """(x, y) 경로를 step_m 이하 간격으로 촘촘히 하고 경로 시작부터의 거리를 함께 돌려준다."""
    out, dist = [points[0]], [0.0]
    for (ax, ay), (bx, by) in zip(points[:-1], points[1:]):
        length = math.hypot(bx - ax, by - ay)
        n = max(1, int(math.ceil(length / step_m)))
        for i in range(1, n + 1):
            out.append((ax + (bx - ax) * i / n, ay + (by - ay) * i / n))
            dist.append(dist[-1] + length / n)
    return out, dist


def match_path(index, path_lonlat, buffer_m=60.0, step_m=25.0, min_run_m=100.0):
    """경로가 지나는 구간을 순서대로 찾는다.

    상·하행이 갈라진 곳은 경로가 구간 선에서 수십 m 떨어지므로 buffer_m을 둔다. 나들목 연결로처럼 구간 옆을 잠깐
    스치는 경우는 min_run_m보다 짧은 구간 묶음으로 나타나므로 뺀다.
    반환: ([{"seg": 구간 번호, "enter_m": 경로상 시작, "exit_m": 경로상 끝, "offset_m": 평균 이격}], 경로 전체 길이 m)
    """
    points, dist = densify([to_xy(lon, lat) for lon, lat in path_lonlat], step_m)
    runs = []
    for (x, y), d in zip(points, dist):
        hit = index.nearest_xy(x, y, buffer_m)
        if hit is None:
            continue
        s, off, _ = hit
        last = runs[-1] if runs else None
        # 다른 구간으로 넘어가지 않고 끊겼다 이어진 경우(연결로 분기 등)는 한 묶음으로 본다
        if last and last["seg"] == s and d - last["exit_m"] <= 4 * step_m:
            last["exit_m"], last["sum"], last["n"] = d, last["sum"] + off, last["n"] + 1
        else:
            runs.append({"seg": s, "enter_m": d, "exit_m": d, "sum": off, "n": 1})
    kept = []
    for r in runs:
        if r["exit_m"] - r["enter_m"] < min_run_m:
            continue
        if kept and kept[-1]["seg"] == r["seg"]:  # 구간 이음매에서 옆 구간으로 잠깐 튄 조각을 뺀 경우
            kept[-1]["exit_m"] = r["exit_m"]
            continue
        kept.append({"seg": r["seg"], "enter_m": r["enter_m"], "exit_m": r["exit_m"], "offset_m": r["sum"] / r["n"]})
    return kept, dist[-1]
