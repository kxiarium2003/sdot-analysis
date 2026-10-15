"""1단계 절대 기온 지도 (그림 A·B·C). 재계산 없이 out/step1 의 step1_gu.csv, step1_dong.csv, gu25_rank_abs_vs_dT.csv 만 쓴다.
모든 값은 '2024+2025' 행(두 해 여름 평균). 경계는 2016 집계구를 코드 앞 5자리(자치구)·7자리(행정동)로 합친 것(모양만 사용).
출력: out/step1_fig/figA_gu_abs_day_night.png, figB_dong_abs_day_night.png, figC_gu_dT_vs_abs_day.png, captions_maps.md
실행: PYTHONDONTWRITEBYTECODE=1 python3 rq1_followup/step1_maps.py
"""
import json
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
S1 = ROOT / "rq1_followup/out/step1"; OUT = ROOT / "rq1_followup/out/step1_fig"; OUT.mkdir(parents=True, exist_ok=True)
plt.rcParams["font.family"] = "AppleGothic"; plt.rcParams["axes.unicode_minus"] = False
CAVEAT = "단서: 절대 기온은 그 센서가 잰 기온이며 설치 환경 차이(1.2–2.0°C) 포함. 동 단위 값은 하한, 집계구는 상한."
CMAP = "YlOrRd"; check = {}

gu = pd.read_csv(S1 / "step1_gu.csv", dtype={"gu5": str, "year": str}); gu = gu[gu.year == "2024+2025"]
dong = pd.read_csv(S1 / "step1_dong.csv", dtype={"dong7": str, "year": str}); dong = dong[dong.year == "2024+2025"]
rk = pd.read_csv(S1 / "gu25_rank_abs_vs_dT.csv")
B = gpd.read_file(ROOT / "merged_data/D9_boundary/bnd_oa_11_2016_4Q/bnd_oa_11_2016_4Q.shp").set_crs(5179, allow_override=True)
B["gu5"] = B.TOT_REG_CD.astype(str).str[:5]; B["dong7"] = B.TOT_REG_CD.astype(str).str[:7]
GU = B[["gu5", "geometry"]].dissolve(by="gu5").reset_index().merge(gu, on="gu5")
DG = B[["dong7", "geometry"]].dissolve(by="dong7").reset_index().merge(dong, on="dong7")


def colorbar(fig, ax, lo, hi, n=5, extend="neither"):
    sm = plt.cm.ScalarMappable(cmap=CMAP, norm=plt.Normalize(lo, hi))
    cb = fig.colorbar(sm, ax=ax, shrink=.7, extend=extend); tk = np.linspace(lo, hi, n); cb.set_ticks(tk); cb.set_ticklabels([f"{t:.2f}" for t in tk])


def gu_panel(fig, ax, col, title, mark_top=False, label_all=True):
    lo, hi = GU[col].min(), GU[col].max()
    GU.plot(column=col, ax=ax, cmap=CMAP, vmin=lo, vmax=hi, edgecolor="#555555", linewidth=.6)
    top = GU.nlargest(5, col)
    for _, r in GU.iterrows():
        p = r.geometry.representative_point(); is_top = r.gu5 in set(top.gu5)
        if label_all or is_top:
            ax.text(p.x, p.y, f"{r['name']}\n{r[col]:.2f}", ha="center", va="center", fontsize=7.5,
                    fontweight="bold" if (mark_top and is_top) else "normal",
                    bbox=dict(boxstyle="round,pad=.15", fc="white", ec="black" if (mark_top and is_top) else "none", lw=.8, alpha=.8))
    colorbar(fig, ax, lo, hi); ax.axis("off")
    ax.set_title(f"{title}\n색 범위 최소–최대 {lo:.2f}–{hi:.2f}°C", fontsize=11)
    return dict(min=float(lo), max=float(hi), top5=[(r["name"], round(float(r[col]), 2)) for _, r in top.iterrows()])


# 그림 A
fig, axs = plt.subplots(1, 2, figsize=(17, 7.5))
check["A"] = {c: gu_panel(fig, ax, c, t) for ax, c, t in zip(axs, ("abs_day_mean", "abs_night_mean"), ("낮(07–20시) 평균 절대 기온", "밤(21–06시) 평균 절대 기온"))}
fig.suptitle("자치구 25개 절대 기온 (배경 기온 + ΔT 예측값), 2024·2025 여름 평균", fontsize=13)
fig.text(.5, .03, CAVEAT, ha="center", fontsize=8.5)
fig.savefig(OUT / "figA_gu_abs_day_night.png", dpi=150, bbox_inches="tight"); plt.close(fig)

# 그림 B
fig, axs = plt.subplots(1, 2, figsize=(17, 7.5)); check["B"] = {}
for ax, col, t in zip(axs, ("abs_day_mean", "abs_night_mean"), ("낮(07–20시) 평균 절대 기온", "밤(21–06시) 평균 절대 기온")):
    lo, hi = np.percentile(DG[col], 5), np.percentile(DG[col], 95)
    DG.plot(column=col, ax=ax, cmap=CMAP, vmin=lo, vmax=hi, edgecolor="white", linewidth=.2)
    top = DG.nlargest(5, col); lines = []
    for i, (_, r) in enumerate(top.iterrows(), 1):
        p = r.geometry.representative_point()
        ax.text(p.x, p.y, str(i), ha="center", va="center", fontsize=8, fontweight="bold", bbox=dict(boxstyle="circle,pad=.15", fc="white", ec="black", lw=.6))
        lines.append(f"{i}. {r['name']} {r[col]:.2f}")
    ax.text(0.0, 0.02, "가장 더운 5개 동\n" + "\n".join(lines), transform=ax.transAxes, fontsize=9, va="bottom",
            bbox=dict(boxstyle="round,pad=.4", fc="white", ec="#999999", alpha=.95))
    colorbar(fig, ax, lo, hi, extend="both"); ax.axis("off")
    ax.set_title(f"{t}\n색 범위 5–95백분위 {lo:.2f}–{hi:.2f}°C", fontsize=11)
    check["B"][col] = dict(p5=float(lo), p95=float(hi), top5=[(r["name"], round(float(r[col]), 2)) for _, r in top.iterrows()])
fig.suptitle("행정동 424개 절대 기온 (배경 기온 + ΔT 예측값), 2024·2025 여름 평균", fontsize=13)
fig.text(.5, .03, CAVEAT, ha="center", fontsize=8.5)
fig.savefig(OUT / "figB_dong_abs_day_night.png", dpi=150, bbox_inches="tight"); plt.close(fig)

# 그림 C
fig, axs = plt.subplots(1, 2, figsize=(17, 7.5))
check["C"] = {c: gu_panel(fig, ax, c, t, mark_top=True, label_all=True) for ax, c, t in
              zip(axs, ("dT_day_mean", "abs_day_mean"), ("낮(07–20시) 평균 ΔT 예측값 (°C)", "낮(07–20시) 평균 절대 기온 (°C)"))}
fig.suptitle("자치구 25개 낮 평균: ΔT 예측값 vs 절대 기온 (같은 색상표, 각자 범위; 굵은 테두리 = 상위 5개 구)", fontsize=13)
fig.text(.5, .03, CAVEAT, ha="center", fontsize=8.5)
fig.savefig(OUT / "figC_gu_dT_vs_abs_day.png", dpi=150, bbox_inches="tight"); plt.close(fig)

tA, tC = check["A"], check["C"]
both = sorted(set(n for n, _ in tC["dT_day_mean"]["top5"]) & set(n for n, _ in tC["abs_day_mean"]["top5"]))
cap = ["# 1단계 절대 기온 지도 캡션 (그림 A·B·C)\n",
       "\n그림: out/step1_fig/figA_gu_abs_day_night.png\n",
       f"\n**읽는 법:** 진할수록 더운 구. 낮 가장 더운 구는 {tA['abs_day_mean']['top5'][0][0]}({tA['abs_day_mean']['top5'][0][1]:.2f}°C), "
       f"밤은 {tA['abs_night_mean']['top5'][0][0]}({tA['abs_night_mean']['top5'][0][1]:.2f}°C). 구 간 차이는 낮 {tA['abs_day_mean']['max'] - tA['abs_day_mean']['min']:.2f}°C, "
       f"밤 {tA['abs_night_mean']['max'] - tA['abs_night_mean']['min']:.2f}°C(최대 − 최소).\n",
       f"\n{CAVEAT}\n",
       "\n그림: out/step1_fig/figB_dong_abs_day_night.png\n",
       f"\n**읽는 법:** 번호 1–5가 가장 더운 동. 낮 상위 5: {', '.join(n for n, _ in check['B']['abs_day_mean']['top5'])} / "
       f"밤 상위 5: {', '.join(n for n, _ in check['B']['abs_night_mean']['top5'])}. 색 범위는 각 지도의 5–95백분위.\n",
       f"\n{CAVEAT}\n",
       "\n그림: out/step1_fig/figC_gu_dT_vs_abs_day.png\n",
       f"\n**읽는 법:** 같은 색상표라도 진한 구가 다르다. ΔT 예측값 상위 5: {', '.join(n for n, _ in tC['dT_day_mean']['top5'])} / "
       f"절대 기온 상위 5: {', '.join(n for n, _ in tC['abs_day_mean']['top5'])}. 두 목록에 모두 있는 구: {', '.join(both) or '없음'}.\n",
       f"\n{CAVEAT}\n"]
open(OUT / "captions_maps.md", "w").write("".join(cap))
json.dump(check, open(OUT / "_check_maps.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(check, ensure_ascii=False, indent=1))
