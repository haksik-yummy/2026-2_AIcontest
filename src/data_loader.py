"""제공 데이터 불러오기.

관측 데이터(RWIS, 목표안개, ASOS, AWS)는 일별 CSV 240개씩 나뉘어 있으므로
하나의 DataFrame으로 합쳐서 반환한다. 경로와 인코딩은 config를 따른다.
"""
from src import config


def load_observations(source):
    """관측 데이터를 기간 전체로 합쳐서 불러온다.

    Args:
        source: "rwis", "fog", "asos", "aws" 중 하나

    Returns:
        관측시각·지점번호를 포함한 DataFrame
    """
    raise NotImplementedError


def load_bridges():
    """교량 시작·종료점 위경도를 불러온다. (컬럼 순서: 위도, 경도)"""
    raise NotImplementedError


def load_tunnels():
    """터널 시작·종료점 위경도를 불러온다. (컬럼 순서: 경도, 위도로 교량과 반대)"""
    raise NotImplementedError


def load_centerline():
    """고속도로 중심선 shapefile을 불러온다."""
    raise NotImplementedError


def load_dem():
    """수치 표고 모델(TIF)을 불러온다."""
    raise NotImplementedError


def load_boundary():
    """국토교통부 도로·교량·터널·하천 경계 데이터(zip 내 shapefile)를 불러온다."""
    raise NotImplementedError
