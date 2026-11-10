"""s03b_compare_figs.py - 하차 시각 H1·H2 비교표, 일별 서울 전체 그림.

입력: s03_month_hour_vs_d16.csv, s03_daily_seoul_totals.csv
출력: s03b_alight_h1_h2_vs_d16.csv, s03b_daily_d25_vs_d15.csv, fig_s03_daily_seoul.png, fig_s03_alight_hour_h1_h2.png
그림 색은 dataviz 기본 팔레트 슬롯 1~3 (문서상 전 쌍 검증값).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("EST_V2_SCRATCH", "/tmp")
from s00_common import OUT, D25_MISSING, HOLIDAYS
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

plt.rcParams["font.family"] = "AppleGothic"; plt.rcParams["axes.unicode_minus"] = False
S1, S2, S3, INK, INK2, MUTE, GRID, BASE, SURF = "#2a78d6", "#eb6834", "#1baf7a", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"


def style(ax):
    ax.set_facecolor(SURF); ax.grid(axis="y", color=GRID, lw=.6); ax.set_axisbelow(True)
    for s in ("top", "right", "left"): ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(BASE); ax.tick_params(colors=MUTE, length=0, labelsize=8)


# H1/H2 vs D16: 시간대 점유율 비교(결측일이 있는 달도 공정하게 비교)
m = pd.read_csv(OUT / "s03_month_hour_vs_d16.csv")
rows = []
for ym, x in m.groupby("ym"):
    full = x.n_days.iloc[0] == x.all_days.iloc[0]
    d = x.d16_alight.to_numpy() / x.d16_alight.sum()
    for nm in ("h1", "h2"):
        s = x[nm].to_numpy() / x[nm].sum()
        pp = (s - d) * 100
        mh = ((s - d) * np.arange(24)).sum()
        rows.append(dict(ym=ym, 방식=nm.upper(), 전체일수비교=bool(full), 최대점유율차_pp=float(np.abs(pp).max()), 최대차시각=int(np.abs(pp).argmax()), 총변동거리_TVD=float(np.abs(s - d).sum() / 2), 평균시각차_시간=float(mh),
                         월합_D16대비pct=float((x[nm].sum() / x.d16_alight.sum() - 1) * 100) if full else np.nan,
                         오전7시pp=float(pp[7]), 오전8시pp=float(pp[8]), 오후19시pp=float(pp[19])))
r = pd.DataFrame(rows); r.to_csv(OUT / "s03b_alight_h1_h2_vs_d16.csv", index=False, encoding="utf-8-sig"); print(r.round(4).to_string())
bb = []
for ym, x in m.groupby("ym"):
    bb.append(dict(ym=ym, 승차_최대점유율차_pp=float(np.abs(x.d25_board / x.d25_board.sum() - x.d16_board / x.d16_board.sum()).max() * 100), 승차월합_D16대비pct=float((x.d25_board.sum() / x.d16_board.sum() - 1) * 100) if x.n_days.iloc[0] == x.all_days.iloc[0] else np.nan))
print(pd.DataFrame(bb).round(4).to_string())
pd.DataFrame(bb).to_csv(OUT / "s03b_board_vs_d16.csv", index=False, encoding="utf-8-sig")

d = pd.read_csv(OUT / "s03_daily_seoul_totals.csv", dtype={"date": str})
g = d.groupby("date", as_index=False).agg(board=("board", "sum"), alight=("alight_h1", "sum"), d15_board=("d15_board", "first"), d15_alight=("d15_alight", "first"), imputed=("imputed", "max"))
g["승차차이pct"] = (g.board / g.d15_board - 1) * 100; g["하차차이pct"] = (g.alight / g.d15_alight - 1) * 100
g.to_csv(OUT / "s03b_daily_d25_vs_d15.csv", index=False, encoding="utf-8-sig")
print(g.loc[g["승차차이pct"].abs().sort_values(ascending=False).index].head(8).round(3).to_string())
g["dt"] = pd.to_datetime(g.date)
fig, axs = plt.subplots(2, 2, figsize=(11, 6), facecolor=SURF, sharey=True)
for ax, ym in zip(axs.ravel(), ["202407", "202408", "202507", "202508"]):
    x = g[g.date.str.startswith(ym)]
    ax.plot(x.dt, x.board / 1e6, color=S1, lw=1.5, label="승차")
    ax.plot(x.dt, x.alight / 1e6, color=S2, lw=1.5, label="하차(D25 하차 ID 있음)")
    imp = x[x.imputed]
    if len(imp):
        ax.scatter(imp.dt, imp.board / 1e6, s=48, facecolor=SURF, edgecolor=INK2, zorder=4, lw=1.2, label="결측일(D15·D16 대체)")
    hol = x[x.date.isin(HOLIDAYS)]
    for _, h in hol.iterrows():
        ax.annotate("광복절", (h["dt"], h["board"] / 1e6), xytext=(0, -14), textcoords="offset points", ha="center", fontsize=7, color=INK2)
    ax.set_title(f"{ym[:4]}-{ym[4:]}", loc="left", fontsize=10, color=INK); style(ax)
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=7)); ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.set_ylim(0, None)
h, l = [], []
for ax in axs.ravel():
    a, b = ax.get_legend_handles_labels()
    for i, j in zip(a, b):
        if j not in l: h.append(i); l.append(j)
fig.legend(h, l, loc="lower center", ncol=3, frameon=False, fontsize=9)
axs[0, 0].set_ylabel("서울 전체(백만 명/일)", fontsize=8, color=MUTE); axs[1, 0].set_ylabel("서울 전체(백만 명/일)", fontsize=8, color=MUTE)
fig.suptitle("D25 기반 서울 버스 일별 승차·하차 (ARS 01~25, 가상정류장 제외)", x=.01, ha="left", fontsize=12, color=INK)
fig.tight_layout(rect=(0, .05, 1, .96)); fig.savefig(OUT / "fig_s03_daily_seoul.png", dpi=150)

fig, ax = plt.subplots(figsize=(9, 4.2), facecolor=SURF)
x = m[m.ym == 202508]
tot = lambda c: x[c].to_numpy() / x[c].sum() * 100
ax.plot(x.hour, tot("d16_alight"), color=S3, lw=2.2, label="D16 실제 하차")
ax.plot(x.hour, tot("h1"), color=S1, lw=1.5, marker="o", ms=4, label="H1: D25 시각(승차 시각)")
ax.plot(x.hour, tot("h2"), color=S2, lw=1.5, ls="--", label="H2: D16 하차 분포로 재배분")
ax.set_xticks(range(0, 24, 2)); ax.set_xlabel("시", fontsize=8, color=MUTE); ax.set_ylabel("하루 하차 중 비중(%)", fontsize=8, color=MUTE); style(ax)
ax.legend(frameon=False, fontsize=9); ax.set_title("2025-08 시간대별 하차 비중: H2는 D16과 겹치고 H1은 7~8시 쪽으로 이르게 잡힘", loc="left", fontsize=10, color=INK)
fig.tight_layout(); fig.savefig(OUT / "fig_s03_alight_hour_h1_h2.png", dpi=150)
