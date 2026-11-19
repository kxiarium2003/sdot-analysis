"""s03 - 유형별 시간 비율 pi(t, 월, h) = (c) 유형 t 의 h시 이용건수 / 유형 t 시간 합. h=0 은 00~01시.

(c) 는 버스+지하철 수단통행, 월 전체 날(평일·주말 구분 없음) 표다.
분모는 표의 '전체' 행 대신 24칸 합을 써서 합 = 1 이 정확히 되게 한다(차이는 반올림 수준, 같이 기록).
출력: s03_pi.csv (ym, type, hour, count, pi), s03_pi_check.csv
사용: python3 -I s03_pi.py
"""
from pathlib import Path
import pandas as pd

OUT = Path(__file__).resolve().parent
C = pd.read_csv(OUT / "s01_report_type_hour.csv", dtype={"ym": str})
TYPES = ["일반", "어린이", "청소년", "경로", "장애인", "기타"]
h = C[(C.hour >= 0) & C.type.isin(TYPES)].copy()
tot = C[C.hour == -1].set_index(["ym", "type"])["count"]
h["pi"] = h["count"] / h.groupby(["ym", "type"])["count"].transform("sum")
h[["ym", "type", "hour", "count", "pi"]].sort_values(["ym", "type", "hour"]).to_csv(OUT / "s03_pi.csv", index=False, encoding="utf-8-sig")
chk = h.groupby(["ym", "type"]).agg(pi_sum=("pi", "sum"), hour_sum=("count", "sum")).join(tot.rename("table_total"))
chk["hour_sum_minus_total"] = chk.hour_sum - chk.table_total
chk.to_csv(OUT / "s03_pi_check.csv", encoding="utf-8-sig")
print(chk.to_string())
assert (chk.pi_sum - 1).abs().max() < 1e-12
