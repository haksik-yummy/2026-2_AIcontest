# 전북 고속도로 지도·API

결빙 위험도 분석 결과를 지도와 API로 쓰는 코드입니다. 프로젝트 노트북(01~05)의 결과를 읽습니다.

| 기능 | 실행 | 필요한 것 |
|---|---|---|
| 결빙 위험도 지도 (인터넷 없이 열리는 HTML 한 파일) | `python build_risk_map.py --open` | Python |
| 결과 API와 지도 화면 | `python service/server.py --open` | Python |
| 네이버 지도 배경, 경로 위험 | 같은 서버 | 네이버 Client ID, Directions 5 인증키 |
| 현재 관측 수집과 구간 추정 | `python realtime/pipeline.py ...` | 프로젝트 환경, 기상청 API허브 인증키 |
| 키 없는 재생 시연 | `python realtime/pipeline.py --source replay ...` | 프로젝트 환경, `data/raw` |
| 우선 구간 목록 | `python ops/briefing.py --start 2025-01-27T18:00` | Python |
| 기존 결빙취약구간 층 | `python ops/vulnerable_sections.py` | 프로젝트 환경, 노트북 05-2의 결과 |
| 교량·터널·RWIS 위치 지도 (이전 자료) | `python build_map.py --open` | Python |

API와 네이버, 현재 관측 연결은 [jeonbuk_naver_api_guide.md](jeonbuk_naver_api_guide.md), 요청·응답 계약은 [service/API.md](service/API.md)에 있습니다.

## 결과 묶음 만들기

`bundle/`은 지도와 API가 읽는 분석 결과입니다. 제공 자료의 관측값이 들어 있어 `data/`, `output/`과 함께 저장소에 넣지 않습니다. 노트북 05-2까지 실행한 뒤 프로젝트 환경에서 한 번 만듭니다. 그다음 단계는 Python 기본 기능만 씁니다.

```bash
python jeonbuk_map_code/export_bundle.py           # bundle/
python jeonbuk_map_code/ops/vulnerable_sections.py # 기존 결빙취약구간 층 (선택)
python jeonbuk_map_code/build_risk_map.py          # output/jeonbuk_risk_atlas.html
```

제출 폴더에 둘 때는 `python build_risk_map.py --output ../figures/risk_map_atlas.html`처럼 경로를 줍니다.

## 결빙 위험도 지도

| 보기 | 내용 |
|---|---|
| 위험 등급 | 두 겨울 전체로 매긴 233개 구간의 관심·주의·경계·심각 |
| 추정 노면온도 | 고른 시각의 구간별 추정값. 관측소 칸은 같은 색 척도의 실측값 |
| 결빙 가능 조건 | 고른 시각의 조건·모델 예측. 붉은 테두리는 관측소의 결빙관련 노면 관측 |

- 날짜·시각을 고르거나 `재생`으로 시간을 넘깁니다. 주요 사례일은 예측 구간이 많았던 날입니다.
- 구간을 누르면 등급의 근거(M1~T3 지표와 기준)와 72시간 노면온도를 봅니다. 관측소가 있는 구간은 실측을 겹쳐 봅니다.
- 노선 띠 그림은 노선 거리 × 시각으로 어디가 언제 차가운지 표시합니다.
- `표로 보기`는 지금 시각의 233개 구간 값입니다.
- 주소 뒤 `#mode=state&t=2025-01-28T06&seg=TD-014&theme=dark`로 같은 화면을 다시 엽니다.

### 해석할 때

- 지도는 결빙이 생기기 쉬운 곳과 때를 나타냅니다. 실제 결빙을 확인한 것이 아니며, 낮은 등급이나 조건 미충족은 안전 판정이 아닙니다.
- 시간별 지도는 추정 노면온도와 결빙 가능 조건을 중심으로 보세요. 결빙 분류의 검증 지점 일별 F1이 낮아 모델 예측은 참고값입니다. 실제 결빙이 있는 검증 지점은 부곡교 한 곳뿐입니다. 확률을 결빙 가능성(%)으로 읽지 마세요.
- 위험 등급은 관측소의 노면 0°C 이하 비율과 순위상관이 높지만 Ice 관측 비율과는 거의 상관이 없습니다.
- 기존 결빙취약구간 22개소 중 전북 구간에 들어오는 11곳의 경계·심각 비율은 48%로 전체(31%)보다 높습니다. 같은 노선에 무작위로 놓아도 41%가 나와서 차이의 대부분은 노선 구성입니다.
- 교량·터널 구간은 위험도 계산에 쓴 국토부 경계입니다. 제공 교량 위경도 CSV의 대표 위치와 다를 수 있습니다.
- 학습 지점이 있는 구간은 그 관측이 추정에 들어가 실측과 가깝게 나옵니다. 독립 비교는 검증 지점(◆) 구간에서 보세요.

## 우선 구간 목록

```bash
python ops/briefing.py --start 2025-01-27T18:00 --hours 15 --group sigungu --top 5 --out output/briefing_20250127
python ops/briefing.py --api http://127.0.0.1:8000     # 마지막 수신 시각 기준
```

인쇄용 HTML과 CSV를 만듭니다. 모델 예측 시간, 결빙 가능 조건 시간, 위험 등급, 최저 추정 노면온도 순으로 정렬할 뿐 살포 시점이나 작업량을 정하지 않습니다.

지사별로 묶으려면 `--group branch --branches 지사.csv`를 씁니다 (열: 지사명·위도·경도). 가장 가까운 지사를 직선거리로 고르므로 실제 관할과 다를 수 있습니다. 공개된 지사 위치(data.go.kr 15151921)는 재난안전데이터 공유플랫폼의 인증키가 필요해 넣지 않았습니다.

## 폴더 구성

```text
jeonbuk_map_code/
  export_bundle.py        #프로젝트 결과 → bundle/ (프로젝트 환경)
  build_risk_map.py       #bundle/ → 결빙 위험도 지도 HTML
  build_map.py            #교량·터널·RWIS 위치 지도
  bundle/                 #지도·API가 읽는 분석 결과
  assets/                 #지도 템플릿, D3, 시군구 경계
  output/                 #만들어진 지도와 목록
  service/                #API 서버, 지도 화면, 검사
    server.py  store.py  geo.py  ops.py  naver.py  API.md  static/
  realtime/               #수집과 구간 추정 (프로젝트 환경)
    pipeline.py  engine.py  kma_client.py  replay.py  build_static.py
  ops/                    #우선 구간 목록, 기존 결빙취약구간 층
  data/                   #위치 지도용 CSV 사본
```

`bundle/`과 지도 HTML에는 대회 제공 RWIS 관측값이 들어 있습니다. `data/`에는 제공 원자료 사본이 있습니다. 그래서 세 폴더는 저장소에 넣지 않았습니다.

## 부록. 교량·터널·RWIS 위치 지도

`build_map.py`는 분석 전에 제공 자료의 위치를 확인하려고 만든 지도입니다. 결빙 위험도나 모델 성능은 나타내지 않습니다. `data/`의 CSV를 읽어 `output/jeonbuk_map.html`을 만들고 Python 기본 기능만 씁니다.

```bash
python build_map.py --open
python build_map.py --bridges 교량.csv --tunnels 터널.csv --rwis RWIS.csv --output 지도.html
```

- 교량 CSV 453행은 시작점 좌표 기준 151개 대표 위치로, 터널 CSV 14행은 7개 대표 위치로 묶습니다.
- 시작·종료 좌표가 같은 행이 많아서 표시점을 실제 입구나 중심으로 보거나 길이를 계산하면 안 됩니다.
- RWIS는 2024-11-01 하루치에서 고유 관측 위치만 표시합니다.
- 배경은 2013년 시군구 경계입니다.
