"""s02_cover.py - 정적·동적 커버율. 쉼터 D7 무더위쉼터 목록(20250916), 반경 300m 직선거리(EPSG:5179).

정적: D9 집계구 경계 2025 2Q 중심점이 무더위쉼터 300m 안이면 D6 SGIS 집계구 인구 데이터 65+ 전체 커버. 스마트쉼터 제외.
동적: est_v3 2025-07·08 11~17시 65+ 승차(중간) 하루 평균. (i) 무더위쉼터만 (ii) 스마트쉼터 정류장 또는 무더위쉼터 300m.
행정동·자치구: D9 집계구 경계 2025 2Q의 ADM_CD(8자리)로 통일. 정류장은 공간 조인, 경계 밖은 최근접.
출력: table_city.csv, table_gu.csv, table_gu_rank_corr.csv, table_dong_all.csv, table_hidden_gap_top20.csv, cover_check_est_v3.csv / 스크래치: dong.parquet(지도용)
"""
import sys, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd, geopandas as gpd, duckdb
from scipy.spatial import cKDTree
from scipy.stats import spearmanr

oa = gpd.read_file(D9_2025).to_crs(5179)[["ADM_CD", "TOT_OA_CD", "geometry"]].rename(columns={"TOT_OA_CD": "oa", "ADM_CD": "dong"})
dong = oa.dissolve("dong").reset_index()[["dong", "geometry"]]
dong["gu5"] = dong.dong.str[:5]; dong["gu"] = dong.gu5.map(GU_NAMES)
# 행정동 이름: 2016 경계와 가장 많이 겹치는 동
d16 = gpd.read_file(D9_2016_DONG).set_crs(5179, allow_override=True)[["ADM_CD", "ADM_NM", "geometry"]]
ov = gpd.overlay(dong[["dong", "geometry"]], d16, how="intersection", keep_geom_type=True); ov["a"] = ov.area
top = ov.sort_values("a", ascending=False).drop_duplicates("dong").set_index("dong")
dong["name"] = dong.dong.map(top.ADM_NM); dong["name_share"] = dong.dong.map(top.a) / dong.area.values
dong["name_code_match"] = dong.dong.map(top.ADM_CD) == dong.dong.str[:7]
print("행정동", len(dong), "이름 코드 앞7자리와 일치", int(dong.name_code_match.sum()), "겹침<0.9", int((dong.name_share < .9).sum()))
print(dong[(~dong.name_code_match) | (dong.name_share < .9)][["dong", "name", "name_share", "name_code_match"]].to_string())
c = pd.read_excel(COOL, header=None, dtype=str); h = c.iloc[4].tolist(); lo, la = h.index("경도"), h.index("위도"); t = c.iloc[5:]
cool = pd.DataFrame({"name": t[1], "lon": pd.to_numeric(t[lo], errors="coerce"), "lat": pd.to_numeric(t[la], errors="coerce")}); cool = cool[cool.name.notna()].dropna(subset=["lon", "lat"])
g = gpd.GeoDataFrame(cool, geometry=gpd.points_from_xy(cool.lon, cool.lat), crs=4326).to_crs(5179)
seoul = d16.union_all(); g = g[g.within(seoul)]; cxy = np.c_[g.geometry.x, g.geometry.y]; tree = cKDTree(cxy); print("무더위쉼터", len(g))
near = lambda xy: np.array([len(n) > 0 for n in tree.query_ball_point(xy, r=R)])
# 정적
pop = pd.read_parquet(SCRATCH / "oa65.parquet")
oc = oa.merge(pop, on="oa", how="left"); c0 = oc.centroid
oc["x"] = c0.x; oc["y"] = c0.y; oc["cov"] = near(np.c_[oc.x, oc.y])
oc[["pop65_lo", "pop65_hi", "tot"]] = oc[["pop65_lo", "pop65_hi", "tot"]].fillna(0)
oc["gu"] = oc.dong.str[:5].map(GU_NAMES)
print("D9 집계구", len(oc), "D6 없는 집계구", int(oc.tot.eq(0).sum()), "중심점 커버", int(oc["cov"].sum()))
# 동적
def xl(n):
    d = pd.read_excel(D21_DIR / n, dtype=str)
    return pd.DataFrame({"node": d.NODE_ID.str.strip(), "ars": d.ARS_ID.str.strip(), "sname": d["정류소명"], "lon": pd.to_numeric(d["X좌표"]), "lat": pd.to_numeric(d["Y좌표"]), "stype": d["정류소타입"]})
s = xl("서울시버스정류소위치정보(20250801).xlsx")
for a, of in {"09642": "서울시버스정류소위치정보(20251117).xlsx", "05229": "서울시버스정류소위치정보(20260902).xlsx"}.items():
    o = xl(of).query("ars == @a").iloc[0]; s.loc[s.ars == a, ["lon", "lat"]] = [o.lon, o.lat]
s = s[s.ars.str[:2].isin({f"{i:02d}" for i in range(1, 26)}) & ~s.stype.eq("가상정류장")].copy()
gs = gpd.GeoDataFrame(s, geometry=gpd.points_from_xy(s.lon, s.lat), crs=4326).to_crs(5179)
j = gpd.sjoin(gs, dong[["dong", "gu", "geometry"]], how="left", predicate="within").drop(columns="index_right"); j = j[~j.index.duplicated()]
ms = j[j.dong.isna()]
nn = gpd.sjoin_nearest(ms.drop(columns=["dong", "gu"]), dong[["dong", "gu", "geometry"]], how="left", distance_col="dist"); nn = nn[~nn.index.duplicated()]
j.loc[nn.index, ["dong", "gu"]] = nn[["dong", "gu"]].to_numpy()
print("정류장", len(j), "경계 밖 최근접", len(nn), "최대거리", round(float(nn.dist.max()), 1))
f = sorted(glob.glob(str(SCRATCH / "raw/est/est_20250[78].parquet"))); assert len(f) == 2, f
cn = duckdb.connect(); fl = "[" + ",".join(f"'{x}'" for x in f) + "]"
nd = cn.execute(f"SELECT count(DISTINCT date) FROM read_parquet({fl})").fetchone()[0]
w = cn.execute(f"SELECT node, SUM(CASE WHEN hour BETWEEN 11 AND 17 THEN board65_mid ELSE 0 END)/{nd} w FROM read_parquet({fl}) GROUP BY 1").df()
st = pd.DataFrame(j.drop(columns="geometry")).merge(w, on="node", how="left").fillna({"w": 0})
st["x"] = j.geometry.x.values; st["y"] = j.geometry.y.values
L = pd.read_csv(EST3 / "s07_smart_link_2025.csv", dtype={"node": str, "ars": str}); okc = "D21 서울시 버스정류소 위치정보 ARS 일치"
smart = set(L[L[okc] & ~L["공사중"] & (L["설치년도"].astype(int) <= 2025)].node.dropna())
st["smart"] = st.node.isin(smart); st["cool"] = near(np.c_[st.x, st.y]); st["any"] = st.smart | st.cool
print("일수", nd, "스마트", len(smart), "w합", round(st.w.sum()), "커버 정류장", int(st["any"].sum()), "미커버", int((~st["any"]).sum()))
# est_v3 재현 점검
e3 = pd.read_csv(EST3 / "o1_coverage_city.csv", dtype={"연도": str}); e3 = e3[(e3.연도 == "2025") & (e3.반경 == 300) & e3.기준.str.startswith("w65(")].iloc[0]
chk = pd.DataFrame([dict(항목="w 합", 재계산=st.w.sum(), est_v3=e3.총량_하루), dict(항목="무더위쉼터 커버율", 재계산=st.w[st.cool].sum() / st.w.sum(), est_v3=e3.b무더위), dict(항목="커버율(스마트 포함)", 재계산=st.w[st["any"]].sum() / st.w.sum(), est_v3=e3.c합), dict(항목="미커버 정류장", 재계산=int((~st["any"]).sum()), est_v3=e3.정류장_d)])
chk.to_csv(OUT / "cover_check_est_v3.csv", index=False, encoding="utf-8-sig"); print(chk.to_string())
# 서울
sr = lambda n, v, m: dict(기준=n, 단위=v[0], 총량=v[1], 커버량=v[2], 커버율=v[2] / v[1], 미커버량=v[1] - v[2], 대상수=v[3], 대상_커버=m)
city = pd.DataFrame([
    sr("정적: D6 SGIS 집계구 인구 데이터 65+ 거주(무더위쉼터 300m)", ("명", oc.pop65_lo.sum(), oc.pop65_lo[oc["cov"]].sum(), len(oc)), int(oc["cov"].sum())),
    sr("정적: 마스킹 상한(없는 연령 구간 4)", ("명", oc.pop65_hi.sum(), oc.pop65_hi[oc["cov"]].sum(), len(oc)), int(oc["cov"].sum())),
    sr("동적: 65+ 버스 승차(무더위쉼터만)", ("명/일 승차", st.w.sum(), st.w[st.cool].sum(), len(st)), int(st.cool.sum())),
    sr("동적: 65+ 버스 승차(스마트쉼터 포함, est_v3 정의)", ("명/일 승차", st.w.sum(), st.w[st["any"]].sum(), len(st)), int(st["any"].sum()))])
city.to_csv(OUT / "table_city.csv", index=False, encoding="utf-8-sig"); print(city.round(4).to_string())
def agg(keys):
    a = oc.assign(c=oc.pop65_lo * oc["cov"]).groupby(keys).agg(정적_65인구=("pop65_lo", "sum"), 정적_커버인구=("c", "sum"))
    b = st.assign(wc=st.w * st.cool, wa=st.w * st["any"]).groupby(keys).agg(동적_w=("w", "sum"), 동적_무더위커버=("wc", "sum"), 동적_전체커버=("wa", "sum"), 정류장수=("node", "count"))
    t = a.join(b, how="outer").fillna({"정적_65인구": 0, "정적_커버인구": 0, "동적_w": 0, "동적_무더위커버": 0, "동적_전체커버": 0, "정류장수": 0}).reset_index()
    t["정적커버율"] = t.정적_커버인구 / t.정적_65인구.replace(0, np.nan)
    t["동적커버율_무더위만"] = t.동적_무더위커버 / t.동적_w.replace(0, np.nan)
    t["동적커버율_스마트포함"] = t.동적_전체커버 / t.동적_w.replace(0, np.nan)
    t["차이_무더위만"] = t.동적커버율_무더위만 - t.정적커버율; t["차이_스마트포함"] = t.동적커버율_스마트포함 - t.정적커버율
    t["동적미커버_스마트포함"] = t.동적_w - t.동적_전체커버; t["동적미커버_무더위만"] = t.동적_w - t.동적_무더위커버
    return t
gu = agg("gu").sort_values("차이_스마트포함").reset_index(drop=True)
for c0, nm in (("정적커버율", "순위_정적"), ("동적커버율_무더위만", "순위_동적_무더위만"), ("동적커버율_스마트포함", "순위_동적_스마트포함")):
    gu[nm] = gu[c0].rank(ascending=False, method="min").astype(int)
gu.to_csv(OUT / "table_gu.csv", index=False, encoding="utf-8-sig"); print(gu.round(3).to_string())
dn = agg("dong").merge(dong[["dong", "gu", "name", "name_share", "name_code_match"]], on="dong", how="left")
def corr(t, lv):
    out = []
    for c0, nm in (("동적커버율_무더위만", "정적 vs 동적(무더위쉼터만)"), ("동적커버율_스마트포함", "정적 vs 동적(스마트쉼터 포함)")):
        ok = t.정적커버율.notna() & t[c0].notna(); r = spearmanr(t.정적커버율[ok], t[c0][ok])
        out.append(dict(단위=lv, 비교=nm, N=int(ok.sum()), 스피어만=r.statistic, p값=r.pvalue))
    return out
rc = pd.DataFrame(corr(gu, "자치구") + corr(dn, "행정동")); rc.to_csv(OUT / "table_gu_rank_corr.csv", index=False, encoding="utf-8-sig"); print(rc.round(4).to_string())
med = dn.정적커버율.median(); print("행정동 정적 커버율 중앙값", med, "자격 행정동", int((dn.정적커버율 >= med).sum()))
dn["정적_중앙값이상"] = dn.정적커버율 >= med; dn = dn.sort_values("동적미커버_스마트포함", ascending=False)
dn.to_csv(OUT / "table_dong_all.csv", index=False, encoding="utf-8-sig")
un = st[~st["any"]].sort_values("w", ascending=False)
ug = un.groupby("dong").agg(미커버정류장수=("node", "count"), 최대미커버정류장=("sname", "first"), 최대미커버정류장_ars=("ars", "first"), 최대미커버정류장_w=("w", "first"))
dn = dn.merge(ug, on="dong", how="left"); dn["최대정류장_몫"] = dn.최대미커버정류장_w / dn.동적미커버_스마트포함.replace(0, np.nan)
dn = dn.sort_values("동적미커버_스마트포함", ascending=False); dn.to_csv(OUT / "table_dong_all.csv", index=False, encoding="utf-8-sig")
hid = dn[dn.정적_중앙값이상].head(20).copy(); hid.insert(0, "순위", range(1, 21))
hid2 = hid[["순위", "gu", "name", "dong", "정적커버율", "동적커버율_무더위만", "동적커버율_스마트포함", "동적미커버_스마트포함", "동적미커버_무더위만", "동적_w", "정적_65인구", "정류장수", "미커버정류장수", "최대미커버정류장", "최대미커버정류장_w", "최대정류장_몫", "name_share", "name_code_match"]]
hid2.to_csv(OUT / "table_hidden_gap_top20.csv", index=False, encoding="utf-8-sig"); print(hid2.round(3).to_string())
print("정적 없음/동적 없음 행정동", dn[dn.정적커버율.isna()][["dong", "name"]].values.tolist(), dn[dn.동적커버율_무더위만.isna()][["dong", "name"]].values.tolist())
print("상위20 미커버 합", hid2.동적미커버_스마트포함.sum(), "전체 미커버 중", hid2.동적미커버_스마트포함.sum() / st.w[~st["any"]].sum(), "자격 행정동 미커버 합", dn[dn.정적_중앙값이상].동적미커버_스마트포함.sum())
dg = dong.merge(dn[["dong", "정적커버율", "동적커버율_무더위만", "동적커버율_스마트포함", "차이_무더위만", "차이_스마트포함", "동적_w", "정류장수", "정적_중앙값이상"]], on="dong", how="left")
dg["순위"] = dg.dong.map(dict(zip(hid2.dong, hid2.순위)))
dg.to_parquet(SCRATCH / "dong.parquet")
