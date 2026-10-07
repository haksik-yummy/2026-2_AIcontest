"""프로젝트 전역 설정: 경로, 분석 기간, 대상 노선, 검증 지점, 평가 기준."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ===== 경로 =====
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"              # 경진대회 제공 데이터 (20261007 배포본)
PROCESSED_DIR = DATA_DIR / "processed"  # 정제·병합한 중간 데이터
RESULT_DIR = DATA_DIR / "results"       # 제출용 CSV (성능지표, 구간별 추정값 등)
MODEL_DIR = ROOT / "model"
FIGURE_DIR = ROOT / "figures"

# 제공 데이터 위치 (RAW_DIR 기준, 일별 CSV는 glob 패턴)
RAW_FILES = {
    "rwis": "1. 전북도 고속도로 RWIS(도로기상) 관측 데이터/Jeonbuk_RWIS_daily_*.csv",
    "fog": "1-1. 전북도 고속도로 목표안개 관측소(2개소) 관측 데이터/Jeonbuk_RWIS_daily_*.csv",
    "asos": "2. 전북도 ASOS(종관기상) 관측 데이터/Jeonbuk_ASOS_daily_*.csv",
    "aws": "3. 전북도 AWS(방재기상) 관측 데이터/Jeonbuk_aws_daily_*.csv",
    "bridge": "4. 전북도 교량 위경도 데이터.csv",
    "tunnel": "5. 전북도 터널 위경도 데이터.csv",
    "centerline": "6. 전북도 고속도로 중심선 데이터/jb_road_center_line.shp",
    "dem": "7. 전북도 수치 표고 모델 고도 데이터.tif",
    "boundary": "8. 국토교통부 도로, 교량, 터널, 하천 경계 데이터.zip",
}
CSV_ENCODING = "utf-8-sig"  # 제공 CSV는 BOM이 붙은 UTF-8

# ===== 분석 기간 (겨울철만 제공) =====
PERIODS = [
    ("2024-11-01", "2025-02-28"),
    ("2025-11-01", "2026-02-28"),
]
TIME_STEP = "10min"  # RWIS·AWS 관측 간격, 예측 결과도 10분 단위로 제시

# ===== 대상 노선 (RWIS '고속도로' 컬럼 값 기준) =====
TARGET_ROUTES = ["서해안", "통영-대전중부선", "호남선"]

# ===== 검증 지점: 학습에서 제외하고 성능 평가에만 사용 =====
HOLDOUT_STATIONS = {
    12410: ("부곡교", "서해안"),
    33411: ("삼봉", "통영-대전중부선"),
    23402: ("해전", "호남선"),
}

# ===== 결빙 판정 =====
# 노면상태가 Ice이면 결빙(1), 그 외는 모두 비결빙(0)으로 이진 분류
ICE_STATE_CODES = []  # TODO: 데이터 설명자료 PDF에서 Ice에 해당하는 노면상태 값 확인

# ===== 구간 분할 =====
SEGMENT_LENGTH_M = 1000  # 500 또는 1000 (제출 형식 기준)
