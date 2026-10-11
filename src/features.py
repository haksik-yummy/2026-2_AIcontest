"""결빙 영향요인 후보 변수 생성 (기상, 도로, 지형)."""


def add_meteo_features(df):
    """기상 파생 변수를 추가한다. (예: 노면온도-기온 차, 이슬점 관련 변수)"""
    raise NotImplementedError


def add_road_features(points, bridges, tunnels, centerline):
    """지점별 도로환경 변수를 추가한다. (예: 교량·터널 여부 및 거리, 곡률)"""
    raise NotImplementedError


def add_terrain_features(points, dem, boundary):
    """지점별 지형·환경 변수를 추가한다. (예: 고도, 하천과의 거리)"""
    raise NotImplementedError
