import cdsapi, os, time, glob, shutil, zipfile
import numpy as np, pandas as pd
from functools import reduce

BASE = r"C:\Users\기환\Desktop\sdk\era5land"
MERGED = os.path.join(BASE, "merged")
CELLS_DIR = os.path.join(BASE, "cells")
os.makedirs(CELLS_DIR, exist_ok=True)

# 도로 중심선이 지나는 ERA5-Land 0.1° 격자 27칸 (격자 중심 위도, 경도)
NEED = [
    (35.3, 126.6), (35.4, 126.6), (35.4, 126.7), (35.5, 126.7), (35.5, 126.8), (35.6, 126.7),
    (35.6, 126.8), (35.6, 126.9), (35.7, 126.7), (35.7, 126.8), (35.7, 126.9), (35.7, 127.0),
    (35.7, 127.6), (35.8, 126.8), (35.8, 127.0), (35.8, 127.6), (35.8, 127.7), (35.9, 126.8),
    (35.9, 127.0), (35.9, 127.1), (35.9, 127.6), (35.9, 127.7), (36.0, 126.8), (36.0, 127.1),
    (36.0, 127.6), (36.0, 127.7), (36.1, 127.1),
]

dataset = "reanalysis-era5-land-timeseries"
base_req = {
    "variable": [
        "2m_dewpoint_temperature", "2m_temperature", "surface_pressure",
        "total_precipitation", "surface_solar_radiation_downwards",
        "surface_thermal_radiation_downwards", "skin_temperature", "snowfall",
        "10m_u_component_of_wind", "10m_v_component_of_wind"
    ],
    "date": ["2024-10-25/2026-02-28"],
    "data_format": "csv",
}

def cell_csv(lat, lon):
    return os.path.join(MERGED, f"era5land_cell_{lat:.1f}_{lon:.1f}.csv")

def merge_zip(zip_path, out_csv):
    with zipfile.ZipFile(zip_path) as z:
        dfs = []
        for n in z.namelist():
            if n.endswith(".csv"):
                with z.open(n) as f:
                    dfs.append(pd.read_csv(f, parse_dates=["valid_time"]))
    grid = dfs[0][["latitude", "longitude"]].iloc[0]
    dfs = [d.drop(columns=["latitude", "longitude"]) for d in dfs]
    m = reduce(lambda a, b: a.merge(b, on="valid_time", how="outer"), dfs).sort_values("valid_time")
    o = pd.DataFrame({"time_kst": m["valid_time"] + pd.Timedelta(hours=9)})   # UTC → KST
    o["t2m_c"] = m["t2m"] - 273.15
    o["d2m_c"] = m["d2m"] - 273.15
    o["skt_c"] = m["skt"] - 273.15
    o["dewpt_depression_c"] = m["t2m"] - m["d2m"]
    o["sp_hpa"] = m["sp"] / 100
    o["tp_mm"] = (m["tp"] * 1000).clip(lower=0)
    o["sf_mm"] = (m["sf"] * 1000).clip(lower=0)
    o["ssrd_wm2"] = (m["ssrd"] / 3600).clip(lower=0)
    o["strd_wm2"] = (m["strd"] / 3600).clip(lower=0)
    o["wind_speed_ms"] = np.hypot(m["u10"], m["v10"])
    o["wind_dir_deg"] = (270 - np.degrees(np.arctan2(m["v10"], m["u10"]))) % 360
    o["grid_lat"], o["grid_lon"] = grid["latitude"], grid["longitude"]
    o.to_csv(out_csv, index=False, encoding="utf-8-sig")
    return o

# 1) 이미 받은 지점별 파일(17개)에서 같은 격자 파일을 복사해 격자 이름으로 저장
for f in glob.glob(os.path.join(MERGED, "era5land_[0-9]*.csv")):
    g = pd.read_csv(f, nrows=1)
    key = (round(float(g["grid_lat"].iloc[0]), 1), round(float(g["grid_lon"].iloc[0]), 1))
    if key in NEED and not os.path.exists(cell_csv(*key)):
        shutil.copyfile(f, cell_csv(*key))
        print("기존 파일 재사용:", os.path.basename(f), "→ 격자", key)

# 2) 아직 없는 격자만 시계열로 요청 (한 번에 하나씩, 오류 시 중단)
todo = [c for c in NEED if not os.path.exists(cell_csv(*c))]
print("전체 격자:", len(NEED), "/ 이미 있음:", len(NEED) - len(todo), "/ 새로 요청:", len(todo), flush=True)

client = None
for lat, lon in todo:
    zip_path = os.path.join(CELLS_DIR, f"cell_{lat:.1f}_{lon:.1f}.zip")
    if not os.path.exists(zip_path):
        if client is None:
            client = cdsapi.Client()
        req = dict(base_req, location={"longitude": lon, "latitude": lat})
        print("요청:", lat, lon, flush=True)
        try:
            client.retrieve(dataset, req).download(zip_path)
        except Exception as e:
            print("오류로 중단:", lat, lon, e)                 # 자동 재시도 없이 멈춤
            break
        time.sleep(10)
    o = merge_zip(zip_path, cell_csv(lat, lon))
    print("병합 완료:", lat, lon, o.shape, "격자:", round(o["grid_lat"].iloc[0], 1), round(o["grid_lon"].iloc[0], 1), flush=True)

print("현재 보유 격자:", sum(os.path.exists(cell_csv(*c)) for c in NEED), "/", len(NEED))