"""제공 원자료를 실시간 입력처럼 읽습니다. 프로젝트 data/raw의 일별 CSV에서 valid_time까지의 자료만 돌려줍니다.

수집 경로가 없어도 전체 흐름을 시연하고, 실시간 코드가 노트북과 같은 값을 내는지 검사할 때 씁니다.
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
RWIS_COLS = {"노면상태": "state", "노면온도 (광학)": "rst", "기온 (C)": "ta", "습도 (%)": "rh", "1분 풍속 (m/s)": "ws",
             "일 누적 강수량 (mm)": "pr_day", "시정 (m)": "vis"}
AWS_COLS = {"1분 평균 기온(°C)": "ta", "이슬점온도(°C)": "td", "1분 평균 상대습도(%)": "rh", "10분 평균 풍속(m/s)": "ws", "강수감지(0-무강수)": "rain",
            "60분 누적 강수량(mm)": "pr60", "12시간 누적 강수량(mm)": "pr12h", "일 누적 강수량(mm)": "pr_day"}
ASOS_COLS = {"전운량(10분위)": "cloud", "지면온도(°C)": "tg", "적설(cm)": "snow", "일조(hr)": "sunshine"}


def _days(start, end):
    return pd.date_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize(), freq="1D")


def _read(folder, pattern, start, end, date_format="%Y%m%d"):
    frames = []
    for day in _days(start, end):
        path = next(iter(RAW.glob(f"{folder}/{pattern.format(day=day.strftime(date_format))}")), None)
        if path is not None:
            frames.append(pd.read_csv(path, encoding="utf-8-sig"))
    if not frames:
        raise FileNotFoundError(f"{folder}에서 {start}~{end} 자료를 찾지 못했습니다")
    return pd.concat(frames, ignore_index=True)


class ReplaySource:
    name = "replay"

    def collect(self, start, end):
        """start~end의 원본을 표준 이름으로 바꿔 돌려준다. end 뒤의 자료는 주지 않는다."""
        raw = _read("1. *", "Jeonbuk_RWIS_daily_{day}.csv", start, end).rename(columns=RWIS_COLS)
        raw["time"] = pd.to_datetime(raw["관측시각 (KST)"].astype(str), format="%Y%m%d%H%M")
        raw["stn"] = raw["관측 지점번호"]
        rwis = raw[["stn", "time", *RWIS_COLS.values()]]
        raw = _read("3. *", "Jeonbuk_aws_daily_{day}.csv", start, end).rename(columns=AWS_COLS)
        raw["time"] = pd.to_datetime(raw["시간(KST)"])
        raw["stn"] = raw["지점 번호"]
        aws = raw[["stn", "time", *AWS_COLS.values()]]
        raw = _read("2. *", "Jeonbuk_ASOS_daily_{day}.csv", start, end, "%Y-%m-%d").rename(columns=ASOS_COLS)
        raw["time"] = pd.to_datetime(raw["시간"])
        raw["stn"] = raw["지점"]
        asos = raw[["stn", "time", *ASOS_COLS.values()]]
        cut = lambda df: df[(df["time"] >= start) & (df["time"] <= end)]  # noqa: E731
        return {"rwis": cut(rwis), "aws": cut(aws), "asos": cut(asos)}
