# 기상과 도로환경 융합자료를 활용한 AI 기반 전북도 고속도로 결빙 위험도 분석

2026 DATA·AI 분석 경진대회 (전주기상지청 출제) 제출 결과물

## 1. 개요

기상(ASOS, AWS), 도로기상(RWIS), 도로시설·지형 자료를 융합하여 전북도 고속도로(서해안선, 통영-대전중부선, 호남선) 구간별 기상학적 결빙 위험도를 산출한다.

| 결과물 | 위치 |
|--------|------|
| 도로 결빙 발생 영향요인 및 환경조건(임계값) | `data/results/icing_factors.csv`, `icing_conditions.csv` (05-1) |
| 도로기상 미관측 지점 관측값 추정 AI 모델 | `model/road_temp_*` (03-2·03-3) |
| 결빙 위험도 기준표 | `data/results/risk_criteria.csv` (05-2) |
| 고속도로 구간별 결빙 위험도 지도 | `figures/risk_map.jpg`, `risk_map.png`, `risk_map.html`, `risk_map_shp/` (05-2) |
| 성능지표 CSV (BIAS·MAE·RMSE, F1-score·Precision·Recall) | `data/results/estimation_scores.csv` (03-3), `icing_scores.csv` (04-3) |

## 2. 폴더 구성

| 경로 | 내용 |
|------|------|
| `README.md` | 결과물 구성, 실행환경, 실행 방법 설명 |
| `requirements.txt` | 주요 라이브러리 버전 (pip) |
| `environment.yml` | 전체 실행환경 (conda) |
| `data/` | 학습·평가 데이터. `raw/`에 제공 데이터, `external/`에 추가 데이터(ERA5-Land)를 두고, 노트북이 `interim/`·`processed/`에 중간 자료, `results/`에 성능지표·기준표 CSV를 저장한다 (용량 문제로 저장소에는 미포함) |
| `model/` | 학습된 모델 파일 (노면온도 추정 `road_temp_*`, 결빙 분류 `icing_*`) |
| `src/` | 공통 설정(`config.py`)과 데이터 처리, 변수 생성, 모델, 평가, 위험도 산출, 시각화 모듈 뼈대 |
| `notebooks/` | 단계별 Jupyter Notebook. 단계(01~05)별 폴더 안에 01-1~05-2로 나뉘어 있다 |
| `scripts/` | 전처리, 학습, 평가, 위험도 지도 생성 스크립트 뼈대 (미구현) |
| `demo/` | 추론 과정 데모영상 (준비 중) |
| `figures/` | 결과 설명용 그림과 구간별 결빙 위험도 지도 (jpg·png·html·shapefile) |

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

`config.py` 외의 모듈은 함수 구성만 정해 둔 뼈대이다. 현재 분석 코드는 `notebooks/`에 있다.

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
- 제공 데이터 외 추가 데이터: ERA5-Land 재분석, 서해 해기차 2종 (아래)

### 추가 데이터: ERA5-Land 재분석

| 항목 | 내용 |
|------|------|
| 자료 | ECMWF ERA5-Land hourly time series. Copernicus Climate Change Service(C3S) Climate Data Store의 `reanalysis-era5-land-timeseries` |
| 출처 | Muñoz-Sabater, J., et al. (2021). ERA5-Land: a state-of-the-art global reanalysis dataset for land applications. *Earth System Science Data*, 13, 4349–4383. 정확한 인용 문구는 데이터셋 페이지의 안내를 따른다 |
| 이용 조건 | CC-BY 4.0 (출처 표기) |
| 받은 범위 | RWIS 17곳 좌표에서 가장 가까운 0.1°(약 9km) 격자 13개, 2024-10-25 ~ 2026-02-28(UTC 기준 요청), 1시간 |
| 변수 | 2m 기온·이슬점, 지표면온도, 지표 기압, 강수, 강설(물 환산), 하향 단파·장파 복사, 10m 바람(u·v) |
| 받는 방법 | CDS API로 지점 좌표를 하나씩 요청해 변수별 CSV를 받고, 지점별로 병합하며 단위를 바꾼다 (K → °C, m → mm, J/m² → W/m², UTC → KST) |
| 두는 곳 | `data/external/era5land_<지점번호>.csv` (지점별 병합본 14열, 용량 문제로 저장소에는 미포함) |
| 쓰는 근거 | 노면 에너지 수지의 기상 입력(복사·기온·이슬점·바람·강수, Chapman et al. 2001)과 대응하고, 결빙의 수분 공급 가운데 **눈인지 비인지**를 제공 데이터보다 직접 나타낸다. RWIS 관측은 ERA5에 동화되지 않으므로 검증 지점의 관측이 입력에 섞이지 않는다 |
| 쓰는 곳 | 02-3에서 10분 시간축에 맞춘다 (순간값은 선형 보간, 1시간 합계는 시간 가운데에 두고 보간). 03-2의 3-6-8(노면온도 밑그림), 04-2의 2-3(결빙 분류), 05-1의 2장(영향인자), 05-2의 M3(구간이 쓰는 격자를 모두 받았을 때) |
| 기여 (학습 지점 교차검증) | 노면온도 추정: 없음. B3 밑그림 RMSE 1.590°C → ERA5 복사 1.594, ERA5 기온 1.821°C로 쓰지 않는다 (03-2의 3-6-8)<br>결빙 분류: AP만 소폭 상승(로지스틱 결빙관련 AP 0.487 → 0.502), 일별 F1 차이의 95% 구간이 0을 포함해 최종 모델에 넣지 않는다 (04-2의 2-3)<br>결빙 영향인자: 3시간 강설의 Ice 판별력 AUC 0.87로 단일 변수 가운데 가장 높다(기존 변수 최고 0.85). 관측소 Ice 비율과의 순위상관은 ERA5 강설 & 영하 노면 0.31, AWS 강수 감지 & 영하 노면 0.16 (14곳이라 유의하지 않음, 05-1의 2장) |

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

현재 분석은 `notebooks/`의 Notebook으로 실행한다. 01-2부터 05-2까지 번호 순서대로 실행한다 (01-1은 이론 정리 마크다운 문서).
02-3부터는 `data/external/`의 ERA5-Land 파일(3장)이 필요하다.
각 Notebook은 자신이 있는 단계 폴더(`notebooks/<단계 폴더>/`)를 작업 폴더로 두고 실행하며, 앞 Notebook이 저장한 중간 자료(`data/interim/`, `data/processed/`)를 뒤 Notebook이 불러 쓴다.

| Notebook | 내용 |
|----------|------|
| `01_data_exploration/01-1_theory.md` | 이론적 배경과 검증할 가설 (마크다운 문서) |
| `01_data_exploration/01-2_data_quality.ipynb` | 데이터 구성, 관측망, 결측·이상값·센서 고착 점검, 분석용 자료 저장 |
| `01_data_exploration/01-3_road_surface.ipynb` | 노면온도와 노면상태(Ice) 분포 |
| `01_data_exploration/01-4_icing_weather.ipynb` | 결빙 기상 조건, 두 겨울 비교, 기온감률, 사례, 검증 지점 |
| `01_data_exploration/01-5_road_terrain_fog.ipynb` | 도로·지형 자료, 목표안개 관측소 |
| `01_data_exploration/01-6_theory_check_icing.ipynb` | 이론 검증 Ⅰ: 결빙 조건 |
| `01_data_exploration/01-7_theory_check_spatial.ipynb` | 이론 검증 Ⅱ: 노면온도의 공간 변동과 노면상태, 탐색 정리 |
| `02_preprocessing_features/02-1_cleaning.ipynb` | 정제, 10분 시간축 정렬, 결빙 라벨 |
| `02_preprocessing_features/02-2_features_segments.ipynb` | 변수 생성, 구간 분할 |
| `02_preprocessing_features/02-3_external_era5.ipynb` | 추가 데이터 ERA5-Land를 10분 시간축에 정렬, 구간이 쓰는 격자 확인 |
| `03_observation_estimation/03-1_estimation_cv.ipynb` | 관측값 추정 후보 모델 교차검증(묶음 누수 방지), 기본 앙상블 선택 |
| `03_observation_estimation/03-2_estimation_experiments.ipynb` | 관측값 추정 추가 실험 (고전 ML, MLP, 앙상블, 지점 특성), RWIS 노면온도 보간 개선(밑그림 + 지문 + 크리깅)과 최종 앙상블 확정, ERA5 밑그림 실험 |
| `03_observation_estimation/03-3_estimation_holdout.ipynb` | 관측값 추정 검증 지점 평가, 모델 저장 |
| `04_icing_classification/04-1_icing_cv.ipynb` | 결빙 분류 후보 모델 교차검증, 최종 모델 선택·해석 |
| `04_icing_classification/04-2_icing_experiments.ipynb` | 결빙 분류 고전 ML 기법·MLP·앙상블 비교, ERA5 강수·강설 기여 |
| `04_icing_classification/04-3_icing_holdout.ipynb` | 결빙 분류 검증 지점 평가, 성능지표 산출 |
| `05_risk_map/05-1_icing_factors.ipynb` | 구간별 추정, 결빙 영향인자·임계값 (ERA5 강설 지표 포함) |
| `05_risk_map/05-2_risk_map.ipynb` | 위험도 기준표, 구간별 위험도, 위험도 지도 (ERA5 강설 지표 M3는 구간 격자 확보 시) |

`scripts/`의 스크립트는 같은 과정을 명령줄로 실행하기 위한 뼈대이며 아직 구현되지 않았다. 구현 후 실행 순서는 다음과 같다.

```bash
python scripts/preprocess.py      # 정제·변수 생성·구간 분할 → data/processed/
python scripts/train.py           # 검증 지점 제외 학습 → model/
python scripts/evaluate.py        # 검증 지점 성능 평가 → data/results/
python scripts/make_risk_map.py   # 구간별 위험도 산출·지도 → figures/
```

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
| 활용 도구 | Claude Code (Claude Opus 5.5), GitHub Copilot |
| 활용 단계 | 프로젝트 구조 설계, 실행환경 문서화 |
| 주요 활용 내용 | Claude Code: 제출 규정에 맞춘 폴더 구조와 `.gitignore`, 분석 코드 뼈대(모듈·함수 구성, Notebook 단계 구성), 실행환경 설정 파일과 README 초안 작성, 코드를 주피터 노트북에 통합, 논문 내용을 md 파일로 요약 저장<br>GitHub Copilot: 코드 및 주석 작성 보조 |
| 참가자 주요 기여 및 검증 | 데이터 탐색·전처리, 변수 설계, 모델 선택·학습·평가, 함수 구현, 결과 분석을 팀원이 직접 수행 |
| 검토한 대안 및 실패사례 | (작성 예정) |
| 최종 선택 이유 | (작성 예정) |
