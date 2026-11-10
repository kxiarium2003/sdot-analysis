"""s03_denominator.py - Step 1 분모 구축과 D15·D16 검증.

대상: D21 판본(2024-09-03 / 2025-08-01) ARS 01~25, 가상정류장 제외.
- 승차: D25 9자리 승차 ID(대상 정류장) × 날짜 × D25 시(=승차 시각 기준 [추정])
- 하차 H1: D25 9자리 하차 ID(대상 정류장) × 날짜 × D25 시 그대로
- 하차 H2: 정류장×날짜 하차 합 × D16 같은 달 그 정류장 하차 시간 분포
- D25 결측일: D15 승차·하차 × D16 정류장 시간 분포 (imputed=True, H1=H2)
출력(스크래치): denom/denom_YYYYMM.parquet (이후 Drive 업로드)
출력(요약): s03_*.csv, fig_s03_*.png
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd

D = SCRATCH / "denom"; D.mkdir(exist_ok=True)
GEO = SCRATCH / "geo"
con = duck()


def load_d16(ym):
    d = pd.read_csv(d16_csv(ym), encoding="cp949", dtype=str, keep_default_na=False)
    d = d[d["표준버스정류장ID"].str.fullmatch(r"\d{9}")]
    out = {}
    for side in ("승차", "하차"):
        cols = {h: [c for c in d.columns if re.fullmatch(rf"0*{h}시{side}총승객수", c)][0] for h in range(24)}
        t = pd.DataFrame({h: pd.to_numeric(d[c], errors="coerce").fillna(0).to_numpy() for h, c in cols.items()})
        t["node"] = d["표준버스정류장ID"].to_numpy()
        out[side] = t.groupby("node").sum()
    return out


def load_d15(ym):
    d = pd.read_csv(d15_csv(ym), encoding="cp949", dtype=str, keep_default_na=False, usecols=["사용일자", "표준버스정류장ID", "승차총승객수", "하차총승객수"])
    d = d[d["표준버스정류장ID"].str.fullmatch(r"\d{9}")].copy()
    d["board"] = pd.to_numeric(d["승차총승객수"], errors="coerce").fillna(0)
    d["alight"] = pd.to_numeric(d["하차총승객수"], errors="coerce").fillna(0)
    return d.groupby(["사용일자", "표준버스정류장ID"])[["board", "alight"]].sum().reset_index().rename(columns={"사용일자": "date", "표준버스정류장ID": "node"})


allmask, val_day, val_stopday, val_month_hour, hour_prof, extra = [], [], [], [], [], []
for ym in MONTHS:
    y = ym[:4]
    st = pd.read_parquet(GEO / f"stops_{y}.parquet")[["node", "ars", "dong7", "gu5"]]
    nodes = set(st.node)
    con.register("stops", st)
    lg = SCRATCH / f"d25long/{ym}*.parquet"
    # 하차 결측 구조
    q = con.execute(f"""
      SELECT CASE WHEN length(board_id)=9 THEN 'bus' ELSE 'subway' END kind,
             CASE WHEN alight_id='' THEN 'blank' WHEN alight_id='-' THEN 'dash' WHEN length(alight_id)=9 THEN 'bus9' WHEN length(alight_id)=4 THEN 'sub4' ELSE 'other' END al,
             SUM(pax) pax, COUNT(*) n
      FROM read_parquet('{lg}') GROUP BY 1,2""").df()
    q.insert(0, "ym", ym); extra.append(q)
    # 승차
    b = con.execute(f"""SELECT date, hour, board_id node, SUM(pax) board FROM read_parquet('{lg}') WHERE length(board_id)=9 AND board_id IN (SELECT node FROM stops) GROUP BY 1,2,3""").df()
    h1 = con.execute(f"""SELECT date, hour, alight_id node, SUM(pax) alight_h1 FROM read_parquet('{lg}') WHERE length(board_id)=9 AND length(alight_id)=9 AND alight_id IN (SELECT node FROM stops) GROUP BY 1,2,3""").df()
    d = b.merge(h1, on=["date", "hour", "node"], how="outer").fillna({"board": 0, "alight_h1": 0})
    d16 = load_d16(ym)
    d15 = load_d15(ym)
    d15u = d15[d15.node.isin(nodes)].copy()
    # H2 share
    al = d16["하차"]; ba = d16["승차"]
    al = al[al.index.isin(nodes)]; ba = ba[ba.index.isin(nodes)]
    city_al = al.sum().to_numpy() / al.sum().sum(); city_ba = ba.sum().to_numpy() / ba.sum().sum()
    def shares(tbl, city):
        arr = tbl.to_numpy(dtype=float)
        s = arr.sum(1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            sh = np.where(s > 0, arr / s, np.nan)
        sh = np.where(np.isnan(sh), np.tile(city, (len(arr), 1)), sh)
        return pd.DataFrame(sh, index=tbl.index, columns=range(24))
    sh_al = shares(al, city_al); sh_ba = shares(ba, city_ba)
    day_al = d.groupby(["date", "node"]).alight_h1.sum().rename("day_al").reset_index()
    # H2 long: 정류장×날짜 하차 합 × 시간 분포
    m_sh = sh_al.reindex(day_al.node).to_numpy()
    fallback = np.isnan(m_sh[:, 0])
    m_sh[fallback] = city_al
    long_al = pd.DataFrame({"date": np.repeat(day_al.date.to_numpy(), 24), "node": np.repeat(day_al.node.to_numpy(), 24),
                            "hour": np.tile(np.arange(24), len(day_al)), "alight_h2": (day_al.day_al.to_numpy()[:, None] * m_sh).ravel()})
    long_al = long_al[long_al.alight_h2 > 0]
    d = d.merge(long_al, on=["date", "hour", "node"], how="outer").fillna({"board": 0, "alight_h1": 0, "alight_h2": 0})
    d["imputed"] = False
    # 결측일 대체
    miss = [x for x in D25_MISSING if x[:6] == ym]
    imp = []
    for dd in miss:
        x = d15u[d15u.date == dd]
        m_ba = sh_ba.reindex(x.node).to_numpy(); m_al = sh_al.reindex(x.node).to_numpy()
        m_ba[np.isnan(m_ba[:, 0])] = city_ba; m_al[np.isnan(m_al[:, 0])] = city_al
        t = pd.DataFrame({"date": dd, "node": np.repeat(x.node.to_numpy(), 24), "hour": np.tile(np.arange(24), len(x)),
                          "board": (x.board.to_numpy()[:, None] * m_ba).ravel(), "alight_h1": (x.alight.to_numpy()[:, None] * m_al).ravel()})
        t["alight_h2"] = t.alight_h1; t["imputed"] = True
        imp.append(t[(t.board > 0) | (t.alight_h1 > 0)])
    if imp:
        d = pd.concat([d] + imp, ignore_index=True)
    d = d.merge(st[["node", "ars"]], on="node", how="left")
    dt = pd.to_datetime(d.date)
    d["ym"] = ym; d["weekday"] = dt.dt.dayofweek.astype("int8"); d["is_holiday"] = d.date.isin(HOLIDAYS)
    d = d[["date", "hour", "node", "ars", "board", "alight_h1", "alight_h2", "imputed", "is_holiday", "weekday", "ym"]]
    d.to_parquet(D / f"denom_{ym}.parquet", compression="zstd", index=False)
    print(ym, "rows", len(d), "dates", d.date.nunique(), "board", d.board.sum(), "al1", d.alight_h1.sum(), "fallback_share_stops", int(fallback.sum()), flush=True)
    # ---- 검증 ----
    nodup = d[~d.imputed]
    ds = nodup.groupby(["date", "node"])[["board", "alight_h1"]].sum().reset_index()
    v = ds.merge(d15u, on=["date", "node"], how="outer", suffixes=("_d25", "_d15")).fillna(0)
    v["ym"] = ym
    val_stopday.append(v[v.date.isin(ds.date)])
    # 서울 전체 일별
    day = d.groupby(["date", "imputed"])[["board", "alight_h1"]].sum().reset_index()
    day = day.merge(d15u.groupby("date")[["board", "alight"]].sum().rename(columns={"board": "d15_board", "alight": "d15_alight"}).reset_index(), on="date", how="left")
    val_day.append(day)
    # 월×시 vs D16
    t = nodup.groupby("hour")[["board", "alight_h1", "alight_h2"]].sum()
    n_days = nodup.date.nunique()
    all_days = d.date.nunique()
    t16b = ba.sum().reindex(range(24)); t16a = al.sum().reindex(range(24))
    r = pd.DataFrame({"ym": ym, "hour": range(24), "d25_board": t.board.values, "d16_board": t16b.values, "h1": t.alight_h1.values, "h2": t.alight_h2.values, "d16_alight": t16a.values, "n_days": n_days, "all_days": all_days})
    val_month_hour.append(r)
    # 정류장×월×시 하차 일치(정규화 후 분포 차이)
    stop_h = nodup.groupby(["node", "hour"])[["alight_h1", "alight_h2", "board"]].sum().reset_index()
    a_s = stop_h.pivot(index="node", columns="hour", values="alight_h1").reindex(columns=range(24)).fillna(0)
    b_s = stop_h.pivot(index="node", columns="hour", values="alight_h2").reindex(columns=range(24)).fillna(0)
    common = a_s.index.intersection(al.index)
    a_s = a_s.loc[common]; b_s = b_s.loc[common]; dd = al.loc[common]
    good = dd.to_numpy().sum(1) >= 500
    def shape_mae(x):
        p = x.to_numpy()[good]; q0 = dd.to_numpy()[good]
        ps = p / p.sum(1, keepdims=True); qs = q0 / q0.sum(1, keepdims=True)
        mh_p = (ps * np.arange(24)).sum(1); mh_q = (qs * np.arange(24)).sum(1)
        return np.nanmedian(np.abs(ps - qs).sum(1) / 2), np.nanmedian(mh_p - mh_q)
    for nm, x in (("H1", a_s), ("H2", b_s)):
        tvd, mh = shape_mae(x)
        hour_prof.append(dict(ym=ym, 방식=nm, 정류장수=int(good.sum()), 분포차_TVD_중앙값=tvd, 평균시각차_시간_중앙값=mh))

e = pd.concat(extra); e.to_csv(OUT / "s03_d25_alight_structure.csv", index=False, encoding="utf-8-sig"); print(e.to_string())
pd.DataFrame(hour_prof).to_csv(OUT / "s03_alight_h1_h2_stop_shape.csv", index=False, encoding="utf-8-sig"); print(pd.DataFrame(hour_prof).to_string())
vd = pd.concat(val_day); vd.to_csv(OUT / "s03_daily_seoul_totals.csv", index=False, encoding="utf-8-sig")
mh = pd.concat(val_month_hour); mh.to_csv(OUT / "s03_month_hour_vs_d16.csv", index=False, encoding="utf-8-sig")
vs = pd.concat(val_stopday, ignore_index=True)
qs = [.01, .05, .25, .5, .75, .95, .99]
rows = []
for side, a, b in (("승차", "board_d25", "board_d15"), ("하차", "alight_h1", "alight")):
    for lab, x in (("전체(>=10명)", vs[vs[b] >= 10]), ("D15>=100명", vs[vs[b] >= 100])):
        r = (x[a] / x[b])
        rows.append(dict(대상=side, 범위=lab, 셀수=len(x), **{f"p{int(q*100)}": r.quantile(q) for q in qs}, 평균=r.mean(), 절대오차10퍼이내=(np.abs(r - 1) <= .1).mean()))
pd.DataFrame(rows).to_csv(OUT / "s03_stopday_ratio_vs_d15.csv", index=False, encoding="utf-8-sig"); print(pd.DataFrame(rows).round(4).to_string())
tot = []
for ym, x in vs.groupby("ym"):
    tot.append(dict(ym=ym, D25승차=x.board_d25.sum(), D15승차=x.board_d15.sum(), 승차차이pct=(x.board_d25.sum() / x.board_d15.sum() - 1) * 100, D25하차=x.alight_h1.sum(), D15하차=x.alight.sum(), 하차차이pct=(x.alight_h1.sum() / x.alight.sum() - 1) * 100))
pd.DataFrame(tot).to_csv(OUT / "s03_month_seoul_vs_d15.csv", index=False, encoding="utf-8-sig"); print(pd.DataFrame(tot).round(3).to_string())
