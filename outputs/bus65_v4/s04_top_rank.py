"""s04 - 14~16시(14시·15시 구간) 하루 평균 65+ 승차: 상위 30개 정류장과 순위상관.

v4: s03_stop_1416_sum_YYYYMM.csv (정류장별 14·15시 합, 그 달 일수)
v3: Drive interim/bus65_v3/est_YYYYMM.parquet 의 board65_mid (스크래치로 받아 집계 후 삭제)
하루 평균 = 4개월 합 / 4개월 일수 합(그날 승차가 없는 정류장은 0으로 셈).
사용: python3 -I s04_top_rank.py <SCRATCH>
"""
import sys, subprocess
from pathlib import Path
import duckdb, pandas as pd
from scipy.stats import spearmanr

OUT = Path(__file__).resolve().parent
SCR = Path(sys.argv[1])
MS = ["202407", "202408", "202507", "202508"]

# v3 집계
v3p = []
for ym in MS:
    cache = SCR / f"v3_1416_{ym}.csv"
    if not cache.exists():
        dl = SCR / "dl_v3"
        dl.mkdir(exist_ok=True)
        subprocess.run(["rclone", "copy", f"googledrive:sdot-analysis/interim/bus65_v3/est_{ym}.parquet", str(dl)], check=True)
        f = dl / f"est_{ym}.parquet"
        con = duckdb.connect()
        d = con.execute(f"""SELECT node, sum(board65_mid) v3_65, sum(board) v3_board, (SELECT count(DISTINCT date) FROM read_parquet('{f}')) AS days
            FROM read_parquet('{f}') WHERE CAST(hour AS INT) IN (14, 15) GROUP BY node""").df()
        d.to_csv(cache, index=False)
        f.unlink()
    v3p.append(pd.read_csv(cache, dtype={"node": str}).assign(ym=ym))
v3 = pd.concat(v3p)

v4p = [pd.read_csv(OUT / f"s03_stop_1416_sum_{ym}.csv", dtype={"node": str}).assign(ym=ym) for ym in MS]
v4 = pd.concat(v4p)
attr = pd.concat([pd.read_csv(SCR / f"stop_attr_{ym}.csv", dtype={"node": str, "ars": str, "dong7": str}) for ym in MS]).drop_duplicates("node", keep="last")


def daily(df, cols, days):
    return df.groupby("node")[cols].sum() / days


days4 = v4.drop_duplicates("ym").days.sum()
days3 = v3.drop_duplicates("ym").days.sum()
A = daily(v4, ["board", "est65_base", "est65_d24"], days4).join(daily(v3, ["v3_65"], days3), how="left")
A = A.join(attr.set_index("node"), how="left")
A["pct_base"] = 100 * A.est65_base / A.board
A["pct_d24"] = 100 * A.est65_d24 / A.board

top = []
for v, col in [("기본판", "est65_base"), ("D24판", "est65_d24")]:
    t = A.sort_values(col, ascending=False).head(30).reset_index()
    t.insert(0, "rank", range(1, 31))
    t.insert(0, "판", v)
    top.append(t)
T = pd.concat(top)
T = T.rename(columns={"node": "정류장ID", "ars": "ARS", "name": "정류장명", "dong7": "행정동코드", "dong_nm": "행정동", "gu_by_xy": "자치구",
                      "board": "총승차_1416_하루평균", "est65_base": "65+기본판_1416_하루평균", "est65_d24": "65+D24판_1416_하루평균",
                      "r_d24": "D24경로비율", "r_src": "경로비율_출처", "pct_base": "65+비율_기본판%", "pct_d24": "65+비율_D24판%", "v3_65": "v3_65+_1416_하루평균"})
T[["판", "rank", "ARS", "정류장ID", "정류장명", "자치구", "행정동", "행정동코드", "총승차_1416_하루평균", "65+기본판_1416_하루평균", "65+D24판_1416_하루평균",
   "65+비율_기본판%", "65+비율_D24판%", "D24경로비율", "경로비율_출처", "v3_65+_1416_하루평균"]].to_csv(OUT / "table_top30_1416.csv", index=False, encoding="utf-8-sig")

rows = []


def rc(df, a, b, scope):
    m = df[[a, b]].dropna()
    m = m[m[a].gt(0) | m[b].gt(0)]
    r = spearmanr(m[a], m[b])
    rows.append(dict(범위=scope, 비교=f"{a} vs {b}", 정류장수=len(m), spearman=r.statistic))


pairs = [("est65_base", "est65_d24"), ("est65_base", "board"), ("est65_d24", "board"), ("est65_base", "v3_65"), ("est65_d24", "v3_65")]
for a, b in pairs:
    rc(A, a, b, "4개월 합")
for ym in MS:
    x = daily(v4[v4.ym == ym], ["board", "est65_base", "est65_d24"], v4[v4.ym == ym].days.iloc[0]).join(
        daily(v3[v3.ym == ym], ["v3_65"], v3[v3.ym == ym].days.iloc[0]), how="left")
    for a, b in pairs:
        rc(x, a, b, ym)
R = pd.DataFrame(rows)
R["비교"] = R["비교"].replace({"est65_base vs est65_d24": "기본판 vs D24판", "est65_base vs board": "기본판 vs 총 승차", "est65_d24 vs board": "D24판 vs 총 승차",
                            "est65_base vs v3_65": "기본판 vs v3(board65_mid)", "est65_d24 vs v3_65": "D24판 vs v3(board65_mid)"})
ov = len(set(top[0].node) & set(top[1].node))
R = pd.concat([R, pd.DataFrame([dict(범위="4개월 합", 비교="상위 30 겹침(기본판 vs D24판)", 정류장수=ov, spearman=None)])])
R.to_csv(OUT / "table_rank_corr.csv", index=False, encoding="utf-8-sig")
A.reset_index().to_csv(OUT / "s04_stop_1416_daily_4m.csv", index=False, encoding="utf-8-sig")
print(R.to_string()); print("days v4", days4, "v3", days3)
