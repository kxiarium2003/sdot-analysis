"""s02 - 지하철 입력 정리, 후보 B 가중치 q_B, 시험 2(후보 B 역 빼고 맞히기).

입력:
  D26 서울교통공사 역별 일별 시간대별 노인 승하차 (SCRATCH/d26/*.csv, Drive data1 사본. 2025는 열린데이터광장 파일)
  D18 서울교통공사 역별 (일별) 시간대별 승하차 (data/raw/D18_subway_hourly/ 2024·2025 파일)
  D22 서울시 역사마스터(OA-21232) 좌표, 정류장 좌표 SCRATCH/stop_geo.parquet(감사 작업 s02 연결)
  행정동 경계 2025_2Q(역의 자치구 배정용)
시간 묶음(D18·D26 공통 20칸): pre06(06시 이전), 06..23, post24(24시 이후). 버스 시간 h -> 0:post24, 1~5:pre06, 6~23:같은 시.
평일/주말: 토·일 = 주말, 8월 15일은 평일(R_d 규칙과 같음).
역 묶기: 역명(괄호·공백·끝의 '역' 제거)이 같은 역번호를 한 역으로(환승역). 좌표는 D22 BLDN_ID(=역번호 4자리) 평균.
출력(SCRATCH): stations.parquet, sub_cell.parquet(역 x 월 x 평일/주말 x 묶음 E,T), qB.parquet(정류장 x 월 x 평일/주말 x 묶음)
출력(OUT): s02_stations.csv, s02_stop_nearest_dist.csv, table_test2_subway.csv(후보 B·C 부분), s02_subway_daily.csv
사용: python3 -I s02_subway_qB.py <SCRATCH>
"""
import sys, re, json, glob
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd
from scipy.spatial import cKDTree
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SCR = Path(sys.argv[1])
MS = ["202407", "202408", "202507", "202508"]
BK = ["pre06"] + [f"{h:02d}" for h in range(6, 24)] + ["post24"]
GU = dict(zip([f"11{i:02d}0" for i in range(1, 26)], "종로구 중구 용산구 성동구 광진구 동대문구 중랑구 성북구 강북구 도봉구 노원구 은평구 서대문구 마포구 양천구 강서구 구로구 금천구 영등포구 동작구 관악구 서초구 강남구 송파구 강동구".split()))


def norm(s):
    s = re.sub(r"\(.*?\)", "", str(s)).replace(" ", "")
    return s[:-1] if s.endswith("역") and len(s) > 2 else s


def load(path, datecol, kind_col, first_bucket_idx):
    d = pd.read_csv(path, encoding="cp949", dtype=str)
    d = d[d[kind_col] == "승차"]
    d = d[d[datecol].str[:7].str.replace("-", "").isin(MS)]
    b = d.columns[first_bucket_idx:first_bucket_idx + 20]
    out = pd.DataFrame({"date": d[datecol].str.replace("-", ""), "code": pd.to_numeric(d["역번호"]).astype(int), "name": d["역명"]})
    for k, c in zip(BK, b):
        out[k] = pd.to_numeric(d[c].str.replace(",", ""), errors="coerce").fillna(0).to_numpy()
    return out


d26 = pd.concat([load(f, "수송일자", "승하차구분", 5) for f in sorted(glob.glob(str(SCR / "d26/*.csv")))])
d18 = pd.concat([load(ROOT / "data/raw/D18_subway_hourly/서울교통공사_역별 시간대별 승하차인원(24.1~24.12).csv", "날짜", "구분", 6),
                 load(ROOT / "data/raw/D18_subway_hourly/서울교통공사_역별 일별 시간대별 승하차인원_20251231.csv", "수송일자", "승하차구분", 6)])
for d in (d26, d18):
    d["key"] = d.name.map(norm)
# 역 묶기와 좌표
j = json.load(open(ROOT / "data/raw/D22_station_master/subwayStationMaster_000001_000784.json"))["subwayStationMaster"]["row"]
d22 = pd.DataFrame(j)
d22["code"] = d22.BLDN_ID.astype(int)
d22["lat"], d22["lon"] = pd.to_numeric(d22.LAT), pd.to_numeric(d22.LOT)
codes = pd.concat([d26[["code", "key"]], d18[["code", "key"]]]).drop_duplicates()
cc = codes.merge(d22[["code", "lat", "lon"]], on="code", how="left")
st = cc.groupby("key").agg(codes=("code", lambda x: ",".join(map(str, sorted(set(x))))), lat=("lat", "mean"), lon=("lon", "mean")).reset_index()
g = gpd.GeoDataFrame(st, geometry=gpd.points_from_xy(st.lon, st.lat), crs=4326).to_crs("EPSG:5179")
st["x"], st["y"] = g.geometry.x, g.geometry.y
oa = gpd.read_file(ROOT / "data/raw/D9_zone_boundary/bnd_oa_11_2025_2Q").to_crs("EPSG:5179")
jj = gpd.sjoin(g, oa[["ADM_CD", "geometry"]], how="left", predicate="within")
jj = jj[~jj.index.duplicated()]
st["gu"] = jj.ADM_CD.str[:5].map(GU).values

# 역 x 날짜 x 묶음 E, T
E = d26.groupby(["key", "date"])[BK].sum()
T = d18.groupby(["key", "date"])[BK].sum()
both = E.index.intersection(T.index)
E, T = E.loc[both], T.loc[both]
dt = pd.to_datetime(both.get_level_values("date"))
daytype = np.where(dt.dayofweek >= 5, "주말", "평일")
ym = both.get_level_values("date").str[:6]
EL = E.reset_index().melt(id_vars=["key", "date"], var_name="bk", value_name="E")
TL = T.reset_index().melt(id_vars=["key", "date"], var_name="bk", value_name="T")
cell = EL.merge(TL, on=["key", "date", "bk"])
cell["ym"] = cell.date.str[:6]
cell["daytype"] = np.where(pd.to_datetime(cell.date).dt.dayofweek >= 5, "주말", "평일")
# 서울 일별 합 (4절 비교용)
daily = cell.merge(st[["key", "gu"]], on="key", how="left")
daily.groupby(["date", "ym", "daytype", "gu", "bk"], dropna=False)[["E", "T"]].sum().reset_index().to_csv(OUT / "s02_subway_daily.csv", index=False, encoding="utf-8-sig")
sc = cell.groupby(["key", "ym", "daytype", "bk"])[["E", "T"]].sum().reset_index()
sc.to_parquet(SCR / "sub_cell.parquet", index=False)
# 쓸 역: 좌표가 있고 네 달 모두 T>0
have = sc.groupby(["key", "ym"]).T.sum().unstack()
use = have.index[(have > 0).all(axis=1)]
st["used"] = st.key.isin(use) & st.x.notna()
st.to_parquet(SCR / "stations.parquet", index=False)
st.drop(columns=[]).to_csv(OUT / "s02_stations.csv", index=False, encoding="utf-8-sig")
S = st[st.used].reset_index(drop=True)
print("stations total", len(st), "used", len(S), "no coord", int(st.x.isna().sum()), flush=True)

# ---- q_B: 정류장 최근접 3역
geo = pd.read_parquet(SCR / "stop_geo.parquet")
gp = gpd.GeoDataFrame(geo, geometry=gpd.points_from_xy(geo.lon, geo.lat), crs=4326).to_crs("EPSG:5179")
tree = cKDTree(S[["x", "y"]].to_numpy())
dist, idx = tree.query(np.c_[gp.geometry.x, gp.geometry.y], k=3)
w = 1 / np.maximum(dist, 100)
nd = pd.DataFrame({"node": geo.node, "ars": geo.ars, "d1": dist[:, 0], "d2": dist[:, 1], "d3": dist[:, 2],
                   "s1": S.key.values[idx[:, 0]], "s2": S.key.values[idx[:, 1]], "s3": S.key.values[idx[:, 2]]})
nd.to_csv(OUT / "s02_stop_nearest_dist.csv", index=False, encoding="utf-8-sig")
# 셀 값 배열: [역, 월, 평일/주말, 묶음]
scu = sc[sc.key.isin(S.key)]
kpos = {k: i for i, k in enumerate(S.key)}
DT = ["평일", "주말"]
Ea = np.zeros((len(S), 4, 2, 20)); Ta = np.zeros_like(Ea)
for r in scu.itertuples():
    a = (kpos[r.key], MS.index(r.ym), DT.index(r.daytype), BK.index(r.bk))
    Ea[a] += r.E; Ta[a] += r.T


def predict(idx, w):
    num = (Ea[idx] * w[:, :, None, None, None]).sum(1)
    den = (Ta[idx] * w[:, :, None, None, None]).sum(1)
    raw = (Ta[idx]).sum(1)
    dnum = (Ea[idx].sum(-1) * w[:, :, None, None]).sum(1)
    dden = (Ta[idx].sum(-1) * w[:, :, None, None]).sum(1)
    q = np.where(raw >= 100, num / np.where(den > 0, den, np.nan), (dnum / dden)[..., None])
    return q, raw < 100


qB, fb = predict(idx, w)
rows = []
for m in range(4):
    for t in range(2):
        df = pd.DataFrame(qB[:, m, t, :], columns=BK)
        df.insert(0, "node", geo.node.values)
        df = df.melt(id_vars="node", var_name="bk", value_name="q_B")
        df["ym"], df["daytype"] = MS[m], DT[t]
        rows.append(df)
pd.concat(rows).to_parquet(SCR / "qB.parquet", index=False)
dist_summary = dict(stops=len(nd), d1_min=nd.d1.min(), d1_p10=nd.d1.quantile(.1), d1_q1=nd.d1.quantile(.25), d1_median=nd.d1.median(),
                    d1_q3=nd.d1.quantile(.75), d1_p90=nd.d1.quantile(.9), d1_max=nd.d1.max(), stops_d1_over_1km=int((nd.d1 > 1000).sum()),
                    qB_fallback_cell_pct=100 * fb.mean())
pd.Series(dist_summary).to_csv(OUT / "s02_stop_nearest_summary.csv", header=["value"], encoding="utf-8-sig")
print(dist_summary, flush=True)

# ---- 시험 2: 후보 B 역 빼고 가장 가까운 3역
dk, ik = tree.query(S[["x", "y"]].to_numpy(), k=4)
dk, ik = dk[:, 1:], ik[:, 1:]
wk = 1 / np.maximum(dk, 100)
pk, _ = predict(ik, wk)
act = Ea / np.where(Ta > 0, Ta, np.nan)
res = []
H = [BK.index(f"{h:02d}") for h in range(6, 24)]
# ① 역 x 월 (전체 날)
am = Ea.sum((2, 3)) / Ta.sum((2, 3))
pm_num = (Ea[ik].sum((3, 4)) * wk[:, :, None]).sum(1); pm_den = (Ta[ik].sum((3, 4)) * wk[:, :, None]).sum(1)
pm = pm_num / pm_den
r = spearmanr(am.ravel(), pm.ravel())
res.append(dict(후보="B 주변 3역(본 역 제외)", 단위="① 역x월", N=am.size, spearman=r.statistic))
# ② 역 x 월 x 시(06~23), 평일+주말 합
num = (Ea[ik][..., H].sum(3) * wk[:, :, None, None]).sum(1)  # [s, m, h]
den = (Ta[ik][..., H].sum(3) * wk[:, :, None, None]).sum(1)
ah = Ea[..., H].sum(2) / np.where(Ta[..., H].sum(2) > 0, Ta[..., H].sum(2), np.nan)
ph = num / den
ok = np.isfinite(ah) & np.isfinite(ph) & (Ta[..., H].sum(2) >= 10)
r = spearmanr(ah[ok], ph[ok])
res.append(dict(후보="B 주변 3역(본 역 제외)", 단위="② 역x월x시(06~23시, 칸 승차 10명 이상)", N=int(ok.sum()), spearman=r.statistic))
# 역 하루 전체 (4개월 합)
a4 = Ea.sum((1, 2, 3)) / Ta.sum((1, 2, 3))
p4 = (Ea[ik].sum((2, 3, 4)) * wk).sum(1) / (Ta[ik].sum((2, 3, 4)) * wk).sum(1)
r = spearmanr(a4, p4)
res.append(dict(후보="B 주변 3역(본 역 제외)", 단위="역 하루 전체(4개월 합)", N=len(a4), spearman=r.statistic))
# 평일/주말 x 시
for t in range(2):
    a_ = Ea[:, :, t][..., H] / np.where(Ta[:, :, t][..., H] > 0, Ta[:, :, t][..., H], np.nan)
    n_ = (Ea[ik][:, :, :, t][..., H] * wk[:, :, None, None]).sum(1); d_ = (Ta[ik][:, :, :, t][..., H] * wk[:, :, None, None]).sum(1)
    p_ = n_ / d_
    ok = np.isfinite(a_) & np.isfinite(p_) & (Ta[:, :, t][..., H] >= 10)
    r = spearmanr(a_[ok], p_[ok])
    res.append(dict(후보="B 주변 3역(본 역 제외)", 단위=f"역x월x시(06~23시), {DT[t]}", N=int(ok.sum()), spearman=r.statistic))
for m in range(4):
    r = spearmanr(am[:, m], pm[:, m])
    res.append(dict(후보="B 주변 3역(본 역 제외)", 단위=f"역 하루 전체 {MS[m]}", N=len(S), spearman=r.statistic))
res += [dict(후보="C 서울 평균(기준선)", 단위=u, N=None, spearman=0.0, 비고="예측이 상수라 순위상관이 정의되지 않아 0으로 둠") for u in ["① 역x월", "② 역x월x시(06~23시)", "역 하루 전체(4개월 합)"]]
res += [dict(후보="A P1 m3 (v2 인용)", 단위="① 역x월 (N=1,031)", N=1031, spearman=0.810, 비고="outputs/est_v2/report_est_v2_eda.md C-1, 보정 전, 공간 CV 0.806"),
        dict(후보="A P1 m3 (v2 인용)", 단위="② 역x월x시(06~23시) (N=18,558)", N=18558, spearman=0.873, 비고="같은 표, 공간 CV 0.871"),
        dict(후보="A P1 m3 (v2 인용)", 단위="③ 역x날짜x시 (N=560,621)", N=560621, spearman=0.804, 비고="같은 표, 공간 CV 0.801")]
pd.DataFrame(res).to_csv(OUT / "table_test2_subway.csv", index=False, encoding="utf-8-sig")
print(pd.DataFrame(res).to_string())
