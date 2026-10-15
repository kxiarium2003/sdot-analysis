"""RQ1 후속 2단계: 취약계층(0–14세, 65세 이상) 이동 시각화 — 새벽 3시 대비 시각별 인구 변화.

[사전등록 — 결과 보기 전에 고정] (작성 2026-10-12)
  인구        내국인 생활인구(연령 보정 = common.load_livingpop, 24시간 기준), 2024·2025 여름(6–9월) 하루 평균의 두 해 평균.
              외국인 생활인구는 연령 정보가 없어 쓰지 않는다.
  단위        행정동 = 2016 집계구 코드 앞 7자리(424개). 히트맵은 자치구(25개).
  지도 값     변화율(%) = 100 × (h시 인구 − 03시 인구) ÷ 03시 인구, h ∈ {07, 09, 12, 14, 15, 18, 22}.
              유입(+) 빨강, 유출(−) 파랑 (RdBu_r). 색 범위는 모든 연령 지도에 같게: ±R, R = 전 연령 7개 시각 |변화율|의 95백분위.
              R 밖은 끝 색으로 자른다(색 막대 양끝 화살표).
  히트맵 값   h시 인구 ÷ 03시 인구 (자치구 × 24시), 연령별. 색은 1 중심 발산형, 범위는 세 연령 공통(전체 값의 2–98백분위를 1 기준 대칭).
  14시 표     행정동 14시 순증(명) = 14시 인구 − 03시 인구, 연령별 상위·하위 10.
실행: python -m rq1_followup.step2_mobility_maps
출력: rq1_followup/out/step2/
"""
import numpy as np, pandas as pd
import rq1_modules.common as c

OUT = c.ROOT / "rq1_followup/out/step2"; OUT.mkdir(parents=True, exist_ok=True)
HOURS = [7, 9, 12, 14, 15, 18, 22]
AGES = {"all": "전 연령", "a0_14": "0–14세", "a65p": "65세 이상"}
NOTE = "내국인 생활인구 기준(외국인은 연령 정보 없음). 2024·2025 여름(6–9월) 하루 평균. 동 단위 값은 동 안 이동을 놓쳐 이동을 작게 잡음(하한)."


def hourly_pop(scale):
    lp = c.load_livingpop(); lp = lp[lp.season == "summer"].copy()
    for a in AGES: lp[a] = lp[a] / lp.n_days
    lp["u"] = c.unit_of(lp.tract16, scale)
    return lp.groupby(["u", "year", "hour"])[list(AGES)].sum().groupby(["u", "hour"]).mean()     # 두 해 평균


def main():
    import geopandas as gpd, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm, LogNorm
    plt.rcParams["font.family"] = "AppleGothic"; plt.rcParams["axes.unicode_minus"] = False
    names = c.dong_names()
    D = hourly_pop("dong")
    base = D.xs(3, level="hour")
    chg = {a: pd.DataFrame({h: 100 * (D.xs(h, level="hour")[a] - base[a]) / base[a] for h in HOURS}) for a in AGES}
    R = float(np.nanpercentile(np.abs(chg["all"].values), 95))
    B = gpd.read_file(c.P["boundary"]).set_crs(5179, allow_override=True); B["u"] = B.TOT_REG_CD.astype(str).str[:7]
    G = B[["u", "geometry"]].dissolve(by="u").reset_index()
    figs = []
    # (1) 연령별 지도 3행 × 7시각 (한 장) + 연령별 한 장씩
    def panel_row(axs, a):
        for ax, h in zip(axs, HOURS):
            g = G.merge(chg[a][[h]].rename(columns={h: "v"}), left_on="u", right_index=True, how="left")
            g.plot(column="v", ax=ax, cmap="RdBu_r", vmin=-R, vmax=R, edgecolor="#999999", linewidth=0.08, missing_kwds={"color": "#eeeeee"})
            ax.set_title(f"{AGES[a]} · {h:02d}시", fontsize=10); ax.axis("off")
    fig, ax = plt.subplots(3, 7, figsize=(24, 11))
    for r, a in enumerate(AGES): panel_row(ax[r], a)
    sm = plt.cm.ScalarMappable(cmap="RdBu_r", norm=plt.Normalize(-R, R))
    fig.colorbar(sm, ax=ax, shrink=.6, extend="both", label="새벽 3시 대비 변화율(%) · 빨강 유입 / 파랑 유출")
    cap = f"행정동(424) 새벽 3시 대비 시각별 인구 변화율. 세 연령 같은 색 범위 ±{R:.0f}%(전 연령 95백분위). {NOTE}"
    fig.suptitle("연령별 낮 이동: 새벽 3시 대비 인구 변화 (행정동)", fontsize=15); fig.text(.45, .03, cap, ha="center", fontsize=10)
    p = OUT / "map_dong_change_vs03_3ages.png"; fig.savefig(p, dpi=130, bbox_inches="tight"); plt.close(fig); figs.append((p, cap))
    for a in ("a0_14", "a65p"):
        fig, ax = plt.subplots(1, 7, figsize=(26, 5)); panel_row(ax, a)
        fig.colorbar(sm, ax=ax, shrink=.7, extend="both", label="3시 대비 변화율(%)")
        cap = f"{AGES[a]} 행정동 새벽 3시 대비 변화율. 색 범위 ±{R:.0f}% = 전 연령 지도와 같음. {NOTE}"
        fig.text(.45, .02, cap, ha="center", fontsize=10)
        p = OUT / f"map_dong_change_vs03_{a}.png"; fig.savefig(p, dpi=130, bbox_inches="tight"); plt.close(fig); figs.append((p, cap))
    # (2) 자치구 × 시각 히트맵 (h ÷ 03)
    Gu = hourly_pop("gu"); b3 = Gu.xs(3, level="hour")
    H = {a: pd.DataFrame({h: Gu.xs(h, level="hour")[a] / b3[a] for h in range(24)}) for a in AGES}
    allv = np.concatenate([np.log(H[a].values.ravel()) for a in AGES]); L = float(np.nanpercentile(np.abs(allv), 98))
    order = H["all"][14].sort_values(ascending=False).index
    fig, ax = plt.subplots(1, 3, figsize=(24, 9))
    for x, a in zip(ax, AGES):
        M = H[a].loc[order]
        im = x.imshow(M.values, cmap="RdBu_r", norm=LogNorm(np.exp(-L), np.exp(L)), aspect="auto")
        x.set_yticks(range(len(order))); x.set_yticklabels([c.GU.get(u, u) for u in order], fontsize=9)
        x.set_xticks(range(24)); x.set_xticklabels([f"{h:02d}" for h in range(24)], fontsize=8)
        x.set_title(f"{AGES[a]}: h시 인구 ÷ 03시 인구", fontsize=12)
        for i in range(M.shape[0]):
            for j in (9, 14, 18):
                x.text(j, i, f"{M.values[i, j]:.2f}", ha="center", va="center", fontsize=6)
    cb = fig.colorbar(im, ax=ax, shrink=.7, label="h시 ÷ 03시 (로그 눈금, 1 = 변화 없음)")
    tk = [t for t in (0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75) if np.exp(-L) <= t <= np.exp(L)]
    cb.set_ticks(tk); cb.set_ticklabels([f"{t:g}" for t in tk]); cb.ax.minorticks_off()
    cap = f"자치구(25) × 시각 인구비(h시 ÷ 03시), 세 연령 같은 색 범위 {np.exp(-L):.2f}–{np.exp(L):.2f}. 행 순서 = 전 연령 14시 비율. 숫자는 09·14·18시. {NOTE.split(' 동 단위')[0]}"
    fig.text(.45, .03, cap, ha="center", fontsize=10)
    p = OUT / "heatmap_gu_hour_ratio_vs03.png"; fig.savefig(p, dpi=130, bbox_inches="tight"); plt.close(fig); figs.append((p, cap))
    for a in AGES: H[a].to_csv(OUT / f"gu_hour_ratio_vs03_{a}.csv", encoding="utf-8-sig")
    # (3) 14시 순증 상위·하위 10 행정동
    rows = []
    for a in AGES:
        n14 = (D.xs(14, level="hour")[a] - base[a]); t = pd.DataFrame({"dong7": n14.index, "name": [names.get(u, u) for u in n14.index],
                                                                         "pop03": base[a].values, "pop14": D.xs(14, level="hour")[a].reindex(n14.index).values, "net14": n14.values})
        t["pct"] = 100 * t.net14 / t.pop03
        for lab, s in (("상위", t.nlargest(10, "net14")), ("하위", t.nsmallest(10, "net14"))):
            rows.append(s.assign(age=AGES[a], rank_side=lab))
    T = pd.concat(rows); T.to_csv(OUT / "dong_top_bottom10_net14.csv", index=False, encoding="utf-8-sig")
    for a in AGES: chg[a].assign(name=lambda d: [names.get(u, u) for u in d.index]).to_csv(OUT / f"dong_change_vs03_{a}.csv", encoding="utf-8-sig")
    md = ["# 2단계: 취약계층 이동 시각화\n"] + [f"- `{p.relative_to(c.ROOT)}` — {cap}\n" for p, cap in figs]
    md.append(f"\n색 범위 R = {R:.1f}% (사전등록: 전 연령 7개 시각 |변화율| 95백분위)\n\n## 14시 순증 상위·하위 10 행정동 (명, 하루 평균)\n")
    for a in AGES:
        for lab in ("상위", "하위"):
            s = T[(T.age == AGES[a]) & (T.rank_side == lab)]
            md.append(f"\n**{AGES[a]} {lab} 10**: " + ", ".join(f"{r['name']} {r.net14:+,.0f}({r.pct:+.0f}%)" for _, r in s.iterrows()) + "\n")
    md.append("\n" + NOTE + " 집계구 값은 상한에 가까움.\n")
    open(OUT / "step2_summary.md", "w").write("".join(md))
    print(f"R={R:.1f}%  L={L:.3f}"); print("".join(md))


if __name__ == "__main__":
    main()
