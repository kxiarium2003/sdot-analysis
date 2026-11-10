"""s10_summary.py - 평가 요약표와 비교 그림, 크게 틀리는 역의 환승 여부.

입력: s09_metrics_*.csv, s09_transfer_*.csv, s09_worst_stations.csv, geo/stations.parquet(스크래치)
출력: s10_metrics_summary.csv, s10_worst_with_transfer.csv, fig_s10_method_comparison.png
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "AppleGothic"; plt.rcParams["axes.unicode_minus"] = False
S1, S2, S3, INK, MUTE, GRID, BASE, SURF = "#2a78d6", "#eb6834", "#1baf7a", "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
U = {"station_month": "① 역×월", "station_hour": "② 역×시간대(월)", "cell": "③ 역×날짜×시"}
r = []
for u, lab in U.items():
    m = pd.read_csv(OUT / f"s09_metrics_{u}.csv"); t = pd.read_csv(OUT / f"s09_transfer_{u}.csv")
    x = m.merge(t[["예측", "평가_RMSE", "평가_R2", "평가_스피어만"]], on="예측"); x["단위라벨"] = lab; r.append(x)
a = pd.concat(r); a.to_csv(OUT / "s10_metrics_summary.csv", index=False, encoding="utf-8-sig")
P = [("P0_m3", "P0 자치구(마스킹=3)", S1), ("P1_m3", "P1 OD 매칭(마스킹=3)", S2), ("P2_300", "P2 반경 300m", S3)]
fig, axs = plt.subplots(1, 2, figsize=(10.5, 4.2), facecolor=SURF, sharey=True)
for ax, (c, tt) in zip(axs, (("CV_스피어만", "공간 교차검증 순위 상관"), ("CV_R2", "공간 교차검증 R²"))):
    w = .26
    for i, (p, lab, col) in enumerate(P):
        v = a[a["예측"] == p].set_index("단위")[c].reindex(U).to_numpy()
        xs = np.arange(3) + (i - 1) * w
        b = ax.bar(xs, v, w * .92, color=col, label=lab, edgecolor=SURF, linewidth=1)
        for xi, vi in zip(xs, v):
            ax.text(xi, vi + .012, f"{vi:.2f}", ha="center", fontsize=7.5, color=INK)
    ax.set_xticks(range(3)); ax.set_xticklabels(U.values(), fontsize=9); ax.set_title(tt, loc="left", fontsize=10, color=INK); ax.set_facecolor(SURF); ax.grid(axis="y", color=GRID, lw=.6); ax.set_axisbelow(True)
    for s in ("top", "right", "left"): ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(BASE); ax.tick_params(colors=MUTE, length=0, labelsize=8); ax.set_ylim(0, 1)
    ax.tick_params(axis="x", labelcolor=INK)
h, l = axs[0].get_legend_handles_labels()
fig.legend(h, l, loc="lower center", ncol=3, frameon=False, fontsize=9)
fig.suptitle("지하철역 65+ 승차 비율 예측: 시간대가 들어가면 P2가 크게 떨어진다", x=.01, ha="left", fontsize=12, color=INK)
fig.tight_layout(rect=(0, .07, 1, .95)); fig.savefig(OUT / "fig_s10_method_comparison.png", dpi=150)

st = pd.read_parquet(SCRATCH / "geo/stations.parquet")
s = st[st.seoul_d9].copy()


def norm(n):
    n = re.sub(r"\(.*?\)", "", str(n)).replace(" ", "").strip()
    return re.sub(r"역$", "", n) if len(n) > 2 else n


s["nm"] = s.name.map(norm)
cnt = s.groupby("nm").route.agg(list)
w = pd.read_csv(OUT / "s09_worst_stations.csv", dtype={"bldn": str})
w["bldn"] = w.bldn.str.zfill(4)
m = s.set_index("bldn")
w["환승역"] = w.bldn.map(lambda b: len(cnt[m.loc[b, "nm"]]) >= 2)
w["노선들"] = w.bldn.map(lambda b: ",".join(cnt[m.loc[b, "nm"]]))
w["구"] = w.gu_final.astype(str).map(GU_NAMES)
w.to_csv(OUT / "s10_worst_with_transfer.csv", index=False, encoding="utf-8-sig")
pd.set_option("display.width", 200)
print(w[w["방법"].isin(["P1_m3", "P2_300"])][["방법", "name", "구", "실제", "예측", "평균잔차", "환승역", "노선들"]].round(3).to_string())
for b in ("2615", "2753"):
    print(b, st[st.bldn == b][["name", "route", "seoul_d9"]].values.tolist())
