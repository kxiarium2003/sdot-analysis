"""RQ1 후속 1단계: 절대 기온 기준 더운 지역 (H5 확장). rq1_modules 는 import 만 하고 수정하지 않는다.

[사전등록 — 결과를 보기 전에 고정, 이후 변경 금지] (작성 2026-10-12)
  절대 기온   T_abs = 배경 기온(KED, AWS 66곳, 종로 ASOS 108 제외) + ΔT̂ (phase3/absolute_temp_tract.parquet, H5 와 같은 정의).
              센서 위치에서는 S-DoT 실측과 같고, 센서 없는 집계구는 ΔT̂(OLS 예측).
  기간        2024·2025 여름(6–9월). '2024+2025' 행: 기온은 두 해 평균, 시간·일수·인시는 두 해 합.
  낮/밤       낮 = 07–20시, 밤 = 21–06시 (common.NIGHT).
  33°C 초과   그 시각 단위 기온 > 33.0°C 인 시간 수 (여름 6–9월 시각만). 행정동·자치구 단위 기온 = 집계구 대표점 기온의
              인구총조사 거주 인구 가중 평균 (H5.threshold 와 같은 방식).
  열대야      밤(시작일 d 의 21–23시 + d+1 의 00–06시, 10시간) 최저 기온 > 25.0°C 인 밤. 시작일 6/1–9/30 (122밤/년).
              각 시각은 그 시각 계절의 ΔT̂ 를 쓴다(10/1 00–06시는 가을 ΔT̂). 10시간 중 하나라도 보간 불가면 그 밤은 세지 않는다.
  노출        65+·0–14 × 33°C 초과 인시. 거주 = 인구총조사 연령 인구 × 초과 시간. 활동 = Σ시각 (그 시각 하루 평균 생활인구 × 초과 시간).
              생활인구는 내국인(연령 정보 있음). 연령 보정 = common.load_livingpop (24시간 기준).
  순위 기준   자치구 표: 두 해 여름 낮 평균 절대 기온 순위 vs 낮 평균 ΔT 순위 (밤도 병기).
              행정동 상위 20: (a) 두 해 여름 낮 평균 절대 기온, (b) 65+ × 33°C 초과 인시(거주 기준, 두 해 합).
  홀드아웃    종로 ASOS 108 이 있는 집계구(1101058020001) 대표점의 추정치 vs ASOS 108 실측: 매시각 편향(추정−실측)·RMSE,
              배경 기온만 / 절대 기온 각각. 여름 6–9월.

실행: python -m rq1_followup.step1_absolute [--check-h5]
  --check-h5  rq1_modules.H5_absolute.threshold(33°C, 연중)를 같이 돌려 1인당 시간과 비교 (약 3분 추가)
출력: rq1_followup/out/step1/
"""
import sys, time, json
from pathlib import Path
import numpy as np, pandas as pd
import rq1_modules.common as c
from rq1_modules import H5_absolute as H5

OUT = c.ROOT / "rq1_followup/out/step1"; OUT.mkdir(parents=True, exist_ok=True)
c.P["out"] = OUT / "_module_json"          # 모듈 save() 가 rq1_modules/out 을 덮어쓰지 않게
THR, TN = 33.0, 25.0
DAYH = list(range(7, 21)); NIGHTH = sorted(c.NIGHT)
SE = ["winter", "spring", "summer", "autumn"]
SEASON = {12: 0, 1: 0, 2: 0, 3: 1, 4: 1, 5: 1, 6: 2, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3}
ST108_TRACT = "1101058020001"
SCALES = ("tract", "dong", "gu")
CAVEAT_SCALE = "단서: 동 단위 값은 동 안 이동을 놓쳐 이동 효과를 작게 잡음(하한), 집계구 값은 상한에 가까움."
CAVEAT_ABS = "단서: 센서 ΔT에 설치 환경 차이(1.2–2.0°C)가 섞여 있어 절대 기온은 '그 센서가 잰 기온'이지 그 지역의 실제 기온이 아님."
CAVEAT_AGE = "연령별 값은 내국인 생활인구 기준(외국인 생활인구는 연령 정보 없음). 0–14세 집계구 값은 3명 이하 마스킹 영향으로 참고용."


def ked_loop():
    """여름(6/1 00시 – 10/1 06시) 매시각 KED 를 집계구 대표점에 다시 계산 (H5.threshold 와 같은 설정)."""
    import geopandas as gpd
    t0 = time.time()
    st = pd.read_csv(c.ROOT / "merged_data/D2_aws/stations_kma.csv", dtype={"stn_id": str}); st["elev"] = st.elev_m_kma.astype(float)
    aws = pd.read_parquet(c.ROOT / "merged_data/D2_aws/awsh_2024_2025.parquet", columns=["stn_id", "ta", "measure_time"])
    aws = aws[aws.stn_id.isin(st.stn_id)]; aws["measure_time"] = aws.measure_time.dt.floor("h")
    T = aws.pivot_table(index="measure_time", columns="stn_id", values="ta", aggfunc="mean")
    keep = np.zeros(len(T), bool)
    for y in (2024, 2025): keep |= (T.index >= f"{y}-06-01") & (T.index < f"{y}-10-01 07:00")
    T = T[keep]
    stk = st[st.stn_id != "108"].set_index("stn_id"); ids = [x for x in T.columns if x != "108" and x in stk.index]
    xy = stk.loc[ids, ["x_5179", "y_5179"]].values; el = stk.loc[ids, "elev"].values
    vg = pd.read_csv(c.ROOT / "phase1/variogram_monthly_2y_merged.csv", dtype={"month": str}).drop_duplicates("month").set_index("month")[["nugget", "psill", "range_km"]]
    gam = lambda h, nug, ps, rg: nug + ps * (1 - np.exp(-h / rg))
    B = gpd.read_file(c.P["boundary"]).set_crs(5179, allow_override=True); rp = B.geometry.representative_point()
    pts = pd.DataFrame({"tract16": B.TOT_REG_CD.astype(str).values, "x": rp.x.values, "y": rp.y.values})
    pts = pts.merge(pd.read_parquet(c.ROOT / "phase2/covariates_tract16_buf250.parquet")[["tract16", "elev"]], on="tract16", how="left")
    pts["elev"] = pts.elev.fillna(pts.elev.median())
    Z = c.load_field(); pts = pts[pts.tract16.isin(Z.tract16.unique())].reset_index(drop=True); NZ = len(pts); tix = {t: i for i, t in enumerate(pts.tract16)}
    DT = np.full((2, 4, 24, NZ), np.nan, dtype=np.float32); Zt = Z[Z.tract16.isin(tix)]
    DT[Zt.year.map({2024: 0, 2025: 1}).values, Zt.season.map({s: i for i, s in enumerate(SE)}).values, Zt.hour.values, Zt.tract16.map(tix).values] = Zt.dT_hat.values
    res = c.load_census(); wres = res["all"].reindex(pts.tract16).fillna(0).values
    AGG = {}
    for s in SCALES:
        if s == "tract": AGG[s] = (None, pts.tract16.values, np.arange(NZ)); continue
        codes, uniq = pd.factorize(c.unit_of(pts.tract16, s)); W = np.zeros((len(uniq), NZ)); W[codes, np.arange(NZ)] = wres
        z = W.sum(1) == 0; W[z] = (codes[None, :] == np.where(z)[0][:, None]).astype(float); AGG[s] = (W / W.sum(1, keepdims=True), uniq, codes)
    nu = {s: len(AGG[s][1]) for s in SCALES}
    N33 = {s: np.zeros((2, 24, nu[s]), np.int16) for s in SCALES}
    TNc = {s: np.zeros((2, nu[s]), np.int16) for s in SCALES}
    nmin = {s: np.full(nu[s], np.inf) for s in SCALES}; nh = 0; night_ok = True; n_tn_nights = np.zeros(2, int); n_bad_nights = np.zeros(2, int)
    BGs = np.zeros((2, 24, NZ)); BGn = np.zeros((2, 24))
    i108 = tix[ST108_TRACT]; rec108 = []
    Dq = np.sqrt((xy[:, 0][:, None] - pts.x.values[None, :]) ** 2 + (xy[:, 1][:, None] - pts.y.values[None, :]) ** 2) / 1000
    Dp = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1)) / 1000
    full = pd.date_range("2024-06-01", "2024-10-01 06:00", freq="h").append(pd.date_range("2025-06-01", "2025-10-01 06:00", freq="h"))
    T = T.reindex(full)
    for i, ts in enumerate(T.index):
        v = T.loc[ts, ids].values.astype(float); ok = ~np.isnan(v); n = ok.sum(); yi, h = ts.year - 2024, ts.hour
        summer = 6 <= ts.month <= 9
        if h == 21: nmin = {s: np.full(nu[s], np.inf) for s in SCALES}; nh = 0; night_ok = True
        if n < 10:
            if h in c.NIGHT: night_ok = False
            continue
        p = vg.loc[ts.strftime("%Y%m")].values
        Gm = gam(Dp[np.ix_(ok, ok)], *p); np.fill_diagonal(Gm, 0.0); F = np.c_[np.ones(n), el[ok]]
        K = np.zeros((n + 2, n + 2)); K[:n, :n] = Gm; K[:n, n:] = F; K[n:, :n] = F.T
        Bm = np.zeros((n + 2, NZ)); Bm[:n] = gam(Dq[ok], *p); Bm[n] = 1; Bm[n + 1] = pts.elev.values
        try: Lw = np.linalg.solve(K, Bm)
        except np.linalg.LinAlgError: Lw = np.linalg.lstsq(K, Bm, rcond=None)[0]
        bg = v[ok] @ Lw[:n]; tl = bg + np.nan_to_num(DT[yi, SEASON[ts.month], h])
        if summer:
            BGs[yi, h] += bg; BGn[yi, h] += 1
            rec108.append((ts, bg[i108], tl[i108]))
        for s in SCALES:
            tu = tl if s == "tract" else AGG[s][0] @ tl
            if summer: N33[s][yi, h] += (tu > THR)
            if h in c.NIGHT: nmin[s] = np.minimum(nmin[s], tu)
        if h in c.NIGHT: nh += 1
        if h == 6:
            start = ts - pd.Timedelta(days=1)
            if 6 <= start.month <= 9 and start.year == ts.year:
                if night_ok and nh == 10:
                    for s in SCALES: TNc[s][yi] += (nmin[s] > TN)
                    n_tn_nights[yi] += 1
                else: n_bad_nights[yi] += 1
        if i % 1000 == 0: print(f"  KED {i}/{len(T)} {time.time() - t0:.0f}s", flush=True)
    print(f"  KED 완료 {time.time() - t0:.0f}s | 열대야 판정 가능 밤 {n_tn_nights.tolist()} · 제외 {n_bad_nights.tolist()}")
    BGm = BGs / np.where(BGn > 0, BGn, np.nan)[:, :, None]
    bgchk = pd.DataFrame({"tract16": np.tile(pts.tract16.values, 48), "year": np.repeat([2024, 2025], 24 * NZ),
                          "hour": np.tile(np.repeat(np.arange(24), NZ), 2), "T_bg_rerun": BGm.reshape(-1)})
    return dict(N33=N33, TN=TNc, AGG=AGG, pts=pts, bgchk=bgchk, rec108=pd.DataFrame(rec108, columns=["ts", "bg_est", "abs_est"]),
                nights=dict(ok=n_tn_nights.tolist(), excluded=n_bad_nights.tolist()))


def unit_table(K, scale, names):
    """단위 × 연도 표 (인구·온도·더위·노출)."""
    X = H5.panel(); U = H5.units(X, scale)           # 온도(거주 가중) + 생활인구 합 + 인구총조사
    U["pop_d"] = U["all"] / U.nd
    for a in ("a0_14", "a65p"): U[f"{a}_d"] = U[a] / U.nd
    g = U.groupby(["u", "year"])
    day, nig = U[U.hour.isin(DAYH)].groupby(["u", "year"]), U[U.hour.isin(NIGHTH)].groupby(["u", "year"])
    T = pd.DataFrame({
        "res_all": g.res_all.first(), "res_a65p": g.res_a65p.first(), "res_a0_14": g.res_a0_14.first(), "res_a15_64": g.res_a15_64.first(),
        "act_day_mean": day.pop_d.mean(), "act_14h": U[U.hour == 14].set_index(["u", "year"]).pop_d,
        "act_night_mean": nig.pop_d.mean(),
        **{f"{v}_day_mean": day[v].mean() for v in ("bg", "dT", "abs")},
        **{f"{v}_15h": U[U.hour == 15].set_index(["u", "year"])[v] for v in ("bg", "dT", "abs")},
        **{f"{v}_night_mean": nig[v].mean() for v in ("bg", "dT", "abs")}}).reset_index()
    # 더위·노출 (KED 루프 결과): 단위 순서는 AGG[scale][1]
    uniq = K["AGG"][scale][1]; n33 = K["N33"][scale]; tn = K["TN"][scale]
    lp = c.load_livingpop(); lp = lp[(lp.season == "summer") & lp.tract16.isin(set(K["pts"].tract16))]
    lp = lp.assign(u=c.unit_of(lp.tract16, scale))
    pa = lp.groupby(["u", "year", "hour"])[["a0_14", "a15_64", "a65p", "all"]].sum().div(lp.groupby(["u", "year", "hour"]).n_days.max(), axis=0)
    rows = []
    for yi, y in enumerate((2024, 2025)):
        H = pd.DataFrame(n33[yi].T, index=pd.Index(uniq, name="u"), columns=range(24))     # u × hour 초과 시간
        P_ = {a: pa.xs(y, level="year")[a].unstack("hour").reindex(index=uniq, columns=range(24)).fillna(0) for a in ("a0_14", "a15_64", "a65p", "all")}
        d = pd.DataFrame({"u": uniq, "year": y, "h33": H.sum(1).values, "h33_day": H[DAYH].sum(1).values, "h33_night": H[NIGHTH].sum(1).values,
                          "tropical_nights": tn[yi]})
        for a in ("a0_14", "a15_64", "a65p", "all"): d[f"EA33_{a}"] = (H * P_[a]).sum(1).values
        rows.append(d)
    E = pd.concat(rows)
    T = T.merge(E, on=["u", "year"], how="outer")      # 인구총조사 없는 집계구(130개)의 생활인구도 활동 노출에 넣는다 (H5.threshold 와 같음)
    T[[x for x in T.columns if x.startswith("res_")]] = T[[x for x in T.columns if x.startswith("res_")]].fillna(0)
    for a in ("a0_14", "a15_64", "a65p", "all"): T[f"ER33_{a}"] = T[f"res_{a}"] * T.h33
    # 2024+2025
    temp = [x for x in T.columns if x.startswith(("bg_", "dT_", "abs_", "act_"))]
    cnt = ["h33", "h33_day", "h33_night", "tropical_nights"] + [x for x in T.columns if x.startswith(("EA33", "ER33"))]
    S = T.groupby("u").agg(**{x: (x, "mean") for x in temp}, **{x: (x, "sum") for x in cnt},
                            **{x: (x, "first") for x in ("res_all", "res_a65p", "res_a0_14", "res_a15_64")}).reset_index().assign(year="2024+2025")
    T = pd.concat([T.assign(year=T.year.astype(str)), S], ignore_index=True)
    T.insert(1, "name", [c.unit_label(u, scale, names) for u in T.u])
    if scale != "gu": T.insert(2, "gu", [c.GU.get(u[:5], u[:5]) for u in T.u])
    return T.rename(columns={"u": {"tract": "tract16", "dong": "dong7", "gu": "gu5"}[scale]})


def holdout108(K):
    a = pd.read_parquet(c.ROOT / "merged_data/D3_asos108/asos108_2024_2025.parquet", columns=["measure_time", "TA"])
    a = a[(a.TA > -50)].assign(ts=a.measure_time.dt.floor("h")).groupby("ts").TA.mean()
    R = K["rec108"].assign(obs=lambda d: d.ts.map(a)).dropna()
    out = {}
    for lab, sub in [("all", R), ("day", R[R.ts.dt.hour.isin(DAYH)]), ("night", R[R.ts.dt.hour.isin(NIGHTH)]),
                     ("2024", R[R.ts.dt.year == 2024]), ("2025", R[R.ts.dt.year == 2025])]:
        out[lab] = dict(n=len(sub), **{f"{k}_bias": float((sub[f"{k}_est"] - sub.obs).mean()) for k in ("bg", "abs")},
                        **{f"{k}_rmse": float(np.sqrt(((sub[f"{k}_est"] - sub.obs) ** 2).mean())) for k in ("bg", "abs")})
    # 33°C 초과 시간 수 비교 (그 집계구 추정 vs ASOS 실측)
    out["h33"] = dict(asos=int((R.obs > THR).sum()), abs_est=int((R.abs_est > THR).sum()), bg_est=int((R.bg_est > THR).sum()))
    return out


def draw_map(D, names):
    import geopandas as gpd, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "AppleGothic"; plt.rcParams["axes.unicode_minus"] = False
    B = gpd.read_file(c.P["boundary"]).set_crs(5179, allow_override=True); B["dong7"] = B.TOT_REG_CD.astype(str).str[:7]
    G = B[["dong7", "geometry"]].dissolve(by="dong7").reset_index()
    G = G.merge(D[D.year == "2024+2025"], on="dong7", how="left")
    fig, ax = plt.subplots(1, 3, figsize=(18, 6))
    for a, (col, ttl, cm) in zip(ax, [("abs_day_mean", "낮(07–20시) 평균 절대 기온 (°C)", "YlOrRd"), ("abs_night_mean", "밤(21–06시) 평균 절대 기온 (°C)", "YlOrRd"),
                                      ("h33", "33°C 초과 시간 (두 해 여름 합)", "Reds")]):
        G.plot(column=col, ax=a, cmap=cm, legend=True, edgecolor="white", linewidth=0.15,
               vmin=G[col].quantile(.02), vmax=G[col].quantile(.98), legend_kwds={"shrink": .6})
        a.set_title(ttl, fontsize=12); a.axis("off")
    fig.suptitle("행정동(2016 경계, 424개) 절대 기온 = 배경 기온(KED) + ΔT 예측값 · 2024·2025 여름(6–9월)", fontsize=13)
    fig.text(.5, .02, "색 범위: 2–98 백분위. " + CAVEAT_ABS, ha="center", fontsize=9)
    p = OUT / "map_dong_abs_temp.png"; fig.savefig(p, dpi=150, bbox_inches="tight"); plt.close(fig); return p


def md_table(df, cols, fmt):
    h = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return h + "".join("| " + " | ".join(fmt.get(k, str)(r[k]) for k in cols) + " |\n" for _, r in df.iterrows())


def main():
    t0 = time.time(); names = c.dong_names()
    import pickle
    cache = OUT / "_ked_cache.pkl"          # KED 결과 캐시 (입력이 바뀌면 지우고 다시 실행)
    if cache.exists() and "--fresh" not in sys.argv: K = pickle.load(open(cache, "rb")); print("KED 캐시 사용:", cache)
    else: K = ked_loop(); pickle.dump(K, open(cache, "wb"))
    # 3단계 재사용용: 단위 × 연도 × 시각 33°C 초과 시간 수
    for s in SCALES:
        n = K["N33"][s]; uniq = K["AGG"][s][1]
        pd.DataFrame({"u": np.tile(uniq, 48), "year": np.repeat([2024, 2025], 24 * len(uniq)), "hour": np.tile(np.repeat(np.arange(24), len(uniq)), 2),
                      "h33": n.reshape(-1)}).to_parquet(OUT / f"exceed33_{s}.parquet", index=False)
    # 복원 방식 확인: 다시 계산한 배경 기온 평균 vs phase3 파일
    AT = pd.read_parquet(c.P["abs_temp"]).rename(columns={"summer": "year"})
    chk = AT.merge(K["bgchk"], on=["tract16", "year", "hour"]); dbg = (chk.T_bg_rerun - chk.T_bg).abs()
    rest = dict(n=len(chk), max_abs_diff=float(dbg.max()), mean_abs_diff=float(dbg.mean()))
    print("배경 기온 재계산 vs phase3 파일:", rest)
    tabs = {s: unit_table(K, s, names) for s in SCALES}
    for s, T in tabs.items(): T.to_csv(OUT / f"step1_{s}.csv", index=False, encoding="utf-8-sig")
    ho = holdout108(K); print("ASOS 108 홀드아웃:", json.dumps(ho, ensure_ascii=False))
    # 시 전체 1인당 33°C 초과 시간 (거주·활동) — H5 비교용
    tot = c.load_census().sum(); city = {}
    for s, T in tabs.items():
        t = T[T.year == "2024+2025"]
        city[s] = {a: dict(res_h=float(t[f"ER33_{a}"].sum() / tot[a] / 2), act_h=float(t[f"EA33_{a}"].sum() / tot[a] / 2)) for a in ("a0_14", "a65p")}
    h5 = None
    if "--check-h5" in sys.argv:
        h5 = H5.threshold(SCALES, thr=(33,))
    # 자치구 순위 표
    G = tabs["gu"][tabs["gu"].year == "2024+2025"].copy()
    for p in ("day", "night"):
        G[f"rank_abs_{p}"] = G[f"abs_{p}_mean"].rank(ascending=False).astype(int); G[f"rank_dT_{p}"] = G[f"dT_{p}_mean"].rank(ascending=False).astype(int)
    G = G.sort_values("rank_abs_day"); G.to_csv(OUT / "gu25_rank_abs_vs_dT.csv", index=False, encoding="utf-8-sig")
    rho_gu = {p: c.rho(G[f"abs_{p}_mean"], G[f"dT_{p}_mean"]) for p in ("day", "night")}
    D = tabs["dong"]; D2 = D[D.year == "2024+2025"]
    top_abs = D2.nlargest(20, "abs_day_mean"); top_e65 = D2.nlargest(20, "ER33_a65p")
    top_abs.to_csv(OUT / "dong_top20_abs_day.csv", index=False, encoding="utf-8-sig"); top_e65.to_csv(OUT / "dong_top20_65p_exposure33.csv", index=False, encoding="utf-8-sig")
    mp = draw_map(D, names)
    summ = dict(restoration=rest, holdout108=ho, city_per_capita_33=city, h5_threshold_33=h5, rho_gu_abs_vs_dT=rho_gu, nights=K["nights"],
                n_units={s: int(T[T.year == "2024"].shape[0]) for s, T in tabs.items()}, seconds=time.time() - t0)
    json.dump(summ, open(OUT / "step1_summary.json", "w"), ensure_ascii=False, indent=1, default=float)
    # 요약 markdown
    f1 = lambda x: f"{x:.1f}"; f2 = lambda x: f"{x:.2f}"; f0 = lambda x: f"{x:,.0f}"
    L = ["# 1단계 요약: 절대 기온 기준 더운 지역\n", "행정동 경계: 2016 집계구 코드 앞 7자리 = 424개 (2025 행정동 426개와 다름: 오류2동→오류2동+항동, 강일동→강일동+상일2동 분할).\n",
         f"## 자치구 25개 (두 해 여름 평균, 절대 기온 낮 순위 순) — 순위 상관(절대 vs ΔT) 낮 {rho_gu['day']:.2f} · 밤 {rho_gu['night']:.2f}\n",
         md_table(G, ["name", "rank_abs_day", "rank_dT_day", "abs_day_mean", "dT_day_mean", "rank_abs_night", "rank_dT_night", "abs_night_mean", "h33", "tropical_nights", "ER33_a65p", "EA33_a65p"],
                  {"abs_day_mean": f2, "dT_day_mean": f2, "abs_night_mean": f2, "ER33_a65p": f0, "EA33_a65p": f0}),
         "\n" + CAVEAT_SCALE + "\n" + CAVEAT_ABS + "\n" + CAVEAT_AGE + "\n",
         "\n## 행정동 상위 20 (낮 평균 절대 기온)\n",
         md_table(top_abs, ["name", "abs_day_mean", "bg_day_mean", "dT_day_mean", "abs_15h", "h33", "tropical_nights", "res_a65p", "ER33_a65p"],
                  {"abs_day_mean": f2, "bg_day_mean": f2, "dT_day_mean": f2, "abs_15h": f2, "res_a65p": f0, "ER33_a65p": f0}),
         "\n" + CAVEAT_SCALE + "\n" + CAVEAT_ABS + "\n",
         "\n## 행정동 상위 20 (65+ × 33°C 초과 인시, 거주 기준 두 해 합)\n",
         md_table(top_e65, ["name", "ER33_a65p", "EA33_a65p", "res_a65p", "h33", "abs_day_mean", "dT_day_mean"],
                  {"ER33_a65p": f0, "EA33_a65p": f0, "res_a65p": f0, "abs_day_mean": f2, "dT_day_mean": f2}),
         "\n" + CAVEAT_SCALE + "\n" + CAVEAT_ABS + "\n" + CAVEAT_AGE + "\n"]
    open(OUT / "step1_summary.md", "w").write("".join(L))
    print(f"완료 {time.time() - t0:.0f}s → {OUT}")


if __name__ == "__main__":
    main()
