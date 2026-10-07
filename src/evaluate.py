"""성능 평가.

1. 관측값 추정: 검증 지점의 실제 관측값과 비교 (BIAS, MAE, RMSE)
2. 결빙 분류: 일별(00:00~23:50) TP·FP·FN으로 F1-score, Precision, Recall을 구하고
   평가기간 평균을 최종 성능으로 제시
   - 지점별 평균과 세 지점 평균을 함께 제출 (QnA 2026-09-29)
   - 세 지점의 TP·FP·FN을 합산하는 방식은 평가에 반영하지 않음
"""


def regression_scores(y_true, y_pred):
    """관측값 추정 성능을 계산한다.

    Returns:
        {"BIAS": ..., "MAE": ..., "RMSE": ...}
    """
    raise NotImplementedError


def daily_icing_scores(df):
    """한 지점의 일별 TP, FP, FN, F1-score, Precision, Recall을 계산한다.

    Args:
        df: 관측시각, 실제 결빙(0/1), 예측 결빙(0/1)을 가진 10분 단위 DataFrame

    TODO: 실제·예측 모두 결빙이 없는 날(TP+FP+FN=0)의 처리 기준 정하기
    """
    raise NotImplementedError


def summarize_holdout(daily_by_station):
    """검증 지점별 평가기간 평균과 세 지점 평균을 정리한다.

    Args:
        daily_by_station: {지점번호: daily_icing_scores 결과}

    Returns:
        지점별 행 3개 + 세 지점 평균 행 1개로 된 DataFrame (제출용 CSV)
    """
    raise NotImplementedError
