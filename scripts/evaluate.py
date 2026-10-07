"""검증 지점(부곡교, 삼봉, 해전)에서 모델 성능을 평가하고 CSV로 저장한다.

실행: python scripts/evaluate.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config, evaluate, model  # noqa: E402


def main():
    # 1. 저장된 모델 불러오기
    # 2. 검증 지점 관측값 추정 → BIAS, MAE, RMSE
    # 3. 검증 지점 10분 단위 결빙 예측 → 일별 F1-score, Precision, Recall
    # 4. 지점별 평균 + 세 지점 평균을 config.RESULT_DIR에 CSV로 저장
    raise NotImplementedError


if __name__ == "__main__":
    main()
