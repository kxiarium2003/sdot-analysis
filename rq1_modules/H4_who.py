"""H4. 누가: 연령("출퇴근하는 연령에서 차이가 클 것이다")과 SES("저지가 지역 주민이 활동 기준에서 더 노출될 것이다")
(보고서 2장 H4, 2.7절 결과 9·10, 그림 G)

계산 (단위마다)
  age          연령별 노출 순위 상관과 상위 10%(자치구는 5곳) 일치, 16조건 평균
  ses          공시지가 5분위(15–64세, 2024·2025 여름 낮): 분위별 주민·낮 체류 인구(만 명, 시간 평균), 체류 ÷ 주민,
               주민 기준 ΔT, 체류 인구 기준 ΔT, Q1 ÷ Q5 노출 비(거주 → 활동) = 온도 비 × 낮 인구 비 × 낮의 온도 변화
               집계구 분위는 zone_ses.parquet 의 q_landprice(집계구 수 기준 5분위).
               행정동·자치구는 거주 인구 가중 평균 공시지가로 단위 수가 같게 나누고, ΔT 는 단위 평균을 쓴다.
기대값 (집계구): 연령 순위 상관 0–14세 0.24, 15–64세 0.44, 65세 이상 0.37; SES Q1/Q5 0.86 → 0.35 = 0.86 × 0.47 × 0.87
실행: .venv/bin/python -m rq1_modules.H4_who [--scale=...]
"""
import sys
import numpy as np, pandas as pd
from rq1_modules.common import (AGES, GROUPS, AGE_KO, SCALE_KO, TOPK, P, build_panel, load_census, unit_of, unit_exposure, top_overlap, rho,
                                parse_scales, save)


def age_rank(M, scale):
    E = unit_exposure(M, scale, groups=GROUPS); rows = []
    for _, g in E.groupby(["year", "season", "period"]):
        g = g.set_index("u")
        rows.append({**{a: rho(g[f"EA_{a}"], g[f"ER_{a}"]) for a in GROUPS}, **{f"top_{a}": top_overlap(g[f"EA_{a}"], g[f"ER_{a}"], TOPK[scale]) for a in GROUPS}})
    return pd.DataFrame(rows).mean().to_dict()


def ses(M, scale, age="a15_64"):
    S = M[(M.season == "summer") & (M.period == "day")]
    hours = S.groupby("year").apply(lambda g: g.n_days.max() * g.hour.nunique(), include_groups=False).sum()
    D = S.assign(EA=S.dT * S[f"PA_{age}"], ER=S.dT * S[f"PR_{age}"], dw=S.dT * S.res_all).groupby("tract16").agg(
        PA=(f"PA_{age}", "sum"), PR=(f"PR_{age}", "sum"), EA=("EA", "sum"), ER=("ER", "sum"), dw=("dw", "sum"), w=("res_all", "sum")).reset_index()
    z = pd.read_parquet(P["ses"])[["tract16", "landprice_2024", "q_landprice"]]
    D = D.merge(z, on="tract16", how="left"); D["res"] = load_census()[age].reindex(D.tract16).values
    D["u"] = unit_of(D.tract16, scale); D["lpw"] = D.landprice_2024 * D.res
    U = D.groupby("u").agg(PA=("PA", "sum"), PR=("PR", "sum"), EA=("EA", "sum"), ER=("ER", "sum"), dw=("dw", "sum"), w=("w", "sum"),
                           lpw=("lpw", "sum"), res=("res", "sum"), q0=("q_landprice", "first"))
    U["lp"] = U.lpw / U.res
    if scale == "tract": U["q"] = U.q0
    else:
        U["q"] = pd.qcut(U.lp.rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
        U["dT"] = U.dw / U.w; U["EA"] = U.PA * U.dT; U["ER"] = U.PR * U.dT          # 단위 평균 ΔT
    Q = U.dropna(subset=["q"]).groupby("q").agg(n=("PA", "size"), PA=("PA", "sum"), PR=("PR", "sum"), EA=("EA", "sum"), ER=("ER", "sum"),
                                                 lp_min=("lp", "min"), lp_max=("lp", "max"))
    Q.index = Q.index.astype(int)
    Q["res_10k"] = Q.PR / hours / 1e4; Q["day_10k"] = Q.PA / hours / 1e4; Q["ratio"] = Q.PA / Q.PR
    Q["dT_R"] = Q.ER / Q.PR; Q["dT_A"] = Q.EA / Q.PA
    q1, q5 = Q.loc[1], Q.loc[5]
    dec = dict(residence=(q1.ER / q1.PR) / (q5.ER / q5.PR), activity=(q1.EA / q1.PR) / (q5.EA / q5.PR),
               heat=q1.dT_R / q5.dT_R, pop=q1.ratio / q5.ratio, heat_shift=(q1.dT_A / q1.dT_R) / (q5.dT_A / q5.dT_R))
    return dict(quintiles=Q[["n", "lp_min", "lp_max", "res_10k", "day_10k", "ratio", "dT_R", "dT_A"]].round(4).to_dict("index"), q1_q5=dec)


def run(scales=("tract", "dong", "gu"), verbose=True):
    M = build_panel()
    out = {s: dict(age=age_rank(M, s), ses=ses(M, s)) for s in scales}
    if verbose:
        for s, o in out.items():
            print(f"\n=== H4 누가 · {SCALE_KO[s]} ===")
            print("연령 노출 순위 상관 / 상위 일치: " + "  ".join(f"{AGE_KO[a]} {o['age'][a]:.2f} / {o['age']['top_' + a]:.0f}%" for a in GROUPS))
            print("분위 | 공시지가(만원/m²) | 주민(만) | 낮 체류(만) | 체류 ÷ 주민 | 주민 기준 ΔT | 체류 기준 ΔT")
            for q, d in o["ses"]["quintiles"].items():
                print(f"Q{q} | {d['lp_min']/1e4:.0f}–{d['lp_max']/1e4:.0f} | {d['res_10k']:.1f} | {d['day_10k']:.1f} | {d['ratio']:.2f} | {d['dT_R']:.2f} | {d['dT_A']:.2f}")
            d = o["ses"]["q1_q5"]
            print(f"Q1 ÷ Q5 노출 비: 거주 {d['residence']:.2f} → 활동 {d['activity']:.2f} = 온도 비 {d['heat']:.2f} × 낮 인구 비 {d['pop']:.2f} × 낮의 온도 변화 {d['heat_shift']:.2f}")
    save(out, "H4_who")
    return out


if __name__ == "__main__":
    run(parse_scales(sys.argv))
