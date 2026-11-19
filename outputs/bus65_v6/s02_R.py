"""s02 - 유형별 하루 버스 승차 R(t, 월, daytype) = (a) 전체 행 목적통행 x k(t, 월).

k(t, 월) = sum_패턴 (b) 비율/100 x 버스 승차 횟수 (s01_report_pattern.csv 의 bus_boards).
  버스(단독) 1, 버스 2회 2, 버스1회·지하철1회 1, 버스 3·4·5회 3·4·5,
  3·4·5회 버스+지하철 1.5·2·2.5 [가정: 구성 미상이라 절반], 지하철만 0.
daytype: 월평균 / 평일(보고서 주중평균) / 주말(보고서 주말평균). k 는 월 하나(보고서 통행행태 표가 월 전체만 있음).
기타 유형은 추정에서 빼되 규모를 같이 적는다(in_estimate=False).
출력: s02_R.csv (ym, daytype, type, trips, k, R, in_estimate), s02_R_diag.csv (sum R / 보고서 버스 승차)
사용: python3 -I s02_R.py
"""
from pathlib import Path
import pandas as pd

OUT = Path(__file__).resolve().parent
A = pd.read_csv(OUT / "s01_report_types.csv", dtype={"ym": str})
B = pd.read_csv(OUT / "s01_report_pattern.csv", dtype={"ym": str})
D = pd.read_csv(OUT / "s01_report_bus_total.csv", dtype={"ym": str})
TYPES = ["일반", "어린이", "청소년", "경로", "장애인"]
DT = {"월평균": "월평균", "주중평균": "평일", "주말평균": "주말"}

k = (B.assign(w=B.pct / 100 * B.bus_boards).groupby(["ym", "type"]).w.sum().rename("k"))
a = A[(A.row == "전체") & A.type.isin(TYPES + ["기타"])].copy()
a["daytype"] = a.period.map(DT)
R = a.join(k, on=["ym", "type"])
R["R"] = R.trips * R.k
R["in_estimate"] = R.type.isin(TYPES)
R = R[["ym", "daytype", "type", "trips", "k", "R", "in_estimate"]]
R.to_csv(OUT / "s02_R.csv", index=False, encoding="utf-8-sig")

dmap = {"전체": "월평균", "주중": "평일", "주말": "주말"}
D["daytype"] = D.daytype.map(dmap)
g = R.groupby(["ym", "daytype", "in_estimate"]).R.sum().unstack()
diag = pd.DataFrame({"R_5types": g[True], "R_기타": g[False]}).reset_index()
diag = diag.merge(D[["ym", "daytype", "bus_total", "bus_total_bytype", "bus_ref", "bus_ref_src"]], on=["ym", "daytype"])
diag["ratio_5types_pct"] = 100 * diag.R_5types / diag.bus_ref
diag["ratio_with_기타_pct"] = 100 * (diag.R_5types + diag.R_기타) / diag.bus_ref
diag.to_csv(OUT / "s02_R_diag.csv", index=False, encoding="utf-8-sig")

pd.set_option("display.width", 200)
print(R[(R.ym == "202508") & (R.daytype == "월평균")].to_string(index=False))
print(diag.to_string(index=False))
