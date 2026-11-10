"""s04_e1_bus_p1.py - E1 버스 P1: 정류장×날짜×시 65+ 승차·하차 비율(m0, m3). 인자: 월 목록.

비율 규칙(OD 한 행에 비율 하나, 승차·하차 양쪽에 같은 값):
  od    승차·하차 동 둘 다 있고 D12 칸(t0>0)이 있음 → 동쌍×요일×출발시 비율
  fb_o  승차 동은 있으나 하차가 서울 밖·결측이거나 D12 칸 없음 → 출발 동(도착지 전체) 비율
  fb_d  승차가 대상 밖(하차만 대상) → 도착 동(출발지 전체) 비율 [사양에 없어 대칭으로 처리]
  fb_c  위 비율이 모두 없음 → 서울 전체 요일×시 비율
대체일(2024-08-20·21, 2025-07-01·02): 같은 달 같은 요일 정류장×시 합산 비율(대체일 제외).
분모: est_v2 denom. 2024-08-20은 D15×D16으로 다시 만든다(imputed=True).
출력(스크래치): e1/e1_YYYYMM.parquet / 요약: s04_e1_class_share.csv, s04_e1_check_denom.csv, s04_e1_imputed_fallback.csv (월 추가)
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd

E = SCRATCH / "e1"; E.mkdir(exist_ok=True)
CD = SCRATCH / "d12cells"
con = duck()


def append_csv(name, df, ym):
    p = OUT / name
    if p.exists():
        old = pd.read_csv(p, dtype={"ym": str}); old = old[old.ym != ym]; df = pd.concat([old, df], ignore_index=True)
    df.sort_values("ym").to_csv(p, index=False, encoding="utf-8-sig")


def d16_shares(ym, nodes):
    d = pd.read_csv(d16_csv(ym), encoding="cp949", dtype=str, keep_default_na=False)
    d = d[d["표준버스정류장ID"].str.fullmatch(r"\d{9}")]
    out = {}
    for side in ("승차", "하차"):
        cols = {h: [c for c in d.columns if re.fullmatch(rf"0*{h}시{side}총승객수", c)][0] for h in range(24)}
        t = pd.DataFrame({h: pd.to_numeric(d[c], errors="coerce").fillna(0).to_numpy() for h, c in cols.items()})
        t["node"] = d["표준버스정류장ID"].to_numpy()
        t = t.groupby("node").sum(); t = t[t.index.isin(nodes)]
        city = t.sum().to_numpy() / t.sum().sum(); arr = t.to_numpy(float); s = arr.sum(1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            sh = np.where(s > 0, arr / s, np.nan)
        sh = np.where(np.isnan(sh), np.tile(city, (len(arr), 1)), sh)
        out[side] = (pd.DataFrame(sh, index=t.index, columns=range(24)), city)
    return out


def impute_day(ym, dd, st):
    d = pd.read_csv(d15_csv(ym), encoding="cp949", dtype=str, keep_default_na=False, usecols=["사용일자", "표준버스정류장ID", "승차총승객수", "하차총승객수"])
    d = d[d["표준버스정류장ID"].str.fullmatch(r"\d{9}") & (d["사용일자"] == dd)].copy()
    d["board"] = pd.to_numeric(d["승차총승객수"], errors="coerce").fillna(0); d["alight"] = pd.to_numeric(d["하차총승객수"], errors="coerce").fillna(0)
    x = d.groupby("표준버스정류장ID")[["board", "alight"]].sum().reset_index().rename(columns={"표준버스정류장ID": "node"})
    x = x[x.node.isin(set(st.node))]
    sh = d16_shares(ym, set(st.node))
    (ba, cb), (al, ca) = sh["승차"], sh["하차"]
    mb = ba.reindex(x.node).to_numpy(); ma = al.reindex(x.node).to_numpy()
    mb[np.isnan(mb[:, 0])] = cb; ma[np.isnan(ma[:, 0])] = ca
    t = pd.DataFrame({"date": dd, "node": np.repeat(x.node.to_numpy(), 24), "hour": np.tile(np.arange(24), len(x)),
                      "board": (x.board.to_numpy()[:, None] * mb).ravel(), "alight_h1": (x.alight.to_numpy()[:, None] * ma).ravel()})
    t["alight_h2"] = t.alight_h1; t["imputed"] = True
    return t[(t.board > 0) | (t.alight_h1 > 0)]


for ym in sys.argv[1].split(","):
    y = ym[:4]
    st = pd.read_parquet(SCRATCH / f"geo/stops_{y}.parquet")[["node", "ars", "dong7"]]
    con.register("stops", st)
    lg = f"{SCRATCH}/d25long/{ym}*.parquet"
    rated = f"{E}/rated_{ym}.parquet"
    def rate(sfx):
        den = {"m0": "{a}.t0", "m3": "({a}.t0+3*{a}.nm)"}[sfx]
        return "CASE " + " ".join(f"WHEN {cond} THEN {a}.s65/{den.format(a=a)}" for cond, a in [("c.t0>0", "c"), ("in_a AND oa.t0>0", "oa"), ("NOT in_a AND da.t0>0", "da")]) + f" ELSE ca.s65/{den.format(a='ca')} END"
    con.execute(f"""COPY (
      WITH f AS (SELECT l.date, l.hour, l.board_id, l.alight_id, l.pax, isodow(strptime(l.date,'%Y%m%d'))-1 wd, a.dong7 o, b.dong7 d,
                        a.node IS NOT NULL in_a, b.node IS NOT NULL in_b
                 FROM read_parquet('{lg}') l LEFT JOIN stops a ON l.board_id=a.node LEFT JOIN stops b ON l.alight_id=b.node
                 WHERE a.node IS NOT NULL OR b.node IS NOT NULL)
      SELECT f.date, f.hour, f.board_id, f.alight_id, f.pax, f.in_a, f.in_b, f.o, f.d,
             CASE WHEN c.t0>0 THEN 'od' WHEN in_a AND oa.t0>0 THEN 'fb_o' WHEN NOT in_a AND da.t0>0 THEN 'fb_d' ELSE 'fb_c' END cls,
             CASE WHEN alight_id IN ('','-') THEN 'alight_missing' WHEN NOT in_b THEN 'alight_outside' WHEN NOT in_a THEN 'board_outside' WHEN c.t0>0 THEN 'matched' ELSE 'no_d12_cell' END why,
             {rate('m0')} r0, {rate('m3')} r3
      FROM f
      LEFT JOIN read_parquet('{CD}/dep_{ym}.parquet') c ON f.wd=c.wd AND f.hour=c.hour AND f.o=c.o AND f.d=c.d
      LEFT JOIN read_parquet('{CD}/oall_{ym}.parquet') oa ON f.wd=oa.wd AND f.hour=oa.hour AND f.o=oa.o
      LEFT JOIN read_parquet('{CD}/dall_{ym}.parquet') da ON f.wd=da.wd AND f.hour=da.hour AND f.d=da.d
      LEFT JOIN read_parquet('{CD}/city_{ym}.parquet') ca ON f.wd=ca.wd AND f.hour=ca.hour
    ) TO '{rated}' (FORMAT parquet, COMPRESSION zstd)""")
    cls = con.execute(f"""SELECT '{ym}' ym, why, cls, SUM(CASE WHEN in_a THEN pax ELSE 0 END) board_pax, SUM(CASE WHEN in_b THEN pax ELSE 0 END) alight_pax,
                          SUM(CASE WHEN o=d THEN pax ELSE 0 END) same_dong_pax, SUM(CASE WHEN r0 IS NULL THEN pax ELSE 0 END) null_rate_pax FROM read_parquet('{rated}') GROUP BY 2,3""").df()
    cls["board_share"] = cls.board_pax / cls.board_pax.sum(); cls["alight_share"] = cls.alight_pax / cls.alight_pax.sum()
    append_csv("s04_e1_class_share.csv", cls, ym); print(cls.round(4).to_string(), flush=True)
    b = con.execute(f"SELECT date, hour, board_id node, SUM(pax) bp, SUM(pax*r0) b0, SUM(pax*r3) b3 FROM read_parquet('{rated}') WHERE in_a GROUP BY 1,2,3").df()
    a = con.execute(f"SELECT date, hour, alight_id node, SUM(pax) ap, SUM(pax*r0) a0, SUM(pax*r3) a3 FROM read_parquet('{rated}') WHERE in_b GROUP BY 1,2,3").df()
    os.remove(rated)
    d = pd.read_parquet(SCRATCH / f"raw/denom/denom_{ym}.parquet").drop(columns=["ars"])
    d["hour"] = d.hour.astype(int)
    days = IMPUTED_DAYS.get(ym, [])
    extra = [x for x in days if not d[(d.date == x)].imputed.any()]   # 2024-08-20만 해당
    meta = d[["date", "is_holiday", "weekday", "ym"]].drop_duplicates("date")
    for dd in extra:
        before = d[d.date == dd][["board", "alight_h1"]].sum()
        t = impute_day(ym, dd, st)
        d = pd.concat([d[d.date != dd], t.merge(meta[meta.date == dd], on="date")], ignore_index=True)
        print("replaced", dd, "D25 board/alight", before.to_dict(), "D15xD16", t[["board", "alight_h1"]].sum().to_dict(), flush=True)
    d = d.merge(b, on=["date", "hour", "node"], how="left").merge(a, on=["date", "hour", "node"], how="left")
    norm = ~d.imputed
    chk = dict(ym=ym, denom_board=float(d[norm].board.sum()), bp=float(d[norm].bp.sum()), denom_alight=float(d[norm].alight_h1.sum()), ap=float(d[norm].ap.sum()),
               cell_board_max_absdiff=float((d[norm].board - d[norm].bp.fillna(0)).abs().max()), cell_alight_max_absdiff=float((d[norm].alight_h1 - d[norm].ap.fillna(0)).abs().max()),
               null_b_where_board=int(d[norm & (d.board > 0)].bp.isna().sum()), null_a_where_alight=int(d[norm & (d.alight_h1 > 0)].ap.isna().sum()))
    append_csv("s04_e1_check_denom.csv", pd.DataFrame([chk]), ym); print(chk, flush=True)
    # 대체일 비율
    n = d[norm].fillna({"bp": 0, "ap": 0, "b0": 0, "b3": 0, "a0": 0, "a3": 0})
    k = ["weekday", "node", "hour"]
    pool = n.groupby(k)[["bp", "b0", "b3", "ap", "a0", "a3"]].sum().reset_index()
    p2 = n.groupby(["node", "hour"])[["bp", "b0", "b3", "ap", "a0", "a3"]].sum().reset_index()
    p3 = n.groupby(["weekday", "hour"])[["bp", "b0", "b3", "ap", "a0", "a3"]].sum().reset_index()
    def ratio(t, suffix=""):
        with np.errstate(invalid="ignore", divide="ignore"):
            return pd.DataFrame({f"rb0{suffix}": t.b0 / t.bp, f"rb3{suffix}": t.b3 / t.bp, f"ra0{suffix}": t.a0 / t.ap, f"ra3{suffix}": t.a3 / t.ap})
    pool = pd.concat([pool[k], ratio(pool)], axis=1); p2 = pd.concat([p2[["node", "hour"]], ratio(p2, "_n")], axis=1); p3 = pd.concat([p3[["weekday", "hour"]], ratio(p3, "_c")], axis=1)
    d["hour"] = d.hour.astype(int); d["weekday"] = d.weekday.astype(int)
    for c in ("bp", "ap"):
        d[c] = d[c].replace(0, np.nan)
    d["rb0"] = d.b0 / d.bp; d["rb3"] = d.b3 / d.bp; d["ra0"] = d.a0 / d.ap; d["ra3"] = d.a3 / d.ap
    imp = d[d.imputed].drop(columns=["rb0", "rb3", "ra0", "ra3"]).merge(pool, on=k, how="left").merge(p2, on=["node", "hour"], how="left").merge(p3, on=["weekday", "hour"], how="left")
    fb = []
    for side, den in (("b", "board"), ("a", "alight_h1")):
        lv1 = imp[f"r{side}3"].notna(); lv2 = ~lv1 & imp[f"r{side}3_n"].notna(); lv3 = ~lv1 & ~lv2
        w = imp[den]
        fb.append(dict(ym=ym, side=den, cells=len(imp), same_weekday=float(w[lv1].sum() / w.sum()), node_hour=float(w[lv2].sum() / w.sum()), city_wd_hour=float(w[lv3].sum() / w.sum())))
        for m in ("0", "3"):
            imp[f"r{side}{m}"] = imp[f"r{side}{m}"].fillna(imp[f"r{side}{m}_n"]).fillna(imp[f"r{side}{m}_c"])
    append_csv("s04_e1_imputed_fallback.csv", pd.DataFrame(fb), ym); print(fb, flush=True)
    cols = ["date", "hour", "node", "board", "alight_h1", "imputed", "is_holiday", "weekday", "ym", "rb0", "rb3", "ra0", "ra3"]
    res = pd.concat([d[~d.imputed][cols], imp[cols]], ignore_index=True).merge(st[["node", "ars"]], on="node", how="left")
    res.to_parquet(E / f"e1_{ym}.parquet", index=False, compression="zstd")
    print(ym, "rows", len(res), res[["board", "alight_h1"]].sum().to_dict(), "imputed days", sorted(res[res.imputed].date.unique()), "null ratio where board>0", int(res[(res.board > 0)].rb3.isna().sum()), flush=True)
    print(res[res.board > 0][["rb0", "rb3"]].describe().round(4).T.to_string(), flush=True)
