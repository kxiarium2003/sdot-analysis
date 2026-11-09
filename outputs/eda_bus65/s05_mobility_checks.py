"""
s05_mobility_checks.py - s02 요약표로 Q3(마스킹 영향), Q4(출발/도착 시각), Q5(대리 지표 일관성) 수치 계산

입력: outputs/eda_bus65/ 의 d12_dep_dong_hour.csv, d12_dep_dong_hour_wd.csv, d13_dep_dong_hour.csv.gz,
      dong_crosswalk_8to7.csv, q2_monthly_citywide.csv (s02, s03 산출)
출력(outputs/eda_bus65/):
  q3_share_bounds_dong.csv   동별 10~16시 65+ 비율 하한·상한(분모 별표 = 0 / 3)
  q3_summary.csv             마스킹 영향 요약
  q4_hour_profiles.csv       D12 65+ 도착시각, D13 60+ 출발·도착시각 분포
  q5_dong_share_d12_vs_d13.csv  동별 D12 65+ 비율 vs D13 60+ 비율
  q5_citywide_coef.csv       서울 전체: D17 우대권 비율 vs D12 65+ 비율
  gu_65p_share.csv           자치구별 10~16시 65+ 비율과 구 안 동 간 범위
  fig_q4_hour_profiles.png, fig_q5_dong_share.png
실행: python outputs/eda_bus65/s05_mobility_checks.py
"""
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]; OUT = ROOT / "outputs/eda_bus65"
plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": "#52514e", "xtick.color": "#52514e", "ytick.color": "#52514e", "figure.facecolor": "#fcfcfb",
                     "axes.facecolor": "#fcfcfb", "axes.grid": True, "grid.color": "#e6e5e0", "grid.linewidth": .6})
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"
H = list(range(10, 17)); STAR_HI = 3
import sys; sys.path.insert(0, str(ROOT))
from rq1_modules.common import GU, dong_names
NM = dong_names()

d12 = pd.read_csv(OUT / "d12_dep_dong_hour.csv", dtype={"dong7": str})
cw = pd.read_csv(OUT / "dong_crosswalk_8to7.csv", dtype=str)
d13 = pd.read_csv(OUT / "d13_dep_dong_hour.csv.gz", dtype={"dong8": str}).merge(cw, on="dong8", how="left")

# ---------- Q3 ----------
w = d12[d12.hour.isin(H)].pivot_table(index="dong7", columns="ag", values=["v", "n_star"], aggfunc="sum")
b = pd.DataFrame({"v65": w["v"]["65p"], "vu65": w["v"]["u65"], "star65": w["n_star"]["65p"], "staru65": w["n_star"]["u65"]})
b["share_hi"] = b.v65 / (b.v65 + b.vu65)                                   # 별표 = 0 → 분모 최소 → 비율 상한
b["share_lo"] = b.v65 / (b.v65 + b.vu65 + STAR_HI * b.staru65)              # 별표 = 3 → 비율 하한
b["gap_pp"] = 100 * (b.share_hi - b.share_lo)
b["name"] = b.index.map(NM); b.to_csv(OUT / "q3_share_bounds_dong.csv", encoding="utf-8-sig")
cell = d12.groupby(["dong7", "hour", "ag"])[["n_star"]].sum().reset_index()
allcell = d12.groupby(["dong7", "hour"]).n_star.sum()
tot = d12.groupby("ag")[["v", "n_star", "n_rows"]].sum()
q3 = pd.Series({
    "65p_star_rows": tot.loc["65p", "n_star"], "65p_rows": tot.loc["65p", "n_rows"],
    "u65_star_row_share": tot.loc["u65", "n_star"] / tot.loc["u65", "n_rows"],
    "u65_underest_upper_pct": 100 * STAR_HI * tot.loc["u65", "n_star"] / (tot.loc["u65", "v"] + STAR_HI * tot.loc["u65", "n_star"]),
    "dong_hour_cells_allage_with_star_share": (allcell > 0).mean(),
    "dong_hour_cells_65p_with_star_share": (cell[cell.ag == "65p"].n_star > 0).mean(),
    "seoul_share65_10_16_hi": b.v65.sum() / (b.v65.sum() + b.vu65.sum()),
    "seoul_share65_10_16_lo": b.v65.sum() / (b.v65.sum() + b.vu65.sum() + STAR_HI * b.staru65.sum()),
    "dong_gap_pp_median": b.gap_pp.median(), "dong_gap_pp_max": b.gap_pp.max(),
    "dong_rank_rho_lo_vs_hi": spearmanr(b.share_lo, b.share_hi).statistic})
q3.to_csv(OUT / "q3_summary.csv", header=["value"], encoding="utf-8-sig"); print("[Q3]\n", q3.round(4).to_string())

# ---------- Q4 ----------
p12 = d12[d12.ag == "65p"].groupby("hour").v.sum(); p12a = d12.groupby("hour").v.sum()
p13d = d13.groupby("st_hour").v60.sum(); p13a = d13.groupby("fns_hour").v60.sum(); p13t = d13.groupby("st_hour").vtot.sum()
prof = pd.DataFrame({"d12_65p_arr": p12 / p12.sum(), "d12_all_arr": p12a / p12a.sum(), "d13_60p_dep": p13d / p13d.sum(),
                     "d13_60p_arr": p13a / p13a.sum(), "d13_all_dep": p13t / p13t.sum()}).fillna(0)
prof.to_csv(OUT / "q4_hour_profiles.csv", encoding="utf-8-sig")
mt60 = d13.mt60.sum() / d13.v60.sum(); mtt = d13.mttot.sum() / d13.vtot.sum()
same_hr = d13[d13.st_hour == d13.fns_hour].v60.sum() / d13.v60.sum()
print("[Q4] 10~16시 비중", prof.loc[H].sum().round(3).to_dict(), f"\n  D13 평균 이동시간 60+ {mt60:.1f}분, 전체 {mtt:.1f}분; 60+ 출발·도착 같은 시각 비율 {same_hr:.3f}")
fig, ax = plt.subplots(figsize=(8, 4))
for c, col, lab, ls in [("d12_65p_arr", C2, "D12 65세 이상, 도착시각", "-"), ("d13_60p_dep", C1, "D13 60세 이상, 출발시각", "-"),
                        ("d13_60p_arr", C1, "D13 60세 이상, 도착시각", "--"), ("d12_all_arr", "#52514e", "D12 전 연령, 도착시각", ":")]:
    ax.plot(prof.index, prof[c] * 100, color=col, lw=2 if ls == "-" else 1.5, ls=ls, label=lab)
ax.axvspan(10, 17, color="#e6e5e0", alpha=.5, lw=0)
ax.set_xlabel("시각"); ax.set_ylabel("하루 이동 중 비중 (%)"); ax.legend(frameon=False, fontsize=8.5)
ax.set_title("서울 출발 이동의 시각 분포, 2025-08 (회색 = 10~16시)", fontsize=11, loc="left")
fig.tight_layout(); fig.savefig(OUT / "fig_q4_hour_profiles.png", dpi=150); plt.close(fig)

# ---------- Q5 (동 단위: D12 vs D13 / 서울 전체: D17 vs D12) ----------
x13 = d13[d13.st_hour.isin(H) & d13.dong7.notna()].groupby("dong7")[["v60", "vtot"]].sum()
x13["share60_d13"] = x13.v60 / x13.vtot
x13e = d13[d13.st_hour.isin(H) & d13.dong7.notna() & ~d13.same].groupby("dong7")[["v60", "vtot"]].sum()
c = b.join(x13[["share60_d13"]], how="inner").join((x13e.v60 / x13e.vtot).rename("share60_d13_excl_same"))
x12e = d12[d12.hour.isin(H) & ~d12.same].pivot_table(index="dong7", columns="ag", values="v", aggfunc="sum")
c["share65_d12_excl_same_hi"] = x12e["65p"] / x12e.sum(1)
c.to_csv(OUT / "q5_dong_share_d12_vs_d13.csv", encoding="utf-8-sig")
r1 = spearmanr(c.share_hi, c.share60_d13).statistic; r2 = spearmanr(c.share65_d12_excl_same_hi, c.share60_d13_excl_same).statistic
print(f"[Q5] 동 {len(c)}개: D12 65+ 비율(상한) vs D13 60+ 비율 ρ={r1:.3f}; 동내 이동 제외 ρ={r2:.3f}")
cm = pd.read_csv(OUT / "q2_monthly_citywide.csv", dtype={"ym": str}).set_index("ym")
alld = d12.groupby("ag").v.sum(); all_star = d12[d12.ag == "u65"].n_star.sum()
cc = pd.Series({"d17_ratio_202508": cm.loc["202508", "ratio"],
                "d12_share65_allhours_hi": alld["65p"] / alld.sum(), "d12_share65_allhours_lo": alld["65p"] / (alld.sum() + STAR_HI * all_star),
                "d12_share65_10_16_hi": q3.seoul_share65_10_16_hi, "d12_share65_10_16_lo": q3.seoul_share65_10_16_lo})
cc["coef_allhours_hi"] = cc.d17_ratio_202508 / cc.d12_share65_allhours_hi; cc["coef_allhours_lo"] = cc.d17_ratio_202508 / cc.d12_share65_allhours_lo
cc.to_csv(OUT / "q5_citywide_coef.csv", header=["value"], encoding="utf-8-sig"); print(cc.round(4).to_string())

fig, ax = plt.subplots(figsize=(5.5, 5))
ax.scatter(c.share_hi * 100, c.share60_d13 * 100, s=12, color=C1, alpha=.7, edgecolor="#fcfcfb", linewidth=.4)
ax.set_xlabel("D12 65세 이상 비율 (%, 도착 10~16시, 상한)"); ax.set_ylabel("D13 60세 이상 비율 (%, 출발 10~16시)")
ax.set_title(f"행정동 출발 이동 중 고령자 비율, 2025-08\n(n={len(c)}, ρ={r1:.2f})", fontsize=10.5, loc="left")
fig.tight_layout(); fig.savefig(OUT / "fig_q5_dong_share.png", dpi=150); plt.close(fig)

# ---------- 자치구 수준 변동 (방법 A 자치구판 판단용) ----------
b["gu"] = b.index.str[:5]
g = b.groupby("gu").agg(v65=("v65", "sum"), vu65=("vu65", "sum"), dong_min=("share_hi", "min"), dong_max=("share_hi", "max"), n_dong=("v65", "size"))
g["share_hi"] = g.v65 / (g.v65 + g.vu65); g["name"] = g.index.map(GU)
g.to_csv(OUT / "gu_65p_share.csv", encoding="utf-8-sig")
print("[자치구] 65+ 비율 범위 %.3f~%.3f; 종로구 %.3f (동 %.3f~%.3f)" % (g.share_hi.min(), g.share_hi.max(), *g.loc["11010", ["share_hi", "dong_min", "dong_max"]]))
print("동 비율 분산 중 자치구 간 비중 %.2f" % (b.groupby("gu").share_hi.transform("mean").var() / b.share_hi.var()))
