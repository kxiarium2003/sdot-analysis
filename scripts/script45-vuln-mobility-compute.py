"""
script45-vuln-mobility-compute.py - 취약계층 유동성 분석 계산 단계 (사전등록 docs/preregistration.md §7)

입력(읽기만): Drive interim/seoul_living_population/agg_dong_summer_2024_2025.parquet (v2)
  `rclone serve http googledrive:sdot-analysis/interim/seoul_living_population --addr 127.0.0.1:8766 --read-only`
  로 열고 DuckDB httpfs 로 필요한 컬럼(연령 14구간의 _lo, _hi)만 읽는다.
  날짜 유형: rq1_followup/out/step5_vuln/date_types.csv (script44)

연령 구간(11) × 하한/상한(2) 마다 다음을 계산해 rq1_followup/out/step5_vuln/stage/ 에 작은 파일로 저장한다.
끝난 (구간, 하한/상한)은 _done 표시로 건너뛰므로 다시 실행하면 이어서 진행한다.
  Mdaily  일별 이동 강도 M_g,t(h) (242일 × 24시)
  mbar    날짜 집합별 M̄(h)와 일별 25·75 백분위
  hstar   날짜 집합별 H* (0.7/0.8/0.9)
  dong    날짜 집합 × 임계값별 동의 N̄, L̄Q (H* 시각 평균), 일별 IQR, 03시 평균 인구, LQ 제외 여부
  win     학기 평일 시간대(오전/점심/오후)와 14시의 동별 N̄
  persist 학기 평일 날짜별 LQ ≥ 1.5 시간 수의 평균, 시각별 비율
실행: python scripts/script45-vuln-mobility-compute.py
"""
import json, time, sys
from pathlib import Path
import duckdb, numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "rq1_followup/out/step5_vuln"; ST = OUT / "stage"; ST.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8766/agg_dong_summer_2024_2025.parquet"
BANDS = ["a0_9", "a10_14", "a15_19", "a20_24", "a25_29", "a30_34", "a35_39", "a40_44", "a45_49", "a50_54", "a55_59", "a60_64", "a65_69", "a70p"]
GROUPS = {"0-14": ["a0_9", "a10_14"], "15-64": BANDS[2:12], "65+": ["a65_69", "a70p"],
          "0-9": ["a0_9"], "10-14": ["a10_14"], "15-19": ["a15_19"], "20-34": ["a20_24", "a25_29", "a30_34"],
          "35-49": ["a35_39", "a40_44", "a45_49"], "50-64": ["a50_54", "a55_59", "a60_64"], "65-69": ["a65_69"], "70+": ["a70p"]}
THR = (0.7, 0.8, 0.9); MAIN_THR = 0.8
WINDOWS = {"오전": [9, 10, 11], "점심": [12, 13], "오후": [14, 15, 16, 17], "14시": [14]}
fname = lambda g: g.replace("+", "p").replace("-", "_")

# 날짜 집합: 유형(6) × 기간(6~9월, 7~8월) × 연도(전체, 2024, 2025)
D = pd.read_csv(OUT / "date_types.csv", dtype={"기준일ID": str})
TYPES = {"SW": D.날짜유형 == "학기 평일", "VW": D.날짜유형 == "방학 평일", "SAT": D.날짜유형 == "토요일", "SUN": D.날짜유형 == "일요일·공휴일",
         "WD": D.날짜유형.isin(["학기 평일", "방학 평일"]), "VWc": D.핵심정의_유형 == "방학 평일"}
SETS = {}
for tk, tm in TYPES.items():
    for pk, pm in {"all": D.월 > 0, "JA": D.칠팔월}.items():
        for yk, ym in {"all": D.연도 > 0, "2024": D.연도 == 2024, "2025": D.연도 == 2025}.items():
            SETS[f"{tk}|{pk}|{yk}"] = sorted(D[tm & pm & ym].기준일ID)


def main():
    con = duckdb.connect(); con.execute("LOAD httpfs; SET http_timeout=600; SET http_retries=10; SET http_retry_wait_ms=3000; SET threads TO 4;")
    todo = [(g, b) for g in GROUPS for b in ("lo", "hi") if not (ST / f"_done__{fname(g)}__{b}").exists()]
    print(f"남은 (구간, 하한/상한): {len(todo)}개", flush=True)
    if not todo: return
    t0 = time.time()
    cols = ", ".join(f"{x}_{b}" for x in BANDS for b in ("lo", "hi"))
    con.execute(f"CREATE TABLE src AS SELECT 행정동코드 AS dong, 기준일ID AS date, CAST(시간대구분 AS INTEGER) AS hour, {cols} FROM read_parquet('{URL}')")
    print(f"입력 적재 {con.execute('SELECT count(*) FROM src').fetchone()[0]:,}행 ({time.time()-t0:.0f}s)", flush=True)
    for g, b in todo:
        t1 = time.time(); one(con, g, b)
        (ST / f"_done__{fname(g)}__{b}").write_text("ok")
        print(f"  {g} {b} 완료 ({time.time()-t1:.0f}s)", flush=True)


def one(con, g, b):
    expr = " + ".join(f"{x}_{b}" for x in GROUPS[g])
    con.execute(f"CREATE OR REPLACE TABLE P AS SELECT dong, date, hour, ({expr}) AS p FROM src")
    con.execute("""CREATE OR REPLACE TABLE L AS
        WITH b3 AS (SELECT dong, date, p AS p3 FROM P WHERE hour = 3),
             s AS (SELECT date, hour, SUM(p) AS sh FROM P GROUP BY ALL),
             s3 AS (SELECT date, SUM(p) AS s3 FROM P WHERE hour = 3 GROUP BY ALL)
        SELECT P.dong, P.date, P.hour, P.p, b3.p3, P.p - b3.p3 AS N,
               CASE WHEN b3.p3 > 0 AND s.sh > 0 THEN (P.p / s.sh) / (b3.p3 / s3.s3) END AS LQ
        FROM P JOIN b3 USING (dong, date) JOIN s USING (date, hour) JOIN s3 USING (date)""")
    Md = con.execute("SELECT date, hour, 0.5 * SUM(abs(p - p3)) / SUM(p3) AS M FROM L GROUP BY ALL ORDER BY date, hour").df()
    Md.to_parquet(ST / f"Mdaily__{fname(g)}__{b}.parquet", index=False)
    mrows, hrows, drows = [], [], []
    for sk, dates in SETS.items():
        if not dates: continue
        m = Md[Md.date.isin(dates)].groupby("hour").M
        mb = pd.DataFrame({"mean": m.mean(), "p25": m.quantile(.25), "p75": m.quantile(.75), "n_days": m.size()}).reindex(range(24))
        for h, r in mb.iterrows(): mrows.append(dict(set=sk, hour=h, **r.to_dict()))
        mx = mb["mean"].max(); tk, pk, yk = sk.split("|")
        thrs = THR if (pk == "all" and yk == "all") else (MAIN_THR,)
        for th in THR:
            hs = [int(h) for h in mb.index[mb["mean"] >= th * mx]]
            hrows.append(dict(set=sk, thr=th, hstar=json.dumps(hs), peak_hour=int(mb["mean"].idxmax()), peak=mx))
            if th not in thrs: continue
            drows.append(dong_level(con, dates, hs).assign(set=sk, thr=th))
    pd.DataFrame(mrows).to_parquet(ST / f"mbar__{fname(g)}__{b}.parquet", index=False)
    pd.DataFrame(hrows).to_parquet(ST / f"hstar__{fname(g)}__{b}.parquet", index=False)
    pd.concat(drows).to_parquet(ST / f"dong__{fname(g)}__{b}.parquet", index=False)
    sw = SETS["SW|all|all"]
    wrows = [dong_level(con, sw, hs).assign(window=wk) for wk, hs in WINDOWS.items()]
    pd.concat(wrows).to_parquet(ST / f"win__{fname(g)}__{b}.parquet", index=False)
    dl = "', '".join(sw)
    p1 = con.execute(f"""SELECT dong, AVG(nh) AS hours_mean FROM (SELECT dong, date, SUM(CASE WHEN LQ >= 1.5 THEN 1 ELSE 0 END) AS nh
                         FROM L WHERE date IN ('{dl}') GROUP BY ALL) GROUP BY dong""").df()
    p2 = con.execute(f"""SELECT dong, hour, AVG(CASE WHEN LQ >= 1.5 THEN 1.0 ELSE 0.0 END) AS frac FROM L WHERE date IN ('{dl}') GROUP BY ALL""").df()
    p1.to_parquet(ST / f"persist__{fname(g)}__{b}.parquet", index=False)
    p2.to_parquet(ST / f"persisthour__{fname(g)}__{b}.parquet", index=False)


def dong_level(con, dates, hours):
    dl = "', '".join(dates); hl = ", ".join(map(str, hours))
    return con.execute(f"""WITH day AS (SELECT dong, date, AVG(N) AS N, AVG(LQ) AS LQ FROM L WHERE date IN ('{dl}') AND hour IN ({hl}) GROUP BY ALL),
                               p3 AS (SELECT dong, AVG(p3) AS P3 FROM L WHERE date IN ('{dl}') AND hour = 3 GROUP BY ALL)
        SELECT day.dong, AVG(N) AS N_mean, quantile_cont(N, 0.25) AS N_p25, quantile_cont(N, 0.75) AS N_p75,
               AVG(LQ) AS LQ_mean, quantile_cont(LQ, 0.25) AS LQ_p25, quantile_cont(LQ, 0.75) AS LQ_p75, ANY_VALUE(p3.P3) AS P3_mean,
               count(*) AS n_days FROM day JOIN p3 USING (dong) GROUP BY day.dong""").df()


if __name__ == "__main__":
    main()
