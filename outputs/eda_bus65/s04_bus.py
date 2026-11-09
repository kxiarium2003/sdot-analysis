"""
s04_bus.py - 버스 정류장 키·위치 확인(Q4)과 종로구 시범 추정(4단계, 방법 A의 자치구판)

입력(읽기만): data/raw/D16_bus_hourly (2025-08), metadata/노선 및 정류장현황.csv (500행 표본),
         merged_data/D9_boundary/bnd_oa_11_2016_4Q (집계구 경계 → 행정동 7자리 = 앞 7자리),
         outputs/eda_bus65/d12_dep_dong_hour.csv (s02 산출)
출력(outputs/eda_bus65/):
  q4_ars_vs_stdid_prefix.csv     ARS 앞 2자리 × 표준정류장ID 앞 3자리 교차표 (2025-08)
  q4_meta_sample_point_check.csv metadata 표본 정류장: 좌표 → 행정동/자치구, D16과 (노선번호, 순번) 매칭, ARS 앞자리와 자치구 비교
  pilot_jongno_d12_share_by_hour.csv  종로구 출발 이동 중 65세 이상 비율(도착시각별, D12 2025-08)
  pilot_jongno_stops_202508.csv  종로구(ARS 01) 정류장별 10~16시 승차와 65세 이상 추정치
  pilot_jongno_top20.csv, fig_pilot_jongno_hist.png
실행: python outputs/eda_bus65/s04_bus.py
"""
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]; RAW = ROOT / "data/raw"; OUT = ROOT / "outputs/eda_bus65"
plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": "#52514e", "xtick.color": "#52514e", "ytick.color": "#52514e", "figure.facecolor": "#fcfcfb",
                     "axes.facecolor": "#fcfcfb", "axes.grid": True, "grid.color": "#e6e5e0", "grid.linewidth": .6})
C1 = "#2a78d6"; H = list(range(10, 17))
GU = {"11010": "종로구", "11020": "중구", "11030": "용산구", "11040": "성동구", "11050": "광진구", "11060": "동대문구", "11070": "중랑구",
      "11080": "성북구", "11090": "강북구", "11100": "도봉구", "11110": "노원구", "11120": "은평구", "11130": "서대문구", "11140": "마포구",
      "11150": "양천구", "11160": "강서구", "11170": "구로구", "11180": "금천구", "11190": "영등포구", "11200": "동작구", "11210": "관악구",
      "11220": "서초구", "11230": "강남구", "11240": "송파구", "11250": "강동구"}

b = pd.read_csv(RAW / "D16_bus_hourly/2025년_버스노선별_정류장별_시간대별_승하차_인원_정보(08월).csv", encoding="cp949", dtype=str)
bc = {int(c.split("시")[0]): c for c in b.columns if c.endswith("승차총승객수")}
b[list(bc.values())] = b[list(bc.values())].apply(pd.to_numeric)
b["ars"] = b.버스정류장ARS번호.where(b.버스정류장ARS번호 == "~", b.버스정류장ARS번호.str.zfill(5))
b["seq"] = b.역명.str.extract(r"\((\d+)\)$")[0].astype(float)
b["name"] = b.역명.str.replace(r"\(\d+\)$", "", regex=True)

# Q4-1 ARS 앞 2자리 vs 표준ID 앞 3자리
x = b[b.ars != "~"].drop_duplicates("표준버스정류장ID")
ct = pd.crosstab(x.ars.str[:2], x.표준버스정류장ID.str[:3])
ct.to_csv(OUT / "q4_ars_vs_stdid_prefix.csv", encoding="utf-8-sig")
dom = (ct.max(1) / ct.sum(1))
print("ARS 앞2자리별 가장 흔한 표준ID 앞3자리 비중: 중앙값 %.3f, 최소 %.3f" % (dom.median(), dom.min()))
print("ARS 앞 2자리 분포(정류장 수):", x.ars.str[:2].value_counts().sort_index().to_dict())

# Q4-2 metadata 표본 좌표 → 행정동
m = pd.read_csv(ROOT / "metadata/노선 및 정류장현황.csv", encoding="cp949", dtype=str)
dm = lambda s: np.floor(s.astype(float) / 100) + (s.astype(float) % 100) / 60   # DDDMM.mmmm → 도
m["lon"], m["lat"] = dm(m.정류장X좌표), dm(m.정류장Y좌표)
P = gpd.GeoDataFrame(m, geometry=gpd.points_from_xy(m.lon, m.lat), crs=4326).to_crs(5179)
Bd = gpd.read_file(ROOT / "merged_data/D9_boundary/bnd_oa_11_2016_4Q/bnd_oa_11_2016_4Q.shp").set_crs(5179, allow_override=True)
Bd["dong7"] = Bd.TOT_REG_CD.astype(str).str[:7]
P = gpd.sjoin(P, Bd[["dong7", "geometry"]], how="left", predicate="within").drop(columns="index_right")
P["gu"] = P.dong7.str[:5].map(GU)
P["정류장순서"] = P.정류장순서.astype(float)
J = P.merge(b[["노선번호", "seq", "ars", "name", "표준버스정류장ID"]], left_on=["노선번호", "정류장순서"], right_on=["노선번호", "seq"], how="left")
J["name_match"] = J.apply(lambda r: isinstance(r["name"], str) and (r.정류장명.replace(" ", "") in r["name"].replace(" ", "") or r["name"].replace(" ", "") in r.정류장명.replace(" ", "")), axis=1)
gu_code = {v: f"{i:02d}" for i, v in enumerate(GU.values(), 1)}          # 가설: ARS 앞 2자리 = 자치구 순번(통계청 코드 순서)
J["ars_gu_hyp"] = J.gu.map(gu_code)
J["ars_prefix_match"] = np.where(J.name_match & J.ars.notna() & J.gu.notna(), J.ars.str[:2] == J.ars_gu_hyp, np.nan)
J.drop(columns="geometry").to_csv(OUT / "q4_meta_sample_point_check.csv", index=False, encoding="utf-8-sig")
v = J[J.name_match & J.gu.notna() & J.ars.notna() & (J.ars != "~")]
print(f"표본 {len(m)}행: 서울 경계 안 {P.dong7.notna().sum()}, 종료일자 99991231 {int((m.종료일자=='99991231').sum())}, "
      f"D16(2025-08)과 (노선번호, 순번) 매칭 {J.ars.notna().sum()}, 이름까지 일치 {J.name_match.sum()}, "
      f"그중 ARS 앞2자리 = 좌표 자치구 순번 {int((v.ars.str[:2] == v.ars_gu_hyp).sum())}/{len(v)}")

# Q4-3 D14 스마트쉼터(기존 냉방 정류장 후보) ↔ ARS
sm = pd.read_excel(RAW / "D14_heat_mitigation_facility/스마트쉼터 현황.xlsx", header=3, dtype=str).dropna(how="all")
sm["ars"] = sm.설치장소.str.extract(r"(\d{2})-(\d{3})").fillna("").sum(1)
sm["addr_gu"] = sm.시군구.where(sm.시군구.isin(GU.values()), sm.상세주소.str.extract(r"(?:^|\s)(\S+구)(?:\s|$)")[0])
sm["ars_gu"] = sm.ars.str[:2].map({f"{i:02d}": g for i, g in enumerate(GU.values(), 1)})
sm["in_d16"] = sm.ars.isin(set(b.ars))
sm.to_csv(OUT / "q4_d14_smart_shelter_ars.csv", index=False, encoding="utf-8-sig")
k = sm[sm.ars.str.len() == 5]
print(f"D14 스마트쉼터 {len(sm)}행: 설치장소에 ARS형 번호 {len(k)}, D16 ARS 일치 {k.in_d16.sum()}, ARS 앞2자리 자치구 = 주소 자치구 {(k.ars_gu == k.addr_gu).sum()}/{k.addr_gu.notna().sum()}")

# 4단계 시범: 종로구
d12 = pd.read_csv(OUT / "d12_dep_dong_hour.csv", dtype={"dong7": str})
jn = d12[d12.dong7.str.startswith("11010")]
sh = jn.groupby(["hour", "ag"]).v.sum().unstack(); sh["share65"] = sh["65p"] / (sh["65p"] + sh["u65"])
jx = jn[~jn.same].groupby(["hour", "ag"]).v.sum().unstack(); sh["share65_excl_same"] = jx["65p"] / (jx["65p"] + jx["u65"])
sh.to_csv(OUT / "pilot_jongno_d12_share_by_hour.csv", encoding="utf-8-sig")
s1016 = sh.loc[H, "65p"].sum() / sh.loc[H, ["65p", "u65"]].sum().sum()
print("종로구 D12 10~16시 65+ 비율 %.4f (동내 이동 제외 %.4f)" % (s1016, jx.loc[H, "65p"].sum() / jx.loc[H].sum().sum()))

jb = b[b.ars.str.startswith("01")]
st = jb.groupby("ars").agg(name=("name", "first"), n_routes=("노선번호", "nunique"), std_ids=("표준버스정류장ID", lambda s: "|".join(sorted(set(s)))),
                           **{f"h{h}": (bc[h], "sum") for h in H})
st["board_10_16"] = st[[f"h{h}" for h in H]].sum(1)
st["est65_A_const"] = st.board_10_16 * s1016                                   # 자치구 상수 비율
st["est65_A_hour"] = sum(st[f"h{h}"] * sh.loc[h, "share65"] for h in H)        # 시각별 비율
n_days = 31
st["est65_A_hour_per_day"] = st.est65_A_hour / n_days
st = st.sort_values("est65_A_hour", ascending=False)
st.to_csv(OUT / "pilot_jongno_stops_202508.csv", encoding="utf-8-sig")
top = st.head(20)[["name", "n_routes", "board_10_16", "est65_A_const", "est65_A_hour", "est65_A_hour_per_day"]].round(1)
top.to_csv(OUT / "pilot_jongno_top20.csv", encoding="utf-8-sig"); print(top.to_string())
from scipy.stats import spearmanr
print("종로구 정류장 %d개, 10~16시 승차 합 %.0f, 추정 65+ 합 %.0f; 순위 상관(승차 vs 시각별 추정) %.4f" % (
    len(st), st.board_10_16.sum(), st.est65_A_hour.sum(), spearmanr(st.board_10_16, st.est65_A_hour).statistic))

fig, ax = plt.subplots(figsize=(7, 4))
ax.hist(st.est65_A_hour_per_day, bins=np.arange(0, st.est65_A_hour_per_day.max() + 10, 10), color=C1, edgecolor="#fcfcfb", linewidth=1)
ax.set_xlabel("정류장별 65세 이상 승차 추정치 (명/일, 10~16시)"); ax.set_ylabel("정류장 수 (ARS 기준)")
ax.set_title(f"종로구 시범 추정, 2025-08 (방법 A 자치구판, n={len(st)})", fontsize=11, loc="left")
fig.tight_layout(); fig.savefig(OUT / "fig_pilot_jongno_hist.png", dpi=150); plt.close(fig)
