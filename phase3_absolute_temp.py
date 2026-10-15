"""절대 기온 기반 분석 (여름 6–9월, 2024–2025).

ΔT 는 "배경 기온보다 몇 도 더운가"라서, 배경 기온 자체가 서울 안에서 다른 것(내륙·해안 쪽, 표고)은 빠진다.
여기서는 집계구 대표점마다 기준 기온장(KED, AWS 66곳, Phase 1과 같은 설정)을 시간별로 다시 계산하고
절대 기온 T̂ = 기준 기온 + ΔT̂ 를 복원해 다음을 본다.
  1. 공간 차이의 출처: 집계구 간 T̂ 의 차이 중 배경 기온과 ΔT 의 몫
  2. 절대 기온으로 본 "더운 곳": 자치구 순위, ΔT 기준 상위 10% 와의 일치
  3. 절대 기온 노출: 1인당 평균 기온(거주 vs 활동, 주야, 연령) — "사람들이 평균 몇 도인 곳에 있었나"
  4. 집계구 노출 순위: ΔT 기준과 절대 기온 기준이 같은 순서를 주는가
한계: ΔT̂ 는 (연도 × 계절 × 시각) 평균 프로파일. 배경 기온은 시간별 실측 보간.
실행: .venv/bin/python phase3_absolute_temp.py
산출: phase3/absolute_temp_summary.json, phase3/absolute_temp_tract.parquet (집계구 × 연도 × 시각 평균 기준 기온·T̂)
"""
import json, time
import numpy as np, pandas as pd, geopandas as gpd
from scipy.stats import spearmanr

t0 = time.time(); HOLDOUT = "108"; NIGHT = {21, 22, 23, 0, 1, 2, 3, 4, 5, 6}; AGES = ["a0_14", "a15_64", "a65p"]
GU = {"11010": "종로", "11020": "중구", "11030": "용산", "11040": "성동", "11050": "광진", "11060": "동대문", "11070": "중랑",
      "11080": "성북", "11090": "강북", "11100": "도봉", "11110": "노원", "11120": "은평", "11130": "서대문", "11140": "마포",
      "11150": "양천", "11160": "강서", "11170": "구로", "11180": "금천", "11190": "영등포", "11200": "동작", "11210": "관악",
      "11220": "서초", "11230": "강남", "11240": "송파", "11250": "강동"}

st = pd.read_csv("merged_data/D2_aws/stations_kma.csv", dtype={"stn_id": str}); st["elev"] = st.elev_m_kma.astype(float)
aws = pd.read_parquet("merged_data/D2_aws/awsh_2024_2025.parquet", columns=["stn_id", "ta", "measure_time"])
aws = aws[aws.stn_id.isin(st.stn_id)]; aws["measure_time"] = aws.measure_time.dt.floor("h")
T = aws.pivot_table(index="measure_time", columns="stn_id", values="ta", aggfunc="mean")
T = T[T.index.month.isin([6, 7, 8, 9]) & (T.index.year.isin([2024, 2025]))]
stk = st[st.stn_id != HOLDOUT].set_index("stn_id"); ids = [c for c in T.columns if c != HOLDOUT and c in stk.index]
xy = stk.loc[ids, ["x_5179", "y_5179"]].values; el = stk.loc[ids, "elev"].values
vg = pd.read_csv("phase1/variogram_monthly_2y_merged.csv", dtype={"month": str}).drop_duplicates("month").set_index("month")[["nugget", "psill", "range_km"]]
def gamma_exp(h, nug, psill, rng): return nug + psill * (1 - np.exp(-h / rng))

G = gpd.read_file("merged_data/D9_boundary/bnd_oa_11_2016_4Q/bnd_oa_11_2016_4Q.shp").set_crs(5179, allow_override=True)
rp = G.geometry.representative_point()
pts = pd.DataFrame({"tract16": G.TOT_REG_CD.astype(str).values, "x": rp.x.values, "y": rp.y.values})
pts = pts.merge(pd.read_parquet("phase2/covariates_tract16_buf250.parquet")[["tract16", "elev"]], on="tract16", how="left")
pts["elev"] = pts.elev.fillna(pts.elev.median())
Z = pd.read_parquet("phase2/anomaly_by_zone_2y_merged.parquet", columns=["tract16", "summer", "season", "hour", "dT_hat"])
Z = Z[Z.season == "summer"]
pts = pts[pts.tract16.isin(Z.tract16.unique())].reset_index(drop=True); NZ = len(pts); tix = {t: i for i, t in enumerate(pts.tract16)}
qx, qy, qe = pts.x.values, pts.y.values, pts.elev.values
Dq = np.sqrt((xy[:, 0][:, None] - qx[None, :]) ** 2 + (xy[:, 1][:, None] - qy[None, :]) ** 2) / 1000
Dp = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1)) / 1000

# 시간별 KED → 집계구 × (연도, 시각) 평균 기준 기온
S = np.zeros((2, 24, NZ)); C = np.zeros((2, 24))
for i, ts in enumerate(T.index):
    v = T.loc[ts, ids].values.astype(float); ok = ~np.isnan(v)
    if ok.sum() < 10: continue
    p = vg.loc[ts.strftime("%Y%m")].values; n = ok.sum()
    Gm = gamma_exp(Dp[np.ix_(ok, ok)], *p); np.fill_diagonal(Gm, 0.0)
    F = np.c_[np.ones(n), el[ok]]; K = np.zeros((n + 2, n + 2)); K[:n, :n] = Gm; K[:n, n:] = F; K[n:, :n] = F.T
    B = np.zeros((n + 2, NZ)); B[:n] = gamma_exp(Dq[ok], *p); B[n] = 1; B[n + 1] = qe
    try: Lw = np.linalg.solve(K, B)
    except np.linalg.LinAlgError: Lw = np.linalg.lstsq(K, B, rcond=None)[0]
    yi = ts.year - 2024; S[yi, ts.hour] += v[ok] @ Lw[:n]; C[yi, ts.hour] += 1
    if i % 1000 == 0: print("hour", i, len(T), f"{time.time()-t0:.0f}s", flush=True)
BG = S / C[:, :, None]                                                  # 평균 기준 기온 [연도, 시각, 집계구]
rows = []
for yi, y in enumerate((2024, 2025)):
    for h in range(24):
        rows.append(pd.DataFrame({"tract16": pts.tract16, "summer": y, "hour": h, "T_bg": BG[yi, h]}))
A = pd.concat(rows).merge(Z.drop(columns="season"), on=["tract16", "summer", "hour"])
A["T_abs"] = A.T_bg + A.dT_hat; A["period"] = np.where(A.hour.isin(NIGHT), "night", "day")
A.to_parquet("phase3/absolute_temp_tract.parquet", index=False)
out = {}

# 1. 공간 차이의 출처 (집계구 평균, 2년)
m = A.groupby(["tract16", "period"])[["T_bg", "dT_hat", "T_abs"]].mean().unstack()
src = {}
for per in ("day", "night"):
    bg, dt, ab = m[("T_bg", per)], m[("dT_hat", per)], m[("T_abs", per)]
    src[per] = dict(sd_bg=bg.std(), sd_dT=dt.std(), sd_abs=ab.std(), corr_abs_dT=np.corrcoef(ab, dt)[0, 1], corr_abs_bg=np.corrcoef(ab, bg)[0, 1],
                    range_bg_p1_p99=float(bg.quantile(.99) - bg.quantile(.01)), mean_abs=ab.mean(),
                    var_share_bg=float(np.cov(bg, ab)[0, 1] / ab.var()), var_share_dT=float(np.cov(dt, ab)[0, 1] / ab.var()))
    k = int(len(ab) * .1); src[per]["top10_overlap_abs_vs_dT"] = 100 * len(set(ab.nlargest(k).index) & set(dt.nlargest(k).index)) / k
out["spatial_source"] = src
gu = m.groupby(m.index.str[:5].map(GU)).mean()
out["gu_abs"] = {per: gu[("T_abs", per)].sort_values().round(2).to_dict() for per in ("day", "night")}
out["gu_bg"] = {per: gu[("T_bg", per)].sort_values().round(2).to_dict() for per in ("day", "night")}

# 3. 절대 기온 노출 (1인당 평균 기온) 및 4. 순위
lp = pd.read_parquet("merged_data/D5_livingpop/livingpop_agg_2024_2025_native.parquet").rename(columns={"tract": "tract16"})
lp = lp[lp.season == "summer"]
sc = pd.read_csv("merged_data/D5_livingpop/age_scale.csv").set_index("year")
for a in AGES: lp[a] = lp[a] * lp.summer.map(sc[a])
res = pd.read_parquet("merged_data/D6_census/census2024_age3_tract16.parquet").set_index("tract16")[AGES]
M = A.merge(lp[["tract16", "summer", "hour", "n_days"] + AGES], on=["tract16", "summer", "hour"]).join(res.add_suffix("_res"), on="tract16", how="inner")   # 인구총조사에 있는 집계구만 (본문과 같음)
expo = {}
for per in ("day", "night", "all"):
    g = M if per == "all" else M[M.period == per]
    for a in AGES + ["all"]:
        PA = g[AGES].sum(1) if a == "all" else g[a]; PR = (g[[x + "_res" for x in AGES]].sum(1) if a == "all" else g[a + "_res"]) * g.n_days
        expo[f"{per}_{a}"] = dict(T_res=float((g.T_abs * PR).sum() / PR.sum()), T_act=float((g.T_abs * PA).sum() / PA.sum()),
                                  dT_res=float((g.dT_hat * PR).sum() / PR.sum()), dT_act=float((g.dT_hat * PA).sum() / PA.sum()),
                                  bg_res=float((g.T_bg * PR).sum() / PR.sum()), bg_act=float((g.T_bg * PA).sum() / PA.sum()))
out["per_capita_temp"] = expo
rk = {}
for (y, per), g in M.assign(PA=M[AGES].sum(1), PR=M[[x + "_res" for x in AGES]].sum(1) * M.n_days).groupby(["summer", "period"]):
    t = g.groupby("tract16").apply(lambda q: pd.Series({"EA_dT": (q.dT_hat * q.PA).sum(), "ER_dT": (q.dT_hat * q.PR).sum(),
                                                        "EA_abs": (q.T_abs * q.PA).sum(), "ER_abs": (q.T_abs * q.PR).sum()}), include_groups=False)
    k = int(len(t) * .1)
    rk[f"{y}_{per}"] = dict(rho_dT=spearmanr(t.EA_dT, t.ER_dT)[0], rho_abs=spearmanr(t.EA_abs, t.ER_abs)[0],
                            top10_dT=100 * len(set(t.EA_dT.nlargest(k).index) & set(t.ER_dT.nlargest(k).index)) / k,
                            top10_abs=100 * len(set(t.EA_abs.nlargest(k).index) & set(t.ER_abs.nlargest(k).index)) / k,
                            rho_EA_abs_vs_dT=spearmanr(t.EA_abs, t.EA_dT)[0])
out["rank"] = rk
json.dump(out, open("phase3/absolute_temp_summary.json", "w"), ensure_ascii=False, indent=1, default=float)
print(json.dumps({k: out[k] for k in ["spatial_source", "rank"]}, ensure_ascii=False, indent=1, default=lambda x: round(float(x), 3)))
print("gu_abs", out["gu_abs"]); print("gu_bg", out["gu_bg"])
for k in ["day_all", "night_all", "day_a15_64", "day_a65p", "day_a0_14"]:
    e = expo[k]; print(k, {kk: round(vv, 3) for kk, vv in e.items()})
print(f"done {time.time()-t0:.0f}s")
