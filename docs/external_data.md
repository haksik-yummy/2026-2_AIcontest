# 외부 데이터 사용 명세

주최 측 답변: 출처를 밝히면 외부 공공데이터를 써도 된다. 학습 지점이 아닌 지점의 추정에 다른 학습 지점의 같은 시각 노면상태는 입력으로 쓸 수 없다.

## 1. 데이터

| 데이터 | 출처 | 범위 | 파일 |
| --- | --- | --- | --- |
| ERA5-Land 재분석 (기온, 이슬점, 지표면온도, 기압, 강수, 강설, 일사·열복사, 10 m 바람) | ECMWF Copernicus Climate Data Store, `reanalysis-era5-land-timeseries`, CC-BY 4.0 | 중심선이 지나는 0.1° 격자 27개, 2024-10-25~2026-02-28, 시간별 | `data/external/era5land_cells/era5land_cell_{lat}_{lon}.csv` |
| 서해 해기차 dT = 전날 해수면온도 − 850hPa 기온 | NOAA OISST v2.1 (일별 0.25°), ERA5 pressure levels (850hPa) | A(36.0N,126.0E), B(36.5N,125.5E), 6시간 간격 | `data/external/haegicha_6h_kst.csv` |

- 시각은 모두 KST (원본 UTC + 9시간). ssrd·strd는 3600으로 나눠 W/m², 기온은 ℃, 기압은 hPa, 강수·강설은 mm.
- 격자 연결: 구간·지점 중간점 좌표가 속한 0.1° 격자. 전북 범위 격자 요청(`reanalysis-era5-land`)은 한도 초과(403)로 실패해 지점 시계열 방식으로 받았다.
- 노면온도(광학)와 ERA5의 상관은 지점별 0.90~0.95(전체), 야간 기온 기준 RMSE 1.4~3.4℃. ERA5가 노면온도보다 대체로 차갑게 나온다(편향 −0.2~−4.0℃, 내륙일수록 큼).

## 2. 사용법

```python
from src import external as ex
feat = ex.external_features(points, id_col="seg_id", lon="lon", lat="lat", freq="1h")  # 또는 "10min"
```

- 직전 값 유지(ffill)만 사용해 미래 정보가 들어가지 않는다. `era5l_t2m_7d_mean`, `era5l_t2m_min12h`는 현재 시각까지의 값으로 계산한다.
- 해기차(`sea_*`)는 모든 구간에 같은 시계열이다.

## 3. 근거 (초록 수준 확인, 원문 확인 필요)

- 도로기상 모델(METRo, RoadSurf)은 대기 강제력으로 기온, 이슬점, 바람, 강수, 복사를 사용한다.
- 해기차: 서해 해수면–상공 850hPa 기온차가 클 때 호남 서해안 눈구름이 발달한다는 선행연구가 있다(문헌 기준 약 13℃).
