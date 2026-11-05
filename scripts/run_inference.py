"""저장된 모델로 검증 지점 3곳을 다시 예측하고 성능지표를 출력합니다. 학습은 하지 않습니다.

실행: python scripts/run_inference.py
입력: model/ 의 모델 파일, data/processed/ 의 station_features.parquet, estimation_b3.parquet
출력: 화면에 지점별 지표를 출력하고, 노트북이 저장한 제출 표(data/results/holdout_submission_10min.csv)와 값을 비교합니다.
"""
import json
import sys
import time
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config, evaluate  # noqa: E402


def load_holdout():
    """검증 지점의 변수와 B3 추정값을 읽습니다. 관측값은 평가에만 씁니다."""
    features = pd.read_parquet(config.PROCESSED_DIR / "station_features.parquet")
    features = features[features["stn"].isin(config.HOLDOUT_STATIONS)]
    b3 = pd.read_parquet(config.PROCESSED_DIR / "estimation_b3.parquet")
    return features.merge(b3, on=["stn", "time"], how="left", validate="one_to_one").reset_index(drop=True)


def estimate_road_temperature(df):
    """노면온도 앙상블: LightGBM, Ridge, 주변 노면온도(B1), B3의 단순 평균입니다."""
    meta = json.loads((config.MODEL_DIR / "road_temp_meta.json").read_text(encoding="utf-8"))
    lgbm = lgb.Booster(model_file=str(config.MODEL_DIR / "road_temp_lgbm.txt"))
    ridge = joblib.load(config.MODEL_DIR / "road_temp_ridge.joblib")
    parts = pd.DataFrame({"LightGBM(핵심)": lgbm.predict(df[meta["features"]]),
                          "Ridge(핵심)": ridge.predict(df[meta["features"]]),
                          "B1 주변 노면온도": df["nbr_rst"].to_numpy(),
                          meta["b3"]: df["b3"].to_numpy()})
    return parts[meta["ensemble"]].mean(axis=1).to_numpy()


def predict_icing(df):
    """결빙 분류: 저장된 LightGBM의 확률과 임계값 판정을 돌려줍니다."""
    meta = json.loads((config.MODEL_DIR / "icing_meta.json").read_text(encoding="utf-8"))
    booster = lgb.Booster(model_file=str(config.MODEL_DIR / meta["model_file"]))
    prob = booster.predict(df[meta["features"]])
    return prob, (prob >= meta["threshold"]).astype(int), meta


def main():
    pd.set_option("display.unicode.east_asian_width", True)
    t0 = time.time()
    df = load_holdout()
    print(f"검증 지점 {df['stn'].nunique()}곳, 10분 자료 {len(df):,}행")

    df["rst_est"] = estimate_road_temperature(df)
    rows = {config.HOLDOUT_STATIONS[s][0]: evaluate.regression_scores(g["rst"], g["rst_est"]) for s, g in df.groupby("stn")}
    df["rst_est"] = df["rst_est"].astype("float32")  # 노트북이 저장한 추정값과 같은 정밀도로 결빙을 판정합니다
    scores = pd.DataFrame(rows).T
    scores.loc["세 지점 평균"] = scores.mean()
    print("\n[노면온도 추정] BIAS, MAE, RMSE (°C)")
    print(scores[["BIAS", "MAE", "RMSE"]].round(3).to_string())

    df["rst_dpd"] = df["rst_est"] - df["td"]
    df["prob"], df["pred"], meta = predict_icing(df)
    daily = evaluate.daily_icing_scores(df[["stn", "time"]].assign(y_true=df["ice"], y_pred=df["pred"]))
    table, used = evaluate.summarize_holdout(daily)
    table.index = [config.HOLDOUT_STATIONS.get(i, (i,))[0] for i in table.index]
    print(f"\n[결빙 분류] 일별 지표 평균, 모델 {meta['method']}, 임계값 {meta['threshold']:.3f}, 활용 지점 {used}개소")
    print(table.map(lambda v: round(v, 3) if isinstance(v, float) else v).to_string())

    saved_path = config.RESULT_DIR / "holdout_submission_10min.csv"
    if saved_path.exists():
        saved = pd.read_csv(saved_path, encoding="utf-8-sig")
        same_pred = (np.where(df["pred"] == 1, "결빙", "비결빙") == saved["노면상태 예측값(결빙여부)"].to_numpy()).mean()
        gap = np.nanmax(np.abs(df["rst_est"].round(2).to_numpy() - saved["노면온도 예측값"].to_numpy()))
        print(f"\n저장된 제출 표와 비교: 결빙 판정 일치 {same_pred:.2%}, 노면온도 최대 차이 {gap:.3f}°C")
    print(f"완료 {time.time() - t0:.1f}초")


if __name__ == "__main__":
    main()
