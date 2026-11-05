# 외부 데이터 사용 명세

주최 측 답변(QnA)은 다음과 같습니다.

- 공개된 공공데이터에 해당하는 기상자료는 활용 근거와 출처를 함께 제시하면 학습에 쓸 수 있습니다 (2026-10-07).
- 평가 대상 3개 관측소의 추정 대상 실측값을 외부 자료에서 확보해 입력으로 쓰거나 예측 결과로 제출하면 안 됩니다 (2026-10-06).
- 다른 학습 지점의 동일 시각 노면상태 정보는 입력변수로 쓸 수 없습니다 (2026-11-02).

자료 파일은 저장소에 넣지 않았습니다. `data/external/`에 두고 3장의 스크립트로 다시 만듭니다.

## 1. 데이터

| 데이터 | 출처 | 이용 조건 | 범위 | 파일 |
| --- | --- | --- | --- | --- |
| ERA5-Land 재분석 (기온, 이슬점, 지표면온도, 기압, 강수, 강설, 일사·열복사, 10 m 바람) | ECMWF Copernicus Climate Data Store, `reanalysis-era5-land-timeseries` (Muñoz-Sabater et al. 2021) | CC-BY 4.0, 출처 표기 | 0.1° 격자 27개 (구간 선이 지나는 격자), 2024-10-25 ~ 2026-02-28, 1시간 | `era5land_cells/era5land_cell_<위도>_<경도>.csv` |
| 서해 해기차 dT = 전날 해수면온도 - 850hPa 기온 | NOAA OISST v2.1 (일별 0.25°, doi:10.25921/RE9P-PT57, ERDDAP `ncdcOisst21Agg_LonPM180`), ERA5 기압면 시계열 `reanalysis-era5-pressure-levels-timeseries`의 850hPa (Hersbach et al. 2020) | OISST는 사용 제한 없음(인용 표기), ERA5는 CC-BY 4.0 | 서해 A(36.0N, 126.0E), B(36.5N, 125.5E), 6시간 | `haegicha_6h_kst.csv` |
| 상습 결빙구간 | 행정안전부 (공공데이터포털 15067396) | 이용허락범위 제한 없음 | 전국, 기점·종점 위경도 | `행정안전부_상습 결빙구간_20251107.csv` |
| 나들목 누적거리 | 위키백과 서해안고속도로, 호남고속도로, 통영대전고속도로 문서 | CC BY-SA | 대상 3개 노선 | `src/vulnerable.py`에 기재 |
| 나들목 좌표 | OpenStreetMap Nominatim | ODbL | 대상 3개 노선 | `src/vulnerable.py`에 기재 |

시각은 모두 KST입니다(원본 UTC + 9시간). ssrd와 strd는 3600으로 나눠 W/m²로, 기온은 ℃, 기압은 hPa, 강수·강설은 mm로 바꿉니다.

구간·지점은 좌표에서 가장 가까운 0.1° 격자에 연결합니다. 전북 범위 격자 요청(`reanalysis-era5-land`)은 한도 초과(403)로 실패해서 지점 시계열 방식으로 받았습니다. 구간 중간점이 쓰는 격자는 25개, 관측소가 쓰는 격자는 13개이고 모두 위 27개 안에 있습니다.

상습 결빙구간과 나들목 자료는 기존 결빙취약구간 22개소의 이정을 도로 위 위치로 바꾸는 기준점으로만 씁니다. 상습 결빙구간의 구간번호 70100-83~91, 95는 22개소 표와 연장·순서가 같습니다.

## 2. 사용법

```python
from src import external as ex

times, _ = ex.analysis_times()
feat = ex.external_features(points, id_col="seg_id", lon="lon", lat="lat")   # 분석 기간 10분 시간축
hourly = ex.external_features(points, times=times[times.minute == 0])        # 정시만
```

시간 정렬은 02-1의 ASOS 자료와 같은 규칙입니다. 순간값은 시각 사이를 선형 보간합니다. 그 시각에 끝나는 1시간 합계(강수, 강설, 복사)는 시간 가운데(-30분)에 두고 보간해서 시간당 비율로 씁니다.

없는 격자는 가까운 격자로 대신하지 않고 오류를 냅니다. `t2m_7d_mean`, `t2m_min12h`는 현재 시각까지의 1시간 값으로 계산합니다. 해기차(`sea_*`)는 모든 구간에 같은 시계열이고 바람은 u·v 성분으로 보간합니다.

## 3. 다시 만드는 방법

```bash
python scripts/external/download_era5_cells.py    # CDS 계정(~/.cdsapirc)과 cdsapi 패키지 필요
python scripts/external/download_era5_850hpa.py   # 같은 조건. data/external/era5pl_A_raw, era5pl_B_raw를 만듭니다
python scripts/external/build_dT_final.py         # OISST를 ERDDAP에서 받아 해기차 파일을 만듭니다
```

ERA5 기압면 시계열은 6시간 간격이고 기압면 13개를 한 번에 줍니다. `build_dT_final.py`가 850hPa를 고릅니다. 읽는 열은 `valid_time`, `pressureLevel`, `t`, `u`, `v`, `latitude`, `longitude`입니다.

`build_dT_final.py`는 OISST를 다시 받아 기존 `haegicha_6h_kst.csv`와 값이 같음을 확인했습니다. `download_era5_850hpa.py`는 CDS 공개 양식과 받은 파일의 구조에 맞춰 작성했고 CDS 계정으로 실제 내려받기는 확인하지 못했습니다.

## 4. 자료 확인 결과

- ERA5-Land 격자 27개 모두 11,808시간이 끊기지 않고 결측이 없습니다. 파일 이름과 격자 중심이 같고 지점별로 받은 파일과 값이 같습니다.
- 하향 단파 복사의 평균은 13시(그 시각에 끝나는 1시간)에 가장 큽니다.
- 해기차는 파일의 dT를 다시 계산해도 같고 OISST 원본 값과 일치합니다. 850hPa 풍향은 흑산도 라디오존데와 대체로 같습니다. 기온은 더 북쪽 지점이라 찬 공기 유입 때 1~4℃ 낮습니다.
- 겨울철 시간별로 노면온도(광학)와 ERA5의 상관은 지점별로 지표면온도 0.92~0.95, 2m 기온 0.87~0.94입니다. 밤(19~06시) 2m 기온의 RMSE는 1.4~3.0℃입니다. ERA5 지표면온도는 노면온도보다 대체로 차갑습니다(편향 +0.4~-4.0℃).
- 22개소 이정 변환은 기준점을 하나씩 빼고 맞춰 봤습니다. 오차는 무주나들목 0.37km, 나머지 0.08km 이내입니다.

## 5. 근거

도로기상 모델 METRo(Crevier & Delage 2001)와 RoadSurf(Kangas et al. 2015)는 수치예보의 기상 입력으로 노면 에너지 수지를 풀어 노면온도와 상태를 계산합니다. ERA5-Land의 변수는 이 입력과 대응합니다.

찬 공기가 따뜻한 바다를 건너면 눈구름이 발달합니다. 오대호에서는 850hPa 해기차 13℃ 이상을 강설 조건으로 씁니다(Niziol 1987). 기상청 자료는 2003~2017년 겨울 서해안 강설 사례 327건 중 315건(96.2%)이 해기차 15℃ 이상이었다는 근거로 서해 임계값을 15℃로 제시합니다. 이 값은 칠발도 수온과 흑산도 850hPa 기온으로 잰 것이라 A·B 지점의 dT에 그대로 옮기지는 못합니다.

## 참고 자료

- Muñoz-Sabater, J., et al. (2021). ERA5-Land: a state-of-the-art global reanalysis dataset for land applications. *Earth System Science Data*, 13, 4349–4383.
- Hersbach, H., et al. (2020). The ERA5 global reanalysis. *Quarterly Journal of the Royal Meteorological Society*, 146, 1999–2049.
- Crevier, L.-P., & Delage, Y. (2001). METRo: A new model for road-condition forecasting in Canada. *Journal of Applied Meteorology*, 40, 2026–2037.
- Kangas, M., Heikinheimo, M., & Hippi, M. (2015). RoadSurf: a modelling system for predicting road weather and road surface conditions. *Meteorological Applications*, 22, 544–553.
- Niziol, T. A. (1987). Operational forecasting of lake effect snowfall in western and central New York. *Weather and Forecasting*, 2, 310–321.
- 기상청 예보국 재해기상대응팀 (2022). Why? How! 겨울 예보 (손에 잡히는 예보기술 제50호), 3.3절. https://www.kma.go.kr/down/e-learning/hands/hands_50.pdf
