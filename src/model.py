"""AI 모델: 미관측 지점 관측값 추정, 결빙 여부 분류."""
from src import config


def train_estimator(train_df, target):
    """도로기상 관측값(target)을 추정하는 모델을 학습한다.

    검증 지점은 학습 데이터에서 제외되어 있어야 한다.
    """
    raise NotImplementedError


def predict_estimator(model, df):
    """구간 또는 검증 지점의 관측값을 추정한다."""
    raise NotImplementedError


def train_icing_classifier(train_df):
    """10분 단위 결빙(1)/비결빙(0) 분류 모델을 학습한다."""
    raise NotImplementedError


def predict_icing(model, df):
    """10분 단위 결빙 여부를 예측한다."""
    raise NotImplementedError


def save_model(model, name):
    """학습된 모델을 config.MODEL_DIR에 저장한다."""
    raise NotImplementedError


def load_model(name):
    """config.MODEL_DIR에서 모델을 불러온다."""
    raise NotImplementedError
