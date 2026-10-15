"""H1. 얼마나: "활동 기반으로 세면 1인당 노출이 달라질 것이다" (보고서 2장 H1, 1.4절, 2.6–2.7절)

계산 (단위마다)
  per_capita   연령별 1인당 연간 노출(°C·시간/년)의 거주 기준·활동 기준, Gap(%), 시간당 차이(°C), 재배치 효과(%)
               노출 = Σ ΔT × 인시 ÷ 서울 인구, 2024·2025년 평균. 재배치 효과 = Σ_조건 A·(d̄_A − d̄_R) (조건 = 연도 × 계절 × 주야)
  anchor       생활인구 보정 기준(24시간·야간·주간 평균을 인구총조사에 맞춤)별 Gap 과 재배치 효과
  placement    인구총조사 배치 대비 생활인구 배치의 비유사도(%), 16조건 평균, 낮·밤
  cancel       이동의 열 효과 네 유형(더운 곳으로 유입, 시원한 곳에서 유출, 시원한 곳으로 유입, 더운 곳에서 유출),
               크기 합, 순효과, 상쇄율 (그림 B). 구간 평균 ΔT 기준
  extremes     가장 더운·시원한 10% 단위(자치구는 5곳)에 있는 인시 비중, 거주 → 활동

기대값 (집계구, 보고서와 같음): 15–64세 13,020 → 12,784 (−1.8%, −0.027°C), 재배치 효과 −1.0%;
  배치 차이 낮 43% · 밤 34%; 낮 크기 0.233°C, 상쇄율 90%; 가장 더운 10% 9.8 → 8.4%

실행: .venv/bin/python -m rq1_modules.H1_how_much [--scale=tract|dong|gu|all]
"""
import sys
import numpy as np, pandas as pd
from rq1_modules.common import (AGES, GROUPS, AGE_KO, SCALE_KO, TOPK, build_panel, load_census, to_units, dissimilarity, parse_scales, save)

COLS = [f"P{x}_{g}" for g in GROUPS for x in ("A", "R")]


def per_capita(M, scale):
    tot = load_census().sum()
    U = to_units(M, scale, COLS); U["period"] = np.where(U.hour.isin({21, 22, 23, 0, 1, 2, 3, 4, 5, 6}), "night", "day")
    acc = {g: dict(act=0.0, res=0.0, redis=0.0) for g in GROUPS}
    for _, q in U.groupby(["year", "season", "period"]):
        for g in GROUPS:
            A, R = q[f"PA_{g}"].sum(), q[f"PR_{g}"].sum(); EA, ER = (q.dT * q[f"PA_{g}"]).sum(), (q.dT * q[f"PR_{g}"]).sum()
            acc[g]["act"] += EA / tot[g] / 2; acc[g]["res"] += ER / tot[g] / 2; acc[g]["redis"] += A * (EA / A - ER / R) / tot[g] / 2
    out = {}
    for g, d in acc.items():
        out[g] = dict(residence=d["res"], activity=d["act"], gap_pct=100 * (d["act"] - d["res"]) / d["res"],
                      per_hour=(d["act"] - d["res"]) / 8760, redis_pct=100 * d["redis"] / d["res"])
    return out


def period_frame(M, scale):
    U = to_units(M, scale, ["PA_all", "PR_all"]); U["period"] = np.where(U.hour.isin({21, 22, 23, 0, 1, 2, 3, 4, 5, 6}), "night", "day")
    return U.groupby(["u", "year", "season", "period"]).agg(PA=("PA_all", "sum"), PR=("PR_all", "sum"), tau=("dT", "mean")).reset_index()


def placement_cancel_extremes(M, scale):
    k = TOPK[scale]; rows = []
    for (y, se, p), g in period_frame(M, scale).groupby(["year", "season", "period"]):
        g = g.set_index("u"); wA, wR = g.PA / g.PA.sum(), g.PR / g.PR.sum(); t = g.tau
        dR = (wR * t).sum(); c = (wA - wR) * (t - dR); dw = wA - wR; warm = t > dR
        q = {"in_warm": (dw > 0) & warm, "out_cool": (dw < 0) & ~warm, "in_cool": (dw > 0) & ~warm, "out_warm": (dw < 0) & warm}
        hot, cool = t >= t.quantile(1 - k), t <= t.quantile(k)
        rows.append(dict(period=p, D=dissimilarity(g.PA, g.PR), gross=c.abs().sum(), net=c.sum(), cancel=1 - abs(c.sum()) / c.abs().sum(),
                         **{f"c_{n}": c[m].sum() for n, m in q.items()}, **{f"w_{n}": 100 * dw[m].abs().sum() for n, m in q.items()},
                         hot_R=100 * wR[hot].sum(), hot_A=100 * wA[hot].sum(), cool_R=100 * wR[cool].sum(), cool_A=100 * wA[cool].sum()))
    return pd.DataFrame(rows).groupby("period").mean().to_dict("index")


def run(scales=("tract", "dong", "gu"), anchors=("24h", "night", "day"), verbose=True):
    out = {s: {} for s in scales}
    panels = {a: build_panel(anchor=a) for a in anchors}
    for s in scales:
        out[s]["per_capita"] = per_capita(panels["24h"], s)
        out[s]["anchor"] = {a: {g: {k: v for k, v in d.items() if k in ("gap_pct", "redis_pct")} for g, d in per_capita(panels[a], s).items()} for a in anchors}
        out[s]["period"] = placement_cancel_extremes(panels["24h"], s)
    if verbose: report(out)
    save(out, "H1_how_much")
    return out


def report(out):
    for s, o in out.items():
        print(f"\n=== H1 얼마나 · {SCALE_KO[s]} ===")
        print("연령 | 거주 기반 | 활동 기반 | 차이 | 시간당 | 재배치 효과")
        for g in GROUPS:
            d = o["per_capita"][g]
            print(f"{AGE_KO[g]} | {d['residence']:,.0f} | {d['activity']:,.0f} | {d['gap_pct']:+.1f}% | {d['per_hour']:+.3f}°C | {d['redis_pct']:+.1f}%")
        print("보정 기준별 15–64세 Gap (재배치 효과):", "  ".join(f"{a} {v['a15_64']['gap_pct']:+.1f}% ({v['a15_64']['redis_pct']:+.1f}%)" for a, v in o["anchor"].items()))
        for p in ("day", "night"):
            d = o["period"][p]
            print(f"[{p}] 배치 차이 {d['D']:.1f}% | 올린 {d['c_in_warm'] + d['c_out_cool']:+.3f} 내린 {d['c_in_cool'] + d['c_out_warm']:+.3f} "
                  f"크기 {d['gross']:.3f} 순 {d['net']:+.3f}°C 상쇄율 {100 * d['cancel']:.0f}% | 가장 더운 곳 {d['hot_R']:.1f} → {d['hot_A']:.1f}%, 가장 시원한 곳 {d['cool_R']:.1f} → {d['cool_A']:.1f}%")


if __name__ == "__main__":
    run(parse_scales(sys.argv))
