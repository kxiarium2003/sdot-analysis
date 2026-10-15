"""S5. 외국인 포함 재분석 (보고서 5.1.1, 2.7절 결과 12)

인구총조사(SGIS 서울 933.5만)는 내국인 + 3개월 이상 거주 외국인이다. 생활인구 설계 세 가지로 다시 계산한다(전 연령, 외국인 자료에 연령 없음).
  A  내국인만 (연령별로 인구총조사에 맞춤, 주 분석)
  B  내국인 + 장기 체류 외국인 (합쳐서 인구총조사 합계에 맞춤, 인구총조사와 같은 대상)
  C  B + 단기 체류 외국인 (보정 없이 더함)
외국인 자료가 빈 날(2025-07-08·09)은 그 계절의 외국인 일평균을 나머지 날로 계산한다.
계산 (단위마다): 1인당 Gap 과 재배치 효과(2년 전체를 한 번에), 16조건 평균 순위 상관, 여름 낮 상위 10%(자치구 5곳) 일치(연도 평균)
기대값 (집계구): Gap A −1.4%, B −0.9%, C +0.9%; 재배치 효과 −1.2, −1.0, −0.9%; 순위 상관 0.42; 상위 일치 38–39%
실행: .venv/bin/python -m rq1_modules.S5_foreigner [--scale=...]
"""
import sys
import numpy as np, pandas as pd
from rq1_modules.common import (AGES, SCALE_KO, TOPK, NIGHT, P, load_census, load_field, load_livingpop, unit_of, top_overlap, rho, parse_scales, save)


def panel():
    Z = load_field(); raw = load_livingpop(raw=True); res = load_census(); tot = res["all"].sum()
    sc = pd.read_csv(P["livingpop"].parent / "age_scale.csv").set_index("year")       # 24시간 평균 보정 배율 (load_livingpop 과 같음)
    FO = pd.read_parquet(P["foreigner"]).rename(columns={"tract": "tract16", "summer": "year", "n_days": "n_days_fo"})
    Xs = []
    for y in (2024, 2025):
        X = raw[raw.year == y][["tract16", "year", "season", "hour", "n_days"] + AGES].merge(
            FO[FO.year == y][["tract16", "season", "hour", "long_term", "short_term", "n_days_fo"]], on=["tract16", "season", "hour"], how="left")
        X["n_days_fo"] = X.n_days_fo.fillna(X.n_days)
        for c in ("long_term", "short_term"): X[c] = X[c].fillna(0.0) * X.n_days / X.n_days_fo
        X = X.merge(Z[Z.year == y], on=["tract16", "year", "season", "hour"]).merge(res["all"].rename("res_all"), left_on="tract16", right_index=True)
        hours = 24 * X.groupby("season").n_days.max().sum(); rn = X[AGES].sum(1)
        X["A"] = sum(X[a] * sc.loc[y, a] for a in AGES)
        X["B"] = (rn + X.long_term) * (tot / ((rn + X.long_term).sum() / hours)); X["C"] = X.B + X.short_term
        X["R"] = X.res_all * X.n_days
        Xs.append(X[["tract16", "year", "season", "hour", "dT_hat", "res_all", "A", "B", "C", "R"]])
    X = pd.concat(Xs).rename(columns={"dT_hat": "dT"}); X["period"] = np.where(X.hour.isin(NIGHT), "night", "day")
    return X


def evaluate(X, scale):
    m = X.assign(u=unit_of(X.tract16, scale), dw=X.dT * X.res_all)
    U = m.groupby(["u", "year", "season", "hour"]).agg(A=("A", "sum"), B=("B", "sum"), C=("C", "sum"), R=("R", "sum"), dw=("dw", "sum"), w=("res_all", "sum"), dm=("dT", "mean")).reset_index()
    U["dTu"] = np.where(U.w > 0, U.dw / U.w.where(U.w > 0, 1), U.dm)
    E = m.assign(**{f"E{v}": m.dT * m[v] for v in "ABCR"}).groupby(["u", "year", "season", "period"])[["EA", "EB", "EC", "ER"]].sum()
    out = {}
    for v in "ABC":
        A, R = U[v].sum(), U.R.sum(); ea, er = (U.dTu * U[v]).sum(), (U.dTu * U.R).sum()
        r = np.mean([rho(g[f"E{v}"], g.ER) for _, g in E.groupby(level=[1, 2, 3])])
        S = E.xs(("summer", "day"), level=("season", "period"))
        top = np.mean([top_overlap(g.droplevel(1)[f"E{v}"], g.droplevel(1).ER, TOPK[scale]) for _, g in S.groupby(level=1)])
        out[v] = dict(gap_pct=100 * (ea - er) / er, redis_pct=100 * A * (ea / A - er / R) / er, rho=r, top=top)
    return out


def run(scales=("tract", "dong", "gu"), verbose=True):
    X = panel(); out = {s: evaluate(X, s) for s in scales}
    if verbose:
        for s, o in out.items():
            print(f"\n=== S5 외국인 포함 · {SCALE_KO[s]} ===")
            for v, d in o.items(): print(f"설계 {v}: Gap {d['gap_pct']:+.1f}% | 재배치 효과 {d['redis_pct']:+.1f}% | 순위 상관 {d['rho']:.2f} | 상위 일치 {d['top']:.0f}%")
    save(out, "S5_foreigner")
    return out


if __name__ == "__main__":
    run(parse_scales(sys.argv))
