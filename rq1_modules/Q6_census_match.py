"""Q6. 인구총조사와 생활인구는 같은 사람을 같은 곳에 세는가 (보고서 6장 Q6, 2.6절 결과 1, 5.1.3)

열노출이 아니라 인구 수로 직접 비교한다(같은 ΔT 를 곱하므로 인구가 같으면 노출도 같다).
모든 집계구(19,153개)를 쓰고, 인구총조사에 없는 130개 집계구는 주민 0명으로 둔다.
계산 (단위마다, 2025 여름): 연령 × 시각(03·09·14·18·22시) 순위 상관, 새벽 3시 상위 10%(자치구 5곳) 일치, 새벽 3시 비유사도
기대값: 새벽 3시 전 연령 순위 상관 집계구 0.28 · 행정동 0.85 · 자치구 0.96, 비유사도 35 / 8.6 / 4.5%
실행: .venv/bin/python -m rq1_modules.Q6_census_match [--scale=...]
"""
import sys
import pandas as pd
from rq1_modules.common import (GROUPS, AGE_KO, SCALE_KO, TOPK, load_census, load_livingpop, unit_of, top_overlap, dissimilarity, rho, parse_scales, save)

HOURS = (3, 9, 14, 18, 22)


def run(scales=("tract", "dong", "gu"), year=2025, verbose=True):
    lp = load_livingpop(); q = lp[(lp.year == year) & (lp.season == "summer")]; res = load_census(); out = {}
    for s in scales:
        R = res.groupby(unit_of(res.index.to_series(), s).values).sum(); o = {}
        for a in GROUPS:
            for h in HOURS:
                qh = q[q.hour == h]; Pp = qh.groupby(unit_of(qh.tract16, s).values)[a].sum()
                o[f"{a}_{h:02d}"] = rho(R[a], Pp)
                if h == 3:
                    x = pd.concat([R[a], Pp], axis=1, keys=["R", "P"]).fillna(0)
                    o[f"top_{a}_03"] = top_overlap(x.R, x.P, TOPK[s]); o[f"D_{a}_03"] = dissimilarity(x.R, x.P)
        out[s] = o
    if verbose:
        for s, o in out.items():
            print(f"\n=== Q6 인구 수 일치 · {SCALE_KO[s]} ({year} 여름) ===")
            print("순위 상관 | " + " | ".join(f"{h:02d}시" for h in HOURS))
            for a in GROUPS: print(f"{AGE_KO[a]} | " + " | ".join(f"{o[f'{a}_{h:02d}']:.2f}" for h in HOURS))
            print("새벽 3시 상위 일치 / 비유사도: " + "  ".join(f"{AGE_KO[a]} {o['top_' + a + '_03']:.0f}% / {o['D_' + a + '_03']:.1f}%" for a in GROUPS))
    save(out, "Q6_census_match")
    return out


if __name__ == "__main__":
    run(parse_scales(sys.argv))
