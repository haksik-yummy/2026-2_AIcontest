"""LightGBM과 로지스틱 회귀의 차이가 시드와 날짜 표집을 넘어서는지 잽니다. 학습 지점만 쓰고 검증 지점은 쓰지 않습니다.

실행: python scripts/check_icing_models.py   (약 5분, 노트북 04-1까지 실행한 뒤)
입력: data/processed/ 의 station_features, station_estimates, icing_cv.json, icing_oof.parquet
출력: data/results/icing_model_check.csv 와 화면 출력. 노트북 04-1의 1장, 04-2의 2-2가 이 결과를 인용합니다.

일별 F1의 임계값은 묶음마다 나머지 지점으로 고릅니다. 구간은 날짜 단위 부트스트랩의 95% 구간입니다 (일별 F1 1,000회, AP 500회).
"""
import json
import sys
import time
import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config  # noqa: E402

warnings.filterwarnings("ignore")
SEEDS = (42, 1, 2, 3, 4)
POS_W = 5
LGBM = "LightGBM(결빙관련 라벨)"
LOGIT = "로지스틱 회귀(결빙관련 라벨)"
QUANTILES = (0.95, 0.98, 0.99, 0.995, 0.998, 0.999, 0.9995, 0.9998)


class Data:
    """학습 지점 자료와 일별 F1 계산에 쓰는 지점-날 배열입니다."""

    def __init__(self):
        sf = pd.read_parquet(config.PROCESSED_DIR / "station_features.parquet")
        sf = sf.merge(pd.read_parquet(config.PROCESSED_DIR / "station_estimates.parquet"), on=["stn", "time"])
        sf["rst_dpd"] = sf["rst_est"] - sf["td"]
        cv = json.loads((config.PROCESSED_DIR / "icing_cv.json").read_text(encoding="utf-8"))
        self.features, self.folds = cv["features"], cv["folds"]
        sf["related"] = sf["state"].isin(cv["related_states"]).astype("float32").where(sf["state"].notna())
        self.train = sf[~sf["stn"].isin(config.HOLDOUT_STATIONS)].reset_index(drop=True)
        self.stns = sorted(self.train["stn"].unique())
        self.pos = {s: i for i, s in enumerate(self.stns)}
        self.oof = pd.read_parquet(config.PROCESSED_DIR / "icing_oof.parquet")
        assert self.oof["stn"].equals(self.train["stn"]) and self.oof["time"].equals(self.train["time"])

        self.labeled = self.train["ice"].notna().to_numpy()
        t = self.train[self.labeled]
        self.dates = pd.factorize(self.train["time"].dt.normalize())[0]
        self.key, _ = pd.factorize(t["stn"].astype(str) + "_" + t["time"].dt.strftime("%Y%m%d"))
        self.day_stn = np.zeros(self.key.max() + 1, int)
        self.day_stn[self.key] = t["stn"].map(self.pos).to_numpy()
        self.day_date = np.zeros(self.key.max() + 1, int)
        self.day_date[self.key] = self.dates[self.labeled]
        self.y = t["ice"].astype(int).to_numpy()
        self.has_ice = np.bincount(self.day_stn, np.bincount(self.key, self.y), len(self.stns)) > 0

    def day_f1(self, pred):
        """지점-날별 F1과 평가 대상 여부를 돌려줍니다. 실제·예측 결빙이 모두 없는 날은 평가에서 뺍니다."""
        p = np.asarray(pred)[self.labeled].astype(int)
        tp = np.bincount(self.key, self.y & p)
        fp = np.bincount(self.key, (1 - self.y) & p)
        fn = np.bincount(self.key, self.y & (1 - p))
        den = 2 * tp + fp + fn
        return np.where(den > 0, 2 * tp / np.maximum(den, 1), 0.0), den > 0

    def mean_f1(self, f1, evaluated, idx=None, weight=None):
        """실제 결빙이 있는 지점의 일별 F1 평균을 지점별로 평균합니다. weight는 날짜 가중치(부트스트랩)입니다."""
        w = evaluated * (1.0 if weight is None else weight[self.day_date])
        num = np.bincount(self.day_stn, f1 * w, len(self.stns))
        den = np.bincount(self.day_stn, w, len(self.stns))
        per_stn = np.where((den > 0) & self.has_ice, num / np.where(den > 0, den, 1), np.nan)
        return np.nanmean(per_stn if idx is None else per_stn[idx])

    def best_threshold(self, prob, idx=None):
        cands = np.unique(np.quantile(prob[~np.isnan(prob)], QUANTILES))
        scores = [self.mean_f1(*self.day_f1(prob >= c), idx) for c in cands]
        return cands[int(np.argmax(scores))], max(scores)

    def nested_pred(self, prob):
        """묶음마다 나머지 지점으로 임계값을 골라 그 묶음에 적용합니다."""
        pred = np.zeros(len(self.train), bool)
        for fold in self.folds:
            idx = np.array([self.pos[s] for s in self.stns if s not in fold])
            threshold, _ = self.best_threshold(prob, idx)
            rows = self.train["stn"].isin(fold).to_numpy()
            pred[rows] = prob[rows] >= threshold
        return pred


def make_lgbm(seed):
    return lgb.LGBMClassifier(objective="binary", learning_rate=0.03, n_estimators=400, num_leaves=15, min_child_samples=200,
                              subsample=0.7, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0, n_jobs=-1, verbose=-1,
                              random_state=seed, scale_pos_weight=POS_W)


def make_logit():
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         LogisticRegression(C=0.1, class_weight={0: 1, 1: POS_W}, max_iter=2000))


def cv_prob(data, make):
    """지점 단위 7묶음 교차검증 확률입니다."""
    train, feats = data.train, data.features
    usable = train["related"].notna().to_numpy()
    prob = np.full(len(train), np.nan)
    for fold in data.folds:
        rows = train["stn"].isin(fold).to_numpy()
        fit = train[~rows & usable]
        prob[rows] = make().fit(fit[feats], fit["related"].astype(int)).predict_proba(train.loc[rows, feats])[:, 1]
    return prob


def other_winter_prob(data, make):
    """다른 지점의 다른 겨울로만 학습한 확률입니다."""
    train, feats = data.train, data.features
    usable = train["related"].notna().to_numpy()
    second = (train["time"] >= pd.Timestamp(config.PERIODS[1][0])).to_numpy()
    prob = np.full(len(train), np.nan)
    for fold in data.folds:
        rows = train["stn"].isin(fold).to_numpy()
        for winter in (False, True):
            test = rows & (second == winter)
            fit = train[~rows & (second != winter) & usable]
            prob[test] = make().fit(fit[feats], fit["related"].astype(int)).predict_proba(train.loc[test, feats])[:, 1]
    return prob


def weighted_ap(prob, y, date_index, weight):
    """날짜 가중치를 준 Average Precision입니다. 같은 확률은 한 임계값으로 묶어서 sklearn의 식과 같습니다."""
    order = np.argsort(-prob, kind="stable")
    w, ys = weight[date_index[order]].astype(float), y[order]
    tp, fp = np.cumsum(w * ys), np.cumsum(w * (1 - ys))
    last = np.r_[np.flatnonzero(np.diff(prob[order])), len(order) - 1]
    tp, fp = tp[last], fp[last]
    return float(np.sum(np.diff(np.r_[0, tp / tp[-1]]) * tp / np.maximum(tp + fp, 1e-12)))


def interval(d):
    return f"{np.mean(d):+.4f} [{np.quantile(d, 0.025):+.4f}, {np.quantile(d, 0.975):+.4f}]"


def main():
    t0 = time.time()
    data = Data()
    n_dates = data.dates.max() + 1
    rng = np.random.default_rng(42)
    boot = np.stack([np.bincount(rng.integers(0, n_dates, n_dates), minlength=n_dates) for _ in range(1000)])
    y_ice = data.y
    logit = data.oof[LOGIT].to_numpy()
    logit_day = data.day_f1(data.nested_pred(logit))

    rows, lgbm_days, probs = [], {}, {}
    for seed in SEEDS:
        prob = cv_prob(data, lambda: make_lgbm(seed))
        probs[seed] = prob
        lgbm_days[seed] = data.day_f1(data.nested_pred(prob))
        rank = pd.DataFrame({"a": prob, "b": logit}).rank(pct=True).mean(axis=1).to_numpy()
        rows.append({"시드": seed, "LightGBM 일별 F1(묶음 밖 임계값)": data.mean_f1(*lgbm_days[seed]),
                     "LightGBM 일별 F1(전체 임계값)": data.best_threshold(prob)[1],
                     "LightGBM AP(Ice)": average_precision_score(y_ice, prob[data.labeled]),
                     "순위 평균 일별 F1(묶음 밖 임계값)": data.mean_f1(*data.day_f1(data.nested_pred(rank))),
                     "순위 평균 AP(Ice)": average_precision_score(y_ice, rank[data.labeled])})
        print(f"시드 {seed}: {time.time() - t0:.0f}초", flush=True)
    table = pd.DataFrame(rows).set_index("시드")
    table.loc["평균"] = table.mean()
    table["로지스틱 일별 F1(묶음 밖 임계값)"] = data.mean_f1(*logit_day)
    table["로지스틱 AP(Ice)"] = average_precision_score(y_ice, logit[data.labeled])
    print(table.round(4).T.to_string())
    table.round(4).to_csv(config.RESULT_DIR / "icing_model_check.csv", encoding="utf-8-sig")

    logit_boot = np.array([data.mean_f1(*logit_day, weight=w) for w in boot])
    lgbm_boot = np.array([np.mean([data.mean_f1(*lgbm_days[s], weight=w) for s in SEEDS]) for w in boot])
    print("\n로지스틱 - LightGBM(시드 5개 평균) 일별 F1:", interval(logit_boot - lgbm_boot))

    rows_rel = data.train["related"].notna().to_numpy()
    related = data.train.loc[rows_rel, "related"].astype(int).to_numpy()
    date_rel = data.dates[rows_rel]
    p_lgbm = data.oof[LGBM].to_numpy()
    assert abs(weighted_ap(p_lgbm[rows_rel], related, date_rel, np.ones(n_dates))
               - average_precision_score(related, p_lgbm[rows_rel])) < 1e-9
    d = [weighted_ap(p_lgbm[rows_rel], related, date_rel, w) - weighted_ap(logit[rows_rel], related, date_rel, w) for w in boot[:500]]
    print("LightGBM - 로지스틱 AP(결빙관련):", interval(d))

    other_lgbm, other_logit = other_winter_prob(data, lambda: make_lgbm(42)), other_winter_prob(data, make_logit)
    d = [weighted_ap(other_lgbm[rows_rel], related, date_rel, w) - weighted_ap(other_logit[rows_rel], related, date_rel, w)
         for w in boot[:500]]
    print("LightGBM - 로지스틱 다른 겨울 AP(결빙관련):", interval(d))
    print(f"완료 {time.time() - t0:.0f}초")


if __name__ == "__main__":
    main()
