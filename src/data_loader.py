"""
데이터 로딩 유틸리티
각 데이터셋에 맞는 전처리를 포함한 로더 함수 모음
"""
import pandas as pd
import geopandas as gpd
import rasterio

from . import config


def load_rwis() -> pd.DataFrame:
    """1. RWIS(도로기상) 관측 데이터 로드"""
    df = config.load_csv(config.RWIS_CSV)
    df["관측시각 (KST)"] = pd.to_datetime(df["관측시각 (KST)"])
    return df


def load_asos() -> pd.DataFrame:
    """2. ASOS(종관기상) 관측 데이터 로드"""
    df = config.load_csv(config.ASOS_CSV)
    df["시각"] = pd.to_datetime(df["시각"])
    return df


def load_aws() -> pd.DataFrame:
    """3. AWS(방재기상) 관측 데이터 로드"""
    df = config.load_csv(config.AWS_CSV)
    df["시각(KST)"] = pd.to_datetime(df["시각(KST)"])
    return df


def load_bridge_locations() -> pd.DataFrame:
    """4. 교량 위경도 데이터 로드"""
    return config.load_csv(config.BRIDGE_CSV)


def load_tunnel_locations() -> pd.DataFrame:
    """5. 터널 위경도 데이터 로드"""
    return config.load_csv(config.TUNNEL_CSV)


def load_curvature() -> gpd.GeoDataFrame:
    """6. 고속도로 곡률 Shapefile 로드"""
    return gpd.read_file(config.CURVATURE_SHP)


def load_dem():
    """7. DEM(수치표고모델) GeoTIFF 로드
    Returns:
        tuple: (numpy array, rasterio profile metadata)
    """
    with rasterio.open(config.DEM_TIF) as src:
        dem_array = src.read(1)
        profile = src.profile
    return dem_array, profile


def load_road_shp() -> gpd.GeoDataFrame:
    """8-1. 도로 Shapefile"""
    return gpd.read_file(config.ROAD_SHP_DIR / "C_UQ151.shp")


def load_bridge_shp() -> gpd.GeoDataFrame:
    """8-2. 교량 Shapefile"""
    return gpd.read_file(config.BRIDGE_SHP_DIR / "N3A_A0070000.shp")


def load_tunnel_shp() -> gpd.GeoDataFrame:
    """8-3. 터널 Shapefile"""
    return gpd.read_file(config.TUNNEL_SHP_DIR / "N3A_A0110020.shp")


def load_river_shp() -> gpd.GeoDataFrame:
    """8-4. 하천 경계 Shapefile"""
    return gpd.read_file(config.RIVER_SHP_DIR / "TN_RIVER_BNDRY.shp")


def load_expressway_zone() -> gpd.GeoDataFrame:
    """8-5. 고속국도 접도구역 Shapefile"""
    return gpd.read_file(config.EXPRESSWAY_ZONE_DIR / "LSMD_CONT_UI201_52_202608.shp")

