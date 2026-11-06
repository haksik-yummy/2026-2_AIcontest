# 분석 결과를 API와 네이버 지도에 연결하기

프로젝트의 결빙 위험도 결과(233개 구간 등급, 구간별 시간당 추정 노면온도·결빙 가능 조건)를 HTTP API로 제공하고, 그 API를 네이버 지도 위에 표시합니다. 모델을 다시 학습하지 않고 저장된 결과와 모델을 그대로 씁니다.

| 원하는 기능 | 구현 | 필요한 것 |
|---|---|---|
| 결과를 다른 프로그램에서 받기 | JSON·GeoJSON API (`service/server.py`) | 없음 |
| 지도에서 구간 상태 보기 | 네이버 지도 Data 레이어, 키가 없으면 내장 지도 | 네이버 지도는 공개 Client ID |
| 출발지·도착지 경로의 위험 요약 | 서버가 Directions 5를 호출해 구간과 맞춤 | Directions 5 인증키 |
| 노선 km 범위의 위험 요약 | `/api/v1/route-risk/stretch` | 없음 |
| 네이버 지도 앱으로 넘기기 | 선택 구간 마커, 자동차 길찾기 호출 | 휴대폰 앱 |
| 현재 상태 갱신 | 기상청 API허브 수집 → 구간 추정 → API 입력 (`realtime/`) | API허브 인증키 |

**네이버 공식 지도 앱에 우리 위험도 레이어를 넣는 기능은 아닙니다.** 공개 앱 연동 문서는 마커·검색·길찾기 호출만 설명합니다. 여러 구간의 상태는 우리 화면에서 보고, 선택한 지점이나 경로만 공식 앱으로 넘깁니다.

## 1. 먼저 실행하기

```bash
cd jeonbuk_map_code
python service/server.py --open
```

`http://localhost:8000`이 열립니다. 종료는 `Ctrl+C`입니다. API 서버는 Python 기본 기능만 씁니다 (3.9 이상, 3.12·3.13에서 실행 확인). 키가 없어도 과거 재생, 내장 지도, 노선 구간 조회, 우선 구간 목록이 동작합니다. `현재 수신`을 누르면 수신 자료가 없으므로 회색입니다. 현재 날씨나 결빙을 임의로 만들지 않습니다.

자세한 분석 지도는 `/atlas`, API 설명은 `/api-docs`입니다. 분석 지도는 `python build_risk_map.py`로 먼저 만들어야 합니다.

## 2. 네이버 지도 배경으로 바꾸기

1. [네이버 클라우드 콘솔](https://console.ncloud.com/)의 **Services → Application Services → Maps → Application**에서 애플리케이션을 등록합니다.
2. **Dynamic Map**을 고르고 공개 **Client ID**를 확인합니다.
3. Web 서비스 URL에 `http://localhost`를 등록합니다. `127.0.0.1`로 접속하면 `http://127.0.0.1`도 등록합니다. 포트와 경로는 넣지 않습니다.
4. `service/config.example.json`을 `service/config.local.json`으로 복사하고 `naver_key_id`에 Client ID를 넣습니다. 이 파일은 저장소에 올라가지 않습니다.
5. 서버를 다시 실행합니다.

지도 배경·도로명은 네이버가, 구간 색·상태·시각은 우리 API가 제공합니다. 키가 틀렸거나 네이버 스크립트를 받지 못하면 화면이 안내문을 띄우고 내장 지도로 바꿉니다.

## 3. 출발지·도착지 경로 위험

콘솔의 같은 Application에서 **Directions 5**를 켠 뒤 인증키를 환경변수로 줍니다. 파일이나 브라우저로는 보내지 않습니다.

```bash
export NCP_MAPS_KEY_ID="..."
export NCP_MAPS_KEY="..."
python service/server.py
```

화면의 `출발지·도착지` 탭에서 좌표를 넣거나 `지도에서`로 찍습니다. 서버는 Directions 5 경로를 25m 간격으로 짚어 60m 안의 구간과 맞추고, 100m보다 짧게 스친 구간은 뺍니다. 통과 시각은 전체 소요 시간을 거리 비율로 나눈 근사입니다.

- `과거 재생`: 그 시각에 출발했다면 지나는 구간의 시각별 값을 보여 줍니다.
- `현재 수신`: 마지막 수신 시각의 상태입니다. 앞으로의 예보가 아닙니다.

경로 응답은 요청 처리에만 쓰고 저장하지 않습니다. 이용 한도와 요금은 콘솔에서 확인하세요.

## 4. 네이버 지도 앱으로 열기

구간을 고른 뒤 `네이버 지도 앱에서 열기`를 누르면 그 좌표의 마커를 엽니다. 이름에 구간, 등급, 상태, 과거/현재 구분, 자료 시각이 들어갑니다. `네이버 지도 앱으로 길찾기`는 입력한 좌표로 자동차 길찾기를 엽니다.

- 일반 호출은 `nmap://place`, `nmap://route/car`입니다. Android는 공식 가이드의 Intent 형식을 씁니다.
- iPhone에 앱이 없으면 설치 화면으로 넘어갑니다. 인앱 브라우저에서 막히면 Chrome·Safari로 여세요.
- PC에서는 앱이 열리지 않으므로 호출 주소만 보여 줍니다.
- 앱으로 넘어간 뒤에는 상태가 갱신되지 않습니다. 다시 확인할 때는 우리 화면으로 돌아옵니다.

## 5. 현재 관측 연결하기

기상청은 2025-12-15부터 도로기상 관측자료를 API로 공개했습니다. 수집기는 AWS(10분)·ASOS(1시간)·도로기상(10분)을 받아 02~05 노트북과 같은 계산으로 구간 값을 만들고 API로 보냅니다.

프로젝트 환경(`conda activate haksik`)에서 실행합니다.

```bash
python jeonbuk_map_code/export_bundle.py          # 처음 한 번, 또는 분석을 다시 돌린 뒤
python jeonbuk_map_code/realtime/build_static.py  # 처음 한 번
```

[기상청 API허브](https://apihub.kma.go.kr/)에서 인증키를 받고 지상관측(ASOS 시간자료·AWS 매분자료), 도로기상관측, CCTV 도로날씨 API의 활용신청 여부를 확인합니다.

**실제 운영 전에 응답 해석을 먼저 대조하세요.** `road_stn_obs.php`의 출력 항목은 API허브 문서에 없어, 헤더를 먼저 읽고 없으면 제공 RWIS CSV의 열 순서로 해석합니다. 도로기상 자료는 2024-01-01부터 조회할 수 있으므로 과거 시각을 제공 자료와 비교합니다.

```bash
export KMA_APIHUB_KEY="..."
cd jeonbuk_map_code
python realtime/pipeline.py --check-api --compare 2025-01-28T06:00
```

항목이 일치하지 않으면 `realtime/cache/raw/`의 응답 원문을 보고 `realtime/road_columns.json`에 열 위치를 적습니다 (예: `{"tm": 0, "stn": 1, "state": 2, "rst": 3}`). 값이 코드표나 온도 범위를 벗어나면 수집기는 값을 보내지 않고 멈춥니다.

운영은 서버와 수집기를 같은 토큰으로 실행합니다. 토큰을 코드나 저장소에 넣지 마세요.

```bash
export ICING_INGEST_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
python service/server.py &
python realtime/pipeline.py --source kma --post http://127.0.0.1:8000 --watch 600
```

처음 실행은 지점별로 78시간 치를 받고, 이후에는 `realtime/cache/`에 쌓아 두고 새 시각만 받습니다. ASOS 정시 자료가 올라올 시간을 두어 15분이 지난 직전 정시를 추정합니다. RWIS 원천 5곳, AWS 10곳, ASOS 3곳보다 적으면 구간 추정을 보내지 않고 관측소 값만 보냅니다.

이 추정은 **같은 시각의 관측으로 구간을 메우는 현재 추정**입니다. 모델 입력에 같은 시각의 주변 RWIS 관측이 들어가므로 앞으로의 시각은 예측하지 못합니다. +N시간 예측에는 예보를 입력으로 쓰는 모델을 따로 학습·평가해야 합니다.

기상청 도로위험기상정보(살얼음 관심·주의·위험)는 도로기상 관측망을 쓰므로 모델 입력에 넣으면 검증 지점 누수가 생깁니다. 파일 형식 정의서를 확인하지 못해 이 코드에는 넣지 않았습니다.

### 화면의 상태와 의미

| 표시 | 뜻 |
|---|---|
| 결빙 가능 조건 + 모델 예측 | 추정 노면온도 ≤ 1°C, 습도 ≥ 70%, 수분 공급이고 분류 확률도 임계값 이상 |
| 결빙 가능 조건 | 위 조건 해당. 실제 결빙과 구분 |
| 모델 예측만 | 분류 확률만 임계값 이상 |
| 조건 미충족 | 안전 판정이 아님 |
| 회색, 정보 부족 | 수신 자료가 없거나 신선도 기준(기본 90분)보다 오래됨. 값을 비움 |
| 관측소의 결빙 관측 / 결빙 보고·품질 미확인 | 센서 Ice 보고를 `quality`로 구분. 수집기는 제공자 QC를 확인할 수 없어 `unverified`로 보냄 |

신선도 90분은 공식 기준이 아니라 서비스 설정입니다. `config.local.json`의 `observation_ttl_minutes`로 바꿉니다.

## 6. 키 없이 시연하기

제공 원자료를 그 시각까지만 읽어 실시간 입력처럼 보냅니다. 서버 시각을 함께 옮겨야 `현재 수신`에 나타납니다. 화면에 시연 시각임을 표시합니다.

```bash
export ICING_INGEST_TOKEN=demo
python service/server.py --sim-clock 2025-01-28T06:12+09:00 --db /tmp/demo.sqlite3 &
python realtime/pipeline.py --source replay --valid-time 2025-01-28T06:00 --post http://127.0.0.1:8000
```

`http://localhost:8000/?mode=live`로 열고, 시연 자료가 운영 DB에 섞이지 않도록 `--db`를 따로 씁니다.

## 7. 휴대폰에서 사용하기

```bash
python service/server.py --host 0.0.0.0 --port 8000
```

같은 Wi-Fi에서 `http://PC의IPv4:8000`을 엽니다. 네이버 지도 배경을 쓰면 그 주소도 Web 서비스 URL에 등록합니다. 외부 네트워크에서 쓰려면 공개 HTTPS 주소와 접근 제한이 필요합니다. 이 서버는 개발·발표용이며 공개 운영 서버가 아닙니다. 자료에 대회 제공 관측값이 들어 있으므로 공개 전에 이용조건을 확인하세요.

## 8. 분석을 다시 돌린 뒤 갱신하기

```bash
python jeonbuk_map_code/export_bundle.py
python jeonbuk_map_code/realtime/build_static.py
python jeonbuk_map_code/ops/vulnerable_sections.py
python jeonbuk_map_code/build_risk_map.py
```

## 9. 확인 범위

| 항목 | 방법 | 결과 |
|---|---|---|
| 실시간 코드와 노트북의 일치 | 원자료를 그 시각까지만 넣어 `segment_estimates.parquet`와 비교 (무작위 30개 시각 × 233구간) | 노면온도·확률 최대 차이 0.00000 |
| API | `python -m unittest discover -s service -p "test_*.py"` | 35개 통과 |
| 실시간 경로 | `python -m unittest discover -s realtime -p "test_*.py"` (프로젝트 환경) | 17개 통과 |
| 화면 | 헤드리스 Chrome으로 선택·툴팁·재생·경로·브리핑 조작 | 오류 없음 |

**확인하지 못한 것**

- 기상청 API허브 실제 응답: 인증키가 없어 호출하지 못했습니다. 해석 검사의 입력은 문서와 제공 CSV 열 순서로 만든 예시입니다.
- 네이버 지도 실제 인증·타일과 Directions 5 실제 호출: SDK와 응답을 공식 문서 형식의 대역으로만 확인했습니다.
- Android·iPhone 앱 호출: 실기기에서 확인하지 않았습니다.

## 10. 출처

2026-11-04 기준으로 확인한 공식 문서입니다.

- [NAVER 지도 JavaScript API 시작하기](https://navermaps.github.io/maps.js.ncp/docs/tutorial-2-Getting-Started.html), [Data 레이어](https://navermaps.github.io/maps.js.ncp/docs/tutorial-2-DataLayer.html)
- [Directions 5 API](https://api.ncloud-docs.com/docs/application-maps-directions5): `maps.apigw.ntruss.com/map-direction/v1/driving`, 인증 헤더, 응답 구조
- [네이버 지도 앱 URL Scheme](https://guide.ncloud-docs.com/docs/maps-url-scheme), [Maps 문제 해결](https://guide.ncloud-docs.com/docs/application-maps-troubleshoot)
- [기상청 API허브](https://apihub.kma.go.kr/): `kma_sfctm3.php`, `nph-aws2_min`, `road_stn_obs.php`, `cctv_ana_info.php`
- [기상청_도로기상관측자료](https://www.data.go.kr/data/15159045/openapi.do), [기상청 보도자료 2025-12-15](https://www.kma.go.kr/kma/flexer/html/press/2025/12/12/ATC202512121749552_f270322e-2563-431d-a2d8-f333fac9b9d1.hwp.files/Sections1.html)

AI는 코드·문서 초안과 검증 절차 구성에 사용했습니다.
