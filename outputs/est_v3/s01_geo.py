"""s01_geo.py - 정류장(2024·2025판)에 행정동·자치구 배정. 경계 밖 정류장은 가장 가까운 행정동(사용자 지정).

출력(스크래치): geo/stops_2024.parquet, stops_2025.parquet / 요약: s01_geo_summary.csv
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import pandas as pd, geopandas as gpd

G = SCRATCH / "geo"; G.mkdir(parents=True, exist_ok=True)
CRS = "EPSG:5179"
dong = gpd.read_file(DONG_SHP).set_crs(CRS, allow_override=True)[["ADM_CD", "SIGUNGU_CD", "geometry"]].rename(columns={"ADM_CD": "dong7", "SIGUNGU_CD": "gu5"})


def xlsx(name):
    d = pd.read_excel(D21_DIR / name, dtype=str)
    return pd.DataFrame({"node": d.NODE_ID.str.strip(), "ars": d.ARS_ID.str.strip(), "name": d["정류소명"],
                         "lon": pd.to_numeric(d["X좌표"]), "lat": pd.to_numeric(d["Y좌표"]), "stype": d["정류소타입"]})


rows = []
for y, f in D21_VINTAGE.items():
    s = xlsx(f)
    for a, of in D21_OVERRIDE.items():
        o = xlsx(of).query("ars == @a").iloc[0]
        s.loc[s.ars == a, ["lon", "lat"]] = [o.lon, o.lat]
    s = s[s.ars.str[:2].isin(SEOUL_ARS) & ~s.stype.eq("가상정류장")].copy()
    g = gpd.GeoDataFrame(s, geometry=gpd.points_from_xy(s.lon, s.lat), crs=4326).to_crs(CRS)
    j = gpd.sjoin(g, dong, how="left", predicate="within").drop(columns="index_right")
    j = j[~j.index.duplicated()]
    miss = j[j.dong7.isna()]
    n = gpd.sjoin_nearest(miss.drop(columns=["dong7", "gu5"]), dong, how="left", distance_col="dist")
    n = n[~n.index.duplicated()]
    j.loc[n.index, ["dong7", "gu5"]] = n[["dong7", "gu5"]].to_numpy()
    j["dong_nearest"] = j.index.isin(n.index)
    j["x"] = j.geometry.x; j["y"] = j.geometry.y
    pd.DataFrame(j.drop(columns="geometry")).to_parquet(G / f"stops_{y}.parquet", index=False)
    rows.append(dict(판본=y, 대상정류장=len(j), 경계밖_최근접배정=len(n), 최근접거리_최대m=float(n.dist.max()), 동미배정_남음=int(j.dong7.isna().sum()), 자치구수=j.gu5.nunique()))
    print(n[["ars", "name", "dong7", "gu5", "dist"]].round(1).to_string())
pd.DataFrame(rows).to_csv(OUT / "s01_geo_summary.csv", index=False, encoding="utf-8-sig")
print(pd.DataFrame(rows).T.to_string()); print(sorted(j.gu5.unique())[:5])
