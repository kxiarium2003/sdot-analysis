"""s02 - 9자리 정류장 ID -> 자치구(ID 앞 3자리), 행정동(좌표, 2016 경계) 연결표.

좌표: D21 2025-08-01판(+ est_v2와 같은 좌표 보정 2건), D21에 없으면 D23 정류장마스터.
출력: SCRATCH/stop_geo.parquet
사용: python3 -I s02_stop_geo.py <SCRATCH>
"""
import sys, json, glob
from pathlib import Path
import pandas as pd, geopandas as gpd

ROOT = Path(__file__).resolve().parents[2]
SCR = Path(sys.argv[1])
RAW = ROOT / "data/raw"
D21 = RAW / "D21_bus_stop_location"


def xlsx(name):
    d = pd.read_excel(D21 / name, dtype=str)
    return pd.DataFrame({"node": d.NODE_ID.str.strip(), "ars": d.ARS_ID.str.strip(), "name": d["정류소명"],
                         "lon": pd.to_numeric(d["X좌표"]), "lat": pd.to_numeric(d["Y좌표"]), "stype": d["정류소타입"]})


s = xlsx("서울시버스정류소위치정보(20250801).xlsx")
for a, f in {"09642": "서울시버스정류소위치정보(20251117).xlsx", "05229": "서울시버스정류소위치정보(20260902).xlsx"}.items():
    o = xlsx(f).query("ars == @a").iloc[0]
    s.loc[s.ars == a, ["lon", "lat"]] = [o.lon, o.lat]
s["src"] = "D21_20250801"
rows = []
for f in sorted(glob.glob(str(RAW / "D23_stop_master/tbisMasterStation_*.json"))):
    j = json.load(open(f))
    rows += j["tbisMasterStation"]["row"]
d23 = pd.DataFrame(rows)
d23 = pd.DataFrame({"node": d23.CRTR_ID.astype(str), "ars": d23.CRTR_NO.astype(str), "name": d23.CRTR_NM,
                    "lon": pd.to_numeric(d23.LOT), "lat": pd.to_numeric(d23.LAT), "stype": d23.CRTR_TYPE, "src": "D23"})
allst = pd.concat([s, d23[~d23.node.isin(s.node)]], ignore_index=True)
g = gpd.GeoDataFrame(allst, geometry=gpd.points_from_xy(allst.lon, allst.lat), crs=4326).to_crs("EPSG:5179")
dong = gpd.read_file(RAW / "D9_zone_boundary/seoul_census_oa_boundary_2016/행정구역.shp").set_crs("EPSG:5179", allow_override=True)
dong = dong[["ADM_CD", "ADM_NM", "SIGUNGU_CD", "SIGUNGU_NM", "geometry"]]
j = gpd.sjoin(g, dong, how="left", predicate="within").drop(columns="index_right")
j = j[~j.index.duplicated()]
gu = pd.read_excel(RAW / "D23_stop_master/자치구정류장코드분류.xlsx", dtype=str)
gu_map = dict(zip(gu["정류장ID(앞3자리)"], gu["자치구"]))
out = pd.DataFrame(j.drop(columns="geometry"))
out["gu_by_id"] = out.node.str[:3].map(gu_map)
out = out.rename(columns={"ADM_CD": "dong7", "ADM_NM": "dong_nm", "SIGUNGU_NM": "gu_by_xy"})
out.to_parquet(SCR / "stop_geo.parquet", index=False)
print(len(out), out.src.value_counts().to_dict(), "dong NA", int(out.dong7.isna().sum()),
      "gu id==xy", round((out.gu_by_id == out.gu_by_xy).mean(), 4))
