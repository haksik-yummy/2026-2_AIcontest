"""
프로젝트 설정 및 데이터 경로 관리
2026 DATA·AI 분석 경진대회 - 전북도 고속도로 결빙위험도 분석
"""
from pathlib import Path

# ===== 프로젝트 루트 =====
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
MODEL_DIR = PROJECT_ROOT / "models"

# 출력 디렉토리 생성
OUTPUT_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

# ===== 데이터 경로 =====
# 1. RWIS(도로기상) 관측 데이터
RWIS_CSV = DATA_DIR / "1. 전북도 고속도로 RWIS(도로기상) 관측 데이터.csv"

# 2. ASOS(종관기상) 관측 데이터
ASOS_CSV = DATA_DIR / "2. 전북도 ASOS(종관기상) 관측 데이터.csv"

# 3. AWS(방재기상) 관측 데이터
AWS_CSV = DATA_DIR / "3. 전북도 AWS(방재기상) 관측 데이터.csv"

# 4. 교량 위경도 데이터
BRIDGE_CSV = DATA_DIR / "4. 전북도 교량 위경도 데이터.csv"

# 5. 터널 위경도 데이터
TUNNEL_CSV = DATA_DIR / "5. 전북도 터널 위경도 데이터.csv"

# 6. 고속도로 곡률 데이터 (Shapefile)
CURVATURE_SHP_DIR = DATA_DIR / "6. 전북도 고속도로 곡률 데이터" / "6. 전북도 고속도로 곡률 데이터"
CURVATURE_SHP = CURVATURE_SHP_DIR / "jeonbuk_convexity_points.shp"

# 7. 수치 표고 모델(DEM) 고도 데이터
DEM_TIF = DATA_DIR / "7. 전북도 수치 표고 모델 고도 데이터.tif"

# 8. 국토교통부 도로/교량/터널/하천 경계 데이터
GEO_BASE_DIR = (
    DATA_DIR
    / "8. 국토교통부 도로, 교량, 터널, 하천 경계 데이터"
    / "국토교통부 도로, 교량, 터널, 하천 경계 데이터"
)
ROAD_SHP_DIR = GEO_BASE_DIR / "C_UQ151(도로)_전북도_국토부_디지털트윈국토"
BRIDGE_SHP_DIR = GEO_BASE_DIR / "N3A_A0070000(교량)_국토부_디지털트윈국토"
TUNNEL_SHP_DIR = GEO_BASE_DIR / "N3A_A0110020(터널)_국토부_디지털트윈국토"
RIVER_SHP_DIR = GEO_BASE_DIR / "국가기본도_하천경계_국토부_디지털트윈국토"
EXPRESSWAY_ZONE_DIR = GEO_BASE_DIR / "LSMD_CONT_UI201_전북도(고속국도 접도구역)_국토부_디지털트윈국토"

# 데이터 설명 PDF
DATA_DESC_PDF = DATA_DIR / "데이터 설명자료(노면상태, 풍향, 운형, 현상번호).pdf"

# ===== 공통 설정 =====
CSV_ENCODING = "cp949"
RANDOM_SEED = 42


def load_csv(path, **kwargs):
    """CP949 인코딩 CSV 로드 헬퍼"""
    import pandas as pd
    return pd.read_csv(path, encoding=CSV_ENCODING, **kwargs)

