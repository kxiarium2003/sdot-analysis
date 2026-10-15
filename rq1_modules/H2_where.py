"""H2. 어디서: "노출이 몰리는 장소는 두 기준에서 다를 것이다" (보고서 2장 H2, 2.6–2.7절, 그림 D·E·J·L)

장소의 노출 총량 = 단위 안 집계구 노출(집계구 ΔT × 인구)의 합. 두 기준에 같은 ΔT 를 곱하므로 차이는 인구 배치에서 나온다.
계산 (단위마다)
  overall      16조건(연도 × 계절 × 주야) 평균: 노출 순위 상관, 상위 1·5·10·20% 일치, 다른 단위로 옮겨 배정되는 노출 비중(노출 비유사도),
               노출비(활동 ÷ 거주) 중앙값·상위 5%
  summer       2024·2025 여름 낮·밤: 순위 상관, 상위 10% 일치, 노출 비유사도 (연도 평균)
  decomposition  2025 여름 상위 k% 일치의 분해(그림 E·L): 인구총조사 vs 14시(이동 + 자료 차이), 인구총조사 vs 03시(자료 차이만), 03시 vs 14시(이동만)
  ranking      자치구 순위표(여름 낮, 2년 합): 활동·거주 비중과 순위, 노출비, 인구비 / 행정동 상위 10(두 기준)
기대값 (집계구): 순위 상관 0.41, 상위 1/5/10/20% 22/32/37/45%, 재배정 38%, 노출비 중앙값 0.69 · 상위 5% 3.43;
  분해 상위 10%: 36.4 / 32.2 / 50.9%
실행: .venv/bin/python -m rq1_modules.H2_where [--scale=...]
"""
import sys
import numpy as np, pandas as pd
from rq1_modules.common import (SCALE_KO, TOPK, GU, build_panel, load_census, unit_of, unit_exposure, top_overlap, dissimilarity, rho,
                                parse_scales, dong_names, unit_label, save)


def overall(M, scale):
    E = unit_exposure(M, scale); rows = []
    for _, g in E.groupby(["year", "season", "period"]):
        g = g.set_index("u"); EA, ER = g.EA_all, g.ER_all; pos = (EA > 0) & (ER > 0); lr = np.log(EA[pos] / ER[pos])
        r = dict(rho=rho(EA, ER), reassigned=dissimilarity(EA, ER), ratio_med=float(np.exp(lr.median())), ratio_p95=float(np.exp(lr.quantile(.95))))
        for k in ((.01, .05, .10, .20) if scale != "gu" else (5, 10)): r[f"top{k}"] = top_overlap(EA, ER, k)
        rows.append(r)
    return pd.DataFrame(rows).mean().to_dict()


def summer(M, scale):
    E = unit_exposure(M[M.season == "summer"], scale, key=("year", "period")); out = {}
    for p, gp in E.groupby("period"):
        v = [dict(rho=rho(g.set_index("u").EA_all, g.set_index("u").ER_all), top=top_overlap(g.set_index("u").EA_all, g.set_index("u").ER_all, TOPK[scale]),
                  reassigned=dissimilarity(g.set_index("u").EA_all, g.set_index("u").ER_all)) for _, g in gp.groupby("year")]
        out[p] = pd.DataFrame(v).mean().to_dict()
    return out


def decomposition(M, scale, year=2025):
    q = M[(M.year == year) & (M.season == "summer") & M.hour.isin([3, 14])]
    nd = q.n_days.max(); dz = q.pivot_table(index="tract16", columns="hour", values="dT"); pz = q.pivot_table(index="tract16", columns="hour", values="PA_all") / nd
    res = q.groupby("tract16").res_all.first()
    E = pd.DataFrame({"R14": dz[14] * res, "R03": dz[3] * res, "A14": dz[14] * pz[14], "A03": dz[3] * pz[3], "A03_14": dz[14] * pz[3]})
    E = E.groupby(unit_of(E.index.to_series(), scale).values).sum()
    pairs = {"census_vs_14": ("R14", "A14"), "census_vs_03": ("R03", "A03"), "03_vs_14": ("A03_14", "A14")}
    ks = (.01, .10, .30) if scale != "gu" else (5, 10)
    return {n: dict(rho=rho(E[a], E[b]), **{f"top{k}": top_overlap(E[a], E[b], k) for k in ks}) for n, (a, b) in pairs.items()}


def ranking(M, scale, names=None):
    S = M[(M.season == "summer") & (M.period == "day")]
    E = unit_exposure(S, scale, key=()).set_index("u"); P = S.assign(u=unit_of(S.tract16, scale)).groupby("u")[["PA_all", "PR_all"]].sum()
    T = E.join(P)
    T["share_A"] = 100 * T.EA_all / T.EA_all.sum(); T["share_R"] = 100 * T.ER_all / T.ER_all.sum()
    T["exp_ratio"] = T.EA_all / T.ER_all; T["pop_ratio"] = T.PA_all / T.PR_all
    T["rank_A"] = T.EA_all.rank(ascending=False).astype(int); T["rank_R"] = T.ER_all.rank(ascending=False).astype(int)
    T["name"] = [unit_label(u, scale, names) for u in T.index]
    cols = ["name", "rank_A", "rank_R", "share_A", "share_R", "exp_ratio", "pop_ratio"]
    if scale == "gu": return T.sort_values("rank_A")[cols].round(3).reset_index().to_dict("records")
    if scale == "dong":
        return dict(top_activity=T.nsmallest(10, "rank_A")[cols].round(3).reset_index().to_dict("records"),
                    top_residence=T.nsmallest(10, "rank_R")[cols].round(3).reset_index().to_dict("records"))
    return None


def run(scales=("tract", "dong", "gu"), verbose=True):
    M = build_panel(); names = dong_names() if "dong" in scales else {}
    out = {s: dict(overall=overall(M, s), summer=summer(M, s), decomposition=decomposition(M, s), ranking=ranking(M, s, names)) for s in scales}
    if verbose: report(out)
    save(out, "H2_where")
    return out


def report(out):
    for s, o in out.items():
        print(f"\n=== H2 어디서 · {SCALE_KO[s]} ===")
        d = o["overall"]; tops = " / ".join(f"{k[3:]}: {v:.0f}%" for k, v in d.items() if k.startswith("top"))
        print(f"16조건: 순위 상관 {d['rho']:.2f} | 상위 일치 {tops} | 재배정 {d['reassigned']:.1f}% | 노출비 중앙값 {d['ratio_med']:.2f} · 상위 5% {d['ratio_p95']:.2f}")
        print("여름: " + "  ".join(f"{p} 순위 상관 {v['rho']:.2f}, 상위 일치 {v['top']:.0f}%, 재배정 {v['reassigned']:.1f}%" for p, v in o["summer"].items()))
        for n, v in o["decomposition"].items():
            print(f"2025 여름 {n}: 순위 상관 {v['rho']:.2f} | " + " / ".join(f"{k[3:]}: {x:.1f}%" for k, x in v.items() if k.startswith("top")))
        if s == "gu":
            print("활동 순위 | 자치구 | 거주 순위 | 활동 비중 | 거주 비중 | 노출비 | 인구비")
            for r in o["ranking"]: print(f"{r['rank_A']} | {r['name']} | {r['rank_R']} | {r['share_A']:.2f}% | {r['share_R']:.2f}% | {r['exp_ratio']:.2f} | {r['pop_ratio']:.2f}")
        if s == "dong":
            ta, tr = o["ranking"]["top_activity"], o["ranking"]["top_residence"]
            for i in range(10): print(f"{i+1} | 활동 상위: {ta[i]['name']} ({ta[i]['rank_R']}) | 거주 상위: {tr[i]['name']} ({tr[i]['rank_A']})")


if __name__ == "__main__":
    run(parse_scales(sys.argv))
