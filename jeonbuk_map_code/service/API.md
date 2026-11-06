# 결빙 위험도 API

서버 실행: `python service/server.py` (기본 `http://localhost:8000`, 화면은 `/`, 이 설명은 `/api-docs`)

- 시각은 ISO 8601이며 시간대가 없으면 KST로 봅니다. 주소에 넣을 때 `+`는 `%2B`로 쓰는 것이 안전합니다.
- 오류는 `{"error": {"code": "...", "message": "..."}}` 형식입니다.
- 값은 분석 추정입니다. 실제 노면 결빙을 확인한 값이 아니며, 조건 미충족은 안전하다고 판정한 것이 아닙니다.

## 조회

| 요청 | 내용 |
|---|---|
| `GET /api/v1/metadata` | 자료 기간, 구간 수, 등급 기준, 결빙 가능 조건, 모델과 검증 성능, 주요 사례일, 수신 상태 |
| `GET /api/v1/segments?route=` | 구간 GeoJSON. 등급, 요인 점수, 하위 지표, 노선 km, 시군 |
| `GET /api/v1/segments/{seg_id}` | 구간 하나의 하위 지표 수준·기준·근거, 구간 안의 관측소 |
| `GET /api/v1/segments/{seg_id}/timeseries?from=&to=` | 시간별 추정값과 구간 안 관측소의 실측값. 한 번에 31일까지. `to`가 없으면 24시간 |
| `GET /api/v1/stations` | RWIS 17곳 위치, 종류, 연결 구간, 검증 지점 여부 |
| `GET /api/v1/facilities` | 위험도 계산에 쓴 교량·터널 구간 GeoJSON |
| `GET /api/v1/status?mode=history&at=` | 그 시각의 구간별 추정값과 관측소 실측값. `format=geojson`, `route=` 가능 |
| `GET /api/v1/status?mode=live`, `GET /api/v1/current` | 최신 수신값. 신선도 기준을 넘기면 값을 비우고 `stale`로 표시 |
| `GET /api/v1/nearest?lat=&lon=&max_m=` | 가장 가까운 구간 (기본 2km 안) |

과거 재생 자료는 2024-11-01\~2025-02-28, 2025-11-01\~2026-02-28의 1시간 간격입니다.

## 경로

| 요청 | 내용 |
|---|---|
| `POST /api/v1/route-risk` | 경로 좌표를 받아 지나는 구간과 통과 시각의 값 요약 |
| `GET /api/v1/route-risk/stretch?route=&from_km=&to_km=&at=&speed_kmh=` | 네이버 키 없이 노선 km 범위로 조회. `from_km > to_km`이면 반대 방향 |
| `GET /api/v1/naver/directions?start=경도,위도&goal=경도,위도&at=` | 서버가 Directions 5를 호출해 경로와 위험 요약을 함께 돌려줌. 키가 없으면 503 |

`POST /api/v1/route-risk` 본문:

```json
{"path": [[126.8, 35.6], [126.81, 35.62]], "mode": "history", "at": "2025-01-28T06:00+09:00", "duration_s": 480, "buffer_m": 60}
```

- `path`: `[경도, 위도]` 2\~20,000개
- `mode`: `history`는 그 시각에 출발했다면의 값, `live`는 마지막 수신 시각의 값 (앞으로의 예보가 아님)
- `duration_s`: 전체 소요 시간. 없으면 시속 90km로 가정하고 `travel.basis`에 표시
- `buffer_m`: 경로와 구간 선의 허용 거리 (기본 60m). 100m보다 짧게 스친 구간은 뺍니다

통과 시각은 전체 소요 시간을 거리 비율로 나눈 근사입니다.

## 운영

| 요청 | 내용 |
|---|---|
| `GET /api/v1/ops/briefing?mode=history&start=&hours=15&group=sigungu&top=5` | 묶음별 우선 구간. `group`은 `sigungu`, `route`, `branch` (`branch`는 서버를 `--branches 지사.csv`로 실행해야 함) |
| `GET /api/v1/ops/briefing?mode=live` | 마지막 수신 시각 기준 (앞으로의 예보가 아님) |
| `GET /api/v1/ops/vulnerable` | 기존 결빙취약구간과 위험 등급 비교 (`ops/vulnerable_sections.py` 실행 후) |
| `GET /api/v1/reference/cctv` | 최신 CCTV 도로날씨 지점. 야간 판별 성능이 낮습니다 |

정렬은 모델 예측 시간, 결빙 가능 조건 시간, 위험 등급, 최저 추정 노면온도 순입니다. 제설제 등의 살포 시점이나 작업량을 정하지 않습니다.

## 입력

`POST /api/v1/ingest`, 헤더 `Authorization: Bearer <ICING_INGEST_TOKEN>`. 서버에 토큰이 없으면 403 error가 발생합니다.

```json
{
  "run_id": "kma-202601150600",
  "valid_time": "2026-01-15T06:00+09:00",
  "source": "kma-apihub",
  "quality": "unverified",
  "inputs": {"rwis_sources": 14, "aws": 34, "asos": 10},
  "model": {"road_temperature": "앙상블+B3"},
  "segments": [{"seg_id": "SH-001", "rst_est": -1.2, "p_icing": 0.02, "condition": true, "prediction": false}],
  "stations": [{"stn": 12410, "observed_at": "2026-01-15T06:00+09:00", "rst": -1.0, "road_state": 1, "ta": -3.0, "rh": 80}],
  "reference": {"cctv": [{"lat": 35.8, "lon": 127.1, "name": "지점명", "wh_cd": 31, "tm": "2026-01-15T06:00+09:00"}]}
}
```

- `quality`의 `valid`는 제공자 QC를 통과한 자료일 때만 씁니다. 서버가 센서와 대조해 인증하는 값이 아닙니다.
- 서버 시각보다 5분 이상 후의 미래인 값, 모르는 구간, 범위 밖 값은 받지 않습니다. 하나라도 틀리면 아무것도 저장하지 않습니다.
- 보내지 않은 구간은 `자료 없음`입니다. 최근 96회만 보관합니다.

## 상태 코드

| 구간 `status.code` | 표시 | 의미 |
|---|---|---|
| `no_condition` | 조건 미충족 | 안전하다고 판정한 것이 아님 |
| `icing_condition` | 결빙 가능 조건 | 추정 노면온도 ≤ 1°C, 습도 ≥ 70%, 수분 공급 |
| `prediction_only` | 모델 예측만 | 분류 확률이 임계값 이상이나 위 조건은 아님 |
| `condition_and_prediction` | 결빙 가능 조건 + 모델 예측 | 둘 다 해당 |
| `no_data` | 자료 없음 | 그 시각·구간의 값이 없음 |
| `stale` | 정보 부족(오래된 자료) | 기본 90분을 넘긴 수신 자료. 값을 비움 |
| `no_live_data` | 정보 부족(수신 자료 없음) | 상태를 만들어 내지 않음 |

관측소의 `road_state`는 RWIS 노면상태 코드입니다. 코드 4(Ice)는 `quality`에 따라 `결빙 관측(센서 보고)`과 `결빙 보고·품질 미확인`으로 구분합니다.

`p_icing`은 결빙관련 노면 분류기의 출력입니다. 검증 지점 일별 F1-Score 수치가 낮으므로 결빙 가능성(%)으로 읽으면 안됩니다.

## Python 예시

```python
import json
from urllib.parse import urlencode
from urllib.request import urlopen

query = urlencode({"mode": "history", "at": "2025-01-28T06:00+09:00"})
with urlopen("http://127.0.0.1:8000/api/v1/status?" + query) as response:
    result = json.load(response)
print(result["data_time"], result["summary"])
```
