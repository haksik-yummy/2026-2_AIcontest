# 2026 DATA·AI 분석 경진대회

## 📋 주제
**기상과 도로환경 융합자료를 활용한 AI기반의 전북도 고속도로 결빙위험도 분석 제시**

- **주관**: KISTI (한국과학기술정보연구원) · 전주기상지청
- **대회 기간**: 참가신청 2026-09-15 ~ 2026-11-06
- **플랫폼**: [AIDA 경진대회](https://aida.kisti.re.kr/competition/main/problem/PROB_000000000004604/detail.do)

## 📂 프로젝트 구조

```
├── data/                  # 데이터 (gitignore 처리)
│   ├── 1. RWIS(도로기상) 관측 데이터.csv
│   ├── 2. ASOS(종관기상) 관측 데이터.csv
│   ├── 3. AWS(방재기상) 관측 데이터.csv
│   ├── 4. 교량 위경도 데이터.csv
│   ├── 5. 터널 위경도 데이터.csv
│   ├── 6. 고속도로 곡률 데이터/  (Shapefile)
│   ├── 7. 수치 표고 모델 고도 데이터.tif  (DEM)
│   └── 8. 국토교통부 도로/교량/터널/하천 경계 데이터/  (Shapefile)
├── notebooks/             # 탐색/분석 Jupyter 노트북
├── src/                   # 소스 코드
│   ├── config.py          # 경로 및 설정 관리
│   └── data_loader.py     # 데이터 로딩 유틸리티
├── models/                # 학습된 모델 저장
├── outputs/               # 분석 결과/시각화 출력
├── requirements.txt       # Python 의존성
└── .gitignore
```

## 🚀 환경 설정

```bash
# 가상환경 생성 및 활성화
python3 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt
```

## 📊 데이터 설명

| # | 데이터 | 형식 | 설명 |
|---|--------|------|------|
| 1 | RWIS 도로기상 | CSV (cp949) | 노면온도, 노면상태, 기온, 습도, 풍향/풍속, 기압 등 |
| 2 | ASOS 종관기상 | CSV (cp949) | 기온, 강수, 풍속, 습도, 기압, 일조, 적설 등 |
| 3 | AWS 방재기상 | CSV (cp949) | 풍향/풍속, 기온, 강수, 습도, 기압 등 |
| 4 | 교량 위경도 | CSV (cp949) | 전북도 고속도로 교량 위치 좌표 |
| 5 | 터널 위경도 | CSV (cp949) | 전북도 고속도로 터널 위치 좌표 |
| 6 | 도로 곡률 | Shapefile | 고속도로 곡률(커브) 포인트 데이터 |
| 7 | 수치표고모델 | GeoTIFF | DEM 고도 데이터 (~265MB) |
| 8 | 국토부 공간 | Shapefile | 도로, 교량, 터널, 하천 경계, 접도구역 |
