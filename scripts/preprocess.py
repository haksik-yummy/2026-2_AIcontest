"""데이터 정제·병합·구간 분할 후 data/processed/에 저장한다.

실행: python scripts/preprocess.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config, data_loader, features, preprocess, segments  # noqa: E402


def main():
    # 1. 관측 데이터 불러오기 및 정제
    # 2. 10분 시간축 정렬, 결빙 라벨 생성
    # 3. 도로·지형 변수 추가, 노선 구간 분할
    # 4. config.PROCESSED_DIR에 저장
    raise NotImplementedError


if __name__ == "__main__":
    main()
