# 데이터·코드 출처

## 입력 자료

- `data/bridges.csv`: `4. 전북도 교량 위경도 데이터.csv`의 사본. 시작점·종료점 좌표 등 원본 열을 유지했습니다.
- `data/tunnels.csv`: `5. 전북도 터널 위경도 데이터.csv`의 사본.
- `data/rwis.csv`: `Jeonbuk_RWIS_daily_20241101.csv`의 사본.
- 입력 CSV는 UTF-8(BOM)으로 저장했습니다. 좌표를 임의로 생성하거나 보간하지 않았습니다.
- 위 파일은 제공 자료의 사본이라 저장소에 넣지 않습니다 (`.gitignore`). `bundle/`, `output/`도 같습니다.

## 시군구 배경

- South Korea maps / southkorea-maps: https://github.com/southkorea/southkorea-maps
- KOSTAT 2013, simplified municipalities GeoJSON:
  https://github.com/southkorea/southkorea-maps/blob/master/kostat/2013/json/skorea_municipalities_geo_simple.json
- 배경의 인접 지역을 일부 남겨 전북의 위치를 알아볼 수 있게 했습니다.
- 2013년 경계·명칭입니다. 현재 시점의 행정구역 포함 여부를 판정하는 데 사용하지 마세요.
- 지도 위의 점을 선으로 연결해 도로 노선을 추정하지 않습니다.

## 결빙 위험도 지도·API

- `bundle/`: 프로젝트 노트북 02\~05의 결과에서 `export_bundle.py`로 만든 값입니다. 구간 등급·요인 점수(`data/results/segment_risk.csv`), 시간별 추정값(`data/processed/segment_estimates.parquet`), RWIS 정시 관측(`data/processed/rwis_10min.parquet`)을 담습니다.
- 교량·터널 구간: 제공 자료 8번의 국토교통부 교량·터널 경계 중 02-2와 같은 방법으로 고른 고속도로 객체와 구간 선이 겹치는 부분입니다. 제공 자료 4·5번 CSV의 대표 위치와 다를 수 있습니다.
- 기존 결빙취약구간: 문제 설명의 [전북도 결빙취약구간 현황] 22개소입니다. 표의 이정은 `src/vulnerable.py`에서 도로 위 위치로 바꿉니다.
  - 기준점: 행정안전부_상습 결빙구간 (공공데이터포털 15067396, 파일 2025-12-08 수정, 이용허락범위 제한 없음). https://www.data.go.kr/data/15067396/fileData.do 구간번호 70100-83\~91, 95는 22개소 표와 연장·순서가 같습니다.
  - 기준점: 노선별 나들목 누적거리(위키백과 서해안고속도로, 호남고속도로, 통영대전고속도로 문서, CC BY-SA)와 나들목 좌표(OpenStreetMap Nominatim, ODbL).
- M3 영하 노면 강설 시간: ERA5-Land 재분석 (Copernicus Climate Change Service, CC-BY 4.0). 출처와 받는 방법은 프로젝트 README 3장입니다.
- 노면상태 코드: 제공 데이터 설명자료와 기상청 API허브의 노면상태 코드(SFS) 문서가 같습니다.

## 실시간 입력

- 기상청 API허브 https://apihub.kma.go.kr/ : 지상관측 시간자료(`kma_sfctm3.php`), AWS 매분자료(`nph-aws2_min`), 도로기상관측(`road_stn_obs.php`), CCTV 기반 도로날씨(`cctv_ana_info.php`).
- 기상청_도로기상관측자료 (공공데이터포털 15159045, 366개소, 이용허락범위 제한 없음). https://www.data.go.kr/data/15159045/openapi.do
- 지점번호는 API허브의 도로기상관측지점 목록과 제공 자료가 같은 체계입니다.

## 시각화 라이브러리

- D3 7.9.0: https://d3js.org/
- Copyright 2010–2023 Mike Bostock
- ISC License 전문은 `assets/D3_LICENSE.txt`에 포함했습니다.
- 지도 생성 시 이 라이브러리와 데이터가 HTML에 삽입됩니다. CDN 접속·지도 API 키는 필요하지 않습니다.
