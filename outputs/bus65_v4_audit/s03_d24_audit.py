"""s03 - D24 2025-08 집중 점검 (DuckDB).

입력(스크래치): d24/*.parquet, d25_board/*.parquet, stop_geo.parquet (s01, s02 산출)
출력(outputs/bus65_v4_audit): d24_*.csv, table_d24_stop_share_202508.csv
사용: python3 -I s03_d24_audit.py <SCRATCH>
"""
import sys
from pathlib import Path
import duckdb, pandas as pd, numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/bus65_v4_audit"
SCR = Path(sys.argv[1])
con = duckdb.connect()
con.execute(f"SET temp_directory='{SCR}/duck_tmp'; SET threads=4; SET memory_limit='4GB'")
con.execute(f"CREATE VIEW raw AS SELECT * FROM read_parquet('{SCR}/d24/*.parquet')")
con.execute("""CREATE VIEW d24 AS SELECT *,
  CASE WHEN length(off_id)=9 THEN 'S' WHEN length(off_id)=4 THEN 'T' ELSE 'X' END ||
  CASE WHEN length(on_id)=9 THEN 'S' WHEN length(on_id)=4 THEN 'T' ELSE 'X' END AS kind,
  (n_gen+n_kid+n_teen+n_eld+n_dis) AS n_types,
  (length(on_id)=9 AND substr(on_id,1,3) BETWEEN '100' AND '124') AS on_seoul
  FROM raw""")
con.execute(f"CREATE VIEW d25 AS SELECT * FROM read_parquet('{SCR}/d25_board/*.parquet')")
con.execute(f"CREATE VIEW geo AS SELECT * FROM read_parquet('{SCR}/stop_geo.parquet')")
KIND = {"SS": "정류장→정류장", "ST": "정류장→역", "TS": "역→정류장", "TT": "역→역"}

# ---------- 1. 품질: 날짜 수, 총계≠유형합, 중복 키
q = con.execute("""SELECT count(*) AS n_rows, count(DISTINCT date) AS n_days, min(date) d0, max(date) d1,
  sum((n>n_types)::INT) rows_n_gt, sum((n<n_types)::INT) rows_n_lt,
  sum(n) n_sum, sum(n_types) types_sum, sum(n-n_types) diff_sum,
  sum(CASE WHEN n>n_types THEN n ELSE 0 END) n_in_gt_rows,
  sum((kind NOT IN ('SS','ST','TS','TT'))::INT) rows_other_kind
  FROM d24""").df()
dup = con.execute("""WITH k AS (SELECT date, off_id, on_id, hh, count(*) c FROM d24 GROUP BY ALL)
  SELECT sum(CASE WHEN c>1 THEN c ELSE 0 END) rows_in_dup_keys, sum((c>1)::INT) dup_keys, count(*) AS n_keys FROM k""").df()
full = con.execute("""WITH k AS (SELECT date, off_id, on_id, hh, n, n_gen, n_kid, n_teen, n_eld, n_dis, t, t_gen, t_kid, t_teen, t_eld, t_dis, count(*) c
  FROM d24 GROUP BY ALL) SELECT sum(c-1) extra_full_dup_rows, sum((c-1)*n) extra_full_dup_n, sum((c-1)*n_eld) extra_full_dup_eld FROM k WHERE c>1""").df()
qual = pd.concat([q, dup, full], axis=1)
qual.to_csv(OUT / "d24_quality_202508.csv", index=False, encoding="utf-8-sig")
# 일별 품질
con.execute("""SELECT date, count(*) AS n_rows, sum((n>n_types)::INT) rows_n_gt, sum(n) n, sum(n_eld) eld FROM d24 GROUP BY date ORDER BY date""").df() \
   .to_csv(OUT / "d24_daily_202508.csv", index=False, encoding="utf-8-sig")
# 총계>유형합 행의 종류별 분포
con.execute("""SELECT kind, sum((n>n_types)::INT) rows_n_gt, sum(n-n_types) diff_sum, sum(n) n,
  round(100*sum(n-n_types)/sum(n),4) diff_pct_of_n FROM d24 GROUP BY kind ORDER BY kind""").df() \
   .to_csv(OUT / "d24_total_vs_types_by_kind_202508.csv", index=False, encoding="utf-8-sig")
# 중복 키 행의 예시(값이 다른 것)
con.execute("""WITH k AS (SELECT date, off_id, on_id, hh FROM d24 WHERE date='20250805' GROUP BY ALL HAVING count(*)>2 LIMIT 3)
  SELECT d.date, d.off_id, d.on_id, d.hh, d.n, d.n_gen, d.n_eld, d.t, d.t_eld FROM d24 d JOIN k USING(date, off_id, on_id, hh) ORDER BY ALL""").df() \
   .to_csv(OUT / "d24_dupkey_examples.csv", index=False, encoding="utf-8-sig")

# ---------- 2. 환승 종류별 유형 비중 (월 합)
k = con.execute("""SELECT kind, sum(n) n, sum(n_types) n_types, sum(n_gen) gen, sum(n_kid) kid, sum(n_teen) teen, sum(n_eld) eld, sum(n_dis) dis
  FROM d24 GROUP BY kind ORDER BY kind""").df()
k["kind_ko"] = k.kind.map(KIND)
for c in ["gen", "kid", "teen", "eld", "dis"]:
    k[f"{c}_pct_of_n"] = 100 * k[c] / k.n
k["eld_pct_of_types"] = 100 * k.eld / k.n_types
k["eld_per_day"] = k.eld / 31
k["n_per_day"] = k.n / 31
k.to_csv(OUT / "d24_by_kind_202508.csv", index=False, encoding="utf-8-sig")
# 서울 승차 정류장만(SS)
ss_seoul = con.execute("SELECT sum(n) n, sum(n_types) nt, sum(n_eld) eld FROM d24 WHERE kind='SS' AND on_seoul").df()

# ---------- 3. 시간대
h = con.execute("""SELECT hh, kind, sum(n) n, sum(n_eld) eld FROM d24 GROUP BY ALL""").df()
hp = h.pivot_table(index="hh", columns="kind", values=["n", "eld"], aggfunc="sum").fillna(0)
hp.columns = [f"{a}_{b}" for a, b in hp.columns]
hp = hp.reset_index()
rep = [546, 97, 76, 130, 3790, 28327, 34765, 43054, 58195, 72835, 79271, 77801, 78077, 76989, 79531, 85883, 80058, 67051, 50972, 36184, 26304, 17478, 9323, 2947]
hp["report_eld_bus_subway_modetrips"] = rep
hp["share_SS_eld"] = 100 * hp.eld_SS / hp.eld_SS.sum()
hp["share_report_eld"] = 100 * hp.report_eld_bus_subway_modetrips / sum(rep)
hp["share_SS_all"] = 100 * hp.n_SS / hp.n_SS.sum()
hp["eld_pct_SS"] = 100 * hp.eld_SS / hp.n_SS
b = con.execute("SELECT hh, sum(v) v FROM d25 WHERE length(on_id)=9 AND substr(on_id,1,3) BETWEEN '100' AND '124' GROUP BY hh").df().set_index("hh").v
hp["d25_bus_board_seoul"] = hp.hh.map(b)
hp["share_d25_bus_board"] = 100 * hp.d25_bus_board_seoul / hp.d25_bus_board_seoul.sum()
hp["SS_pct_of_d25_board"] = 100 * hp.n_SS / hp.d25_bus_board_seoul  # 전체 SS(경기 승차 포함)라 참고값
hp.to_csv(OUT / "d24_hour_202508.csv", index=False, encoding="utf-8-sig")
# 시간대 기준 판별(정류장→역, 역→정류장 환승을 D25 승차 시각별 지하철·버스 승차와 비교)
tb = con.execute("""SELECT hh, sum(CASE WHEN length(on_id)=4 THEN v END) d25_subway_board, sum(CASE WHEN length(on_id)=9 THEN v END) d25_bus_board
  FROM d25 GROUP BY hh""").df().set_index("hh")
tb = tb.join(hp.set_index("hh")[["n_ST", "n_TS", "n_TT", "n_SS"]])
tb["ST_per_subway_board_pct"] = 100 * tb.n_ST / tb.d25_subway_board
tb["ST_per_bus_board_pct"] = 100 * tb.n_ST / tb.d25_bus_board
tb["TS_per_bus_board_pct"] = 100 * tb.n_TS / tb.d25_bus_board
tb["TS_per_subway_board_pct"] = 100 * tb.n_TS / tb.d25_subway_board
tb.reset_index().sort_values("hh").to_csv(OUT / "d24_time_basis_check_202508.csv", index=False, encoding="utf-8-sig")

# ---------- 4. 승차 정류장별 (SS, 서울 승차)
st = con.execute("""SELECT on_id, sum(n) n_ss, sum(n_types) nt_ss, sum(n_gen) gen_ss, sum(n_eld) eld_ss, sum(n_dis) dis_ss,
   sum(CASE WHEN date<='20250815' THEN n ELSE 0 END) n_h1, sum(CASE WHEN date<='20250815' THEN n_eld ELSE 0 END) eld_h1,
   sum(CASE WHEN date> '20250815' THEN n ELSE 0 END) n_h2, sum(CASE WHEN date> '20250815' THEN n_eld ELSE 0 END) eld_h2,
   sum(CASE WHEN dayofweek(strptime(date,'%Y%m%d')) IN (0,6) OR date='20250815' THEN n ELSE 0 END) n_we,
   sum(CASE WHEN dayofweek(strptime(date,'%Y%m%d')) IN (0,6) OR date='20250815' THEN n_eld ELSE 0 END) eld_we,
   sum(CASE WHEN hh BETWEEN '10' AND '16' THEN n ELSE 0 END) n_1016, sum(CASE WHEN hh BETWEEN '10' AND '16' THEN n_eld ELSE 0 END) eld_1016
   FROM d24 WHERE kind='SS' AND on_seoul GROUP BY on_id""").df()
tot = con.execute("""SELECT on_id, sum(n) n_all_kinds, sum(n_eld) eld_all_kinds, sum(CASE WHEN kind='TS' THEN n ELSE 0 END) n_ts,
   sum(CASE WHEN kind='TS' THEN n_eld ELSE 0 END) eld_ts FROM d24 WHERE on_seoul GROUP BY on_id""").df()
brd = con.execute("SELECT on_id, sum(v) d25_board FROM d25 WHERE length(on_id)=9 GROUP BY on_id").df()
geo = con.execute("SELECT node AS on_id, ars, name, stype, src, dong7, dong_nm, gu_by_xy, gu_by_id FROM geo").df()
st = st.merge(tot, on="on_id", how="left").merge(brd, on="on_id", how="left").merge(geo, on="on_id", how="left")
st["eld_share_ss_pct"] = 100 * st.eld_ss / st.n_ss
st["eld_share_ss_types_pct"] = 100 * st.eld_ss / st.nt_ss
st["ss_board_share_of_d25_pct"] = 100 * st.n_ss / st.d25_board
st["eld_share_h1_pct"] = 100 * st.eld_h1 / st.n_h1.replace(0, np.nan)
st["eld_share_h2_pct"] = 100 * st.eld_h2 / st.n_h2.replace(0, np.nan)
st["eld_share_weekend_pct"] = 100 * st.eld_we / st.n_we.replace(0, np.nan)
st["eld_share_wd_pct"] = 100 * (st.eld_ss - st.eld_we) / (st.n_ss - st.n_we).replace(0, np.nan)
st["eld_share_1016_pct"] = 100 * st.eld_1016 / st.n_1016.replace(0, np.nan)
# 이항 근사 95% 구간 폭(참고): 1.96*sqrt(p(1-p)/n)
p = st.eld_ss / st.n_ss
st["ci95_halfwidth_pp"] = 100 * 1.96 * np.sqrt(p * (1 - p) / st.n_ss)
st["stable_eld30"] = st.eld_ss >= 30
st["stable_eld100"] = st.eld_ss >= 100
st = st.sort_values("on_id")
cols = ["on_id", "ars", "name", "stype", "gu_by_id", "gu_by_xy", "dong7", "dong_nm", "src", "n_ss", "nt_ss", "gen_ss", "eld_ss", "dis_ss",
        "eld_share_ss_pct", "eld_share_ss_types_pct", "ci95_halfwidth_pp", "stable_eld30", "stable_eld100",
        "d25_board", "ss_board_share_of_d25_pct", "n_ts", "eld_ts", "n_all_kinds", "eld_all_kinds",
        "n_h1", "eld_h1", "eld_share_h1_pct", "n_h2", "eld_h2", "eld_share_h2_pct",
        "n_we", "eld_we", "eld_share_weekend_pct", "eld_share_wd_pct", "n_1016", "eld_1016", "eld_share_1016_pct"]
st[cols].to_csv(OUT / "table_d24_stop_share_202508.csv", index=False, encoding="utf-8-sig")


# ---------- 5. 분포 요약
def dist(s):
    s = s.dropna()
    return dict(count=len(s), min=s.min(), p10=s.quantile(.1), q1=s.quantile(.25), median=s.median(),
                q3=s.quantile(.75), p90=s.quantile(.9), max=s.max())


rows = []
for lab, m in [("SS 승차 있음(n>0)", st.n_ss > 0), ("월 경로 30건 이상", st.eld_ss >= 30), ("월 경로 100건 이상", st.eld_ss >= 100),
               ("SS 환승 승차 월 3,000건 이상", st.n_ss >= 3000)]:
    rows.append(dict(unit="승차 정류장", subset=lab, metric="경로 비중(%) = 경로/환승_수_합", **dist(st.loc[m, "eld_share_ss_pct"])))
rows.append(dict(unit="승차 정류장", subset="D25 승차 1,000건 이상", metric="SS 환승 승차 / D25 총 승차(%)", **dist(st.loc[st.d25_board >= 1000, "ss_board_share_of_d25_pct"])))
# 자치구, 행정동
for unit, key in [("자치구(ID 앞3자리)", "gu_by_id"), ("행정동(좌표, 2016 경계)", "dong7")]:
    g = st.groupby(key)[["n_ss", "eld_ss", "d25_board", "n_h1", "eld_h1", "n_h2", "eld_h2"]].sum()
    g["share"] = 100 * g.eld_ss / g.n_ss
    g["cov"] = 100 * g.n_ss / g.d25_board
    rows.append(dict(unit=unit, subset="전체", metric="경로 비중(%)", **dist(g.share)))
    rows.append(dict(unit=unit, subset="월 경로 30건 이상", metric="경로 비중(%)", **dist(g.loc[g.eld_ss >= 30, "share"])))
    rows.append(dict(unit=unit, subset="전체", metric="SS 환승 승차 / D25 총 승차(%)", **dist(g["cov"])))
    g.reset_index().to_csv(OUT / f"d24_ss_share_by_{'gu' if key=='gu_by_id' else 'dong'}_202508.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(rows).to_csv(OUT / "d24_distribution_summary_202508.csv", index=False, encoding="utf-8-sig")

# ---------- 6. 같은 달 안 일관성(대체 점검): 전반(1~15일) vs 후반(16~31일), 평일 vs 주말
from scipy.stats import spearmanr
cons = []
for thr in [30, 100]:
    m = (st.eld_h1 >= thr / 2) & (st.eld_h2 >= thr / 2)
    r = spearmanr(st.loc[m, "eld_share_h1_pct"], st.loc[m, "eld_share_h2_pct"])
    cons.append(dict(compare="전반 vs 후반", condition=f"각 반기 경로 {thr//2}건 이상", n_stops=int(m.sum()), spearman=r.statistic,
                     median_abs_diff_pp=(st.loc[m, "eld_share_h1_pct"] - st.loc[m, "eld_share_h2_pct"]).abs().median()))
    m2 = (st.eld_we >= thr / 4) & ((st.eld_ss - st.eld_we) >= thr / 2)
    r2 = spearmanr(st.loc[m2, "eld_share_weekend_pct"], st.loc[m2, "eld_share_wd_pct"])
    cons.append(dict(compare="평일 vs 주말·공휴일", condition=f"평일 경로 {thr//2}·주말 {thr//4}건 이상", n_stops=int(m2.sum()), spearman=r2.statistic,
                     median_abs_diff_pp=(st.loc[m2, "eld_share_weekend_pct"] - st.loc[m2, "eld_share_wd_pct"]).abs().median()))
gg = st.groupby("gu_by_id")[["n_h1", "eld_h1", "n_h2", "eld_h2"]].sum()
r3 = spearmanr(gg.eld_h1 / gg.n_h1, gg.eld_h2 / gg.n_h2)
cons.append(dict(compare="전반 vs 후반", condition="자치구 25개", n_stops=len(gg), spearman=r3.statistic,
                 median_abs_diff_pp=(100 * (gg.eld_h1 / gg.n_h1 - gg.eld_h2 / gg.n_h2)).abs().median()))
pd.DataFrame(cons).to_csv(OUT / "d24_consistency_within_202508.csv", index=False, encoding="utf-8-sig")

# ---------- 7. 서울 전체 요약
d25s = con.execute("SELECT sum(v) FROM d25 WHERE length(on_id)=9 AND substr(on_id,1,3) BETWEEN '100' AND '124'").fetchone()[0]
d25all = con.execute("SELECT sum(v) FROM d25 WHERE length(on_id)=9").fetchone()[0]
summ = dict(ss_seoul_on_n=ss_seoul.n[0], ss_seoul_on_eld=ss_seoul.eld[0], ss_seoul_eld_pct=100 * ss_seoul.eld[0] / ss_seoul.n[0],
            ss_seoul_eld_pct_of_types=100 * ss_seoul.eld[0] / ss_seoul.nt[0],
            d25_bus_board_seoul=d25s, d25_bus_board_all9=d25all,
            ss_seoul_pct_of_d25_seoul=100 * ss_seoul.n[0] / d25s,
            ts_seoul_pct_of_d25_seoul=100 * st.n_ts.sum() / d25s,
            stops_ss=int((st.n_ss > 0).sum()), stops_eld30=int((st.eld_ss >= 30).sum()), stops_eld100=int((st.eld_ss >= 100).sum()),
            d25_board_in_eld30_stops_pct=100 * st.loc[st.eld_ss >= 30, "d25_board"].sum() / d25s)
pd.DataFrame([summ]).T.to_csv(OUT / "d24_seoul_summary_202508.csv", header=["value"], encoding="utf-8-sig")
print(qual.T, k[["kind", "n", "eld", "eld_pct_of_n"]], pd.Series(summ), pd.DataFrame(cons), sep="\n\n")
