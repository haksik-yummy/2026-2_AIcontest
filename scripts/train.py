"""검증 지점을 제외하고 관측값 추정 모델과 결빙 분류 모델을 학습한다.

실행: python scripts/train.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config, model, preprocess  # noqa: E402


def main():
    # 1. data/processed/ 데이터 불러오기
    # 2. 검증 지점 분리 (preprocess.split_holdout)
    # 3. 관측값 추정 모델, 결빙 분류 모델 학습
    # 4. config.MODEL_DIR에 저장
    raise NotImplementedError


if __name__ == "__main__":
    main()
