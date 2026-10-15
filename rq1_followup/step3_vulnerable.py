"""RQ1 후속 3단계: 취약계층(0–14세, 65세 이상) 재분석 — 15–64세와 비교, ΔT 기준과 절대 기온(33°C 초과 인시) 기준.

[사전등록 — 결과 보기 전에 고정] (작성 2026-10-12)
  단위      행정동(주), 집계구·자치구 병기. 0–14세 집계구 열은 3명 이하 마스킹 영향으로 참고용.
  ΔT 기준 지표 (rq1_modules 함수 그대로)
    1인당 Gap·재배치 효과      H1.per_capita (연간, 2년 평균)
    노출 순위 상관·상위 10% 일치  H4.age_rank (16조건 평균; 자치구는 상위 5곳)
    노출비(활동÷거주)          단위 노출 EA/ER 의 중앙값·95백분위, 16조건 평균 (H2.overall 방식을 연령별로)
    시각별 열 차이              H3.hourly 14시·15시 (여름)
    거주 대비 낮 인구 비        단위별 (여름 낮 07–20시 평균 생활인구 ÷ 인구총조사), 거주 > 0 단위의 중앙값·90백분위
  절대 기온 기준 (33°C 초과, 여름 6–9월, step1 의 exceed33_*.parquet)
    1인당 33°C 초과 시간(거주·활동)과 Gap, 순위 상관·상위 10% 일치(단위 EA33 vs ER33, 연도별 계산 후 평균),
    노출비 중앙값·95백분위(둘 다 > 0 인 단위), 시각별 열 차이(절대 기온 지도 위 14·15시, H3 와 같은 방식)
  "15–64세와 다르다" 판정 (어느 하나라도 넘으면 다름):
    Gap·재배치 효과 차이 ≥ 1.0%p, 순위 상관 차이 ≥ 0.10, 상위 10% 일치 차이 ≥ 10%p, 노출비 중앙값 차이 ≥ 0.10,
    열 차이 차이 ≥ 0.010°C, 낮 인구 비 중앙값 차이 ≥ 0.10
실행: python -m rq1_followup.step3_vulnerable   (step1_absolute 먼저 실행)
출력: rq1_followup/out/step3/
"""
import json, time
import numpy as np, pandas as pd
import rq1_modules.common as c
from rq1_modules import H1_how_much as H1, H3_when as H3, H4_who as H4

OUT = c.ROOT / "rq1_followup/out/step3"; OUT.mkdir(parents=True, exist_ok=True)
S1 = c.ROOT / "rq1_followup/out/step1"
c.P["out"] = OUT / "_module_json"
SCALES = ("dong", "tract", "gu"); AG = ["a0_14", "a15_64", "a65p", "all"]
CUT = dict(gap_pct=1.0, redis_pct=1.0, rho=0.10, top=10.0, ratio_med=0.10, heat14=0.010, heat15=0.010, daypop_med=0.10)
DAYH = list(range(7, 21))


def ratio_stats(EA, ER):
    pos = (EA > 0) & (ER > 0); lr = np.log(EA[pos] / ER[pos])
    return float(np.exp(lr.median())), float(np.exp(lr.quantile(.95)))


def dT_metrics(M, s):
    pc = H1.per_capita(M, s); ar = H4.age_rank(M, s); hh = H3.hourly(M, s)
    E = c.unit_exposure(M, s, groups=AG); rr = {a: [] for a in AG}
    for _, g in E.groupby(["year", "season", "period"]):
        for a in AG: rr[a].append(ratio_stats(g[f"EA_{a}"], g[f"ER_{a}"]))
    S = M[(M.season == "summer") & M.hour.isin(DAYH)].assign(u=lambda d: c.unit_of(d.tract16, s))
    out = {}
    for a in AG:
        dp = S.groupby(["u", "year", "hour"]).agg(pa=(f"PA_{a}", "sum"), nd=("n_days", "max")).assign(p=lambda d: d.pa / d.nd).groupby("u").p.mean()
        res = c.load_census()[a].groupby(c.unit_of(c.load_census().index.to_series(), s).values).sum()
        r = (dp / res.reindex(dp.index)).replace([np.inf], np.nan).dropna()
        out[a] = dict(gap_pct=pc[a]["gap_pct"], redis_pct=pc[a]["redis_pct"], residence=pc[a]["residence"], activity=pc[a]["activity"],
                      rho=ar[a], top=ar[f"top_{a}"], ratio_med=float(np.mean([x[0] for x in rr[a]])), ratio_p95=float(np.mean([x[1] for x in rr[a]])),
                      heat14=float(hh.loc[14, a]), heat15=float(hh.loc[15, a]), daypop_med=float(r.median()), daypop_p90=float(r.quantile(.9)))
    return out


def abs_metrics(s, lp, res):
    N = pd.read_parquet(S1 / f"exceed33_{s}.parquet")
    L = lp.assign(u=c.unit_of(lp.tract16, s)).groupby(["u", "year", "hour"])[AG].sum()
    nd = lp.groupby("year").n_days.max()
    L = L.div(L.index.get_level_values("year").map(nd).values, axis=0).reset_index()          # 하루 평균 생활인구
    R = res.groupby(c.unit_of(res.index.to_series(), s).values)[AG].sum()
    X = N.merge(L, on=["u", "year", "hour"], how="left").fillna(0)
    tot = res[AG].sum(); out = {}
    for a in AG:
        X[f"EA_{a}"] = X.h33 * X[a]
        per = X.groupby(["u", "year"]).agg(EA=(f"EA_{a}", "sum"), h=("h33", "sum")).reset_index()
        per["ER"] = per.h * per.u.map(R[a]).fillna(0)
        EA, ER = per.EA.sum() / tot[a] / 2, per.ER.sum() / tot[a] / 2
        k = c.TOPK[s]; rows = [dict(rho=c.rho(g.EA, g.ER), top=c.top_overlap(g.set_index("u").EA, g.set_index("u").ER, k), rm=ratio_stats(g.EA, g.ER))
                              for _, g in per.groupby("year")]
        out[a] = dict(residence_h=ER, activity_h=EA, gap_pct=100 * (EA - ER) / ER if ER > 0 else np.nan,
                      rho=float(np.mean([r["rho"] for r in rows])), top=float(np.mean([r["top"] for r in rows])),
                      ratio_med=float(np.mean([r["rm"][0] for r in rows])), ratio_p95=float(np.mean([r["rm"][1] for r in rows])))
    return out


def abs_heat(s, lp):
    """절대 기온 지도 위 열 차이: (h시 배치 가중 평균 T_abs) − (03시 배치 가중 평균 T_abs), 여름, 2년 평균. 단위 기온 = 거주 가중."""
    from rq1_modules import H5_absolute as H5
    U = H5.units(H5.panel(), s); out = {a: {} for a in AG}
    for h in (14, 15):
        v = {a: [] for a in AG}
        for y, gy in U.groupby("year"):
            g = gy[gy.hour == h].set_index("u"); b = gy[gy.hour == 3].set_index("u").reindex(g.index).fillna(0)
            for a in AG: v[a].append((g[a] * g["abs"]).sum() / g[a].sum() - (b[a] * g["abs"]).sum() / b[a].sum())
        for a in AG: out[a][f"heat{h}"] = float(np.mean(v[a]))
    return out


def judge(m, key):
    ref = m["a15_64"]
    return {a: {k: bool(abs(m[a][k] - ref[k]) >= CUT[k]) for k in CUT if k in m[a] and k in ref and np.isfinite(m[a][k])} for a in ("a0_14", "a65p")}


def main():
    t0 = time.time(); M = c.build_panel(); res = c.load_census()
    lp = c.load_livingpop(); lp = lp[lp.season == "summer"]
    out = {}
    for s in SCALES:
        d = dT_metrics(M, s); a = abs_metrics(s, lp, res); h = abs_heat(s, lp)
        for g in AG: a[g].update(h[g])
        out[s] = dict(dT=d, abs33=a, differs_dT=judge(d, "dT"), differs_abs=judge(a, "abs"))
        print(f"{s} 완료 {time.time() - t0:.0f}s", flush=True)
    json.dump(out, open(OUT / "step3_metrics.json", "w"), ensure_ascii=False, indent=1, default=float)
    rows = []
    for s, o in out.items():
        for base in ("dT", "abs33"):
            for a, d in o[base].items():
                rows.append(dict(scale=s, base=base, age=a, **d))
    pd.DataFrame(rows).to_csv(OUT / "step3_metrics.csv", index=False, encoding="utf-8-sig")
    print(f"완료 {time.time() - t0:.0f}s → {OUT}")


if __name__ == "__main__":
    main()
