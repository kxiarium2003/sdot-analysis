"""s01_d6_check.py - D6 SGIS 집계구 인구 데이터: 연도, 연령 코드 해석 검증, D9 집계구 경계 코드 일치율, 집계구별 65+ 인구.

코드 해석(코드표가 없어 데이터로 검증): in_age_001~021 = 전체, 031~051 = 남, 061~081 = 여, 각 21구간(5세 단위, 마지막 100세 이상으로 가정).
65+ 시작 구간은 노년부양비(to_in_005)·노령화지수(to_in_004)와 대조해 정한다.
5 미만은 행이 없다. 하한 = 없는 구간 0, 상한 = 없는 구간 4(총인구 이하로 제한).
출력: d6_year_columns.csv, d6_age_code_check.csv, d6_boundary_match.csv / 스크래치: oa65.parquet
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd, geopandas as gpd

N = ["year", "oa", "code", "v"]
rd = lambda name: pd.read_csv(D6 / f"11_2024년_{name}.csv", header=None, names=N, dtype={"oa": str, "code": str, "year": str})
a = rd("성연령별인구"); a["n"] = a.code.str[-3:].astype(int)
to = rd("인구총괄(총인구)"); dep = rd("인구총괄(노년부양비)"); aging = rd("인구총괄(노령화지수)")
print("years", a.year.unique(), to.year.unique(), "age rows", len(a), "age OAs", a.oa.nunique(), "code n", a.code.nunique(), "min v", a.v.min(), "dup", a.duplicated(["oa", "code"]).sum())
print(to.groupby("code").v.agg(["size", "sum"]))
tot = to[to.code == "to_in_001"].set_index("oa").v
w = a[a.n <= 21].pivot_table(index="oa", columns="n", values="v", aggfunc="sum").reindex(columns=range(1, 22)).reindex(tot.index)
m = a[(a.n >= 31) & (a.n <= 51)].groupby("oa").v.sum(); f = a[a.n >= 61].groupby("oa").v.sum()
filled = w.fillna(0)
rows = [dict(항목="연도", 값=",".join(sorted(a.year.unique()))), dict(항목="파일", 값="11_2024년_성연령별인구.csv (헤더 없음: 연도, 집계구코드, 항목코드, 값)"),
        dict(항목="연령 항목 코드 수", 값=a.code.nunique()), dict(항목="연령 자료가 있는 집계구", 값=a.oa.nunique()), dict(항목="총인구 파일 집계구", 값=tot.size),
        dict(항목="연령 값 최솟값(5 미만 행 없음)", 값=a.v.min()), dict(항목="서울 총인구(to_in_001 합)", 값=float(tot.sum())), dict(항목="001~021 합", 값=float(filled.sum().sum())),
        dict(항목="001~021 합 / 총인구", 값=float(filled.sum().sum() / tot.sum())), dict(항목="031~051 합(남)", 값=float(m.sum())), dict(항목="061~081 합(여)", 값=float(f.sum())), dict(항목="남+여 / 001~021", 값=float((m.sum() + f.sum()) / filled.sum().sum()))]
pd.DataFrame(rows).to_csv(OUT / "d6_year_columns.csv", index=False, encoding="utf-8-sig"); print(pd.DataFrame(rows).to_string())
big = tot[tot >= 200].index
wb = filled.loc[big]; dv = dep.set_index("oa").v.reindex(big); av = aging.set_index("oa").v.reindex(big)
ck = []
for st in (13, 14, 15):
    old = wb[[c for c in range(st, 22)]].sum(axis=1); work = wb[[c for c in range(4, st)]].sum(axis=1); child = wb[[1, 2, 3]].sum(axis=1)
    r1 = old / work.replace(0, np.nan) * 100; r2 = old / child.replace(0, np.nan) * 100
    ok1 = r1.notna() & dv.notna(); ok2 = r2.notna() & av.notna() & (child >= 30)
    ck.append(dict(시작구간=f"in_age_{st:03d}", 가정나이=f"{(st - 1) * 5}세 이상", 합계=float(filled[[c for c in range(st, 22)]].sum().sum()), 노년부양비_상관=np.corrcoef(r1[ok1], dv[ok1])[0, 1], 노년부양비_절대차_중앙값=float((r1 - dv)[ok1].abs().median()), 노령화지수_상관=np.corrcoef(r2[ok2], av[ok2])[0, 1], 노령화지수_절대차_중앙값=float((r2 - av)[ok2].abs().median()), 집계구수=int(ok1.sum())))
ck = pd.DataFrame(ck); ck.to_csv(OUT / "d6_age_code_check.csv", index=False, encoding="utf-8-sig"); print(ck.round(4).to_string())
OLD = list(range(14, 22))
o = pd.DataFrame({"oa": tot.index, "tot": tot.values, "pop65_lo": filled[OLD].sum(axis=1).values, "miss_bins": w[OLD].isna().sum(axis=1).values})
o["pop65_hi"] = np.minimum(o.pop65_lo + 4 * o.miss_bins, o.tot.clip(lower=o.pop65_lo))
o["has_age"] = o.oa.isin(set(a.oa))
o.to_parquet(SCRATCH / "oa65.parquet", index=False)
print(o[["tot", "pop65_lo", "pop65_hi"]].sum(), "65+ 있는 집계구", int((o.pop65_lo > 0).sum()), "연령자료 없는 집계구", int((~o.has_age).sum()), "그 총인구", float(o[~o.has_age].tot.sum()))
d25 = gpd.read_file(D9_2025); d24 = gpd.read_file(D9_2024); d16 = gpd.read_file(D9_2016_OA)
sets = {"D9 집계구 경계 2025 2Q (TOT_OA_CD, 14자리)": set(d25.TOT_OA_CD), "D9 집계구 경계 2024 2Q (TOT_REG_CD, 14자리)": set(d24.TOT_REG_CD), "D9 집계구 경계 2016 (TOT_REG_CD, 13자리)": set(d16.TOT_REG_CD)}
mr = []
for k, s in sets.items():
    in_b = o.oa.isin(s); age = o[o.has_age]; ain = age.oa.isin(s)
    mr.append(dict(경계=k, 경계_집계구=len(s), D6_총인구파일_집계구=len(o), 일치=int(in_b.sum()), 일치율=float(in_b.mean()), D6_연령자료_집계구=len(age), 연령자료_일치=int(ain.sum()), 연령자료_일치율=float(ain.mean()), 경계_중_D6있음=len(s & set(o.oa)) / len(s), 인구65_가중_일치율=float(age[ain].pop65_lo.sum() / age.pop65_lo.sum()) if ain.sum() else 0))
pd.DataFrame(mr).to_csv(OUT / "d6_boundary_match.csv", index=False, encoding="utf-8-sig"); print(pd.DataFrame(mr).round(4).T.to_string())
