# 전북 고속도로 지도·API

결빙 위험도 분석 결과를 지도와 API로 쓰는 코드입니다. 프로젝트 노트북(01~05)의 결과를 읽습니다.

| 기능 | 실행 | 필요한 것 |
|---|---|---|
| 결빙 위험도 지도 (인터넷 없이 열리는 HTML 한 파일) | `python build_risk_map.py --open` | Python만 |
| 결과 API와 지도 화면 | `python service/server.py --open` | Python만 |
| 네이버 지도 배경, 경로 위험 | 같은 서버 | 네이버 Client ID, Directions 5 인증키 |
| 현재 관측 수집과 구간 추정 | `python realtime/pipeline.py ...` | 프로젝트 환경, 기상청 API허브 인증키 |
| 키 없는 재생 시연 | `python realtime/pipeline.py --source replay ...` | 프로젝트 환경, `data/raw` |
| 우선 구간 목록 | `python ops/briefing.py --start 2025-01-27T18:00` | Python만 |
| 상습 결빙구간 비교 | `python ops/vulnerable_sections.py` | 프로젝트 환경, 상습 결빙구간 CSV |
| 교량·터널·RWIS 위치 지도 (이전 자료) | `python build_map.py --open` | Python만 |

API와 네이버, 현재 관측 연결은 [jeonbuk_naver_api_guide.md](jeonbuk_naver_api_guide.md), 요청·응답 계약은 [service/API.md](service/API.md)에 있습니다.

## 결과 묶음 만들기

`bundle/`은 지도와 API가 읽는 분석 결과입니다. 노트북 05-2까지 실행한 뒤 프로젝트 환경에서 한 번 만듭니다. 그다음 단계는 Python 기본 기능만 씁니다.

```bash
python jeonbuk_map_code/export_bundle.py           # bundle/
python jeonbuk_map_code/ops/vulnerable_sections.py # 상습 결빙구간 층 (선택)
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
- 노선 띠 그림은 노선 거리 × 시각으로 어디가 언제 차가운지 보여 줍니다.
- `표로 보기`는 지금 시각의 233개 구간 값입니다.
- 주소 뒤 `#mode=state&t=2025-01-28T06&seg=TD-014&theme=dark`로 같은 화면을 다시 엽니다.

### 해석할 때

- 지도는 결빙이 생기기 쉬운 곳과 때를 나타냅니다. 실제 결빙을 확인한 것이 아니며, 낮은 등급이나 조건 미충족은 안전 판정이 아닙니다.
- 시간별 지도는 추정 노면온도와 결빙 가능 조건을 중심으로 보세요. 결빙 분류의 검증 지점 일별 F1(빈 날 제외)이 낮아 모델 예측은 참고값입니다. 확률을 결빙 가능성(%)으로 읽지 마세요.
- 위험 등급은 관측소의 노면 0°C 이하 비율과 순위상관이 높지만 Ice 관측 비율과는 거의 상관이 없습니다.
- 상습 결빙구간 8개의 경계·심각 비율은 전체보다 높지만 같은 노선에 무작위로 놓아도 비슷합니다. 차이의 대부분은 노선 구성입니다.
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
  export_bundle.py        프로젝트 결과 → bundle/ (프로젝트 환경)
  build_risk_map.py       bundle/ → 결빙 위험도 지도 HTML
  build_map.py            교량·터널·RWIS 위치 지도
  bundle/                 지도·API가 읽는 분석 결과
  assets/                 지도 템플릿, D3, 시군구 경계
  output/                 만들어진 지도와 목록
  service/                API 서버, 지도 화면, 검사
    server.py  store.py  geo.py  ops.py  naver.py  API.md  static/
  realtime/               수집과 구간 추정 (프로젝트 환경)
    pipeline.py  engine.py  kma_client.py  replay.py  build_static.py
  ops/                    우선 구간 목록, 상습 결빙구간 비교
  data/                   위치 지도용 CSV 사본
```

`bundle/`과 지도 HTML에는 대회 제공 RWIS 관측값이 들어 있습니다. `data/`에는 제공 원자료 사본이 있습니다. 저장소에 올리거나 공개 배포하기 전에 대회 데이터 이용조건을 확인하세요.

## 부록. 교량·터널·RWIS 위치 지도

교량·터널·RWIS CSV를 읽어 위치만 시각화합니다. 별도의 Python 패키지나 API 키는 필요하지 않습니다.

### 1. 바로 실행하기

1. ZIP을 **모두 압축 해제**합니다. ZIP 내부에서 실행하지 마세요.
2. VS Code → `파일 → 폴더 열기`에서 `jeonbuk_map_code` 폴더를 선택합니다.
3. `터미널 → 새 터미널`을 열고 아래 명령을 실행합니다.

```powershell
python build_map.py --open
```

Python 3.9 이상을 사용하세요. 기존 `.venv`도 사용할 수 있습니다.
실행하면 `output/jeonbuk_map.html`이 만들어지고 기본 브라우저에서 열립니다.
이미 만들어 둔 `output/jeonbuk_map.html`을 더블클릭해도 지도를 볼 수 있습니다.
HTML 결과물은 한 파일에 지도·데이터·코드가 포함되어 있어 단독으로 옮길 수 있습니다.

### 2. 지도 조작

- 휠·터치로 확대/축소, 드래그로 이동
- `＋`, `−`, `전체 보기` 버튼
- 교량·터널·RWIS 범례를 눌러 각각 숨기거나 표시
- 점을 누르거나 `지점 선택` 목록에서 선택해 노선·좌표 확인
- 같은 좌표의 교량·터널 행은 하나의 위치로 표시하며 원본 행 수를 따로 표시

### 3. 새 파일로 바꾸기

#### 가장 쉬운 방법

`data` 폴더의 다음 파일을 같은 열 구조의 CSV로 바꾸고 다시 실행합니다.

| 파일 | 내용 |
|---|---|
| `bridges.csv` | 교량 위치 |
| `tunnels.csv` | 터널 위치 |
| `rwis.csv` | RWIS 관측자료 |

#### 원래 파일명을 유지하는 방법

```powershell
python build_map.py --bridges "D:\DATA AI 경진대회 데이터(20261007)\4. 전북도 교량 위경도 데이터.csv" --tunnels "D:\DATA AI 경진대회 데이터(20261007)\5. 전북도 터널 위경도 데이터.csv" --rwis "D:\DATA AI 경진대회 데이터(20261007)\1. 전북도 고속도로 RWIS(도로기상) 관측 데이터.csv" --open
```

이 경로는 사용 예시입니다. 실제 파일 위치와 파일명에 맞게 고치세요.
UTF-8과 CP949는 코드가 자동으로 구분합니다.

### 4. 폴더 구성과 수정 위치

```text
jeonbuk_map_code/
  build_map.py                 CSV 읽기·좌표 정리·HTML 생성
  README.md                   실행 방법
  data/
    bridges.csv
    tunnels.csv
    rwis.csv
  assets/
    map_template.html         지도 모양·클릭·확대·범례 동작
    d3.v7.9.0.min.js           지도 표시용 라이브러리
    municipalities.geojson    시군구 배경 지도
    D3_LICENSE.txt
  output/
    jeonbuk_map.html           바로 열 수 있는 결과
  SOURCES.md                  출처와 데이터 주의점
```

- 제목·설명: `assets/map_template.html`의 `<h1>`과 `.subtitle`
- 색상: 같은 파일 첫 부분의 `--bridge`, `--tunnel`, `--rwis`
- 점 크기: JavaScript `kinds` 배열의 `size`
- 입력 열 이름: `build_map.py`의 `find_column()` 호출 부분
- 생성 위치 변경: `python build_map.py --output "D:\jeonbuk_map.html" --open`

### 5. 데이터 해석

- 이 지도는 **위치 분포**입니다. 결빙 위험도나 모델 성능을 나타내지 않습니다.
- 교량 CSV는 원본 453행을 시작점 좌표 기준 151개 대표 위치로 묶었습니다.
- 터널 CSV는 원본 14행을 시작점 좌표 기준 7개 대표 위치로 묶었습니다.
- 시작·종료 좌표가 같은 행이 많습니다. 표시점을 실제 중심점·입구·출구로 확정하거나 길이를 계산하지 마세요.
- 동일 좌표가 상·하행 시설물인지 중복인지 판별하지 않습니다. 따라서 '151개 교량'이 아닌 '151개 대표 위치'입니다.
- 포함된 RWIS는 2024-11-01 하루치, 2,448행, 17개 지점입니다. 지도에는 관측 행이 아닌 고유 관측 위치를 표시합니다.
- 같은 지점번호가 여러 좌표에 있으면 각 위치를 따로 표시합니다.
- 좌표의 열 이름에 따라 위도·경도를 읽습니다. 국내 범위를 벗어난 좌표는 제외하고 개수를 터미널에 알립니다.
- 입력 좌표는 도 단위 위경도(통상 WGS84)를 전제로 합니다. EPSG:5179 같은 미터 좌표는 먼저 위경도로 변환해야 합니다.
- 배경은 2013년 시군구 경계로, 현재 행정경계의 정밀 판정용이 아닙니다.
- 원본 CSV는 수정하지 않습니다. 출력 HTML에는 입력 좌표가 포함됩니다.

### 6. 오류가 나면

- `python`을 찾지 못함: VS Code에서 설치된 Python 인터프리터를 선택하세요.
- 파일을 찾지 못함: 폴더 전체를 압축 해제했는지, 지정한 CSV 경로가 맞는지 확인하세요.
- 필요한 열을 찾지 못함: 오류 메시지에 나온 열 이름과 원본 CSV의 열 이름을 비교하세요.
- 지도가 안 보임: Chrome·Edge·Firefox의 최신 버전으로 열고 JavaScript 허용 여부를 확인하세요.
- 이 코드는 일반 CSV를 사용합니다. `.shp`, `.tif`, 엑셀 파일을 그대로 넣을 수는 없습니다.
