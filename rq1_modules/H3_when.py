"""H3. 언제: "차이는 낮에 생기고, 밤에는 거주지로 수렴할 것이다" (보고서 2장 H3, 그림 F·F′·K)

같은 생활인구 안에서 새벽 3시 배치와 h시 배치를 비교한다(자료 차이가 없는 순수 이동).
계산 (단위마다, 2024·2025 여름 평균)
  move         이동 규모(%) = 새벽 3시 배치와 h시 배치의 비유사도
  heat         연령별 열 차이(°C) = h시 온도 지도 위에서 (h시 배치로 가중한 평균 ΔT) − (새벽 3시 배치로 가중한 평균 ΔT)
               행정동·자치구는 단위 평균 ΔT 를 쓴다
  day/night 의 노출 순위 상관은 H2_where.summer 에 있다
기대값 (집계구): 14시 이동 36.4%, 15–64세 15시 −0.053°C / 14시 −0.051°C; 행정동 14시 16.5%, 15시 −0.018°C
실행: .venv/bin/python -m rq1_modules.H3_when [--scale=...]
"""
import sys
import pandas as pd
from rq1_modules.common import (GROUPS, AGE_KO, SCALE_KO, build_panel, to_units, dissimilarity, parse_scales, save)


def hourly(M, scale):
    S = M[M.season == "summer"]
    U = to_units(S, scale, [f"PA_{g}" for g in GROUPS], key=("year", "hour"))
    rows = []
    for y, gy in U.groupby("year"):
        a3 = gy[gy.hour == 3].set_index("u")
        for h, g in gy.groupby("hour"):
            g = g.set_index("u"); b = a3.reindex(g.index).fillna(0)
            r = dict(year=y, hour=h, move=dissimilarity(g.PA_all, b.PA_all))
            for a in GROUPS:
                r[a] = (g[f"PA_{a}"] * g.dT).sum() / g[f"PA_{a}"].sum() - (b[f"PA_{a}"] * g.dT).sum() / b[f"PA_{a}"].sum()
            rows.append(r)
    return pd.DataFrame(rows).groupby("hour").mean().drop(columns="year")


def run(scales=("tract", "dong", "gu"), verbose=True):
    M = build_panel()
    out = {s: hourly(M, s) for s in scales}
    if verbose:
        for s, H in out.items():
            print(f"\n=== H3 언제 · {SCALE_KO[s]} (2024·2025 여름, 새벽 3시 대비) ===")
            hs = [3, 7, 9, 12, 14, 15, 18, 20, 22]
            print("시각 | " + " | ".join(f"{h:02d}" for h in hs))
            print("이동 규모(%) | " + " | ".join(f"{H.loc[h, 'move']:.1f}" for h in hs))
            for a in GROUPS: print(f"열 차이 {AGE_KO[a]} | " + " | ".join(f"{H.loc[h, a]:+.3f}" for h in hs))
    save({s: H.round(5).to_dict("index") for s, H in out.items()}, "H3_when")
    return out


if __name__ == "__main__":
    run(parse_scales(sys.argv))
