"""관측 데이터 정제 및 학습/검증 데이터 구성."""
from src import config


def clean_observations(df, source):
    """결측 코드, 이상값, 중복 행을 정리한다.

    Args:
        df: data_loader.load_observations 결과
        source: "rwis", "fog", "asos", "aws" 중 하나
    """
    raise NotImplementedError


def align_time(df, freq=config.TIME_STEP):
    """관측 간격이 다른 자료(ASOS는 1시간)를 10분 시간축에 맞춘다."""
    raise NotImplementedError


def make_ice_label(df):
    """노면상태를 결빙(1)/비결빙(0)으로 변환한다. 기준은 config.ICE_STATE_CODES."""
    raise NotImplementedError


def split_holdout(df):
    """검증 지점(config.HOLDOUT_STATIONS)을 학습 데이터에서 분리한다.

    Returns:
        (학습용 DataFrame, 검증용 DataFrame)
    """
    raise NotImplementedError
