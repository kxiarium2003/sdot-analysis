"""S4. 결과를 믿을 수 있나: 강건성 (보고서 4장)

계산 (단위마다)
  variants     ΔT 지도를 만든 설정을 바꿔도 노출 순위가 같은가: 기본, 폴리곤 예측, 회귀-크리깅, 표본 엄격(1,006대), data1 표본(453대),
               1시간 지연 매칭, 공변량 반경 100 m · 500 m. 16조건 평균 순위 상관, 2025 여름 낮 상위 10%(자치구 5곳) 일치
               입력: phase3/gap_2y_by_tract{tag}.parquet (phase3_exposure_2y.py 산출)
  threshold    30·33°C 초과 노출(집계구 노출의 합)의 여름 낮·밤 순위 상관과 상위 일치, 연도 평균
               입력: phase3/threshold_by_tract_2y_merged.parquet (phase3_threshold_exposure.py 산출)
기대값: 집계구 0.39–0.42 · 33–38%, 행정동 0.74–0.76; 30°C 낮 / 밤 집계구 0.35 / 0.54, 행정동 0.62 / 0.90
실행: .venv/bin/python -m rq1_modules.S4_robustness [--scale=...]
"""
import sys
import numpy as np, pandas as pd
from rq1_modules.common import (ROOT, SCALE_KO, TOPK, unit_of, top_overlap, rho, parse_scales, save)

VARIANTS = [("_merged", "기본 (1,085대)"), ("_merged_poly", "폴리곤 예측"), ("_rk", "회귀-크리깅"), ("_strict_merged", "표본 엄격 (1,006대)"),
            ("_merged_d1_453", "data1 표본 (453대)"), ("_lag1_merged", "1시간 지연 매칭"), ("_merged_buf100", "반경 100 m"), ("_merged_buf500", "반경 500 m")]


def variants(scale):
    out = {}
    for tag, lab in VARIANTS:
        f = ROOT / f"phase3/gap_2y_by_tract{tag}.parquet"
        if not f.exists(): continue
        T = pd.read_parquet(f); T["u"] = unit_of(T.tract16, scale)
        T = T.groupby(["u", "summer", "season", "period"])[["EA", "ER"]].sum().reset_index()
        r = T.groupby(["summer", "season", "period"]).apply(lambda q: rho(q.EA, q.ER), include_groups=False).mean()
        q = T[(T.summer == 2025) & (T.season == "summer") & (T.period == "day")].set_index("u")
        out[lab] = dict(rho=r, top=top_overlap(q.EA, q.ER, TOPK[scale]))
    return out


def threshold(scale):
    f = ROOT / "phase3/threshold_by_tract_2y_merged.parquet"
    if not f.exists(): return {}
    t = pd.read_parquet(f); t["u"] = unit_of(t.tract16, scale)
    t = t.groupby(["u", "thr", "year", "period"])[["EA", "ER"]].sum().reset_index(); out = {}
    for (k, p), g in t.groupby(["thr", "period"]):
        v = [(rho(q.set_index("u").EA, q.set_index("u").ER), top_overlap(q.set_index("u").EA, q.set_index("u").ER, TOPK[scale]))
             for _, q in g[(g.EA > 0) | (g.ER > 0)].groupby("year")]
        out[f"{k}C_{p}"] = dict(rho=np.mean([x[0] for x in v]), top=np.mean([x[1] for x in v]))
    return out


def run(scales=("tract", "dong", "gu"), verbose=True):
    out = {s: dict(variants=variants(s), threshold=threshold(s)) for s in scales}
    if verbose:
        for s, o in out.items():
            print(f"\n=== S4 강건성 · {SCALE_KO[s]} ===")
            for lab, d in o["variants"].items(): print(f"{lab}: 순위 상관 {d['rho']:.2f}, 상위 일치 {d['top']:.0f}%")
            for k, d in o["threshold"].items(): print(f"{k} 초과 노출: 순위 상관 {d['rho']:.2f}, 상위 일치 {d['top']:.0f}%")
    save(out, "S4_robustness")
    return out


if __name__ == "__main__":
    run(parse_scales(sys.argv))
