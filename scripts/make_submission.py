"""제출 압축 파일을 만듭니다.

실행: python scripts/make_submission.py
출력: dist/2026_AIcontest_submission.zip (모델자료), dist/2026_AIcontest_report.zip (설명 문서)

코드와 모델에 data/results, 추론과 최종 모델 학습에 쓰는 data/processed, 추가 데이터를 더합니다.
대회 제공 원자료(data/raw)는 넣지 않습니다.
설명 문서와 데모영상은 저장소에 없어서 작업 폴더에 있어야 합니다.
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "2026_AIcontest_submission.zip"
REPORT_OUT = ROOT / "dist" / "2026_AIcontest_report.zip"
PROCESSED = ["station_features.parquet", "stations.parquet", "features.json", "rwis_10min.parquet", "estimation_b3.parquet",
             "estimation_oof.parquet", "estimation_cv.json", "estimation_final.json", "station_estimates.parquet",
             "icing_cv.json", "icing_models.joblib"]  # 추론, 03-3, 04-1, 04-3을 data/raw 없이 실행하는 데 쓴다
ITEMS = ["README.md", "requirements.txt", "environment.yml", "docs", "model", "src", "notebooks", "scripts", "demo", "figures",
         "jeonbuk_map_code", "data/results", "data/external/era5land_cells", "data/external/haegicha_6h_kst.csv",
         "data/external/행정안전부_상습 결빙구간_20251107.csv", *(f"data/processed/{name}" for name in PROCESSED)]
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".ipynb_checkpoints"}
SKIP_NAMES = {".gitkeep", ".DS_Store"}
SKIP_PREFIX = ("external_check_",)


LOCAL_ONLY = ["docs/report.pdf", "docs/report.md", "demo/demo.mp4"]  # 저장소에 넣지 않는 제출 파일


def files(item):
    path = ROOT / item
    if path.is_file():
        yield path
        return
    for p in sorted(path.rglob("*")):
        if p.is_file() and not SKIP_DIRS & set(p.parts) and p.name not in SKIP_NAMES and not p.name.startswith(SKIP_PREFIX):
            yield p


def main():
    missing = [i for i in [*ITEMS, *LOCAL_ONLY] if not (ROOT / i).exists()]
    if missing:
        print("없는 항목:", missing, file=sys.stderr)
        return 1
    OUT.parent.mkdir(exist_ok=True)
    count = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for item in ITEMS:
            for p in files(item):
                z.write(p, p.relative_to(ROOT).as_posix())
                count += 1
    print(f"{OUT.relative_to(ROOT)}: 파일 {count}개, {OUT.stat().st_size / 1e6:.0f}MB")
    with zipfile.ZipFile(REPORT_OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(ROOT / "docs" / "report.pdf", "report.pdf")
    print(f"{REPORT_OUT.relative_to(ROOT)}: {REPORT_OUT.stat().st_size / 1e6:.1f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
