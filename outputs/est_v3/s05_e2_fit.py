"""s05_e2_fit.py - E2: 지하철 eval_panel에서 logit(실제)=a+b·logit(P1) 적합(m0, m3). P1+P2 300m 참고 실험.

표본: est_v2 s09와 같은 공통 표본(n_tot>0, 모든 예측 있음), 역×날짜×시, n_tot>=10. 실제 로짓은 경험 로짓, 예측 로짓은 0.001~0.999.
CV는 자치구(gu_final) 단위. 참고 실험 결과는 버스에 적용하지 않는다.
출력: s05_e2_params.csv
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd
from scipy.stats import spearmanr

P = pd.read_parquet(SCRATCH / "raw/eval/eval_panel.parquet")
PRED = ["P0_m0", "P0_m3", "P1_m0", "P1_m3", "P1ns_m0", "P1ns_m3", "P2_300", "P2_500", "P2_300_m3", "P2_500_m3"]
P = P[P.n_tot > 0]; C = P[P[PRED].notna().all(axis=1) & (P.n_tot >= 10)].copy()
print("표본", len(C), C.bldn.nunique(), C.date.nunique())
lg = lambda p: np.log(np.clip(p, 1e-3, 1 - 1e-3) / (1 - np.clip(p, 1e-3, 1 - 1e-3)))
y = np.log((C.n65 + .5) / (C.n_tot - C.n65 + .5)).to_numpy()
gu = C.gu_final.to_numpy()


def ols(X, y):
    return np.linalg.lstsq(np.column_stack([np.ones(len(X)), X]), y, rcond=None)[0]


def r2(y, p):
    return 1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum()


def fit(Xcols, tag):
    X = np.column_stack(Xcols)
    b = ols(X, y); pred = b[0] + X @ b[1:]
    oof = np.full(len(y), np.nan)
    for g in np.unique(gu):
        m = gu == g; bb = ols(X[~m], y[~m]); oof[m] = bb[0] + X[m] @ bb[1:]
    return dict(모형=tag, N=len(y), a=b[0], b=b[1], c=b[2] if len(b) > 2 else np.nan, R2=r2(y, pred), CV_R2=r2(y, oof), CV_RMSE=float(np.sqrt(((y - oof) ** 2).mean())), CV_스피어만=spearmanr(oof, y).statistic)


rows = []
for m in ("m0", "m3"):
    x = lg(C[f"P1_{m}"].to_numpy())
    rows.append(fit([x], f"P1_{m}"))
    rows.append(fit([x, lg(C["P2_300"].to_numpy())], f"P1_{m}+P2_300(참고)"))
out = pd.DataFrame(rows); out.to_csv(OUT / "s05_e2_params.csv", index=False, encoding="utf-8-sig")
print(out.round(4).to_string())
