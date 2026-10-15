"""H5. ΔT만 보면 충분한가: 절대 기온(배경 기온 + ΔT)으로 다시 보기 (보고서 2장 H5, 2.7절 결과 11, 그림 I)

입력: phase3/absolute_temp_tract.parquet (phase3_absolute_temp.py: 집계구 대표점에 기상청 관측소 기온을 매시간 보간한 배경 기온의
      2024·2025 여름 연도 × 시각 평균 + 같은 조건의 ΔT). 행정동·자치구는 거주 인구 가중 평균.
계산 (단위마다, 2024·2025 여름)
  spatial      단위 간 표준편차(배경·ΔT·절대), 절대 기온 차이 중 배경 기온 몫, 상위 10% − 하위 10%, 최대 − 최소,
               가장 더운 10%(자치구 5곳)의 절대 기온 기준과 ΔT 기준 일치, 가장 더운 단위 5곳
  per_capita   연령·주야별 1인당 평균 기온(거주·활동)과 차이의 배경 몫·ΔT 몫
  rank         절대 기온 노출과 ΔT 노출의 순위 상관(활동 기준끼리), 거주 vs 활동 순위 상관·상위 일치(절대·ΔT)
  threshold    (--threshold) 30·33°C 초과 시간 노출: 연령별 1인당 연간 시간(거주·활동)과 Gap.
               매시간 관측소 기온을 다시 보간해 단위 평균 기온으로 초과를 센다(약 3분). phase3_threshold_exposure.py 와 같은 설정
기대값 (집계구): 배경 몫 낮 46% · 밤 51%; 더운 10% 일치 낮 38% · 밤 20%; 1인당 낮 +0.013 = +0.046 − 0.033°C;
  30°C 15–64세 786 → 800시간 (+1.8%)
실행: .venv/bin/python -m rq1_modules.H5_absolute [--scale=...] [--threshold]
"""
import sys, time
import numpy as np, pandas as pd
from rq1_modules.common import (AGES, GROUPS, AGE_KO, SCALE_KO, TOPK, NIGHT, P, ROOT, load_census, load_livingpop, load_field, unit_of, top_overlap,
                                rho, parse_scales, dong_names, unit_label, save)


def panel():
    AT = pd.read_parquet(P["abs_temp"]).rename(columns={"summer": "year"})
    lp = load_livingpop(); lp = lp[lp.season == "summer"]
    res = load_census()
    X = AT.merge(lp[["tract16", "year", "hour", "n_days"] + GROUPS], on=["tract16", "year", "hour"]).merge(res.add_prefix("res_"), left_on="tract16", right_index=True)
    return X


def units(X, scale):
    X = X.assign(u=unit_of(X.tract16, scale), **{c + "_w": X[c] * X.res_all for c in ("T_bg", "dT_hat")})
    U = X.groupby(["u", "year", "hour"]).agg(**{g: (g, "sum") for g in GROUPS}, **{f"res_{g}": (f"res_{g}", "sum") for g in GROUPS},
                                             bgw=("T_bg_w", "sum"), dtw=("dT_hat_w", "sum"), bgm=("T_bg", "mean"), dtm=("dT_hat", "mean"), nd=("n_days", "max")).reset_index()
    w = U.res_all.where(U.res_all > 0)
    U["bg"] = (U.bgw / w).fillna(U.bgm); U["dT"] = (U.dtw / w).fillna(U.dtm); U["abs"] = U.bg + U.dT
    U["period"] = np.where(U.hour.isin(NIGHT), "night", "day")
    return U


def spatial(U, scale, names=None):
    m = U.groupby(["u", "period"])[["bg", "dT", "abs"]].mean().unstack(); k = TOPK[scale]; out = {}
    for p in ("day", "night"):
        bg, dt, ab = m[("bg", p)], m[("dT", p)], m[("abs", p)]
        n = max(int(round(len(ab) * k)), 1)
        out[p] = dict(sd_bg=bg.std(), sd_dT=dt.std(), sd_abs=ab.std(), share_bg=100 * np.cov(bg, ab)[0, 1] / ab.var(),
                      p90_p10_abs=ab.quantile(.9) - ab.quantile(.1), range_bg=bg.max() - bg.min(), range_dT=dt.max() - dt.min(), range_abs=ab.max() - ab.min(),
                      hottest_overlap=top_overlap(ab, dt, k), hottest_abs=[unit_label(u, scale, names) for u in ab.nlargest(5).index],
                      hottest_dT=[unit_label(u, scale, names) for u in dt.nlargest(5).index])
    return out


def per_capita(U):
    out = {}
    for p, g in U.groupby("period"):
        for a in GROUPS:
            A, R = g[a], g[f"res_{a}"] * g.nd
            d = {c: (g[c] * A).sum() / A.sum() - (g[c] * R).sum() / R.sum() for c in ("bg", "dT", "abs")}
            out[f"{p}_{a}"] = dict(T_res=(g["abs"] * R).sum() / R.sum(), T_act=(g["abs"] * A).sum() / A.sum(), **d)
    return out


def rank(U, scale):
    rows = []
    for _, g in U.groupby(["year", "period"]):
        t = g.assign(EAd=g.dT * g["all"], EAa=g["abs"] * g["all"], ERd=g.dT * g.res_all * g.nd, ERa=g["abs"] * g.res_all * g.nd).groupby("u")[["EAd", "EAa", "ERd", "ERa"]].sum()
        rows.append(dict(abs_vs_dT=rho(t.EAa, t.EAd), rho_dT=rho(t.EAd, t.ERd), rho_abs=rho(t.EAa, t.ERa),
                         top_dT=top_overlap(t.EAd, t.ERd, TOPK[scale]), top_abs=top_overlap(t.EAa, t.ERa, TOPK[scale])))
    R = pd.DataFrame(rows)
    return {c: [R[c].min(), R[c].max()] for c in R.columns}


def threshold(scales, thr=(30, 33)):
    """30·33°C 초과 시간 노출 (연중 모든 날, 국지 기온 = 배경 기온 + ΔT). 집계구는 phase3_threshold_exposure.py 와 같은 값."""
    import geopandas as gpd
    t0 = time.time(); SE = ["winter", "spring", "summer", "autumn"]
    SEASON = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring", 6: "summer", 7: "summer", 8: "summer", 9: "summer", 10: "autumn", 11: "autumn"}
    st = pd.read_csv(ROOT / "merged_data/D2_aws/stations_kma.csv", dtype={"stn_id": str}); st["elev"] = st.elev_m_kma.astype(float)
    aws = pd.read_parquet(ROOT / "merged_data/D2_aws/awsh_2024_2025.parquet", columns=["stn_id", "ta", "measure_time"])
    aws = aws[aws.stn_id.isin(st.stn_id)]; aws["measure_time"] = aws.measure_time.dt.floor("h")
    T = aws.pivot_table(index="measure_time", columns="stn_id", values="ta", aggfunc="mean"); T = T[(T.index >= "2024-01-01") & (T.index < "2026-01-01")]
    stk = st[st.stn_id != "108"].set_index("stn_id"); ids = [c for c in T.columns if c != "108" and c in stk.index]     # 종로 ASOS 108 은 검증용으로 뺀다
    xy = stk.loc[ids, ["x_5179", "y_5179"]].values; el = stk.loc[ids, "elev"].values
    vg = pd.read_csv(ROOT / "phase1/variogram_monthly_2y_merged.csv", dtype={"month": str}).drop_duplicates("month").set_index("month")[["nugget", "psill", "range_km"]]
    gam = lambda h, nug, ps, rg: nug + ps * (1 - np.exp(-h / rg))
    B = gpd.read_file(P["boundary"]).set_crs(5179, allow_override=True); rp = B.geometry.representative_point()
    pts = pd.DataFrame({"tract16": B.TOT_REG_CD.astype(str).values, "x": rp.x.values, "y": rp.y.values})
    pts = pts.merge(pd.read_parquet(ROOT / "phase2/covariates_tract16_buf250.parquet")[["tract16", "elev"]], on="tract16", how="left")
    pts["elev"] = pts.elev.fillna(pts.elev.median())
    Z = load_field(); pts = pts[pts.tract16.isin(Z.tract16.unique())].reset_index(drop=True); NZ = len(pts); tix = {t: i for i, t in enumerate(pts.tract16)}
    DT = np.full((2, 4, 24, NZ), np.nan, dtype=np.float32); Zt = Z[Z.tract16.isin(tix)]
    DT[Zt.year.map({2024: 0, 2025: 1}).values, Zt.season.map({s: i for i, s in enumerate(SE)}).values, Zt.hour.values, Zt.tract16.map(tix).values] = Zt.dT_hat.values
    res = load_census(); wres = res["all"].reindex(pts.tract16).fillna(0).values
    AGG = {}
    for s in scales:
        if s == "tract": continue
        codes, uniq = pd.factorize(unit_of(pts.tract16, s)); W = np.zeros((len(uniq), NZ)); W[codes, np.arange(NZ)] = wres
        z = W.sum(1) == 0; W[z] = (codes[None, :] == np.where(z)[0][:, None]).astype(float); AGG[s] = (W / W.sum(1, keepdims=True), uniq, codes)
    N = {s: {k: np.zeros((2, 4, 24, NZ if s == "tract" else len(AGG[s][1])), dtype=np.int16) for k in thr} for s in scales}
    cand = T.index[T[ids].max(axis=1) >= min(thr) - float(np.nanmax(DT)) - 1.0]
    Dq = np.sqrt((xy[:, 0][:, None] - pts.x.values[None, :]) ** 2 + (xy[:, 1][:, None] - pts.y.values[None, :]) ** 2) / 1000
    Dp = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1)) / 1000
    for i, ts in enumerate(cand):
        v = T.loc[ts, ids].values.astype(float); ok = ~np.isnan(v); n = ok.sum()
        if n < 10: continue
        p = vg.loc[ts.strftime("%Y%m")].values
        Gm = gam(Dp[np.ix_(ok, ok)], *p); np.fill_diagonal(Gm, 0.0); F = np.c_[np.ones(n), el[ok]]
        K = np.zeros((n + 2, n + 2)); K[:n, :n] = Gm; K[:n, n:] = F; K[n:, :n] = F.T
        Bm = np.zeros((n + 2, NZ)); Bm[:n] = gam(Dq[ok], *p); Bm[n] = 1; Bm[n + 1] = pts.elev.values
        try: Lw = np.linalg.solve(K, Bm)
        except np.linalg.LinAlgError: Lw = np.linalg.lstsq(K, Bm, rcond=None)[0]
        yi, si, h = ts.year - 2024, SE.index(SEASON[ts.month]), ts.hour
        tl = v[ok] @ Lw[:n] + np.nan_to_num(DT[yi, si, h])
        for s in scales:
            tu = tl if s == "tract" else AGG[s][0] @ tl
            for k in thr: N[s][k][yi, si, h] += (tu > k)
        if i % 1000 == 0: print(f"  KED {i}/{len(cand)} {time.time() - t0:.0f}s", flush=True)
    lp = load_livingpop(); lp = lp[lp.tract16.isin(tix)]; nd = lp.groupby(["year", "season"]).n_days.max(); tot = res.sum(); out = {}
    for s in scales:
        if s == "tract": uidx = lp.tract16.map(tix).values; nu = NZ; ures = res.reindex(pts.tract16)[AGES].fillna(0).values
        else:
            _, uniq, codes = AGG[s]; um = {c: j for j, c in enumerate(uniq)}; uidx = unit_of(lp.tract16, s).map(um).values; nu = len(uniq)
            ures = res.reindex(pts.tract16)[AGES].fillna(0).groupby(codes).sum().reindex(range(nu)).values
        PA = np.zeros((3, 2, 4, 24, nu)); yi = lp.year.map({2024: 0, 2025: 1}).values; si = lp.season.map({x: i for i, x in enumerate(SE)}).values
        dd = np.array([nd.loc[(y, x)] for y, x in zip(lp.year, lp.season)], dtype=float)
        for j, a in enumerate(AGES): np.add.at(PA[j], (yi, si, lp.hour.values, uidx), lp[a].values / dd)
        r = {}
        for k in thr:
            n = N[s][k].astype(float)
            for j, a in enumerate(AGES):
                EA = (n * PA[j]).sum(); ER = (n * ures[:, j][None, None, None, :]).sum()
                r[f"{k}_{a}"] = dict(residence_h=ER / tot[a] / 2, activity_h=EA / tot[a] / 2, gap_pct=100 * (EA - ER) / ER)
        out[s] = r
    return out


def run(scales=("tract", "dong", "gu"), with_threshold=False, verbose=True):
    X = panel(); names = dong_names() if "dong" in scales else {}; out = {}
    for s in scales:
        U = units(X, s); out[s] = dict(spatial=spatial(U, s, names), per_capita=per_capita(U), rank=rank(U, s))
    if with_threshold:
        for s, v in threshold(scales).items(): out[s]["threshold"] = v
    if verbose:
        for s, o in out.items():
            print(f"\n=== H5 절대 기온 · {SCALE_KO[s]} (2024·2025 여름) ===")
            for p, d in o["spatial"].items():
                print(f"[{p}] 표준편차 배경 {d['sd_bg']:.2f} · ΔT {d['sd_dT']:.2f} · 절대 {d['sd_abs']:.2f}°C | 배경 몫 {d['share_bg']:.0f}% | 상위−하위 10% {d['p90_p10_abs']:.2f}°C | "
                      f"최대−최소 배경 {d['range_bg']:.2f} · ΔT {d['range_dT']:.2f} · 절대 {d['range_abs']:.2f}°C | 가장 더운 곳 일치 {d['hottest_overlap']:.0f}%")
                print(f"      절대 기온 상위: {', '.join(d['hottest_abs'])} | ΔT 상위: {', '.join(d['hottest_dT'])}")
            for key in ("day_all", "day_a15_64", "day_a65p", "night_all"):
                d = o["per_capita"][key]
                print(f"1인당 {key}: {d['T_res']:.2f} → {d['T_act']:.2f}°C, 차이 {d['abs']:+.3f} = 배경 {d['bg']:+.3f} + ΔT {d['dT']:+.3f}")
            r = o["rank"]; print(f"절대 노출 vs ΔT 노출 순위 상관 {r['abs_vs_dT'][0]:.2f}–{r['abs_vs_dT'][1]:.2f} | 상위 일치 ΔT {r['top_dT'][0]:.0f}–{r['top_dT'][1]:.0f}%, 절대 {r['top_abs'][0]:.0f}–{r['top_abs'][1]:.0f}%")
            if "threshold" in o:
                for k, d in o["threshold"].items(): print(f"{k}: 거주 {d['residence_h']:.1f}시간 → 활동 {d['activity_h']:.1f}시간 ({d['gap_pct']:+.2f}%)")
    save(out, "H5_absolute")
    return out


if __name__ == "__main__":
    run(parse_scales(sys.argv), with_threshold="--threshold" in sys.argv)
