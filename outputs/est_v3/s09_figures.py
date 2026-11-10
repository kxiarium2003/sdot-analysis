"""s09_figures.py - 지도·그림. dataviz 기본 팔레트 1~3번 슬롯(전 쌍 검증값) 사용, 정적 PNG.

출력: fig_o1_map_{연도}.png, fig_o1_gu_uncovered.png, fig_o3_selected_map.png
"""
import sys, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd, geopandas as gpd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from scipy.spatial import cKDTree

plt.rcParams["font.family"] = "AppleGothic"; plt.rcParams["axes.unicode_minus"] = False
SURF, INK, MUT, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#d9d8d2"
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"
dong = gpd.read_file(DONG_SHP).set_crs("EPSG:5179", allow_override=True)
gu = dong.dissolve("SIGUNGU_CD")
years = sorted({os.path.basename(f)[4:8] for f in glob.glob(str(SCRATCH / "est/est_*.parquet"))})


def load(y):
    c = duck(); f = [x for x in glob.glob(str(SCRATCH / "est/est_*.parquet")) if os.path.basename(x)[4:8] == y]; s = "[" + ",".join(f"'{x}'" for x in f) + "]"
    n = c.execute(f"SELECT count(DISTINCT date) FROM read_parquet({s})").fetchone()[0]
    w = c.execute(f"SELECT node, SUM(CASE WHEN hour BETWEEN 11 AND 17 THEN board65_mid ELSE 0 END)/{n} w65 FROM read_parquet({s}) GROUP BY 1").df()
    st = pd.read_parquet(SCRATCH / f"geo/stops_{y}.parquet")[["node", "x", "y"]].merge(w, on="node", how="left").fillna({"w65": 0})
    sm = set(pd.read_parquet(SCRATCH / f"shelters/smart_links_{y}.parquet").node); co = pd.read_parquet(SCRATCH / f"shelters/cooling_{y}.parquet")
    st["smart"] = st.node.isin(sm)
    st["cool"] = [len(n) > 0 for n in cKDTree(co[["x", "y"]].to_numpy()).query_ball_point(st[["x", "y"]].to_numpy(), r=300)]
    return st, co


def base(ax):
    gu.boundary.plot(ax=ax, color=GRID, linewidth=0.8, zorder=1); ax.set_aspect("equal"); ax.axis("off")


for y in years:
    st, co = load(y)
    fig, ax = plt.subplots(figsize=(10, 8.4), facecolor=SURF); base(ax)
    ax.scatter(st.x, st.y, s=0.8 + st.w65 / st.w65.max() * 90, c="#a7a69f", alpha=.45, linewidths=0, zorder=2)
    ax.scatter(co.x, co.y, s=4, c=C3, alpha=.55, linewidths=0, zorder=3)
    sm = st[st.smart]; ax.scatter(sm.x, sm.y, s=38, c=C1, edgecolors=SURF, linewidths=.8, zorder=5)
    un = st[~st.smart & ~st.cool].sort_values("w65", ascending=False).head(50)
    ax.scatter(un.x, un.y, s=46, c=C2, edgecolors=SURF, linewidths=.8, marker="D", zorder=6)
    ax.set_title(f"{y} 정류장 65+ 승차(11~17시)와 폭염 쉼터", loc="left", fontsize=13, color=INK, pad=10)
    h = [Line2D([], [], marker="o", ls="", color="#a7a69f", label="정류장(크기 = 65+ 승차)"), Line2D([], [], marker="o", ls="", color=C3, ms=4, label="D7 무더위쉼터"), Line2D([], [], marker="o", ls="", color=C1, label="D14 폭염저감시설 스마트쉼터 정류장(ID 연결분)"), Line2D([], [], marker="D", ls="", color=C2, label="커버 안 된 상위 50개 정류장(300m)")]
    ax.legend(handles=h, loc="lower left", frameon=False, labelcolor=MUT, fontsize=9.5)
    fig.savefig(OUT / f"fig_o1_map_{y}.png", dpi=180, bbox_inches="tight", facecolor=SURF); plt.close(fig)

g = pd.read_csv(OUT / "o1_coverage_gu.csv", dtype={"연도": str}); g = g[g.기준.str.startswith("w65")]
order = g[g.연도 == years[-1]].sort_values("d없음").gu.tolist()
fig, ax = plt.subplots(figsize=(7.8, 7.6), facecolor=SURF)
n = len(years); yy = np.arange(len(order)); hgt = .72 / n
for i, y in enumerate(years):
    t = g[g.연도 == y].set_index("gu").loc[order]
    ax.barh(yy + (i - (n - 1) / 2) * hgt, t.d없음 * 100, height=hgt - .06, color=[C1, C2][i], label=f"{y}년", zorder=3)
ax.set_yticks(yy); ax.set_yticklabels(order, color=MUT, fontsize=9.5); ax.set_xlabel("커버 없는 65+ 승차 비율(%), 무더위쉼터 300m·스마트쉼터 기준", color=MUT, fontsize=9.5)
ax.tick_params(axis="x", colors=MUT, length=0); ax.tick_params(axis="y", length=0); ax.grid(axis="x", color=GRID, lw=.6, zorder=0)
for s in ax.spines.values(): s.set_visible(False)
ax.set_title("자치구별 쉼터 커버 밖 65+ 승차 비율", loc="left", fontsize=13, color=INK, pad=10)
if n > 1: ax.legend(frameon=False, labelcolor=MUT, loc="lower right")
fig.savefig(OUT / "fig_o1_gu_uncovered.png", dpi=180, bbox_inches="tight", facecolor=SURF); plt.close(fig)

y = years[-1]; st, co = load(y)
o3 = pd.read_csv(OUT / f"o3_selected_{y}.csv", dtype={"ars": str}); st2 = pd.read_parquet(SCRATCH / f"geo/stops_{y}.parquet")[["ars", "x", "y"]]; o3 = o3.merge(st2, on="ars")
o2 = pd.read_csv(OUT / f"o2_selected_{y}.csv", dtype={"ars": str}).head(100).merge(st2, on="ars")
fig, ax = plt.subplots(figsize=(10, 8.4), facecolor=SURF); base(ax)
un = st[~st.smart & ~st.cool]; ax.scatter(un.x, un.y, s=1 + un.w65 / un.w65.max() * 60, c="#a7a69f", alpha=.6, linewidths=0, zorder=2)
p = gpd.GeoSeries(gpd.points_from_xy(o3.x, o3.y), crs=5179).buffer(300); p.plot(ax=ax, color=C3, alpha=.3, zorder=3)
ax.scatter(o3.x, o3.y, s=30, c=C3, edgecolors=SURF, linewidths=.7, zorder=5)
ax.scatter(o2.x, o2.y, s=26, c=C1, edgecolors=SURF, linewidths=.6, marker="s", zorder=4)
ax.set_title(f"{y} 배치 baseline: O2 스마트쉼터 상위 100개, O3 무더위쉼터 50개(후보 위치 대용)", loc="left", fontsize=12, color=INK, pad=10)
h = [Line2D([], [], marker="o", ls="", color="#a7a69f", label="커버 안 된 정류장(크기 = 65+ 승차)"), Line2D([], [], marker="o", ls="", color=C3, label="O3 선택 위치(반경 300m)"), Line2D([], [], marker="s", ls="", color=C1, label="O2 선택 정류장 상위 100개")]
ax.legend(handles=h, loc="lower left", frameon=False, labelcolor=MUT, fontsize=9.5)
fig.savefig(OUT / "fig_o3_selected_map.png", dpi=180, bbox_inches="tight", facecolor=SURF); plt.close(fig)
