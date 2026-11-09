"""
script44-vuln-date-types.py - 취약계층 유동성 분석 [3] 날짜 유형 표 (사전등록 docs/preregistration.md §7 (d))

242일(2024·2025년 6~9월, 2025-07-08·09 제외)마다 연도, 요일, 공휴일 여부, 학기/방학, 날짜 유형 4개,
방학 핵심 구간 여부(민감도)를 붙여 rq1_followup/out/step5_vuln/date_types.csv 로 저장한다.
실행: python scripts/script44-vuln-date-types.py
"""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "rq1_followup/out/step5_vuln"; OUT.mkdir(parents=True, exist_ok=True)
HOLIDAYS = {"2024-06-06", "2024-08-15", "2024-09-16", "2024-09-17", "2024-09-18", "2025-06-03", "2025-06-06", "2025-08-15"}
EXCLUDE = {"2025-07-08", "2025-07-09"}
VACATION = [("2024-07-22", "2024-08-18"), ("2025-07-21", "2025-08-17")]
VAC_CORE = [("2024-07-29", "2024-08-14"), ("2025-07-28", "2025-08-14")]
WD = ["월", "화", "수", "목", "금", "토", "일"]

inr = lambda d, spans: any(pd.Timestamp(a) <= d <= pd.Timestamp(b) for a, b in spans)
days = [d for y in (2024, 2025) for d in pd.date_range(f"{y}-06-01", f"{y}-09-30") if d.strftime("%Y-%m-%d") not in EXCLUDE]
rows = []
for d in days:
    s = d.strftime("%Y-%m-%d"); hol = s in HOLIDAYS; vac = inr(d, VACATION); wd = d.weekday()
    if hol or wd == 6: typ = "일요일·공휴일"
    elif wd == 5: typ = "토요일"
    else: typ = "방학 평일" if vac else "학기 평일"
    rows.append(dict(기준일ID=d.strftime("%Y%m%d"), 날짜=s, 연도=d.year, 월=d.month, 요일=WD[wd], 공휴일=hol, 학기방학="방학" if vac else "학기",
                     날짜유형=typ, 방학핵심=inr(d, VAC_CORE), 핵심정의_유형=("방학 평일" if typ == "방학 평일" and inr(d, VAC_CORE) else
                                                              ("제외(방학 비핵심 평일)" if typ == "방학 평일" else typ)),
                     칠팔월=d.month in (7, 8)))
T = pd.DataFrame(rows)
assert len(T) == 242, len(T)
T.to_csv(OUT / "date_types.csv", index=False, encoding="utf-8-sig")
order = ["학기 평일", "방학 평일", "토요일", "일요일·공휴일"]
c = pd.crosstab(T.날짜유형, T.연도).reindex(order); c["합계"] = c.sum(1)
c2 = pd.crosstab(T[T.칠팔월].날짜유형, T[T.칠팔월].연도).reindex(order).fillna(0).astype(int)
c3 = pd.crosstab(T.핵심정의_유형, T.연도)
print("[6~9월]\n", c.to_string()); print("[7~8월만]\n", c2.to_string()); print("[방학 핵심 정의]\n", c3.to_string())
pd.concat({"6~9월": c, "7~8월": c2}, axis=1).to_csv(OUT / "date_type_counts.csv", encoding="utf-8-sig")
c3.to_csv(OUT / "date_type_counts_vaccore.csv", encoding="utf-8-sig")
