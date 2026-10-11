"""고속도로 노선을 일정 길이 구간으로 나눈다.

관측값 추정, 결빙 위험도 산출, 지도 가시화는 모두 이 구간 단위로 수행한다.
"""
from src import config


def split_route_segments(centerline, length_m=config.SEGMENT_LENGTH_M):
    """대상 노선(config.TARGET_ROUTES) 중심선을 length_m 단위 구간으로 나눈다.

    Returns:
        구간 ID, 노선명, 구간 geometry, 대표 좌표를 가진 GeoDataFrame
    """
    raise NotImplementedError


def match_stations_to_segments(segments, stations):
    """관측소를 가장 가까운 구간에 연결한다."""
    raise NotImplementedError
