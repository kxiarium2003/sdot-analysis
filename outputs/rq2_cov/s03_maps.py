"""s03_maps.py - 지도 2장. dataviz 기본 팔레트(발산 blue↔red, 중간 회색; 범주 슬롯 2). node가 없어 검증 스크립트는 실행하지 못함.

출력: fig_map_dong_diff.png(동적(무더위쉼터만) − 정적), fig_map_hidden_gap.png
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd, geopandas as gpd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from matplotlib.patches import Patch

plt.rcParams["font.family"] = "AppleGothic"; plt.rcParams["axes.unicode_minus"] = False
SURF, INK, MUT, GRID, MID = "#fcfcfb", "#0b0b0b", "#52514e", "#d9d8d2", "#f0efec"
d = gpd.read_parquet(SCRATCH / "dong.parquet")
d["geometry"] = d.buffer(4).buffer(-4)  # 표시용: 집계구 사이 틈 메우기(계산에는 쓰지 않음)
gu = d.dissolve("gu5").buffer(6).buffer(-6)
v = d.차이_무더위만 * 100
lim = float(np.nanpercentile(np.abs(v), 98)); print("lim", lim, "NaN", int(v.isna().sum()), "min/max", float(v.min()), float(v.max()))
cm = LinearSegmentedColormap.from_list("div", ["#e34948", MID, "#2a78d6"])
norm = TwoSlopeNorm(vmin=-lim, vcenter=0, vmax=lim)
fig, ax = plt.subplots(figsize=(10.5, 8.4), facecolor=SURF)
d.assign(v=v).plot(ax=ax, column="v", cmap=cm, norm=norm, edgecolor=SURF, linewidth=.3, missing_kwds={"color": "#c3c2b7"}, zorder=2)
gpd.GeoSeries(gu.geometry).boundary.plot(ax=ax, color=MUT, linewidth=.7, zorder=3); ax.axis("off"); ax.set_aspect("equal")
ax.set_title("행정동별 커버율 차이(동적 - 정적): 동적은 65+ 버스 승차·무더위쉼터만, 정적은 65+ 거주", loc="left", fontsize=13, color=INK, pad=10)
sm = plt.cm.ScalarMappable(norm=norm, cmap=cm); cb = fig.colorbar(sm, ax=ax, orientation="horizontal", fraction=.035, pad=.01, aspect=45)
cb.set_label(f"퍼센트포인트 (색 범위 ±{lim:.0f}, 그 밖은 끝색). 빨강 = 동적 커버가 더 낮음", color=MUT, fontsize=9.5); cb.ax.tick_params(colors=MUT, length=0); cb.outline.set_visible(False)
ax.legend(handles=[Patch(color="#c3c2b7", label="정류장 또는 65+ 인구 없음")], loc="lower left", frameon=False, labelcolor=MUT, fontsize=9.5)
fig.savefig(OUT / "fig_map_dong_diff.png", dpi=180, bbox_inches="tight", facecolor=SURF); plt.close(fig)

fig, (ax, side) = plt.subplots(1, 2, figsize=(13, 8.2), facecolor=SURF, gridspec_kw={"width_ratios": [3.1, 1]})
d.plot(ax=ax, color=MID, edgecolor=SURF, linewidth=.3, zorder=1)
d[d.정적_중앙값이상.fillna(False).astype(bool)].plot(ax=ax, color="#cde2fb", edgecolor=SURF, linewidth=.3, zorder=2)
h = d[d.순위.notna()].copy(); h.plot(ax=ax, color="#eb6834", edgecolor=SURF, linewidth=.5, zorder=3)
gpd.GeoSeries(gu.geometry).boundary.plot(ax=ax, color=MUT, linewidth=.6, zorder=4); ax.axis("off"); ax.set_aspect("equal")
for r in h.itertuples():
    p = r.geometry.representative_point(); ax.text(p.x, p.y, str(int(r.순위)), ha="center", va="center", fontsize=8.5, color=INK, zorder=6, bbox=dict(boxstyle="round,pad=.15", fc=SURF, ec="none", alpha=.9))
ax.set_title("숨은 공백 상위 20개 행정동 (정적 커버율은 중앙값 이상, 동적 미커버 65+ 승차 많음)", loc="left", fontsize=13, color=INK, pad=10)
ax.legend(handles=[Patch(color="#eb6834", label="숨은 공백 상위 20"), Patch(color="#cde2fb", label="정적 커버율 ≥ 행정동 중앙값"), Patch(color=MID, label="그 외 행정동")], loc="lower left", frameon=False, labelcolor=MUT, fontsize=9.5)
side.axis("off"); t = pd.read_csv(OUT / "table_hidden_gap_top20.csv", dtype={"dong": str})
side.text(0, 1, "순위  자치구 행정동 (미커버 승차/일)", color=MUT, fontsize=9.5, va="top", transform=side.transAxes)
for i, r in enumerate(t.itertuples()):
    side.text(0, .955 - i * .0455, f"{int(r.순위):>2}  {r.gu} {r.name}{'*' if not r.name_code_match else ''}  ({r.동적미커버_스마트포함:,.0f})", color=INK, fontsize=9.5, va="top", transform=side.transAxes)
side.text(0, .03, "* 2016 경계 기준 이름(코드 불일치)", color=MUT, fontsize=8.5, transform=side.transAxes)
fig.savefig(OUT / "fig_map_hidden_gap.png", dpi=180, bbox_inches="tight", facecolor=SURF); plt.close(fig)
