"""서해 해기차(dT = 전날 해수면온도 - 850hPa 기온)를 만들어 data/external/haegicha_6h_kst.csv로 저장한다.

실행: python scripts/external/build_dT_final.py
입력: data/external/era5pl_A_raw, era5pl_B_raw (download_era5_850hpa.py가 받는 ERA5 기압면 자료 CSV, valid_time·pressureLevel·t·u·v·latitude·longitude 열).
OISST는 ERDDAP에서 받아 oisst_A.csv, oisst_B.csv로 저장해 다시 쓴다.
"""
import os, urllib.parse
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = os.path.join(ROOT, "data", "external")
POINTS = {"A": (36.0, 126.0), "B": (36.5, 125.5)}      # ERA5 격자 중심 (위도, 경도)
ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/ncdcOisst21Agg_LonPM180.csv"

def load_pl(path, level=850.0):
    d = pd.read_csv(path, parse_dates=["valid_time"])
    d = d[d["pressureLevel"] == level].sort_values("valid_time")
    o = pd.DataFrame({"time_kst": (d["valid_time"] + pd.Timedelta(hours=9)).values})   # UTC → KST
    o["t850_c"] = d["t"].values - 273.15
    o["wind850_speed_ms"] = np.hypot(d["u"].values, d["v"].values)
    o["wind850_dir_deg"] = (270 - np.degrees(np.arctan2(d["v"].values, d["u"].values))) % 360
    o["grid_lat"] = d["latitude"].values
    o["grid_lon"] = d["longitude"].values
    return o.reset_index(drop=True)

def read_sst_csv(path):
    s = pd.read_csv(path)
    s = s[pd.to_numeric(s["sst"], errors="coerce").notna()].copy()     # 2행(단위) 제거
    s["sst"] = s["sst"].astype(float)
    s["time"] = pd.to_datetime(s["time"]).dt.tz_localize(None)
    return s.reset_index(drop=True)

def get_sst(name, lat, lon):
    """ERA5 격자 한 칸(±0.125°)을 덮는 OISST 4개 격자를 받아 일별 평균으로 쓴다."""
    local = os.path.join(BASE, f"oisst_{name}.csv")
    if os.path.exists(local):
        return read_sst_csv(local)
    la0, la1, lo0, lo1 = lat - 0.125, lat + 0.125, lon - 0.125, lon + 0.125
    q = (f"sst[(2024-10-24T12:00:00Z):1:(2026-02-28T12:00:00Z)]"
         f"[(0.0):1:(0.0)][({la0}):1:({la1})][({lo0}):1:({lo1})]")
    url = ERDDAP + "?" + urllib.parse.quote(q, safe="():,.-=")
    s = pd.read_csv(url, skiprows=[1])                                  # 2행은 단위
    s.to_csv(local, index=False)
    return read_sst_csv(local)

out = None
for name, (lat, lon) in POINTS.items():
    raw = os.path.join(BASE, f"era5pl_{name}_raw")
    if not os.path.exists(raw):
        print(f"점 {name}: ERA5 파일이 아직 없어 건너뜀")
        continue
    A = load_pl(raw)
    print(f"점 {name}: 850hPa 행 수 {len(A)}, 격자 {A['grid_lat'].iloc[0]}, {A['grid_lon'].iloc[0]}")
    try:
        sst = get_sst(name, lat, lon)
    except Exception as e:
        print(f"점 {name}: SST 내려받기 실패 → {e}\n  ERDDAP 폼으로 CSV를 받아 oisst_{name}.csv로 저장해 주세요.")
        continue
    print(f"점 {name}: SST 행 {len(sst)}, 격자 위도 {sorted(sst['latitude'].unique())}, 경도 {sorted(sst['longitude'].unique())}")
    s = sst.groupby(sst["time"].dt.normalize())["sst"].mean().asfreq("D").ffill(limit=2)   # 빠진 날은 직전 값으로(최대 2일)
    s_prev = s.shift(1, freq="D")                                       # 하루 전 값 (누수 방지)
    A["date"] = A["time_kst"].dt.normalize()
    A["sst_prev_c"] = A["date"].map(s_prev)
    A["dT_c"] = A["sst_prev_c"] - A["t850_c"]
    keep = A[["time_kst", "t850_c", "wind850_speed_ms", "wind850_dir_deg", "sst_prev_c", "dT_c"]]
    keep = keep.add_suffix(f"_{name}").rename(columns={f"time_kst_{name}": "time_kst"})
    out = keep if out is None else out.merge(keep, on="time_kst", how="outer")

if out is not None:
    out = out.sort_values("time_kst")
    path = os.path.join(BASE, "haegicha_6h_kst.csv")
    out.to_csv(path, index=False, encoding="utf-8-sig")
    print("저장:", path, out.shape)
    print("결측 수:", out.isna().sum().to_dict())
    m = out[(out["time_kst"] >= "2024-11-01") & (out["time_kst"] < "2026-03-01")]
    print(m.groupby(m["time_kst"].dt.to_period("M"))[[c for c in out.columns if c.startswith("dT_c")]].mean().round(1).to_string())
