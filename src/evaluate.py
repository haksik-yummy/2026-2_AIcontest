"""성능 평가 함수. 노트북 03-3·04-3의 계산을 명령줄 추론(scripts/run_inference.py)에서 쓰도록 옮겼습니다.

결빙 평가는 주최 측 QnA 답변을 따릅니다.

- 실제·예측 결빙이 모두 없는 날은 평균에서 뺍니다 (2026-09-30).
- 결빙을 놓친 날은 Precision을 평균에서 빼고 Recall·F1은 0입니다 (2026-10-13).
- 실제 결빙 없이 예측만 한 날은 Recall을 평균에서 빼고 Precision·F1은 0입니다 (2026-11-03).
- 실제 결빙이 한 번도 없는 지점은 '산출불가'로 적고 평균에서 빼며, 활용 지점 수와 평가 날짜 수를 함께 적습니다 (2026-11-02·11-03).
- 세 지점의 TP·FP·FN을 합산하는 방식은 평가에 쓰지 않습니다 (2026-09-29).
"""
import numpy as np
import pandas as pd

NOT_AVAILABLE = "산출불가"


def regression_scores(y_true, y_pred):
    """노면온도 추정 성능. BIAS는 평균(추정 - 관측), R은 피어슨 상관계수입니다."""
    pair = pd.DataFrame({"obs": np.asarray(y_true, float), "est": np.asarray(y_pred, float)}).dropna()
    err = pair["est"] - pair["obs"]
    return {"N": int(len(err)), "BIAS": float(err.mean()), "MAE": float(err.abs().mean()),
            "RMSE": float(np.sqrt((err ** 2).mean())), "R": float(pair["obs"].corr(pair["est"]))}


def daily_icing_scores(df):
    """지점별 일별 TP, FP, FN, Precision, Recall, F1을 구합니다.

    Args:
        df: stn, time, y_true(0/1), y_pred(0/1) 열을 가진 10분 단위 DataFrame. y_true가 비어 있는 시각은 뺍니다.
    """
    d = df.dropna(subset=["y_true"]).copy()
    d["date"] = d["time"].dt.normalize()
    y, p = d["y_true"].astype(int), d["y_pred"].astype(int)
    d["TP"], d["FP"], d["FN"] = y & p, (1 - y) & p, y & (1 - p)
    day = d.groupby(["stn", "date"])[["TP", "FP", "FN"]].sum()
    tp, fp, fn = day["TP"], day["FP"], day["FN"]
    day["Precision"] = (tp / (tp + fp)).where(tp + fp > 0)
    day["Recall"] = (tp / (tp + fn)).where(tp + fn > 0)
    day["F1"] = (2 * tp / (2 * tp + fp + fn)).where(tp + fp + fn > 0)
    return day.reset_index()


def summarize_holdout(daily):
    """지점별 평가기간 평균과 지점 평균을 표로 만듭니다. 실제 결빙이 없는 지점은 '산출불가'입니다."""
    g = daily.assign(obs_day=(daily["TP"] + daily["FN"]) > 0, fp_day=daily["FP"] > 0).groupby("stn")
    out = pd.DataFrame({"평가일수": g["F1"].count(), "결빙관측일수": g["obs_day"].sum(), "오탐일수": g["fp_day"].sum(),
                        "F1": g["F1"].mean(), "Precision": g["Precision"].mean(), "Recall": g["Recall"].mean()})
    used = out["결빙관측일수"] > 0
    metrics = ["F1", "Precision", "Recall"]
    mean = out.loc[used, metrics].mean()
    table = out.astype(object)
    table.loc[~used, metrics] = NOT_AVAILABLE
    table.loc[~used, "평가일수"] = 0
    table.loc["지점 평균"] = {"평가일수": int(out.loc[used, "평가일수"].sum()), "결빙관측일수": int(out.loc[used, "결빙관측일수"].sum()),
                          "오탐일수": int(out.loc[used, "오탐일수"].sum()), **mean.to_dict()}
    return table, int(used.sum())
