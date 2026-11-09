"""
s02_mobility_remote.py - D12 서울 생활이동 · D13 수도권 생활이동 요약 (Q3, Q4, Q5 입력)

입력(읽기만, 로컬 저장 없음): Drive interim/seoul_living_migration/ 의 월 parquet
  먼저 다른 터미널에서:
    rclone serve http googledrive:sdot-analysis --addr 127.0.0.1:8770 --read-only
  DuckDB httpfs로 필요한 컬럼만 읽어 메모리에서 집계한다.
출력(outputs/eda_bus65/, 작은 CSV):
  q3_d12_masking_by_age.csv        나이 × 월 : 행 수, 별표 행 비율, 별표 제외 합, 과소추정 상한
  d12_dep_dong_hour.csv            출발동(서울 7자리) × 도착시각 × 연령군(65p/all) × 동내이동여부 : 합, 별표 행 수 (2025-08)
  d12_dep_dong_hour_wd.csv         같은 표에 평일·주말 구분(65p/all, 동내 포함) (2025-08)
  d13_dep_dong_hour.csv.gz            출발동(서울 8→7자리) × 출발시각/도착시각 × 60+·전체 (2025-08 내국인)
  d13_masking.csv                  D13 연령 컬럼별 별표 행 수
  dong_crosswalk_8to7.csv          D5 2025-08에서 뽑은 행안부 8자리 ↔ 통계청 7자리 대응 (424개)
실행: python outputs/eda_bus65/s02_mobility_remote.py   (약 10~20분, 네트워크 속도에 따름)
"""
import time
from pathlib import Path
import duckdb, pandas as pd

ROOT = Path(__file__).resolve().parents[2]; OUT = ROOT / "outputs/eda_bus65"
B = "http://127.0.0.1:8770/interim"
D12 = B + "/seoul_living_migration/seoul_living_migration_admdong/{ym}.parquet"
D13 = B + "/seoul_living_migration/OA-22299_in/{ym}.parquet"
D5 = B + "/seoul_living_population/native/{ym}.parquet"
YM = "202508"; YM_MASK = ["202408", "202508"]
AGE65 = "('65','70','75','80')"

con = duckdb.connect(); con.execute("LOAD httpfs; SET http_timeout=900; SET http_retries=10; SET http_retry_wait_ms=3000;")
q = lambda s: con.execute(s).df()
t0 = time.time(); log = lambda m: print(f"[{time.time()-t0:6.0f}s] {m}", flush=True)

# 0) 동 코드 대응표 (D5)
if not (OUT / "dong_crosswalk_8to7.csv").exists():
    cw = q(f"SELECT DISTINCT 행정동코드 AS dong8, substr(집계구코드,1,7) AS dong7 FROM read_parquet('{D5.format(ym=YM)}')")
    assert cw.dong8.is_unique and cw.dong7.is_unique, "8↔7 대응이 1:1이 아님"
    cw.to_csv(OUT / "dong_crosswalk_8to7.csv", index=False); log(f"대응표 {len(cw)}개")

# 1) D12 나이별 별표 (Q3) — 이미 있으면 건너뜀(재실행 시 이어서)
rows = [] if not (OUT / "q3_d12_masking_by_age.csv").exists() else None
for ym in (YM_MASK if rows is not None else []):
    m = q(f"""SELECT 나이 AS age, count(*) n_rows, sum(CASE WHEN "이동인구(합)_suppressed" THEN 1 ELSE 0 END) n_star,
              sum("이동인구(합)") obs_sum, min("이동인구(합)") obs_min
              FROM read_parquet('{D12.format(ym=ym)}') GROUP BY 1 ORDER BY 1""")
    m["ym"] = ym; rows.append(m); log(f"D12 {ym} 별표 집계")
if rows:
  M = pd.concat(rows)
  M["star_row_share"] = M.n_star / M.n_rows
  M["underest_upper_pct"] = 100 * 3 * M.n_star / (M.obs_sum + 3 * M.n_star)   # 별표=0으로 둘 때 최대 과소추정(별표 상한 3명 가정)
  M.to_csv(OUT / "q3_d12_masking_by_age.csv", index=False, encoding="utf-8-sig")

# 2) D12 출발동 × 도착시각 × 연령군 × 동내이동 (2025-08)
src = f"read_parquet('{D12.format(ym=YM)}')"
if not (OUT / "d12_dep_dong_hour.csv").exists():
  g = q(f"""SELECT "출발 행정동 코드" AS dong7, CAST(도착시간 AS INTEGER) AS hour,
          CASE WHEN 나이 IN {AGE65} THEN '65p' ELSE 'u65' END AS ag,
          ("출발 행정동 코드" = "도착 행정동 코드") AS same, 요일 AS wd,
          sum("이동인구(합)") v, sum(CASE WHEN "이동인구(합)_suppressed" THEN 1 ELSE 0 END) n_star, count(*) n_rows
          FROM {src} WHERE "출발 행정동 코드" LIKE '11%' AND length("출발 행정동 코드") = 7
          GROUP BY ALL""")
  log(f"D12 {YM} 출발동 집계 {len(g):,}행")
  g.groupby(["dong7", "hour", "ag", "same"], as_index=False)[["v", "n_star", "n_rows"]].sum().to_csv(OUT / "d12_dep_dong_hour.csv", index=False)
  g["daytype"] = g.wd.map(lambda w: "주말" if w in ("토", "일") else "평일")
  g.groupby(["dong7", "daytype", "hour", "ag"], as_index=False)[["v", "n_star", "n_rows"]].sum().to_csv(OUT / "d12_dep_dong_hour_wd.csv", index=False)

# 3) D13 내국인 (2025-08): 출발동 × 출발시각·도착시각 × 60+·전체
src = f"read_parquet('{D13.format(ym=YM)}')"
if not (OUT / "d13_masking.csv").exists():
  m13 = q(f"""SELECT sum(CASE WHEN "60plus_cnt_suppressed" THEN 1 ELSE 0 END) s60, sum(CASE WHEN total_cnt_suppressed THEN 1 ELSE 0 END) stot,
           sum(CASE WHEN "0010_cnt_suppressed" OR "2030_cnt_suppressed" OR "4050_cnt_suppressed" THEN 1 ELSE 0 END) soth, count(*) n,
           sum(CASE WHEN "60plus_cnt" = 0 THEN 1 ELSE 0 END) zero60, min(etl_ymd) dmin, max(etl_ymd) dmax, count(DISTINCT etl_ymd) ndays
           FROM {src}""")
  m13.to_csv(OUT / "d13_masking.csv", index=False); log("D13 별표 확인")
if not (OUT / "d13_dep_dong_hour.csv.gz").exists():
  h = q(f"""SELECT o_admdong_cd AS dong8, substr(st_time_cd,1,2)::INT AS st_hour, substr(fns_time_cd,1,2)::INT AS fns_hour,
          (o_admdong_cd = d_admdong_cd) AS same,
          sum("60plus_cnt") v60, sum(total_cnt) vtot, sum("60plus_cnt" * move_time) mt60, sum(total_cnt * move_time) mttot
          FROM {src} WHERE o_admdong_cd LIKE '11%' AND o_admdong_cd NOT LIKE '%000' GROUP BY ALL""")
  h.to_csv(OUT / "d13_dep_dong_hour.csv.gz", index=False); log(f"D13 출발동 집계 {len(h):,}행")
