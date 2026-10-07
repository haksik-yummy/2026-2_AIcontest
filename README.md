# 기상과 도로환경 융합자료를 활용한 AI 기반 전북도 고속도로 결빙 위험도 분석

2026 DATA·AI 분석 경진대회 (전주기상지청 출제) 제출 결과물

## 1. 개요

기상(ASOS, AWS), 도로기상(RWIS), 도로시설·지형 자료를 융합하여 전북도 고속도로(서해안선, 통영-대전중부선, 호남선) 구간별 기상학적 결빙 위험도를 산출한다.

| 결과물 | 위치 |
|--------|------|
| 도로 결빙 발생 영향요인 및 환경조건(임계값) | (작성 예정) |
| 도로기상 미관측 지점 관측값 추정 AI 모델 | `model/` |
| 결빙 위험도 기준표 | (작성 예정) |
| 고속도로 구간별 결빙 위험도 지도 | `figures/` |
| 성능지표 CSV (BIAS·MAE·RMSE, F1-score·Precision·Recall) | `data/results/` |

## 2. 폴더 구성

| 경로 | 내용 |
|------|------|
| `README.md` | 결과물 구성, 실행환경, 실행 방법 설명 |
| `requirements.txt` | 주요 라이브러리 버전 (pip) |
| `environment.yml` | 전체 실행환경 (conda) |
| `data/` | 학습·평가 데이터. `raw/`에 제공 데이터를 둔다 (용량 문제로 저장소에는 미포함) |
| `model/` | 학습된 모델 파일 |
| `src/` | 데이터 처리, 변수 생성, 모델, 평가, 위험도 산출, 시각화 소스코드 |
| `notebooks/` | 단계별 Jupyter Notebook (01~05) |
| `scripts/` | 전처리, 학습, 평가, 위험도 지도 생성 스크립트 |
| `demo/` | 추론 과정 데모영상 |
| `figures/` | 결과 설명용 그림 |

### src/

| 파일 | 역할 |
|------|------|
| `config.py` | 경로, 분석 기간, 대상 노선, 검증 지점, 결빙 판정 기준, 구간 길이 |
| `data_loader.py` | 제공 데이터 불러오기 |
| `preprocess.py` | 정제, 10분 시간축 정렬, 결빙 라벨 생성, 검증 지점 분리 |
| `features.py` | 기상·도로·지형 변수 생성 |
| `segments.py` | 노선 구간(500m/1km) 분할, 관측소-구간 연결 |
| `model.py` | 관측값 추정 모델, 결빙 분류 모델 |
| `evaluate.py` | 성능지표 계산 |
| `risk.py` | 결빙 영향인자 도출, 위험도 기준표, 구간별 위험도 |
| `visualize.py` | 그림 및 지도 출력 |

## 3. 데이터

[대회 페이지](https://aida.kisti.re.kr/competition/main/problem/PROB_000000000004604/detail.do)의 전체 데이터 `DATA AI 경진대회 데이터(20261007).zip`을 내려받아 압축을 풀고, 안의 내용을 `data/raw/`에 그대로 둔다.

```
data/raw/
├── 1. 전북도 고속도로 RWIS(도로기상) 관측 데이터/          일별 CSV 240개
├── 1-1. 전북도 고속도로 목표안개 관측소(2개소) 관측 데이터/  일별 CSV 240개
├── 2. 전북도 ASOS(종관기상) 관측 데이터/                  일별 CSV 240개
├── 3. 전북도 AWS(방재기상) 관측 데이터/                   일별 CSV 240개
├── 4. 전북도 교량 위경도 데이터.csv
├── 5. 전북도 터널 위경도 데이터.csv
├── 6. 전북도 고속도로 중심선 데이터/
├── 7. 전북도 수치 표고 모델 고도 데이터.tif
├── 8. 국토교통부 도로, 교량, 터널, 하천 경계 데이터.zip
└── 데이터 설명자료(노면상태, 풍향, 운형, 현상번호).pdf
```

- 기간: 2024-11-01 ~ 2025-02-28, 2025-11-01 ~ 2026-02-28
- 제공 데이터 외 추가 데이터: (작성 예정, 사용 시 출처·이용조건·근거 기재)

## 4. 실행환경

| 항목 | 버전 |
|------|------|
| OS | Ubuntu 24.04.4 LTS (Windows WSL2) |
| Python | 3.12.14 |
| 패키지 관리 | conda 26.1.1 |
| GPU | 사용하지 않음 (CPU만 사용) |

주요 라이브러리

| 분류 | 라이브러리 |
|------|-----------|
| 데이터 처리 | numpy 2.5.3, pandas 3.0.6, pyarrow 25.0.1, scipy 1.18.1 |
| 공간 데이터 | geopandas 1.2.0, shapely 2.1.2, pyproj 3.8.0, pyogrio 0.13.0, rasterio 1.5.1 |
| 모델 | scikit-learn 1.9.1, lightgbm 4.7.0, xgboost 3.4.1 |
| 시각화 | matplotlib 3.11.2, seaborn 0.13.2, folium 0.20.0 |

모든 코드와 주석은 UTF-8로 작성하였다. 외부 AI 서비스나 API는 실행에 필요하지 않다.

## 5. 환경 구성

conda (권장, 전체 환경 재현)

```bash
conda env create -f environment.yml
conda activate haksik
```

pip

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 6. 실행 방법

저장소 최상위 폴더에서 순서대로 실행한다.

```bash
python scripts/preprocess.py      # 정제·변수 생성·구간 분할 → data/processed/
python scripts/train.py           # 검증 지점 제외 학습 → model/
python scripts/evaluate.py        # 검증 지점 성능 평가 → data/results/
python scripts/make_risk_map.py   # 구간별 위험도 산출·지도 → figures/
```

Notebook으로 확인할 경우 `notebooks/`의 01~05를 순서대로 실행한다.

| Notebook | 내용 |
|----------|------|
| `01_data_exploration.ipynb` | 데이터 구성, 기간, 지점, 결측, 노면상태 분포 확인 |
| `02_preprocessing_features.ipynb` | 정제, 시간축 정렬, 변수 생성, 구간 분할 |
| `03_observation_estimation.ipynb` | 관측값 추정 모델 학습 및 검증 |
| `04_icing_classification.ipynb` | 결빙 분류 및 성능지표 산출 |
| `05_risk_map.ipynb` | 영향인자·임계값, 위험도 기준표, 위험도 지도 |

## 7. 평가 방법

- 검증 지점(학습 제외): 부곡교(12410, 서해안선), 삼봉(33411, 통영-대전중부선), 해전(23402, 호남선)
- 관측값 추정: 검증 지점 실제 관측값과 비교하여 BIAS, MAE, RMSE 산출
- 결빙 분류: 노면상태 Ice는 결빙, 그 외는 비결빙으로 이진 분류
  - 일(00:00~23:50) 단위 TP·FP·FN으로 F1-score, Precision, Recall 산출 후 평가기간 평균
  - 지점별 평균과 세 지점 평균을 제시 (QnA 2026-09-29 답변 기준)
  - 10분 단위 예측 결과를 함께 제시

## 8. 결과

(작성 예정)

## 9. AI 활용범위 및 주요 검토 과정

| 항목 | 내용 |
|------|------|
| 활용 도구 | Claude Code (Claude Opus 5.5) |
| 활용 단계 | 프로젝트 구조 설계, 실행환경 문서화 |
| 주요 활용 내용 | 제출 규정에 맞춘 폴더 구조와 `.gitignore`, 분석 코드 뼈대(모듈·함수 구성, Notebook 단계 구성), 실행환경 설정 파일과 README 초안 작성 |
| 참가자 주요 기여 및 검증 | 데이터 탐색·전처리, 변수 설계, 모델 선택·학습·평가, 함수 구현, 결과 분석을 팀원이 직접 수행 |
| 검토한 대안 및 실패사례 | (작성 예정) |
| 최종 선택 이유 | (작성 예정) |
