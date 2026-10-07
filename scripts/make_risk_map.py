"""구간별 결빙 위험도를 산출하고 지도(jpg, shapefile)로 저장한다.

실행: python scripts/make_risk_map.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config, model, risk, visualize  # noqa: E402


def main():
    # 1. 구간별 관측값 추정
    # 2. 결빙 영향인자·임계값 도출, 위험도 기준표 작성
    # 3. 구간별 위험도 산출, 기존 결빙취약구간과 비교
    # 4. 위험도 지도와 shapefile 저장
    raise NotImplementedError


if __name__ == "__main__":
    main()
