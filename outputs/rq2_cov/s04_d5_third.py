"""s04_d5_third.py - 세 번째 기준: D5 집계구 생활인구 데이터 내국인 65+ 11~17시(시 라벨 7개) 2025-07·08 평균. 마스킹 하한 0 / 상한 4.

D5 집계구코드(13자리)는 D9 집계구 경계 2016과 맞는다. 그 중심점이 무더위쉼터 300m 안이면 그 집계구 생활인구 커버. 행정동은 중심점이 속한 2025 2Q 행정동(밖이면 최근접).
출력: table_d5_city.csv, table_d5_gu.csv, table_d5_rank_corr.csv, d5_match.csv
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd, geopandas as gpd, duckdb
from scipy.spatial import cKDTree
from scipy.stats import spearmanr

con = duckdb.connect(); con.execute(f"SET memory_limit='8GB'; SET threads=4; SET temp_directory='{SCRATCH}/duck_tmp'")
FL = "[" + ",".join(f"'{SCRATCH}/raw/d5/{m}.parquet'" for m in ("202507", "202508")) + "]"
cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({FL})").fetchall()]
print([c for c in cols if "suppressed" not in c][:12], len(cols))
OLD = ["남자65세부터69세생활인구수", "여자65세부터69세생활인구수", "남자70세이상생활인구수", "여자70세이상생활인구수"]
dc = [c for c in cols if "기준일ID" in c and "suppressed" not in c][0]
lo = " + ".join(f'COALESCE("{c}",0)' for c in OLD); hi = " + ".join(f'COALESCE("{c}",4)' for c in OLD)
hr = "CAST(시간대구분 AS INT)"
dq = '"' + dc.replace('"', '""') + '"'  # 열 이름에 큰따옴표가 들어 있음
ndays = con.execute(f"SELECT count(DISTINCT {dq}) FROM read_parquet({FL})").fetchone()[0]
slots = ndays * 7
print("days", ndays, "slots", slots)
mask = con.execute(f"""SELECT AVG(CASE WHEN {" OR ".join(f'"{c}" IS NULL' for c in OLD)} THEN 1.0 ELSE 0 END) any_null, count(*) n, count(DISTINCT 집계구코드) oas FROM read_parquet({FL}) WHERE {hr} BETWEEN 11 AND 17""").df().iloc[0].to_dict(); print(mask)
d = con.execute(f"SELECT 집계구코드 oa, SUM({lo})/{slots} lo, SUM({hi})/{slots} hi FROM read_parquet({FL}) WHERE {hr} BETWEEN 11 AND 17 GROUP BY 1").df()
oa16 = gpd.read_file(D9_2016_OA).set_crs(5179, allow_override=True)[["TOT_REG_CD", "geometry"]].rename(columns={"TOT_REG_CD": "oa"})
c0 = oa16.assign(geometry=oa16.centroid)
print("D5 집계구", len(d), "2016 경계", len(c0), "일치", d.oa.isin(set(c0.oa)).sum(), "경계 중 일치", c0.oa.isin(set(d.oa)).mean())
pd.DataFrame([dict(항목="D5 집계구", 값=len(d)), dict(항목="D9 집계구 경계 2016 집계구", 값=len(c0)), dict(항목="일치", 값=int(d.oa.isin(set(c0.oa)).sum())), dict(항목="일수", 값=ndays), dict(항목="65+ 열 하나라도 마스킹 비율(11~17시)", 값=mask["any_null"])]).to_csv(OUT / "d5_match.csv", index=False, encoding="utf-8-sig")
c = pd.read_excel(COOL, header=None, dtype=str); h = c.iloc[4].tolist(); lon, lat = h.index("경도"), h.index("위도"); t = c.iloc[5:]
cool = pd.DataFrame({"name": t[1], "lon": pd.to_numeric(t[lon], errors="coerce"), "lat": pd.to_numeric(t[lat], errors="coerce")}); cool = cool[cool.name.notna()].dropna(subset=["lon", "lat"])
g = gpd.GeoDataFrame(cool, geometry=gpd.points_from_xy(cool.lon, cool.lat), crs=4326).to_crs(5179)
seoul = gpd.read_file(D9_2016_DONG).set_crs(5179, allow_override=True).union_all(); g = g[g.within(seoul)]
tree = cKDTree(np.c_[g.geometry.x, g.geometry.y]); print("쉼터", len(g))
c0["cov"] = [len(n) > 0 for n in tree.query_ball_point(np.c_[c0.geometry.x, c0.geometry.y], r=R)]
oa25 = gpd.read_file(D9_2025).to_crs(5179)[["ADM_CD", "geometry"]].rename(columns={"ADM_CD": "dong"}); dg = oa25.dissolve("dong").reset_index()
j = gpd.sjoin(c0, dg, how="left", predicate="within").drop(columns="index_right"); j = j[~j.index.duplicated()]
ms = j[j.dong.isna()]
if len(ms):
    n = gpd.sjoin_nearest(ms.drop(columns="dong"), dg, how="left").drop(columns="index_right"); n = n[~n.index.duplicated()]; j.loc[n.index, "dong"] = n.dong.values
print("2025 동 밖 중심점", len(ms))
x = pd.DataFrame(j.drop(columns="geometry")).merge(d, on="oa", how="left").fillna({"lo": 0, "hi": 0}); x["gu"] = x.dong.str[:5].map(GU_NAMES)
sr = lambda col, tag: dict(기준=f"D5 집계구 생활인구 데이터 내국인 65+ 11~17시 ({tag})", 총량=x[col].sum(), 커버량=x[col][x["cov"]].sum(), 커버율=x[col][x["cov"]].sum() / x[col].sum(), 미커버량=x[col][~x["cov"]].sum(), 집계구=len(x), 집계구_커버=int(x["cov"].sum()))
ct = pd.DataFrame([sr("lo", "마스킹 하한 0"), sr("hi", "마스킹 상한 4")]); ct.to_csv(OUT / "table_d5_city.csv", index=False, encoding="utf-8-sig"); print(ct.round(4).to_string())
def rate(k):
    return x.assign(cl=x.lo * x["cov"], ch=x.hi * x["cov"]).groupby(k).agg(lo=("lo", "sum"), cl=("cl", "sum"), hi=("hi", "sum"), ch=("ch", "sum")).assign(d5_하한=lambda t: t.cl / t.lo.replace(0, np.nan), d5_상한=lambda t: t.ch / t.hi.replace(0, np.nan)).reset_index()
g1 = rate("gu"); gu6 = pd.read_csv(OUT / "table_gu.csv")
g2 = g1.merge(gu6[["gu", "정적커버율", "동적커버율_무더위만", "동적커버율_스마트포함"]], on="gu"); g2["차이_D5하한_정적"] = g2.d5_하한 - g2.정적커버율; g2["차이_동적무더위_D5하한"] = g2.동적커버율_무더위만 - g2.d5_하한
g2.sort_values("차이_동적무더위_D5하한").to_csv(OUT / "table_d5_gu.csv", index=False, encoding="utf-8-sig"); print(g2.round(3).to_string())
dn6 = pd.read_csv(OUT / "table_dong_all.csv", dtype={"dong": str}); dn = rate("dong").merge(dn6[["dong", "정적커버율", "동적커버율_무더위만"]], on="dong")
rc = []
for lv, t in (("자치구", g2), ("행정동", dn)):
    for a, b, nm in (("d5_하한", "정적커버율", "D5 생활인구(하한) vs 정적"), ("d5_하한", "동적커버율_무더위만", "D5 생활인구(하한) vs 동적(무더위쉼터만)"), ("정적커버율", "동적커버율_무더위만", "정적 vs 동적(무더위쉼터만)")):
        ok = t[a].notna() & t[b].notna(); r = spearmanr(t[a][ok], t[b][ok]); rc.append(dict(단위=lv, 비교=nm, N=int(ok.sum()), 스피어만=r.statistic, p값=r.pvalue))
pd.DataFrame(rc).to_csv(OUT / "table_d5_rank_corr.csv", index=False, encoding="utf-8-sig"); print(pd.DataFrame(rc).round(4).to_string())
