"""실시간 추론에 필요한 정적 입력을 만듭니다. 프로젝트 환경에서 한 번만 실행합니다.

실행: python jeonbuk_map_code/realtime/build_static.py

DEM과 관측소·구간 좌표에서 보간 거리·표고·지형 수평선을 미리 계산해 realtime/static/inputs.npz에 저장합니다.
계산은 02-2의 terrain_features, horizon_angles와 같습니다.
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402

N_AZ = 36  # 지형 수평선 방위 구간 (10도 간격), 02-2와 같음


def load_dem():
    with rasterio.open(config.RAW_DIR / config.RAW_FILES["dem"]) as src:
        dem, tf = src.read(1).astype("float32"), src.transform
    dem[dem < -1000] = np.nan
    dem *= json.load(open(config.PROCESSED_DIR / "features.json", encoding="utf-8"))["dem_scale"]
    return dem, tf


def point_elevation(xy, dem, tf):
    """02-2 terrain_features(radius_m=30)의 표고: 셀 값, 비어 있으면 주변 평균, DEM 밖이면 0."""
    r = int(round(30 / tf.a))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    disk = (xx ** 2 + yy ** 2) <= r ** 2
    out = []
    for x, y in xy:
        col, row = ~tf * (x, y)
        row, col = int(row), int(col)
        win = dem[row - r:row + r + 1, col - r:col + r + 1][disk] if (
            r <= row < dem.shape[0] - r and r <= col < dem.shape[1] - r) else np.array([np.nan])
        if np.isnan(win).all():
            out.append(0.0)
            continue
        out.append(dem[row, col] if not np.isnan(dem[row, col]) else np.nanmean(win))
    return np.array(out, dtype="float64")


def horizon_angles(xy, elev, dem, tf, max_dist=5000, step=60):
    """점별·방위별 지형 수평선 고도각(도). 02-2와 같음."""
    az = np.radians(np.arange(N_AZ) * 360 / N_AZ)
    dists = np.arange(step, max_dist + step, step)
    out = np.zeros((len(xy), N_AZ), dtype="float32")
    for i, ((x, y), z0) in enumerate(zip(xy, elev)):
        px = x + np.sin(az)[:, None] * dists
        py = y + np.cos(az)[:, None] * dists
        col, row = ~tf * (px, py)
        row, col = row.astype(int), col.astype(int)
        inside = (row >= 0) & (row < dem.shape[0]) & (col >= 0) & (col < dem.shape[1])
        z = np.full(px.shape, np.nan, dtype="float32")
        z[inside] = dem[row[inside], col[inside]]
        with np.errstate(invalid="ignore"):
            ang = np.degrees(np.arctan((z - z0) / dists))
        out[i] = np.clip(np.nan_to_num(ang, nan=0).max(axis=1), 0, None)
    return out


def project(df):
    g = gpd.GeoSeries(gpd.points_from_xy(df["lon"], df["lat"]), crs=4326).to_crs(5179)
    return np.c_[g.x, g.y]


def main():
    P = config.PROCESSED_DIR
    dem, tf = load_dem()
    aws = pd.read_parquet(P / "aws_stations.parquet")
    asos = pd.read_parquet(P / "asos_stations.parquet")
    stations = pd.read_parquet(P / "stations.parquet")
    train = stations[~stations["holdout"]].reset_index(drop=True)
    segments = gpd.read_file(P / "segments.gpkg")
    b3 = json.load(open(config.MODEL_DIR / "road_temp_b3.json", encoding="utf-8"))
    assert sorted(train["stn"]) == sorted(b3["train_stations"]), "학습 지점이 B3 설정과 다릅니다"

    aws_xy, asos_xy, src_xy = project(aws), project(asos), project(train)
    seg_xy = segments[["mid_x", "mid_y"]].to_numpy(float)
    src_elev, seg_elev = train["elev"].to_numpy(float), segments["elev"].to_numpy(float)
    out = HERE / "static"
    out.mkdir(exist_ok=True)
    np.savez_compressed(
        out / "inputs.npz",
        aws_stn=aws["stn"].to_numpy(int), aws_xy=aws_xy, aws_elev=point_elevation(aws_xy, dem, tf),
        asos_stn=asos["stn"].to_numpy(int), asos_xy=asos_xy, asos_elev=point_elevation(asos_xy, dem, tf),
        src_stn=train["stn"].to_numpy(int), src_xy=src_xy, src_elev=src_elev, src_lat=train["lat"].to_numpy(float),
        src_lon=train["lon"].to_numpy(float), src_horizon=horizon_angles(src_xy, src_elev, dem, tf),
        seg_id=segments["seg_id"].to_numpy(str), seg_xy=seg_xy, seg_elev=seg_elev, seg_lat=segments["lat"].to_numpy(float),
        seg_lon=segments["lon"].to_numpy(float), seg_horizon=horizon_angles(seg_xy, seg_elev, dem, tf),
        all_stn=stations["stn"].to_numpy(int))
    print(f"AWS {len(aws)}, ASOS {len(asos)}, RWIS 원천 {len(train)}, 구간 {len(segments)} → {out / 'inputs.npz'}")


if __name__ == "__main__":
    main()
