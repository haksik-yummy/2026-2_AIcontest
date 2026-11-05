"""서해 해기차에 쓸 ERA5 기압면 시계열을 받아 data/external/era5pl_A_raw, era5pl_B_raw로 저장한다.

실행: python scripts/external/download_era5_850hpa.py
필요: CDS 계정과 ~/.cdsapirc, cdsapi 패키지 (자료를 다시 받을 때만 쓰므로 environment.yml에는 없다)
이 자료는 6시간 간격이고 기압면 13개를 한 번에 준다. 850hPa는 build_dT_final.py가 고른다.
"""
import cdsapi, os, shutil, time, zipfile
import pandas as pd
from functools import reduce

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = os.path.join(ROOT, "data", "external")
POINTS = {"A": (36.0, 126.0), "B": (36.5, 125.5)}      # build_dT_final.py와 같은 지점 (위도, 경도)
KEYS = ["valid_time", "pressureLevel", "latitude", "longitude"]

dataset = "reanalysis-era5-pressure-levels-timeseries"
base_req = {
    "variable": ["temperature", "u_component_of_wind", "v_component_of_wind"],
    "date": ["2024-10-25/2026-02-28"],
    "data_format": "csv",
}

def save_raw(path, out):
    """받은 파일을 CSV 한 개로 저장한다. 변수별 CSV를 묶은 zip이면 시각·기압면으로 합친다."""
    if not zipfile.is_zipfile(path):
        shutil.copyfile(path, out)
        return
    with zipfile.ZipFile(path) as z:
        dfs = []
        for n in z.namelist():
            if n.endswith(".csv"):
                with z.open(n) as f:
                    dfs.append(pd.read_csv(f))
    m = reduce(lambda a, b: a.merge(b, on=KEYS, how="outer"), dfs).sort_values(KEYS[:2])
    m.to_csv(out, index=False)

client = cdsapi.Client()
for name, (lat, lon) in POINTS.items():
    out = os.path.join(BASE, f"era5pl_{name}_raw")
    if os.path.exists(out):
        print("이미 있음:", out)
        continue
    tmp = out + ".download"
    print("요청:", name, lat, lon, flush=True)
    client.retrieve(dataset, dict(base_req, location={"longitude": lon, "latitude": lat})).download(tmp)
    save_raw(tmp, out)
    os.remove(tmp)
    print("저장:", out, flush=True)
    time.sleep(10)
