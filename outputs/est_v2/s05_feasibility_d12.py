"""s05_feasibility_d12.py - B-1: D12 마스킹, 범위 폭, 같은 동 이동, 이동 시간.

입력: s03(분모 범위 정류장), s02(D25 long), s04(D12 칸).
출력: s05_*.csv
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd

GEO = SCRATCH / "geo"; CD = SCRATCH / "d12cells"; BO = SCRATCH / "bus_od"; BO.mkdir(exist_ok=True)
con = duck()
struct, cells, widthsrc = [], [], []
for ym in MONTHS:
    y = ym[:4]
    con.register("stops", pd.read_parquet(GEO / f"stops_{y}.parquet")[["node", "dong7"]])
    lg = f"{SCRATCH}/d25long/{ym}*.parquet"
    con.execute(f"""COPY (SELECT isodow(strptime(date,'%Y%m%d'))-1 wd, hour, a.dong7 o, b.dong7 d, SUM(pax) pax
                   FROM read_parquet('{lg}') l JOIN stops a ON l.board_id=a.node LEFT JOIN stops b ON l.alight_id=b.node
                   WHERE length(board_id)=9 AND a.dong7 IS NOT NULL AND b.dong7 IS NOT NULL GROUP BY 1,2,3,4)
                   TO '{BO}/{ym}.parquet' (FORMAT parquet)""")
    q = con.execute(f"""SELECT SUM(pax) total,
          SUM(CASE WHEN a.dong7 IS NOT NULL THEN pax ELSE 0 END) target_board,
          SUM(CASE WHEN a.dong7 IS NOT NULL AND alight_id IN ('','-') THEN pax ELSE 0 END) alight_missing,
          SUM(CASE WHEN a.dong7 IS NOT NULL AND alight_id NOT IN ('','-') AND b.dong7 IS NULL THEN pax ELSE 0 END) alight_out_scope,
          SUM(CASE WHEN a.dong7 IS NOT NULL AND b.dong7 IS NOT NULL THEN pax ELSE 0 END) both_dong,
          SUM(CASE WHEN a.dong7 IS NOT NULL AND b.dong7 IS NOT NULL AND a.dong7=b.dong7 THEN pax ELSE 0 END) same_dong
          FROM read_parquet('{lg}') l LEFT JOIN stops a ON l.board_id=a.node LEFT JOIN stops b ON l.alight_id=b.node WHERE length(board_id)=9""").df().iloc[0].to_dict()
    q["ym"] = ym; struct.append(q)
    r = con.execute(f"""
       WITH c AS (SELECT * FROM read_parquet('{CD}/dep_{ym}.parquet')), b AS (SELECT * FROM read_parquet('{BO}/{ym}.parquet'))
       SELECT (SELECT count(*) FROM c) n_cells, (SELECT count(*) FROM c WHERE nm>0) n_masked,
              (SELECT count(*) FROM c WHERE t0=0) n_t0zero,
              (SELECT SUM(pax) FROM b) bus_total,
              (SELECT SUM(pax) FROM b JOIN c USING (wd,hour,o,d)) bus_in_d12,
              (SELECT SUM(pax) FROM b JOIN c USING (wd,hour,o,d) WHERE nm>0) bus_masked,
              (SELECT SUM(pax) FROM b JOIN c USING (wd,hour,o,d) WHERE t0>0) bus_t0pos,
              (SELECT SUM(pax*(s65/t0 - s65/(t0+3*nm))) FROM b JOIN c USING (wd,hour,o,d) WHERE t0>0) bus_width_sum""").df().iloc[0].to_dict()
    r["ym"] = ym; cells.append(r); print(ym, r, flush=True)
    widthsrc.append(f"read_parquet('{CD}/dep_{ym}.parquet')")
pd.DataFrame(struct).to_csv(OUT / "s05_bus_od_structure.csv", index=False, encoding="utf-8-sig")
c = pd.DataFrame(cells)
c["칸_마스킹비율"] = c.n_masked / c.n_cells; c["버스가중_마스킹비율"] = c.bus_masked / c.bus_in_d12; c["버스중_D12칸없음"] = 1 - c.bus_in_d12 / c.bus_total
c["버스가중_평균폭_칸"] = c.bus_width_sum / c.bus_t0pos
c.to_csv(OUT / "s05_mask_cells.csv", index=False, encoding="utf-8-sig"); print(c[["ym", "n_cells", "칸_마스킹비율", "버스가중_마스킹비율", "버스중_D12칸없음", "버스가중_평균폭_칸"]].to_string())
s = pd.DataFrame(struct); s["same_dong_ratio"] = s.same_dong / s.both_dong; s["missing_ratio"] = s.alight_missing / s.target_board; s["out_ratio"] = s.alight_out_scope / s.target_board; print(s[["ym", "target_board", "missing_ratio", "out_ratio", "same_dong_ratio"]].to_string())
un = " UNION ALL ".join(f"SELECT wd,hour,o,d,s65,t0,nm,ts FROM {x}" for x in widthsrc)
p = con.execute(f"SELECT o,d, SUM(s65) s65, SUM(t0) t0, SUM(nm) nm, SUM(ts) ts FROM ({un}) GROUP BY 1,2").df()
b = con.execute(f"SELECT o,d, SUM(pax) pax FROM read_parquet('{BO}/*.parquet') GROUP BY 1,2").df()
p = p.merge(b, on=["o", "d"], how="left").fillna({"pax": 0})
pp = p[p.t0 > 0].copy()
pp["U"] = pp.s65 / pp.t0; pp["L"] = pp.s65 / (pp.t0 + 3 * pp.nm); pp["w"] = pp.U - pp.L; pp["tr"] = pp.ts / pp.t0


def wq(x, w, qs):
    i = np.argsort(x); x = x[i]; w = w[i]; c = np.cumsum(w) / w.sum()
    return [float(x[np.searchsorted(c, q)]) for q in qs]


qs = [.1, .25, .5, .75, .9, .99]
tb = [dict(지표="동쌍 범위폭(U-L)", 기준="동쌍 비가중", **dict(zip([f"p{int(q*100)}" for q in qs], pp.w.quantile(qs).round(4).tolist()))),
      dict(지표="동쌍 범위폭(U-L)", 기준="버스OD 가중", **dict(zip([f"p{int(q*100)}" for q in qs], np.round(wq(pp.w.to_numpy(), pp.pax.to_numpy(), qs), 4).tolist()))),
      dict(지표="평균 이동시간(분)", 기준="버스OD 가중 동쌍", **dict(zip([f"p{int(q*100)}" for q in qs], np.round(wq(pp.tr.to_numpy(), pp.pax.to_numpy(), qs), 1).tolist())))]
extra = dict(동쌍수_전체=len(p), 동쌍_t0양수=len(pp), 동쌍_버스OD있음=int((p.pax > 0).sum()), 버스OD가중_중앙폭_상대=(wq(((pp.U - pp.L) / pp.U.replace(0, np.nan)).fillna(0).to_numpy(), pp.pax.to_numpy(), [.5])[0]))
pd.DataFrame(tb).to_csv(OUT / "s05_width_travel_dist.csv", index=False, encoding="utf-8-sig"); print(pd.DataFrame(tb).to_string()); print(extra)
tr = pd.concat([pd.read_parquet(CD / f"travel_{ym}.parquet").assign(ym=ym) for ym in MONTHS]).groupby(["g", "sh"], as_index=False)[["pop", "ts", "pop_over3h", "pop_same_dong", "pop_ss", "n", "n_sup"]].sum()
tr["share"] = tr["pop"] / tr.groupby("g")["pop"].transform("sum")
tr.to_csv(OUT / "s05_travel_shift_classes.csv", index=False, encoding="utf-8-sig"); print(tr.to_string())
tt = tr.groupby("g")[["pop_same_dong", "pop_ss", "n", "n_sup"]].sum(); tt["같은동이동비율_D12"] = tt.pop_same_dong / tt.pop_ss; print(tt.to_string())
pd.Series(extra).to_csv(OUT / "s05_pair_counts.csv", encoding="utf-8-sig")
