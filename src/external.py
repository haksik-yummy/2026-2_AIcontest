"""외부 데이터 접합: ERA5-Land(격자별 시간 시계열)와 서해 해기차(dT).

- 모든 시각은 KST이고 시각 열 이름은 `time`이다.
- 시간축 정렬은 02-1의 ASOS 자료와 같은 규칙이다. 순간값은 시각 사이를 선형 보간하고, 그 시각에 끝나는
  1시간 합계(강수·강설·복사)는 시간 가운데(-30분)에 두고 보간해 시간당 비율로 쓴다.
- 구간(또는 지점)과 격자 연결은 좌표에서 가장 가까운 0.1도 격자이다. 없는 격자는 가까운 격자로 대신하지 않고 오류를 낸다.
"""
import re

import numpy as np
import pandas as pd

from src import config

EXTERNAL_DIR = config.DATA_DIR / "external"
ERA5_DIR = EXTERNAL_DIR / "era5land_cells"
HAEGICHA_FILE = EXTERNAL_DIR / "haegicha_6h_kst.csv"

INST = {"t2m_c": "t2m", "d2m_c": "d2m", "skt_c": "skt", "wind_speed_ms": "ws10"}       # 순간값
ACC = {"tp_mm": "tp_mmh", "sf_mm": "sf_mmh", "ssrd_wm2": "ssrd", "strd_wm2": "strd"}   # 그 시각에 끝나는 1시간 합계


def analysis_times():
    """분석 기간의 10분 시간축과 시각별 겨울 번호."""
    times = pd.DatetimeIndex(np.concatenate([
        pd.date_range(s, pd.Timestamp(e) + pd.Timedelta("23:50:00"), freq=config.TIME_STEP) for s, e in config.PERIODS]))
    period_id = np.searchsorted([pd.Timestamp(s) for s, _ in config.PERIODS[1:]], times, side="right")
    return times, period_id


def available_cells():
    """보유한 ERA5-Land 격자 (lat, lon) 목록."""
    out = []
    for p in sorted(ERA5_DIR.glob("era5land_cell_*.csv")):
        m = re.match(r"era5land_cell_([\d.]+)_([\d.]+)\.csv", p.name)
        out.append((float(m.group(1)), float(m.group(2))))
    return out


def cell_of(lat, lon):
    """가장 가까운 0.1° 격자 중심 (위도, 경도)."""
    return round(round(lat / 0.1) * 0.1, 1), round(round(lon / 0.1) * 0.1, 1)


def load_cell(cell):
    """격자 한 개의 1시간 시계열 (파일 그대로, 시각 색인)."""
    f = ERA5_DIR / f"era5land_cell_{cell[0]:.1f}_{cell[1]:.1f}.csv"
    return pd.read_csv(f, encoding=config.CSV_ENCODING, parse_dates=["time_kst"]).set_index("time_kst").sort_index()


def to_times(df, times):
    """times에 맞춰 시각 사이를 선형 보간한다. 자료 범위 밖은 비워 둔다."""
    return df.reindex(df.index.union(times)).interpolate(method="time", limit_area="inside").reindex(times)


def align(e, times):
    """1시간 ERA5를 times에 맞춘다. 합계 변수는 시간 가운데(-30분)에 두고 보간한 시간당 비율이 된다."""
    inst = e[list(INST)].rename(columns=INST)
    acc = e[list(ACC)].rename(columns=ACC)
    acc.index = acc.index - pd.Timedelta("30min")
    return pd.concat([to_times(p, times) for p in (inst, acc)], axis=1)


def add_history(df, period_id, steps=18):
    """지난 3시간(10분 18칸) 강수·강설 합(mm)과 강설 비율. 기간(겨울)마다 따로 누적한다."""
    g = pd.Series(period_id, index=df.index)
    for c in ("tp", "sf"):
        df[f"{c}3h"] = (df[f"{c}_mmh"] / 6).groupby(g).transform(lambda x: x.rolling(steps, min_periods=1).sum())
    df["snowfrac3h"] = (df["sf3h"] / df["tp3h"]).where(df["tp3h"] > 0.1, 0.0)
    return df


def cell_features(cell, times, period_id):
    """격자 한 개의 외부 변수 (10분 시간축). 직전 7일 평균·12시간 최저 기온은 1시간 자료로 만든 뒤 맞춘다."""
    e = load_cell(cell)
    t2m = e["t2m_c"]
    past = pd.DataFrame({"t2m_7d_mean": t2m.rolling(168, min_periods=24).mean(),
                         "t2m_min12h": t2m.rolling(12, min_periods=1).min()})
    return add_history(align(e, times), period_id).join(to_times(past, times))


def load_haegicha(times):
    """서해 해기차(dT = 전날 해수면온도 - 850hPa 기온)를 times에 맞춘다. 모든 구간에 같은 시계열이다.

    A(36.0N,126.0E), B(36.5N,125.5E) 두 점. 6시간 값 사이를 선형 보간하고, 풍향은 0/360을 넘나들므로
    바람을 u·v 성분으로 보간한 뒤 풍향·풍속으로 되돌린다.
    """
    d = pd.read_csv(HAEGICHA_FILE, encoding=config.CSV_ENCODING, parse_dates=["time_kst"]).set_index("time_kst").sort_index()
    for p in "AB":
        speed, rad = d.pop(f"wind850_speed_ms_{p}"), np.radians(d.pop(f"wind850_dir_deg_{p}"))
        d[f"u850_{p}"], d[f"v850_{p}"] = -speed * np.sin(rad), -speed * np.cos(rad)
    out = to_times(d, times)
    for p in "AB":
        u, v = out.pop(f"u850_{p}"), out.pop(f"v850_{p}")
        out[f"wind850_speed_ms_{p}"] = np.hypot(u, v)
        out[f"wind850_dir_deg_{p}"] = (270 - np.degrees(np.arctan2(v, u))) % 360
    return out.add_prefix("sea_")


def external_features(points, times=None, id_col="seg_id", lon="lon", lat="lat", with_sea=True):
    """(id, time)별 외부 변수 표. points는 id, lon, lat 열을 가진 DataFrame(구간 중간점 또는 관측소).

    times를 주지 않으면 분석 기간의 10분 시간축 전체이다. 정시만 쓰려면 그 일부를 준다.
    """
    full, period_id = analysis_times()
    times = full if times is None else pd.DatetimeIndex(times)
    pts = points[[id_col]].copy()
    pts["_cell"] = [cell_of(y, x) for x, y in zip(points[lon], points[lat])]
    missing = sorted(set(pts["_cell"]) - set(available_cells()))
    if missing:
        raise FileNotFoundError(f"ERA5-Land 격자 파일이 없습니다: {missing}")
    parts = []
    for cell, g in pts.groupby("_cell"):
        e = cell_features(cell, full, period_id).reindex(times).rename_axis("time").reset_index()
        m = g[[id_col]].merge(e, how="cross")
        m["era5_cell"] = f"{cell[0]:.1f}_{cell[1]:.1f}"
        parts.append(m)
    out = pd.concat(parts, ignore_index=True)
    if with_sea:
        out = out.merge(load_haegicha(times).rename_axis("time").reset_index(), on="time", how="left")
    return out
