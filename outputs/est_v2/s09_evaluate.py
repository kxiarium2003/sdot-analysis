"""s09_evaluate.py - C-1 평가. 인자: units (예 'station_month,station_hour' 또는 'cell').

단위: station_month(① 역×월), station_hour(② 역×시간대(월 평균)), cell(③ 역×날짜×시).
- 모든 예측이 있는 칸(공통 표본)만 사용. 집계 단위에서 비율은 실제 승차로 가중.
- 실제 로짓은 경험 로짓 log((k+.5)/(n-k+.5)), 예측 로짓은 0.001~0.999로 자른 뒤 계산.
출력: s09_metrics_<unit>.csv, s09_monthly_<unit>.csv, s09_transfer_<unit>.csv, s09_worst_stations.csv
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd
from scipy.stats import spearmanr

P = pd.read_parquet(SCRATCH / "eval/panel.parquet")
PRED = ["P0_m0", "P0_m3", "P1_m0", "P1_m3", "P1ns_m0", "P1ns_m3", "P2_300", "P2_500", "P2_300_m3", "P2_500_m3"]
units = sys.argv[1].split(",")
P = P[P.n_tot > 0].copy()
ok = P[PRED].notna().all(axis=1)
print("전체 칸", len(P), "공통표본", int(ok.sum()), "역", P[ok].bldn.nunique(), "날짜", P[ok].date.nunique())
C = P[ok].copy()


def logit(p):
    p = np.clip(p, 1e-3, 1 - 1e-3)
    return np.log(p / (1 - p))


def emp(k, n):
    return np.log((k + .5) / (n - k + .5))


def ols(x, y):
    X = np.column_stack([np.ones(len(x)), x])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    return b[0], b[1]


def fit_metrics(x, y):
    a, b = ols(x, y)
    pred = a + b * x
    r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return a, b, r2


def aggregate(df, keys):
    agg = {"n65": "sum", "n_tot": "sum"}
    g = df.groupby(keys).agg(agg)
    for p in PRED:
        g[p] = (df[p] * df.n_tot).groupby([df[k] for k in keys]).sum() / df.n_tot.groupby([df[k] for k in keys]).sum()
    g = g.reset_index()
    return g


def spatial_cv(d, p):
    x, y = logit(d[p].to_numpy()), emp(d.n65.to_numpy(), d.n_tot.to_numpy())
    oof = np.full(len(d), np.nan)
    for gu in d.gu_final.unique():
        m = d.gu_final.to_numpy() == gu
        a, b = ols(x[~m], y[~m]); oof[m] = a + b * x[m]
    return oof, x, y


def evaluate(d, unit):
    rows = []
    for p in PRED:
        x = logit(d[p].to_numpy()); y = emp(d.n65.to_numpy(), d.n_tot.to_numpy())
        rho = spearmanr(d[p].to_numpy(), d.n65.to_numpy() / d.n_tot.to_numpy()).statistic
        a, b, r2 = fit_metrics(x, y)
        oof, _, _ = spatial_cv(d, p)
        rows.append(dict(단위=unit, 예측=p, N=len(d), 스피어만=rho, 로짓RMSE=float(np.sqrt(((x - y) ** 2).mean())), 절편=a, 기울기=b, R2=r2,
                         CV_RMSE=float(np.sqrt(((oof - y) ** 2).mean())), CV_R2=1 - ((y - oof) ** 2).sum() / ((y - y.mean()) ** 2).sum(), CV_스피어만=spearmanr(oof, y).statistic))
    return pd.DataFrame(rows)


meta = C.drop_duplicates("bldn")[["bldn", "name", "route", "gu_final"]]
for unit in units:
    if unit == "station_month":
        d = aggregate(C, ["bldn", "gu_final", "ym"])
    elif unit == "station_hour":
        d = aggregate(C, ["bldn", "gu_final", "ym", "hour"])
    elif unit == "cell":
        d = C[C.n_tot >= 10].copy()
    print(unit, len(d), flush=True)
    m = evaluate(d, unit); m.to_csv(OUT / f"s09_metrics_{unit}.csv", index=False, encoding="utf-8-sig"); print(m.round(3).to_string())
    mo, tr = [], []
    for p in PRED:
        for ym, x in d.groupby("ym"):
            xx = logit(x[p].to_numpy()); yy = emp(x.n65.to_numpy(), x.n_tot.to_numpy()); a, b, r2 = fit_metrics(xx, yy)
            mo.append(dict(단위=unit, 예측=p, ym=ym, N=len(x), 스피어만=spearmanr(x[p], x.n65 / x.n_tot).statistic, 로짓RMSE=float(np.sqrt(((xx - yy) ** 2).mean())), 기울기=b, R2=r2))
        y24 = d[d.ym.str.startswith("2024")]; y25 = d[d.ym.str.startswith("2025")]
        x24, yy24 = logit(y24[p].to_numpy()), emp(y24.n65.to_numpy(), y24.n_tot.to_numpy())
        x25, yy25 = logit(y25[p].to_numpy()), emp(y25.n65.to_numpy(), y25.n_tot.to_numpy())
        a, b = ols(x24, yy24); pr = a + b * x25
        tr.append(dict(단위=unit, 예측=p, 학습N=len(y24), 평가N=len(y25), 절편=a, 기울기=b, 평가_RMSE=float(np.sqrt(((pr - yy25) ** 2).mean())), 평가_R2=1 - ((yy25 - pr) ** 2).sum() / ((yy25 - yy25.mean()) ** 2).sum(), 평가_스피어만=spearmanr(pr, yy25).statistic))
    pd.DataFrame(mo).to_csv(OUT / f"s09_monthly_{unit}.csv", index=False, encoding="utf-8-sig"); pd.DataFrame(tr).to_csv(OUT / f"s09_transfer_{unit}.csv", index=False, encoding="utf-8-sig")
    print(pd.DataFrame(tr).round(3).to_string())
    if unit == "station_month":
        ws = []
        for p in ["P1_m0", "P1_m3", "P2_300", "P2_500", "P0_m0"]:
            oof, x, y = spatial_cv(d, p)
            e = d.assign(res=y - oof, pred=np.exp(oof) / (1 + np.exp(oof)), actual=d.n65 / d.n_tot)
            g = e.groupby("bldn").agg(평균잔차=("res", "mean"), 절대잔차=("res", lambda v: np.abs(v).mean()), 실제=("actual", "mean"), 예측=("pred", "mean"), 승차=("n_tot", "sum")).reset_index().sort_values("절대잔차", ascending=False).head(10)
            ws.append(g.assign(방법=p))
        w = pd.concat(ws).merge(meta, on="bldn", how="left")
        w.to_csv(OUT / "s09_worst_stations.csv", index=False, encoding="utf-8-sig"); print(w.round(3).to_string())
