"""
s03_subway.py - D17 권종별 승차(Q2), D18 시간대별 승하차(Q6), D19 OD 표본(Q1) 요약

입력(읽기만): data/raw/D17_subway_ticket_type, D18_subway_hourly, D19_subway_od_30min_2021
         outputs/eda_bus65/d12_dep_dong_hour.csv (s02 산출, Q6의 65세 이상 시간 분포 비교용)
출력(outputs/eda_bus65/):
  q2_station_ratio_summer2025.csv  역별 2025년 6~9월 우대권 비율, 월별 값, 변동계수
  q2_monthly_citywide.csv          월별 서울교통공사 전체 우대권 비율
  q2_d17_d18_key_match.csv         D17 역코드 ↔ D18 역번호 일치율
  q6_station_hourshare_vs_ratio.csv 역별 2025-08 10~16시 승차 비중 vs 우대권 비율
  q6_hour_corr.csv                 시각별 승차 비중과 우대권 비율의 스피어만 상관
  q1_d19_sample_usertype.csv       D19 표본 사용자구분별 행 수·인원 합
  fig_q2_ratio_hist.png, fig_q6_scatter.png, fig_q6_hour_profile.png
실행: python outputs/eda_bus65/s03_subway.py
"""
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]; RAW = ROOT / "data/raw"; OUT = ROOT / "outputs/eda_bus65"
plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": "#52514e", "axes.labelcolor": "#0b0b0b", "xtick.color": "#52514e", "ytick.color": "#52514e",
                     "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "axes.grid": True, "grid.color": "#e6e5e0", "grid.linewidth": .6})
C1, C2 = "#2a78d6", "#eb6834"
H = list(range(10, 17))  # 10~16시 (10:00~16:59, 7개 1시간 구간)

# ---------- D17 ----------
K = pd.concat([pd.read_csv(f, encoding="cp949", dtype=str) for f in sorted((RAW / "D17_subway_ticket_type").glob("*.csv"))])
K["ym"] = pd.to_datetime(K.수송연월, format="%Y-%m", errors="coerce").fillna(pd.to_datetime(K.수송연월, format="%b-%y", errors="coerce")).dt.strftime("%Y%m")
assert K.ym.notna().all()
K["v"] = pd.to_numeric(K.승차인원수); K = K.rename(columns={"고유역번호(외부역코드)": "code"})
W = K.pivot_table(index=["code", "ym"], columns="권종", values="v", aggfunc="sum")
names = K.drop_duplicates("code").set_index("code")[["역명", "호선"]]
W["total"] = W.sum(1); W["ratio"] = W["우대권"] / W["total"]
W = W.reset_index()
cm = W.groupby("ym")[["우대권", "total"]].sum(); cm["ratio"] = cm["우대권"] / cm.total; cm["우대권_행있음"] = W.groupby("ym")["우대권"].count()
cm.to_csv(OUT / "q2_monthly_citywide.csv", encoding="utf-8-sig")

S = W[W.ym.isin(["202506", "202507", "202508", "202509"])]
st = S.groupby("code").agg(ratio_summer=("우대권", "sum"), total=("total", "sum"))
st["ratio_summer"] = st.ratio_summer / st.total
piv = S.pivot(index="code", columns="ym", values="ratio")
st = st.join(piv.add_prefix("r_")).join(names)
# 연중 변동: 2025년 12개월 역별 변동계수
y25 = W[W.ym.str.startswith("2025")].groupby("code").ratio.agg(["mean", "std", "min", "max"])
st = st.join((y25["std"] / y25["mean"]).rename("cv_2025")).join(y25[["min", "max"]].add_prefix("r2025_"))
st = st.sort_values("ratio_summer", ascending=False)
st.to_csv(OUT / "q2_station_ratio_summer2025.csv", encoding="utf-8-sig")
print("우대권 비율(2025 여름) 분포:\n", st.ratio_summer.describe(percentiles=[.1, .25, .5, .75, .9]).round(4).to_string())
print("상위 10:\n", st.head(10)[["역명", "호선", "ratio_summer", "total"]].to_string())
print("하위 10:\n", st.tail(10)[["역명", "호선", "ratio_summer", "total"]].to_string())
print("역별 2025 CV 중앙값", round(y25.eval("std/mean").median(), 4), "/ 월별 전체:\n", cm.round(4).to_string())

fig, ax = plt.subplots(figsize=(7, 4))
ax.hist(st.ratio_summer * 100, bins=40, color=C1, edgecolor="#fcfcfb", linewidth=1)
med = st.ratio_summer.median() * 100
ax.axvline(med, color="#52514e", lw=1, ls="--"); ax.text(med + .3, ax.get_ylim()[1] * .92, f"중앙값 {med:.1f}%", color="#52514e", fontsize=9)
ax.set_xlabel("우대권 승차 / 전체 승차 (%)"); ax.set_ylabel("역 수 (호선별 역코드)")
ax.set_title("D17 역별 우대권 비율, 2025년 6~9월 합계 (n=%d)" % len(st), fontsize=11, loc="left")
fig.tight_layout(); fig.savefig(OUT / "fig_q2_ratio_hist.png", dpi=150); plt.close(fig)

# ---------- D18 ----------
f25 = RAW / "D18_subway_hourly/서울교통공사_역별 일별 시간대별 승하차인원_20251231.csv"
D = pd.read_csv(f25, encoding="cp949", dtype=str).dropna(subset=["수송일자"])
hc = list(D.columns[6:]); D[hc] = D[hc].apply(pd.to_numeric)
# 시간대 컬럼 → 시각: '06시이전'=5, '06-07시간대'=6, …, '23-24시간대'=23, '24시이후'=24
hmap = {c: (5 if "이전" in c else 24 if "이후" in c else int(c[:2])) for c in hc}
key = pd.DataFrame({"d17": sorted(set(K.code)), "in_d18": [c in set(D.역번호) for c in sorted(set(K.code))]})
key.to_csv(OUT / "q2_d17_d18_key_match.csv", index=False, encoding="utf-8-sig")
print(f"D17 역코드 {len(key)}개 중 D18 역번호와 일치 {key.in_d18.sum()}개; D18 역번호 {D.역번호.nunique()}개")

A = D[(D.승하차구분 == "승차") & D.수송일자.str.startswith("2025-08")].copy()
A["wkday"] = pd.to_datetime(A.수송일자).dt.weekday < 5
def hourshare(x):
    s = x[hc].sum().rename(index=hmap); return s / s.sum()
HS = A.groupby("역번호").apply(hourshare)
HSw = A[A.wkday].groupby("역번호").apply(hourshare)
r8 = W[W.ym == "202508"].set_index("code")
Q6 = pd.DataFrame({"share_10_16": HS[H].sum(1), "share_10_16_weekday": HSw[H].sum(1), "board_aug": A.groupby("역번호")[hc].sum().sum(1)}).join(
    r8[["ratio", "total"]], how="inner").join(names)
Q6.to_csv(OUT / "q6_station_hourshare_vs_ratio.csv", encoding="utf-8-sig")
r_all = spearmanr(Q6.ratio, Q6.share_10_16); r_wd = spearmanr(Q6.ratio, Q6.share_10_16_weekday)
print(f"Q6 n={len(Q6)} 스피어만 ρ(우대권비율, 10~16시 비중) 전체일 {r_all.statistic:.3f} (p={r_all.pvalue:.1e}), 평일 {r_wd.statistic:.3f}")
hc_corr = pd.DataFrame([dict(hour=h, rho=spearmanr(Q6.ratio, HS.loc[Q6.index, h]).statistic) for h in sorted(set(hmap.values()))])
hc_corr.to_csv(OUT / "q6_hour_corr.csv", index=False)

# D12 65세 이상 vs 전 연령 시각 분포 (도착시각 기준, 출발동 서울, 2025-08) — 비교용
prof = None
if (OUT / "d12_dep_dong_hour.csv").exists():   # s02 산출이 있어야 그린다
    d12 = pd.read_csv(OUT / "d12_dep_dong_hour.csv", dtype={"dong7": str})
    prof = d12.groupby(["ag", "hour"]).v.sum().unstack(0); prof["all"] = prof.sum(1)
    prof = prof / prof.sum(); prof.to_csv(OUT / "d12_hour_profile_65p_vs_all.csv", encoding="utf-8-sig")
    print("D12 10~16시 비중: 65+ %.3f, 전 연령 %.3f" % (prof.loc[H, "65p"].sum(), prof.loc[H, "all"].sum()))
# 지하철 상·하위 우대권 사분위 역의 시각 분포
q = Q6.ratio.quantile([.25, .75])
top, bot = HS.loc[Q6.index[Q6.ratio >= q[.75]]].mean(), HS.loc[Q6.index[Q6.ratio <= q[.25]]].mean()

fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))
ax = axs[0]
ax.scatter(Q6.ratio * 100, Q6.share_10_16 * 100, s=14, color=C1, alpha=.75, edgecolor="#fcfcfb", linewidth=.5)
ax.set_xlabel("우대권 비율, 2025-08 (%)"); ax.set_ylabel("10~16시 승차 비중, 2025-08 (%)")
ax.set_title(f"역별 우대권 비율 vs 10~16시 승차 비중 (n={len(Q6)}, ρ={r_all.statistic:.2f})", fontsize=10.5, loc="left")
ax = axs[1]
hrs = list(range(5, 25))
ax.plot(hrs, top.reindex(hrs) * 100, color=C2, lw=2, label="지하철: 우대권 비율 상위 25% 역")
ax.plot(hrs, bot.reindex(hrs) * 100, color=C1, lw=2, label="지하철: 우대권 비율 하위 25% 역")
if prof is not None: ax.plot(range(24), prof["65p"] * 100, color="#52514e", lw=1.5, ls="--", label="D12 65세 이상 이동(도착시각)")
ax.axvspan(10, 17, color="#e6e5e0", alpha=.5, lw=0)
ax.set_xlabel("시각 (D18 승차 시각 / D12 도착 시각)"); ax.set_ylabel("하루 중 비중 (%)"); ax.legend(fontsize=8, frameon=False)
ax.set_title("시각별 분포, 2025-08 (회색 = 10~16시)", fontsize=10.5, loc="left")
fig.tight_layout(); fig.savefig(OUT / "fig_q6_scatter_profile.png", dpi=150); plt.close(fig)

# ---------- D19 표본 ----------
O = pd.read_csv(RAW / "D19_subway_od_30min_2021/서울시 지하철 30분단위 출발-도착 데이터.csv", encoding="cp949", dtype=str)
O["n"] = pd.to_numeric(O["인원합계(PASSN_CNT)"])
u = O.groupby("사용자구분(BILL_USER)").agg(rows=("n", "size"), passengers=("n", "sum")).sort_values("rows", ascending=False)
u.to_csv(OUT / "q1_d19_sample_usertype.csv", encoding="utf-8-sig"); print(u.to_string())
pref = u.loc[["경로", "장애인", "국가유공자"]]
print("표본 우대 3종 중 경로 비중: 행 %.3f, 인원 %.3f" % (pref.rows["경로"] / pref.rows.sum(), pref.passengers["경로"] / pref.passengers.sum()))
