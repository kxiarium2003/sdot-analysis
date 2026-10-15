"""S1. 무엇을 어떻게 쟀나: 기초 수치 (보고서 1.3–1.5절, 그림 A)

계산 (단위마다)
  dist         2025 여름 03·15시 단위 ΔT 분포(하위 10%, 중앙값, 상위 10%)
  annual       연평균 야간 ΔT 2°C 초과 단위 비중과 그곳의 거주 인구 비중, 낮·밤 ΔT 지도의 상관
  gu_table     자치구별 ΔT(연평균·여름 평균, 낮·밤) — 그림 A 의 값 (집계구 단순 평균)
  example      행정동 예시(기본: 강남 역삼1동, 강서 화곡1동) 2025 여름 15시·03시: 인구총조사, 생활인구, 단위 ΔT, 노출 총량, 65세 이상 노출
기대값: 집계구 03시 1.17 / 1.82 / 2.12°C, 15시 0.88 / 1.29 / 1.78°C; 야간 2°C 초과 56% · 거주 인구 55%; 낮밤 상관 0.88;
  역삼1동 15시 생활인구 136,582명(인구총조사 33,801명), 동 ΔT 1.22°C
실행: .venv/bin/python -m rq1_modules.S1_basics [--scale=...] [--dong=역삼1동:강남구,화곡1동:강서구]
"""
import sys
import numpy as np, pandas as pd
from rq1_modules.common import (GU, SCALE_KO, NIGHT, build_panel, load_field, to_units, unit_of, parse_scales, dong_names, save)


def dist_annual(M, scale):
    U = to_units(M, scale, [], key=("year", "season", "hour"))
    q = U[(U.year == 2025) & (U.season == "summer")]
    out = {f"h{h:02d}": dict(p10=q[q.hour == h].dT.quantile(.1), p50=q[q.hour == h].dT.median(), p90=q[q.hour == h].dT.quantile(.9)) for h in (3, 15)}
    U["period"] = np.where(U.hour.isin(NIGHT), "night", "day")
    ann = U.groupby(["u", "period"]).dT.mean().unstack(); w = U.groupby("u").res_all.first().reindex(ann.index)
    out["night_gt2_units_pct"] = 100 * (ann.night > 2).mean(); out["night_gt2_res_pct"] = 100 * w[ann.night > 2].sum() / w.sum()
    out["day_night_corr"] = float(np.corrcoef(ann.day, ann.night)[0, 1])
    return out


def gu_table():
    Z = load_field(); Z["period"] = np.where(Z.hour.isin(NIGHT), "night", "day")
    out = {}
    for lab, z in (("annual", Z), ("summer", Z[Z.season == "summer"])):
        t = z.groupby(["tract16", "period"]).dT_hat.mean().unstack()
        out[lab] = t.groupby(t.index.str[:5].map(GU)).mean().round(3).to_dict("index")
    return out


def example(M, pairs=(("역삼1동", "강남구"), ("화곡1동", "강서구"))):
    names = dong_names(); out = {}
    q = M[(M.year == 2025) & (M.season == "summer")]; nd = q.n_days.max()
    for dname, gu in pairs:
        code = next((c for c, n in names.items() if n == f"{gu} {dname}"), None)
        if code is None: continue
        g = q[unit_of(q.tract16, "dong") == code]; r = g.groupby("tract16")[["res_all", "res_a65p"]].first().sum()
        def pop(h, a): return g[g.hour == h][f"PA_{a}"].sum() / nd
        def dT(h): gh = g[g.hour == h]; return (gh.dT * gh.res_all).sum() / gh.res_all.sum()
        d = dict(code=code, census=r.res_all, census_65=r.res_a65p, pop03=pop(3, "all"), pop15=pop(15, "all"),
                 pop65_03=pop(3, "a65p"), pop65_15=pop(15, "a65p"), dT03=dT(3), dT15=dT(15))
        d.update(ratio15=d["pop15"] / d["census"], E15_res=d["census"] * d["dT15"], E15_act=d["pop15"] * d["dT15"],
                 E65_15=d["pop65_15"] * d["dT15"], E65_03=d["pop65_03"] * d["dT03"])
        out[f"{gu} {dname}"] = d
    return out


def run(scales=("tract", "dong", "gu"), pairs=None, verbose=True):
    M = build_panel()
    out = dict(scales={s: dist_annual(M, s) for s in scales}, gu_table=gu_table(), example=example(M, pairs or (("역삼1동", "강남구"), ("화곡1동", "강서구"))))
    if verbose:
        for s, d in out["scales"].items():
            print(f"\n=== S1 기초 · {SCALE_KO[s]} ===")
            for h in ("h03", "h15"): print(f"2025 여름 {h[1:]}시 ΔT: 하위 10% {d[h]['p10']:.2f} · 중앙값 {d[h]['p50']:.2f} · 상위 10% {d[h]['p90']:.2f}°C (차이 {d[h]['p90'] - d[h]['p10']:.2f})")
            print(f"연평균 야간 ΔT 2°C 초과: 단위 {d['night_gt2_units_pct']:.0f}%, 거주 인구 {d['night_gt2_res_pct']:.0f}% | 낮·밤 지도 상관 {d['day_night_corr']:.2f}")
        print("\n자치구 ΔT (여름 평균 낮 / 밤):", ", ".join(f"{g} {v['day']:.2f}/{v['night']:.2f}" for g, v in sorted(out["gu_table"]["summer"].items(), key=lambda x: x[1]["night"])))
        for k, d in out["example"].items():
            print(f"\n{k} (2025 여름): 인구총조사 {d['census']:,.0f}명, 03시 {d['pop03']:,.0f}명, 15시 {d['pop15']:,.0f}명 ({d['ratio15']:.2f}배), 15시 ΔT {d['dT15']:.2f}°C, "
                  f"15시 노출 {d['E15_res']:,.0f} → {d['E15_act']:,.0f} | 65세 이상 15시 {d['pop65_15']:,.0f}명 × {d['dT15']:.2f} = {d['E65_15']:,.0f}, 03시 {d['pop65_03']:,.0f}명 × {d['dT03']:.2f} = {d['E65_03']:,.0f}")
    save(out, "S1_basics")
    return out


if __name__ == "__main__":
    arg = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--dong=")), None)
    run(parse_scales(sys.argv), pairs=[tuple(x.split(":")) for x in arg.split(",")] if arg else None)
