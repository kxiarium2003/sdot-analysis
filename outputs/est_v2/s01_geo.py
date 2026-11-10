"""s01_geo.py - 정류장·역을 행정동(2016 경계, D5·D12와 같은 7자리)·집계구에 연결.

출력(스크래치): geo/stops_2024.parquet, stops_2025.parquet, stations.parquet,
              station_oa.parquet(역×반경×집계구), stop_oa_counts.parquet
출력(요약): s01_geo_summary.csv
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import pandas as pd, geopandas as gpd

G = SCRATCH / "geo"; G.mkdir(parents=True, exist_ok=True)
CRS = "EPSG:5179"  # readme: UTM-K(GRS80)
dong = gpd.read_file(DONG_SHP).set_crs(CRS, allow_override=True)[["ADM_CD", "SIGUNGU_CD", "geometry"]].rename(columns={"ADM_CD": "dong7", "SIGUNGU_CD": "gu5"})
oa = gpd.read_file(OA_SHP).set_crs(CRS, allow_override=True)[["TOT_REG_CD", "geometry"]].rename(columns={"TOT_REG_CD": "oa"})
centroid = oa.assign(geometry=oa.centroid)
oa25 = gpd.read_file(OA2025_DIR)[["ADM_CD", "geometry"]].to_crs(CRS)
oa25["gu_d9"] = oa25.ADM_CD.str[:5]


def xlsx(name):
    d = pd.read_excel(D21_DIR / name, dtype=str)
    return pd.DataFrame({"node": d.NODE_ID.str.strip(), "ars": d.ARS_ID.str.strip(), "name": d["정류소명"],
                         "lon": pd.to_numeric(d["X좌표"]), "lat": pd.to_numeric(d["Y좌표"]), "stype": d["정류소타입"]})


def pts(df):
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs=4326).to_crs(CRS)


def attach(g):
    j = gpd.sjoin(g, dong, how="left", predicate="within").drop(columns="index_right")
    return j[~j.index.duplicated()]


summary = []
for y, f in D21_VINTAGE.items():
    s = xlsx(f)
    n0 = len(s)
    for a, of in D21_OVERRIDE.items():
        o = xlsx(of).query("ars == @a").iloc[0]
        s.loc[s.ars == a, ["lon", "lat"]] = [o.lon, o.lat]
    is_seoul_ars = s.ars.str[:2].isin(SEOUL_ARS)
    virt = s.stype.eq("가상정류장")
    s = s[is_seoul_ars & ~virt].copy()
    g = attach(pts(s))
    g["n_oa300"] = 0
    for r in (300, 500):
        b = g[["node", "geometry"]].copy()
        b["geometry"] = g.buffer(r)
        c = gpd.sjoin(b, centroid, how="left", predicate="contains")
        n = c.dropna(subset=["oa"]).groupby("node").oa.nunique()
        g[f"n_oa{r}"] = g.node.map(n).fillna(0).astype(int)
        ic = gpd.sjoin(b, oa, how="left", predicate="intersects")
        g[f"n_oa{r}_intersects"] = g.node.map(ic.dropna(subset=["oa"]).groupby("node").oa.nunique()).fillna(0).astype(int)
    out = pd.DataFrame(g.drop(columns="geometry"))
    out.to_parquet(G / f"stops_{y}.parquet")
    summary.append(dict(판본=y, D21행=n0, ARS01_25제외전=int(is_seoul_ars.sum()), 가상제외수=int((is_seoul_ars & virt).sum()), 대상정류장=len(out),
                        동미배정=int(out.dong7.isna().sum()), 반경300집계구없음_중심점=int((out.n_oa300 == 0).sum()), 반경500집계구없음_중심점=int((out.n_oa500 == 0).sum()),
                        반경300집계구없음_교차=int((out.n_oa300_intersects == 0).sum()), 반경500집계구없음_교차=int((out.n_oa500_intersects == 0).sum()),
                        반경300집계구수_중앙=float(out.n_oa300.median()), 반경500집계구수_중앙=float(out.n_oa500.median())))
pd.DataFrame(summary).to_csv(OUT / "s01_geo_summary.csv", index=False, encoding="utf-8-sig")
print(pd.DataFrame(summary).T.to_string())

# stations
dj = json.load(open(D22_JSON, encoding="utf-8"))
k = list(dj)[0]
d = pd.DataFrame(dj[k]["row"])
st = pd.DataFrame({"bldn": d.BLDN_ID.str.strip(), "name": d.BLDN_NM, "route": d.ROUTE, "lat": pd.to_numeric(d.LAT), "lon": pd.to_numeric(d.LOT)})
g = attach(pts(st))
j = gpd.sjoin(g[["bldn", "geometry"]], oa25[["gu_d9", "geometry"]], how="left", predicate="within").drop_duplicates("bldn")
g["gu_d9"] = g.bldn.map(j.set_index("bldn").gu_d9)
g["seoul_d9"] = g.gu_d9.notna()
g["gu_final"] = g.gu_d9.fillna(g.gu5)
out = pd.DataFrame(g.drop(columns="geometry"))
out.to_parquet(G / "stations.parquet")
print("D22", len(out), "seoul_d9", int(out.seoul_d9.sum()), "동배정", int(out.dong7.notna().sum()))
rows = []
for r in (300, 500):
    b = g[g.dong7.notna()][["bldn", "geometry"]].copy()
    b["geometry"] = b.buffer(r)
    c = gpd.sjoin(b, centroid, how="left", predicate="contains").dropna(subset=["oa"])
    x = pd.DataFrame(c[["bldn", "oa"]]); x["radius"] = r; x["method"] = "centroid"
    # 중심점이 하나도 없는 역은 반경과 겹치는 집계구로 보완(method=intersects)
    miss = b[~b.bldn.isin(x.bldn)]
    ic = gpd.sjoin(miss, oa, how="left", predicate="intersects").dropna(subset=["oa"])
    y = pd.DataFrame(ic[["bldn", "oa"]]); y["radius"] = r; y["method"] = "intersects"
    rows += [x, y]
    print("radius", r, "centroid stations", x.bldn.nunique(), "intersects fallback stations", y.bldn.nunique())
pd.concat(rows, ignore_index=True).to_parquet(G / "station_oa.parquet")
