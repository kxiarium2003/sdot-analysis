"""s02 - TOPIS 동별 수단OD(data/transit_od/)에서 날짜별 서울 출발 행정동 버스_승객수 비율.

동 이름 연결: 출발_구가 서울 25개 구이고, (구, 동 이름 공백 제거)가 2016 행정동 경계(D9 행정구역.shp, ADM_NM 공백 제거)와 같으면 연결.
  1단계: 공백 제거만(지시). 2단계: 1단계에서 안 맞은 것 중 ','를 '·'로 바꾸면 맞는 것(2025년 표기 차이).
연결 안 된 동은 비율 분모에서 빼고(연결된 동끼리 비율) 규모를 보고한다.
출력: SCRATCH/dong_share.parquet, outputs/bus65_v4/s02_dong_unmatched.csv, s02_dong_match_summary.csv
사용: python3 -I s02_dong_share.py <SCRATCH>
"""
import sys, glob
from pathlib import Path
import pandas as pd, geopandas as gpd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SCR = Path(sys.argv[1])
d = gpd.read_file(ROOT / "data/raw/D9_zone_boundary/seoul_census_oa_boundary_2016/행정구역.shp")
key16 = {(g, n.replace(" ", "")): c for g, n, c in zip(d.SIGUNGU_NM, d.ADM_NM, d.ADM_CD)}
SEOUL = set(d.SIGUNGU_NM)
rows, um, summ = [], [], []
for ym in ["202407", "202408", "202507", "202508"]:
    for f in sorted(glob.glob(str(ROOT / f"data/transit_od/transit_od_{ym}/동별/수단OD/*.csv"))):
        t = pd.read_csv(f, encoding="cp949", dtype=str, usecols=["기준일자", "출발_구", "출발_동", "버스_승객수"])
        t["bus"] = pd.to_numeric(t["버스_승객수"]).fillna(0)
        t = t[t["출발_구"].isin(SEOUL)]
        g = t.groupby(["기준일자", "출발_구", "출발_동"], as_index=False).bus.sum()
        g["n1"] = g["출발_동"].str.replace(" ", "")
        g["dong7"] = [key16.get((a, b)) for a, b in zip(g["출발_구"], g.n1)]
        g["level"] = g.dong7.notna().map({True: "1_공백제거", False: None})
        m2 = g.dong7.isna()
        g.loc[m2, "dong7"] = [key16.get((a, b.replace(",", "·"))) for a, b in zip(g.loc[m2, "출발_구"], g.loc[m2, "n1"])]
        g.loc[m2 & g.dong7.notna(), "level"] = "2_쉼표→가운뎃점"
        g["date"] = g["기준일자"]
        um.append(g[g.dong7.isna()].assign(ym=ym))
        ok = g[g.dong7.notna()]
        a = ok.groupby(["date", "dong7"], as_index=False).bus.sum()
        a["share"] = a.bus / a.bus.sum()
        rows.append(a)
        summ.append(dict(ym=ym, date=g.date.iloc[0], seoul_gu_dongs=len(g), matched_lvl1=int((g.level == "1_공백제거").sum()),
                         matched_lvl2=int((g.level == "2_쉼표→가운뎃점").sum()), unmatched=int(g.dong7.isna().sum()),
                         bus_seoul_gu=g.bus.sum(), bus_matched=ok.bus.sum(), bus_unmatched=g.loc[g.dong7.isna(), "bus"].sum(),
                         dongs7=a.dong7.nunique()))
pd.concat(rows).to_parquet(SCR / "dong_share.parquet", index=False)
s = pd.DataFrame(summ)
s["unmatched_bus_pct"] = 100 * s.bus_unmatched / s.bus_seoul_gu
s.to_csv(OUT / "s02_dong_match_daily.csv", index=False, encoding="utf-8-sig")
s.groupby("ym").agg(days=("date", "count"), seoul_gu_dongs=("seoul_gu_dongs", "max"), matched_lvl1=("matched_lvl1", "max"),
                    matched_lvl2=("matched_lvl2", "max"), unmatched=("unmatched", "max"), dongs7=("dongs7", "max"),
                    unmatched_bus_pct_mean=("unmatched_bus_pct", "mean")).to_csv(OUT / "s02_dong_match_summary.csv", encoding="utf-8-sig")
u = pd.concat(um).groupby(["ym", "출발_구", "출발_동"]).agg(days=("date", "nunique"), bus_per_day=("bus", "mean")).reset_index()
u.to_csv(OUT / "s02_dong_unmatched.csv", index=False, encoding="utf-8-sig")
# 연결된 동 이름 중 2단계로 맞춘 것
print(pd.read_csv(OUT / "s02_dong_match_summary.csv").to_string()); print(u.to_string())
