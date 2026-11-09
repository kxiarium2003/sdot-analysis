"""
s08_notion_payload.py - Notion 페이지 "버스 승하차 인원 추정"에 붙일 내용(표·그림 설명·실행 로그)을 CSV에서 직접 만든다

수치는 모두 이 폴더의 CSV에서 읽은 값이다(직접 입력한 수치 없음).
입력: rank_summary.csv, method_C_vs_A_gu.csv, pilot_jongno_top20.csv, pilot_jongno_stops_202508.csv,
      q1_d20_monthly.csv, q6_station_hourshare_vs_ratio.csv, 실행 로그 폴더(인자 1, s01~s07 stdout을 {스크립트}.log로 저장한 곳)
출력: notion_append.md (섹션별로 나눠 붙일 수 있게 구분)
실행: python outputs/eda_bus65/s08_notion_payload.py <로그 폴더>
"""
import sys
from pathlib import Path
import pandas as pd
from scipy.stats import spearmanr

OUT = Path(__file__).resolve().parent
LOG = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT / "logs"
GU = {"11010": "종로구", "11020": "중구", "11030": "용산구", "11040": "성동구", "11050": "광진구", "11060": "동대문구", "11070": "중랑구",
      "11080": "성북구", "11090": "강북구", "11100": "도봉구", "11110": "노원구", "11120": "은평구", "11130": "서대문구", "11140": "마포구",
      "11150": "양천구", "11160": "강서구", "11170": "구로구", "11180": "금천구", "11190": "영등포구", "11200": "동작구", "11210": "관악구",
      "11220": "서초구", "11230": "강남구", "11240": "송파구", "11250": "강동구"}


def md_table(df):
    cols = list(df.columns)
    rows = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    rows += ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(rows)


f = lambda x, n=3: "" if pd.isna(x) else f"{x:,.{n}f}"
i = lambda x: "" if pd.isna(x) else f"{x:,.0f}"
parts = []

# ---------- 추정 방법 비교 ----------
R = pd.read_csv(OUT / "rank_summary.csv")
G = pd.read_csv(OUT / "method_C_vs_A_gu.csv", dtype={"gu": str})
G["구"] = G.gu.map(GU)
G["A 순위"] = G.mult_A.rank(ascending=False, method="min").astype(int)
G["C 순위"] = G.mult_C.rank(ascending=False, method="min").astype(int)
G["순위 차"] = (G["A 순위"] - G["C 순위"]).abs()
top5 = G.sort_values(["순위 차", "gu"], ascending=[False, True]).head(5)
rhoAC = spearmanr(G.mult_A, G.mult_C).statistic
dong = R[R.method.str.startswith("A-동(무작위 배정")].iloc[0]; Drow = R[R.method == "D(역 이름 연결)"].iloc[0]
rt = R.rename(columns={"method": "방법", "scope": "범위", "rho_vs_board": "승차 순위와 ρ", "top20_overlap": "상위20 겹침",
                       "top10_overlap": "상위10 겹침", "top100_overlap_vs_board": "상위100 겹침(승차 대비)", "total_per_day": "65+ 승차 추정(명/일)", "note": "비고"})
for c in ["승차 순위와 ρ"]: rt[c] = rt[c].map(lambda x: f(x, 4))
for c in ["상위20 겹침", "상위10 겹침", "상위100 겹침(승차 대비)", "65+ 승차 추정(명/일)"]: rt[c] = rt[c].map(i)
rt["비고"] = rt["비고"].fillna("")
t5 = pd.DataFrame({"구": top5["구"], "A 배수(65+ 비율)": top5.mult_A.map(f), "C 배수(배분 65+/승차)": top5.mult_C.map(f),
                   "A 순위": top5["A 순위"], "C 순위": top5["C 순위"], "순위 차": top5["순위 차"]})
parts.append(("추정 방법 비교", f"""![fig_rank_methods.png](fig_rank_methods.png)
왼쪽: 종로구 정류장에서 지역·역 비율을 곱한 추정치와 승차 순위의 스피어만 ρ(A-동 무작위 배정 중앙값 {f(dong.rho_vs_board)}, D 역 이름 연결 {f(Drow.rho_vs_board)}). 오른쪽: 25개 자치구의 A 배수와 C 배수(ρ = {f(rhoAC, 2)}).

**표. 방법별 순위 평가 (rank_summary.csv)**

{md_table(rt)}

**표. A·C 배수가 가장 다른 자치구 5곳 (method_C_vs_A_gu.csv)**
두 배수는 단위가 달라(A = 65+ 이동 비율, C = 배분된 65+ 승차 / 승차) 값 차이 대신 25개 구 안의 순위 차이로 골랐다.

{md_table(t5)}"""))

# ---------- 종로구 시범 계산 ----------
P = pd.read_csv(OUT / "pilot_jongno_stops_202508.csv", dtype={"ars": str})
T = P.head(20)[["ars", "name", "n_routes", "board_10_16", "est65_A_const", "est65_A_hour", "est65_A_hour_per_day"]].copy()   # 전체 정밀도(top20 CSV는 소수 1자리 반올림본, 순서 같음)
assert list(T.ars) == list(pd.read_csv(OUT / "pilot_jongno_top20.csv", dtype={"ars": str}).ars)
T.insert(0, "순위", range(1, len(T) + 1))
T = T.rename(columns={"ars": "ARS", "name": "정류장", "n_routes": "노선 수", "board_10_16": "10~16시 승차(월)",
                      "est65_A_const": "65+ 추정(월, 구 상수 비율)", "est65_A_hour": "65+ 추정(월, 시각별 비율)", "est65_A_hour_per_day": "65+ 추정(일)"})
for c in ["10~16시 승차(월)", "65+ 추정(월, 구 상수 비율)", "65+ 추정(월, 시각별 비율)", "65+ 추정(일)"]: T[c] = T[c].map(i)
parts.append(("종로구 시범 계산", f"""![fig_pilot_jongno_hist.png](fig_pilot_jongno_hist.png)
종로구(ARS 01) 정류장 {len(P)}개의 2025-08 10~16시 65+ 승차 추정치(명/일) 분포. {int((P.est65_A_hour_per_day < 10).sum())}개가 하루 10명 미만이고 최댓값은 {i(P.est65_A_hour_per_day.max())}명.

**표. 65+ 승차 추정 상위 20개 정류장 (pilot_jongno_stops_202508.csv 상위 20, pilot_jongno_top20.csv와 같은 정류장)**

{md_table(T)}"""))

# ---------- 핵심 질문 결과: Q1, Q6 ----------
M = pd.read_csv(OUT / "q1_d20_monthly.csv", dtype={"ym": str}); b = M["서울버스 포함"]
parts.append(("핵심 질문 결과 · Q1", f"""![fig_q1_d20_monthly.png](fig_q1_d20_monthly.png)
D20 경로 승객 중 서울버스 포함 통행 비율은 월별 {f(b.min() * 100, 1)}%({M.ym[b.idxmin()]})~{f(b.max() * 100, 1)}%({M.ym[b.idxmax()]}), 변동계수 {f(b.std() / b.mean() * 100, 1)}%."""))
Q = pd.read_csv(OUT / "q6_station_hourshare_vs_ratio.csv")
r6 = spearmanr(Q.ratio, Q.share_10_16).statistic
parts.append(("핵심 질문 결과 · Q6", f"""![fig_q6_scatter_profile.png](fig_q6_scatter_profile.png)
2025-08 역 {len(Q)}개에서 우대권 비율과 10~16시 승차 비중의 스피어만 ρ = {f(r6, 2)}(왼쪽), 우대권 비율 상·하위 25% 역과 D12 65+의 시각 분포(오른쪽)."""))

# ---------- 실행 로그 ----------
KEEP = {  # 스크립트별 핵심 출력: 경고·트레이스백 제외, 너무 넓은 표는 뺀다
    "s01_inventory_local": lambda L: [l for l in L if l.endswith(tuple("0123456789")) and (".csv " in l)],
    "s02_mobility_remote": lambda L: [l for l in L if l.startswith("[")],
}
logtxt = []
for s in ["s01_inventory_local", "s02_mobility_remote", "s03_subway", "s04_bus", "s05_mobility_checks", "s06_d20_q1", "s07_method_ranking"]:
    p = LOG / f"{s}.log"
    if not p.exists(): logtxt.append(f"### {s}\n(로그 없음)"); continue
    L = [l.rstrip() for l in p.read_text().splitlines() if l.strip()]
    L = [l for l in L if not any(k in l for k in ("Warning", "warn", "Traceback", "Error", "glyph"))]
    L = KEEP.get(s, lambda L: L)(L)
    logtxt.append(f"### {s}\n```\n" + "\n".join(L) + "\n```")
parts.append(("실행 로그 (토글)", "<details>\n<summary>실행 로그</summary>\n\n" + "\n\n".join(logtxt) + "\n\n</details>"))

txt = "# Notion 추가용 내용 (outputs/eda_bus65)\n\n각 `---` 블록을 페이지의 해당 섹션 아래에 붙인다. 그림은 같은 폴더의 PNG를 업로드한다.\n\n"
txt += "\n\n---\n\n".join(f"## [{h}] 아래에 추가\n\n{body}" for h, body in parts)
(OUT / "notion_append.md").write_text(txt, encoding="utf-8")
print(f"notion_append.md 작성: 섹션 {len(parts)}개, {len(txt):,}자")
print(top5[["구", "mult_A", "mult_C", "A 순위", "C 순위", "순위 차"]].to_string(index=False))
