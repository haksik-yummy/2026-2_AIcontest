"""외부 데이터 접합: ERA5-Land(격자별 시간 시계열)와 서해 해기차(dT).

- 모든 시각은 KST. 열 이름의 `datetime`은 10분/1시간 간격 시각 키.
- 시간 보간은 직전 값 유지(ffill)만 쓴다. 미래 값을 끌어오지 않는다.
- 구간(또는 지점)과 격자 연결은 중간점 좌표가 속한 0.1도 격자(보유한 27개 중 최근접)로 한다.
"""
import re
import numpy as np
import pandas as pd
from src import config

EXTERNAL_DIR = config.DATA_DIR / "external"
ERA5_DIR = EXTERNAL_DIR / "era5land_cells"
HAEGICHA_FILE = EXTERNAL_DIR / "haegicha_6h_kst.csv"

ERA5_VARS = ["t2m_c", "d2m_c", "skt_c", "dewpt_depression_c", "sp_hpa", "tp_mm", "sf_mm",
             "ssrd_wm2", "strd_wm2", "wind_speed_ms", "wind_dir_deg"]


def available_cells():
    """보유한 ERA5-Land 격자 (lat, lon) 목록."""
    out = []
    for p in sorted(ERA5_DIR.glob("era5land_cell_*.csv")):
        m = re.match(r"era5land_cell_([\d.]+)_([\d.]+)\.csv", p.name)
        out.append((float(m.group(1)), float(m.group(2))))
    return out


def cell_for_point(lon, lat, cells=None):
    """좌표가 속한 0.1도 격자. 보유 격자가 아니면 가장 가까운 보유 격자."""
    cells = cells or available_cells()
    c = (round(lat, 1), round(lon, 1))
    if c in cells:
        return c
    return min(cells, key=lambda q: (q[0] - lat) ** 2 + (q[1] - lon) ** 2)


def load_era5_cell(cell, freq="1h"):
    """격자 한 개의 시계열. freq='10min'이면 직전 값을 유지해 10분 간격으로 늘린다.

    추가 변수: t2m_7d_mean(직전 7일 평균 기온), t2m_min12h(직전 12시간 최저 기온). 둘 다 현재 시각까지만 사용.
    """
    f = ERA5_DIR / f"era5land_cell_{cell[0]:.1f}_{cell[1]:.1f}.csv"
    d = pd.read_csv(f, encoding=config.CSV_ENCODING, parse_dates=["time_kst"]).set_index("time_kst").sort_index()
    d = d[ERA5_VARS].copy()
    d["t2m_7d_mean"] = d["t2m_c"].rolling(168, min_periods=24).mean()
    d["t2m_min12h"] = d["t2m_c"].rolling(12, min_periods=1).min()
    if freq != "1h":
        d = d.resample(freq).ffill()
    d.index.name = "datetime"
    return d.add_prefix("era5l_")


def load_haegicha(freq="1h"):
    """서해 해기차(dT = 전날 해수면온도 - 850hPa 기온). A(36.0N,126.0E), B(36.5N,125.5E) 두 점. 모든 구간 공통."""
    d = pd.read_csv(HAEGICHA_FILE, encoding=config.CSV_ENCODING, parse_dates=["time_kst"]).set_index("time_kst").sort_index()
    d = d.resample(freq).ffill()
    d.index.name = "datetime"
    return d.add_prefix("sea_")


def external_features(points, id_col="seg_id", lon="lon", lat="lat", freq="1h", with_sea=True):
    """(id, datetime)별 외부 변수 표. points는 id, lon, lat 열을 가진 DataFrame(구간 중간점 또는 관측소)."""
    cells = available_cells()
    pts = points[[id_col, lon, lat]].copy()
    pts["_cell"] = [cell_for_point(x, y, cells) for x, y in zip(pts[lon], pts[lat])]
    parts = []
    for cell, g in pts.groupby("_cell"):
        e = load_era5_cell(cell, freq).reset_index()
        m = g[[id_col]].merge(e, how="cross")
        m["era5_cell"] = f"{cell[0]:.1f}_{cell[1]:.1f}"
        parts.append(m)
    out = pd.concat(parts, ignore_index=True)
    if with_sea:
        out = out.merge(load_haegicha(freq).reset_index(), on="datetime", how="left")
    return out
