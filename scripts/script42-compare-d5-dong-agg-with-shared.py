"""
script42-compare-d5-dong-agg-with-shared.py - [3] 공유 가공본(현우님) vs script41 행정동 여름 집계본 역산 비교

입력(읽기만)
  A. merged_data/D5_livingpop/livingpop_agg_2024_2025_native.parquet  (공유 가공본: 집계구 × 연도 × 계절 × 시각,
     값 = 그 계절 날짜들의 합, 열 total/a0_14/a15_64/a65p/n_masked/n_days)
  B. script41 산출 agg_dong_summer_2024_2025.parquet (행정동 × 날짜 × 시각, 연령 14구간 _lo/_hi/_nstar/_nnull)
  C. merged_data/D5_livingpop/age_scale.csv (연도 × 연령 배율)

[사전등록 - 결과 보기 전에 고정] (작성 2026-10-19)
  단위 맞춤: A는 season == 'summer'(6–9월) 행을 연도별로 모든 집계구·시각에 걸쳐 합한다(= 날짜 합).
             B는 연도(기준일ID 앞 4자리)별로 모든 행정동·날짜·시각에 걸쳐 합한다. 둘 다 "여름 날짜 합" 단위.
  연령 묶음(B): 0-14 = 0-9 + 10-14, 15-64 = 15-19 ... 60-64(10구간), 65+ = 65-69 + 70+. 총계 = total.
  판정: A가 B 하한과 상대 차 |A/lo − 1| ≤ 0.01% 이면 "하한과 일치", 상한과 같은 기준이면 "상한과 일치",
        lo < A < hi 이면 "범위 안(어느 쪽과도 불일치)", 범위 밖이면 "범위 밖".
  연령 보정 여부: A/lo(또는 A/hi)가 1에 가까우면 보정 전, age_scale.csv 배율과 같으면 보정 후로 본다.
        common.load_livingpop 의 보정(A × 배율)을 적용한 값도 따로 비교한다.
  n_masked: A의 n_masked 합을 B의 별표 칸 수(연령 28칸 합, total 포함/제외)와 대조.
"""
import sys, json
from pathlib import Path
import duckdb, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
A = ROOT / "merged_data/D5_livingpop/livingpop_agg_2024_2025_native.parquet"
B = Path(sys.argv[1])
SCALE = ROOT / "merged_data/D5_livingpop/age_scale.csv"
TOL = 1e-4
G = {"a0_14": ["a0_9", "a10_14"], "a15_64": [f"a{x}_{x + 4}" for x in range(15, 65, 5)], "a65p": ["a65_69", "a70p"], "total": ["total"]}

con = duckdb.connect()
a = con.execute(f"""SELECT summer AS year, SUM(total) total, SUM(a0_14) a0_14, SUM(a15_64) a15_64, SUM(a65p) a65p, SUM(n_masked) n_masked,
                    count(*) n_rows, count(DISTINCT tract) n_tract FROM read_parquet('{A}') WHERE season = 'summer' GROUP BY 1 ORDER BY 1""").df().set_index("year")
sel = []
for g, bands in G.items():
    for k in ("lo", "hi", "nstar"):
        sel.append(f"SUM({' + '.join(f'{b}_{k}' for b in bands)}) AS {g}_{k}")
nstar_age = " + ".join(f"{b}_nstar" for bs in list(G.values())[:3] for b in bs)
b = con.execute(f"""SELECT CAST(substr(기준일ID, 1, 4) AS INTEGER) AS year, {', '.join(sel)}, SUM({nstar_age}) AS nstar_age28,
                    count(DISTINCT 기준일ID) n_days, count(DISTINCT 행정동코드) n_dong FROM read_parquet('{B}') GROUP BY 1 ORDER BY 1""").df().set_index("year")
sc = pd.read_csv(SCALE).set_index("year")

rows = []
for y in a.index:
    for g in G:
        av, lo, hi = float(a.loc[y, g]), float(b.loc[y, f"{g}_lo"]), float(b.loc[y, f"{g}_hi"])
        if abs(av / lo - 1) <= TOL: v = "하한과 일치"
        elif abs(av / hi - 1) <= TOL: v = "상한과 일치"
        elif lo < av < hi: v = "범위 안(불일치)"
        else: v = "범위 밖"
        r = dict(year=int(y), group=g, shared=av, lo=lo, hi=hi, shared_over_lo=av / lo, shared_over_hi=av / hi, verdict=v,
                 hi_minus_lo_pct=100 * (hi - lo) / lo)
        if g in sc.columns:
            s = float(sc.loc[y, g]); r.update(scale=s, scaled_shared_over_lo=av * s / lo, unscaled_shared_over_lo=av / s / lo)
        rows.append(r)
R = pd.DataFrame(rows)
mask = dict(shared_n_masked={int(y): int(a.loc[y, "n_masked"]) for y in a.index},
            agg_nstar_age28={int(y): int(b.loc[y, "nstar_age28"]) for y in b.index},
            agg_nstar_total={int(y): int(b.loc[y, "total_nstar"]) for y in b.index})
cover = dict(shared_rows={int(y): int(a.loc[y, "n_rows"]) for y in a.index}, shared_tracts={int(y): int(a.loc[y, "n_tract"]) for y in a.index},
             agg_days={int(y): int(b.loc[y, "n_days"]) for y in b.index}, agg_dongs={int(y): int(b.loc[y, "n_dong"]) for y in b.index})
pd.set_option("display.width", 220)
print(R.round(6).to_string(index=False)); print(json.dumps(mask, ensure_ascii=False)); print(json.dumps(cover, ensure_ascii=False))
out = B.parent / "compare_shared_vs_dong_agg.json"
json.dump(dict(table=R.to_dict("records"), n_masked=mask, coverage=cover, tol=TOL), open(out, "w"), ensure_ascii=False, indent=1)
print("저장", out)
