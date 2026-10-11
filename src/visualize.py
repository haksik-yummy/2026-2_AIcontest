"""결과 시각화. 그림은 config.FIGURE_DIR에 저장한다."""
from src import config


def plot_estimation(df, station_id):
    """검증 지점의 실제 관측값과 추정값을 비교하는 그림을 그린다."""
    raise NotImplementedError


def plot_risk_map(scored_segments):
    """구간별 결빙 위험도 지도를 그린다. (jpg/png)"""
    raise NotImplementedError


def export_risk_shapefile(scored_segments):
    """구간별 결빙 위험도를 shapefile로 내보낸다."""
    raise NotImplementedError
