"""s02b - (s02 수정본) 분석 연도 행정동 경계로 TOPIS 동별 버스 비율과 정류장 -> 행정동 연결을 다시 만든다.

경계: 2024-07·08 -> D9 bnd_oa_11_2024_2Q, 2025-07·08 -> D9 bnd_oa_11_2025_2Q. 집계구를 ADM_CD(8자리)로 합쳐 행정동 경계를 만든다.
이름표: 경계 파일에 이름이 없어 Drive data2/D9_zone_boundary/sgis_api_2025/2024/emd_*.geojson(SGIS OpenAPI 2024 읍면동, adm_cd·adm_nm)을 쓴다.
  세 코드 집합(이름표·2024_2Q·2025_2Q)이 426개로 같음을 확인하고 쓴다. 2025 이름은 2024 이름표와 같다고 본다.
동 이름 연결: s02와 같다. (구, 동 이름 공백 제거) 1단계, 안 맞으면 ','->'·' 2단계. 연결 안 된 동은 분모에서 뺀다.
정류장 좌표: 감사 작업 연결(outputs/bus65_v4_audit/s02_stop_geo.py 출력 stop_geo.parquet의 lon/lat)을 새 경계에 공간 결합.
D24 행정동 대체값: 감사 표 table_d24_stop_share_202508.csv의 정류장->정류장 경로·총계를 새 행정동으로 다시 합산.
입력: SCRATCH/stop_geo.parquet, SCRATCH/sgis2024/emd_*.geojson
출력: SCRATCH/dong_share_b.parquet, SCRATCH/stop_dong_{2024,2025}.parquet, SCRATCH/d24_dong_{2024,2025}.csv,
      outputs/bus65_v4/s02b_*.csv
사용: python3 -I s02b_dong_share.py <SCRATCH>
"""
import sys, glob
from pathlib import Path
import pandas as pd, geopandas as gpd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
AUD = ROOT / "outputs/bus65_v4_audit"
SCR = Path(sys.argv[1])
BND = {"2024": ROOT / "data/raw/D9_zone_boundary/bnd_oa_11_2024_2Q", "2025": ROOT / "data/raw/D9_zone_boundary/bnd_oa_11_2025_2Q"}

# ---- 이름표 (SGIS API 2024)
nm = pd.concat([gpd.read_file(f) for f in sorted(glob.glob(str(SCR / "sgis2024/emd_*.geojson")))])
nm = pd.DataFrame(nm.drop(columns="geometry"))
p = nm.adm_nm.str.split(" ", n=2, expand=True)
nm["gu"], nm["dong_nm"] = p[1], p[2]
nm["key"] = nm.dong_nm.str.replace(" ", "")
key = {(g, k): c for g, k, c in zip(nm.gu, nm.key, nm.adm_cd.astype(str))}
SEOUL = set(nm.gu)
name_of = dict(zip(nm.adm_cd.astype(str), nm.dong_nm))
gu_of = dict(zip(nm.adm_cd.astype(str), nm.gu))

# ---- 연도별 행정동 경계, 정류장 연결, D24 대체값
geo = pd.read_parquet(SCR / "stop_geo.parquet")[["node", "ars", "name", "lon", "lat", "src"]]
pts = gpd.GeoDataFrame(geo, geometry=gpd.points_from_xy(geo.lon, geo.lat), crs=4326).to_crs("EPSG:5179")
a = pd.read_csv(AUD / "table_d24_stop_share_202508.csv", dtype={"on_id": str})
bsum = []
for y, f in BND.items():
    oa = gpd.read_file(f).to_crs("EPSG:5179")
    dong = oa.dissolve(by="ADM_CD").reset_index()[["ADM_CD", "geometry"]]
    codes = set(dong.ADM_CD)
    j = gpd.sjoin(pts, dong, how="left", predicate="within").drop(columns="index_right")
    j = j[~j.index.duplicated()]
    sd = pd.DataFrame(j.drop(columns="geometry")).rename(columns={"ADM_CD": "dong8"})
    sd["dong_nm"] = sd.dong8.map(name_of)
    sd["gu"] = sd.dong8.map(gu_of)
    sd.to_parquet(SCR / f"stop_dong_{y}.parquet", index=False)
    d24 = a.merge(sd[["node", "dong8"]], left_on="on_id", right_on="node", how="left").groupby("dong8")[["n_ss", "eld_ss"]].sum()
    d24["r_dong"] = d24.eld_ss / d24.n_ss
    d24.to_csv(SCR / f"d24_dong_{y}.csv")
    d24.assign(dong_nm=d24.index.map(name_of), gu=d24.index.map(gu_of)).to_csv(OUT / f"s02b_d24_dong_{y}.csv", encoding="utf-8-sig")
    bsum.append(dict(year=y, boundary=f.name, oa=len(oa), dongs=len(dong), name_table_codes=len(set(name_of)), codes_eq_name_table=codes == set(name_of),
                     stops=len(sd), stops_no_dong=int(sd.dong8.isna().sum()), d24_dongs=len(d24), d24_dong_r_min=d24.r_dong.min(), d24_dong_r_max=d24.r_dong.max(),
                     d24_ss_stops_no_dong=int(a.on_id.isin(sd.loc[sd.dong8.isna(), "node"]).sum())))
pd.DataFrame(bsum).to_csv(OUT / "s02b_boundary_summary.csv", index=False, encoding="utf-8-sig")

# ---- TOPIS 동별 수단OD -> 날짜별 동 버스 비율
rows, um, summ = [], [], []
for ym in ["202407", "202408", "202507", "202508"]:
    for f in sorted(glob.glob(str(ROOT / f"data/transit_od/transit_od_{ym}/동별/수단OD/*.csv"))):
        t = pd.read_csv(f, encoding="cp949", dtype=str, usecols=["기준일자", "출발_구", "출발_동", "버스_승객수"])
        t["bus"] = pd.to_numeric(t["버스_승객수"]).fillna(0)
        t = t[t["출발_구"].isin(SEOUL)]
        g = t.groupby(["기준일자", "출발_구", "출발_동"], as_index=False).bus.sum()
        g["n1"] = g["출발_동"].str.replace(" ", "")
        g["dong8"] = [key.get((x, y)) for x, y in zip(g["출발_구"], g.n1)]
        g["level"] = g.dong8.notna().map({True: "1_공백제거", False: None})
        m2 = g.dong8.isna()
        g.loc[m2, "dong8"] = [key.get((x, y.replace(",", "·"))) for x, y in zip(g.loc[m2, "출발_구"], g.loc[m2, "n1"])]
        g.loc[m2 & g.dong8.notna(), "level"] = "2_쉼표→가운뎃점"
        g["date"] = g["기준일자"]
        um.append(g[g.dong8.isna()].assign(ym=ym))
        ok = g[g.dong8.notna()]
        s = ok.groupby(["date", "dong8"], as_index=False).bus.sum()
        s["share"] = s.bus / s.bus.sum()
        rows.append(s)
        summ.append(dict(ym=ym, date=g.date.iloc[0], seoul_gu_dongs=len(g), matched_lvl1=int((g.level == "1_공백제거").sum()),
                         matched_lvl2=int((g.level == "2_쉼표→가운뎃점").sum()), unmatched=int(g.dong8.isna().sum()),
                         bus_seoul_gu=g.bus.sum(), bus_unmatched=g.loc[g.dong8.isna(), "bus"].sum(),
                         dongs8=s.dong8.nunique(), codes_without_topis=len(set(name_of) - set(s.dong8))))
pd.concat(rows).to_parquet(SCR / "dong_share_b.parquet", index=False)
s = pd.DataFrame(summ)
s["unmatched_bus_pct"] = 100 * s.bus_unmatched / s.bus_seoul_gu
s.to_csv(OUT / "s02b_dong_match_daily.csv", index=False, encoding="utf-8-sig")
s.groupby("ym").agg(days=("date", "count"), seoul_gu_dongs=("seoul_gu_dongs", "max"), matched_lvl1=("matched_lvl1", "max"),
                    matched_lvl2=("matched_lvl2", "max"), unmatched=("unmatched", "max"), dongs8=("dongs8", "max"),
                    codes_without_topis=("codes_without_topis", "max"), unmatched_bus_pct_mean=("unmatched_bus_pct", "mean")) \
    .to_csv(OUT / "s02b_dong_match_summary.csv", encoding="utf-8-sig")
u = pd.concat(um).groupby(["ym", "출발_구", "출발_동"]).agg(days=("date", "nunique"), bus_per_day=("bus", "mean")).reset_index()
u.to_csv(OUT / "s02b_dong_unmatched.csv", index=False, encoding="utf-8-sig")
nt = []
allr = pd.concat(rows)
for ym in ["202407", "202408", "202507", "202508"]:
    have = set(allr.loc[allr.date.str[:6] == ym, "dong8"])
    for c in sorted(set(name_of) - have):
        nt.append(dict(ym=ym, dong8=c, gu=gu_of[c], dong_nm=name_of[c]))
pd.DataFrame(nt, columns=["ym", "dong8", "gu", "dong_nm"]).to_csv(OUT / "s02b_codes_without_topis.csv", index=False, encoding="utf-8-sig")
print(pd.DataFrame(bsum).to_string()); print(pd.read_csv(OUT / "s02b_dong_match_summary.csv").to_string()); print(u.to_string()); print(pd.DataFrame(nt).to_string())
