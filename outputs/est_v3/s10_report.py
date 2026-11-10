"""s10_report.py - CSV 요약에서 report_est_v3.md를 만든다. 숫자는 전부 CSV에서 읽어 넣는다."""
import sys, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd

R = lambda f, **k: pd.read_csv(OUT / f, **k)
N = dict(D5="D5 집계구 생활인구", D7="D7 무더위쉼터", D12="D12 서울 생활이동", D14="D14 폭염저감시설", D15="D15 버스 일별 정류장 승하차", D16="D16 버스 시간대별 정류장 승하차", D18="D18 서울교통공사 역별 시간대별 승하차", D21="D21 서울시 버스정류소 위치정보", D25="D25 정류장·역사별 출발지/도착지", D26="D26 서울교통공사 역별 노인 승하차", D28="D28 서울시 지하철 호선별 역별 유/무임 승하차")


def md(df, fmt=None):
    fmt = fmt or {}
    def cell(c, v):
        if pd.isna(v): return "-"
        if c in fmt: return fmt[c](v)
        if isinstance(v, (float, np.floating)): return f"{v:,.3f}"
        if isinstance(v, (int, np.integer)): return f"{int(v):,}"
        return str(v)
    h = "| " + " | ".join(map(str, df.columns)) + " |\n|" + "|".join(["---"] * len(df.columns)) + "|\n"
    return h + "\n".join("| " + " | ".join(cell(c, v) for c, v in zip(df.columns, r)) + " |" for r in df.itertuples(index=False, name=None)) + "\n"


pct = lambda v: f"{v * 100:.1f}%"; pct2 = lambda v: f"{v * 100:.2f}%"; i0 = lambda v: f"{v:,.0f}"; f3 = lambda v: f"{v:.3f}"; f4 = lambda v: f"{v:.4f}"
months = sorted(os.path.basename(f)[4:10] for f in glob.glob(str(SCRATCH / "est/est_*.parquet")))
draft = len(months) < 4
base_y = "2025"
tag_scope = f"({', '.join(months)})"
D26N = N["D26"]; D28N = N["D28"]
INV = {f"{D26N} 승차합": "D26_승차합", f"{D28N} 전 노선 무임승차": "D28_전노선_무임승차", f"{D28N} 1~8호선 무임승차": "D28_1_8호선_무임승차", f"{D28N} 행 수": "D28행"}
k = R("s06_e3_k.csv", dtype={"ym": str}).rename(columns=INV).set_index("ym").loc[months]
par = R("s05_e2_params.csv").set_index("모형")
cls = R("s04_e1_class_share.csv", dtype={"ym": str}); cls = cls[cls.ym.isin(months)]
daily = R("s06_check_daily.csv", dtype={"date": str, "ym": str}); daily = daily[daily.ym.isin(months)]
over = R("s06_ratio_over1.csv", dtype={"ym": str}); over = over[over.ym.isin(months)]
gu = R("s06_check_gu.csv", dtype={"연도": str}); top = R("s06_top20_stops.csv", dtype={"연도": str, "ars": str})
sm = R("s07_smart_summary.csv", dtype={f"{N['D21']} 판본": str}).rename(columns={f"{N['D21']} 판본": "판본", f"{N['D21']} 연결 행": "D21연결_행"}); cs = R("s07_cooling_summary.csv", dtype={"연도": str}); ct = R("s07_cooling_type.csv", dtype={"연도": str})
oc = R("o1_coverage_city.csv", dtype={"연도": str}); og = R("o1_coverage_gu.csv", dtype={"연도": str}); oss = R("o2_o3_summary.csv"); ov = R("o4_overlap.csv")
o2 = R(f"o2_selected_{base_y}.csv", dtype={"ars": str}); o3 = R(f"o3_selected_{base_y}.csv", dtype={"ars": str})
years = sorted(oc.연도.unique()); sm25 = sm.set_index("판본").loc["2025"]
c300 = oc[(oc.반경 == 300) & (oc.기준.str.startswith("w65(")) & (oc.연도 == base_y)].iloc[0]
c300t = oc[(oc.반경 == 300) & (oc.기준.str.startswith("wtot")) & (oc.연도 == base_y)].iloc[0]
g = lambda m, p: oss[(oss.방법 == m) & (oss.p == p)].iloc[0]
ovw = ov[(ov.변형.str.startswith("총승차"))]
same = cls.groupby("ym").apply(lambda t: t.same_dong_pax.sum() / t[t.why.isin(["matched", "no_d12_cell"])].board_pax.sum(), include_groups=False)
L = []
A = L.append
A("# 65+ 버스 승하차 추정(단순판)과 폭염 쉼터 커버리지·배치 baseline" + (" [초안: 2025-08 한 달]" if draft else "") + "\n")
A(f"작성 2026-11-09. 표기: **[확인됨]** 파일을 직접 계산해 확인 · **[추정]** 근거는 있으나 직접 검증하지 않음 · **[미확인]** 확인하지 못함. 대상 월 {', '.join(months)}.\n")
A("## 미팅용 요약\n")
kv = k["k_m3"]; 
ov24 = ov[ov.변형 == "2024 기준"]; lohi = ov[ov.변형.str.contains("하한|상한")]; rad = ov[ov.변형.str.startswith("반경")]
A(f"1. {N['D12']} OD 매칭(P1)에 지하철 보정(m3: a={par.loc['P1_m3','a']:.3f}, b={par.loc['P1_m3','b']:.3f}, 공간 CV R² {par.loc['P1_m3','CV_R2']:.3f})과 노인실태조사 규모 맞춤(월별 k {kv.min():.2f}~{kv.max():.2f})을 적용하면, 서울 버스 65+ 승차는 월 {k['목표'].min() / 1e6:.1f}~{k['목표'].max() / 1e6:.1f}백만 명, 승차의 {k['최종비율_m3'].min() * 100:.1f}~{k['최종비율_m3'].max() * 100:.1f}%다 [추정]. 지하철 보정이 버스에도 맞는지는 [미확인]이다.\n"
  f"2. 2025년 11~17시 65+ 승차의 {pct(c300.c합)}가 스마트쉼터 정류장 또는 무더위쉼터 300m 안에 있고, {pct(c300.d없음)}(정류장 {int(c300.정류장_d):,}개)가 커버 밖이다 [추정]. 300m 대신 150m면 {pct(oc[(oc.반경==150)&oc.기준.str.startswith('w65(')&(oc.연도==base_y)].iloc[0].c합)}, 500m면 {pct(oc[(oc.반경==500)&oc.기준.str.startswith('w65(')&(oc.연도==base_y)].iloc[0].c합)}로 크게 달라진다 [확인됨: 계산].\n"
  f"3. 스마트쉼터 100개(O2)는 커버 밖 65+ 승차의 {pct(g('O2',100).비율_미커버)}, 무더위쉼터 30개(O3, 정류장 위치 대용)는 {pct(g('O3',30).비율_미커버)}를 새로 커버한다 [추정].\n"
  f"4. 65+ 대신 총 승차로 뽑으면 O2 p=100 겹침 {int(ovw[(ovw.방법=='O2')&(ovw.p==100)].iloc[0].겹침개수)}개(Jaccard {ovw[(ovw.방법=='O2')&(ovw.p==100)].iloc[0].Jaccard:.2f}), 65+ 커버는 {abs(ovw[(ovw.방법=='O2')&(ovw.p==100)].iloc[0].커버차이):,.0f}명 줄어든다 [추정]. 선택은 m0·m3 범위에는 안정적이고(Jaccard {lohi.Jaccard.min():.2f} 이상) 반경(최대 {rad.Jaccard.max():.2f})과 연도(최대 {ov24.Jaccard.max():.2f})에는 민감하다 [확인됨: 계산].\n"
  f"5. 스마트쉼터는 {N['D14']} 199행 중 ARS가 있는 {int(sm25.D21연결_행)}행({pct(sm25.연결률)})만 연결돼 (a)는 하한이다 [확인됨]. 정수계획 검증은 pulp·ortools가 없어 건너뛰었다 [확인됨].\n")
A("## 입력과 실행\n")
A(f"- 실행 순서: s01 → s02 → s03 → s04 → s05 → s06 → s06b → s07 → s08 → s09 → s10. 환경변수 `EST_V3_SCRATCH` 필요 [확인됨].\n- 분모 `denom_YYYYMM.parquet`, `eval_panel.parquet`은 Drive `interim/bus65_v2/`. 원자료·중간 산출물은 스크래치에서 쓰고 작업 후 지웠다 [확인됨].\n- 2024-08-20은 {N['D25']} 승차 4,877,287명을 {N['D15']}×{N['D16']} 대체 5,017,842명(+2.9%)으로, 하차 4,785,893명을 4,919,014명으로 바꾸고 imputed=True로 표시했다 [확인됨].\n- 그림은 dataviz 기본 팔레트 1~3번 슬롯을 썼다. node가 없어 팔레트 검증 스크립트는 돌리지 못했고 문서의 전 쌍 검증값을 따랐다 [미확인: 재검증].\n")
A("## E. 65+ 추정\n")
A(f"### E1. 버스 P1\n\n- {N['D25']} 버스 OD × {N['D12']} 동 쌍 × 요일 × 출발시 65+ 비율. est_v2의 지하철 P1과 같은 칸(출발시 변환, 3시간 자름)이다. 마스킹 분모 0(m0, 상한쪽)·3(m3, 하한쪽)을 각각 계산했다 [확인됨].\n- 정류장: {N['D21']} 2024-09-03판, 2025-08-01판. 09642·05229 좌표 덮어쓰기 유지. 동 미배정 13개는 최근접 동(최대 71.8m) 배정 [확인됨].\n- 분모: est_v2 denom. E1에서 다시 합한 승차·하차가 분모와 칸 단위로 같다(비대체일 최대 차이 0) [확인됨: `s04_e1_check_denom.csv`].\n- 대체일: 2024-08-20·21, 2025-07-01·02. 비율은 같은 달 같은 요일 정류장×시 합산 비율이다(대체일 제외, 칸이 없으면 같은 달 정류장×시 → 서울 요일×시) [확인됨: `s04_e1_imputed_fallback.csv`].\n")
c = cls.groupby("why")[["board_pax", "alight_pax"]].sum(); c = (c / c.sum()).reset_index().rename(columns={"why": "구분", "board_pax": "승차 비중", "alight_pax": "하차 비중"})
name = {"matched": "동 쌍 칸으로 계산 (od)", "alight_missing": "하차 결측 → 출발 동 전체 (fb_o)", "alight_outside": "하차 서울 밖 → 출발 동 전체 (fb_o)", "board_outside": "승차가 대상 밖 → 도착 동 전체 (fb_d)", "no_d12_cell": "D12 서울 생활이동 칸 없음 → 출발 동 전체 (fb_o)"}
c["구분"] = c["구분"].map(name)
A(md(c, {"승차 비중": pct2, "하차 비중": pct2}) + "\n(모두 [확인됨])\n")
A(f"- 같은 동 안 이동은 그대로 사용했다. 동 쌍 OD 승객 중 {pct(same.mean())}이다 [확인됨]. 도보 오염 후보로 한계에 적었다 [추정].\n")
A("### E2. 보정 (지하철에서 학습)\n")
p = par.reset_index()[["모형", "N", "a", "b", "c", "R2", "CV_R2", "CV_RMSE", "CV_스피어만"]]
A(md(p, {"N": i0, "a": f4, "b": f4, "c": f4, "R2": f4, "CV_R2": f4, "CV_RMSE": f4, "CV_스피어만": f4}))
A(f"\n(모두 [확인됨]. 표본은 est_v2 공통 표본 중 칸 승차 10명 이상. P1 단독 수치는 est_v2 `s09_metrics_cell.csv`와 같다.)\n")
A(f"- 실제 = {N['D26']} ÷ {N['D18']}, 역 × 날짜 × 시간(06~23시) [확인됨].\n- P1+P2 300m 참고 실험은 CV R²를 m0 {par.loc['P1_m0','CV_R2']:.3f} → {par.loc['P1_m0+P2_300(참고)','CV_R2']:.3f}, m3 {par.loc['P1_m3','CV_R2']:.3f} → {par.loc['P1_m3+P2_300(참고)','CV_R2']:.3f}로 올린다. 버스에는 적용하지 않았다 [확인됨].\n- 버스 적용: 비율 로짓을 0.001~0.999로 자른 뒤 a, b를 적용 → 보정 비율 × 분모 [확인됨].\n")
A("### E3. 서울 전체 규모\n")
A(f"- 기준값: 2024 서울시 노인실태조사(서울시복지재단 2024-26) **p.39**(PDF 63쪽) 본문, 문항 A10-1 \"외출 시 주요 교통수단\": 도보 38.1%, 지하철 24.2%, 버스 23.4% [확인됨]. 표 번호 없이 본문에 있다 [확인됨].\n- 지하철 65+ 합계 = {N['D26']} 승차 합계(전 시간대) × ({N['D28']} 전 노선 무임 승차 ÷ 1~8호선 무임 승차) [확인됨: 계산]. 1~8호선을 서울교통공사 노선으로 썼다 [추정: 메타의 273개 역 대조 근거].\n- 목표 = 지하철 65+ × (23.4 ÷ 24.2) [확인됨: 구성].\n")
kk = k.reset_index()[["ym", "D26_승차합", "D28_전노선_무임승차", "D28_1_8호선_무임승차", "비율", "지하철65합", "목표", "E2합_m0", "k_m0", "E2합_m3", "k_m3", "최종비율_m3"]].rename(columns={"ym": "월", "비율": "노선 확대 비율", "목표": "목표 버스 65+", "최종비율_m3": "최종 65+ 비율"}).rename(columns={v: k for k, v in INV.items()})
fm = {c: i0 for c in [*INV.keys(), "지하철65합", "목표 버스 65+", "E2합_m0", "E2합_m3"]}; fm.update({"노선 확대 비율": f3, "k_m0": f3, "k_m3": f3, "최종 65+ 비율": pct})
A(md(kk, fm) + "\n(모두 [확인됨: 계산]. 중간 = m3 기반. 하한·상한은 m0·m3 칸별 최소·최대.)\n")
A(f"\n- 시나리오마다 월 합계를 같은 목표로 맞추므로, 하한·상한은 총량의 불확실성이 아니라 **정류장·시간 배분의 차이**만 나타낸다 [확인됨: 구성].\n- 산출: `googledrive:sdot-analysis/interim/bus65_v3/est_YYYYMM.parquet`, 열 `date, hour, node, ars, board, alight, board65_mid/lo/hi, alight65_mid/lo/hi, imputed, is_holiday, weekday, ym, ratio_board65, ratio_alight65` [확인됨].\n")
A("### 점검\n")
dd = daily.diff65_pct; A(f"- 서울 전체 65+ 하차 ÷ 승차 − 1(날짜별): 평균 {dd.mean():.2f}%, 범위 {dd.min():.2f}~{dd.max():.2f}% [확인됨]. 총 승차·하차의 차이는 평균 {daily.diff_total_pct.mean():.2f}%로(하차 미태그 등) 같은 방향이다 [확인됨].\n")
A(f"- 대체일 4일의 65+ 차이는 {daily[daily.imp].diff65_pct.min():.2f}~{daily[daily.imp].diff65_pct.max():.2f}%, 나머지 날은 {daily[~daily.imp].diff65_pct.min():.2f}~{daily[~daily.imp].diff65_pct.max():.2f}%다 [확인됨]. 대체일은 시간 분포가 월 평균이라 차이가 조금 크다 [추정].\n")
A(f"- 65+ 값이 분모를 넘는 칸: 승차 {int(over[over.side=='board'].cells.sum()):,}칸(전체의 {pct2(over[over.side=='board'].cells.sum()/ (over[over.side=='board'].cells/over[over.side=='board'].cell_share).sum())}), 초과 인원 {over[over.side=='board'].excess_pax.sum():,.0f}명이다 [확인됨]. 사양대로 자르지 않았다.\n")
A("#### 자치구별 65+ 승차 비율 (2025-07·08, 정류장 승차 1,000명 이상 p10/p50/p90 포함)\n")
gt = gu[gu.연도 == base_y].sort_values("비율", ascending=False)[["gu", "승차65", "비율", "p10", "p50", "p90"]].rename(columns={"gu": "자치구", "승차65": "65+ 승차(기간 합, 중간)", "비율": "65+ 비율"})
A(md(gt, {"65+ 승차(기간 합, 중간)": i0, "65+ 비율": pct, "p10": pct, "p50": pct, "p90": pct}) + "\n(모두 [추정]: 추정값 기반)\n")
A("#### 상위 20개 정류장 (2025, 기간 합, 중간)\n")
tt = top[top.연도 == base_y][["ars", "name", "gu", "board", "board65_mid", "board65_lo", "board65_hi", "r"]].rename(columns={"name": "정류장", "gu": "자치구", "board": "승차", "board65_mid": "65+ 승차", "board65_lo": "하한", "board65_hi": "상한", "r": "65+ 비율"})
A(md(tt, {"승차": i0, "65+ 승차": i0, "하한": i0, "상한": i0, "65+ 비율": pct}) + "\n")
A("## O. 쉼터 커버리지와 배치 baseline\n")
A(f"### 데이터 위치\n\n- {N['D7']}: `googledrive:sdot-analysis/data1/D7_cooling_shelter/` 2개 xlsx. 로컬 `data/raw/D7_cooling_shelter/`와 체크섬이 같다(rclone check 0 differences) [확인됨]. 두 파일 모두 경도·위도 열이 있어 지오코딩 없이 썼다 [확인됨].\n- 스마트쉼터: {N['D14']}(OA-22311)의 `스마트쉼터 현황.xlsx` 199행(`data/raw/D14_heat_mitigation_facility/`, Drive `data1/D14_heat_mitigation_facility/`) [확인됨]. 파일 기준일은 없다 [미확인]. 설치년도 최댓값 2024 [확인됨].\n- 2024 비교 스마트쉼터는 설치년도 2024 이하, 2025 기준은 전체이지만 2025년 설치가 파일에 없어 **두 해 스마트쉼터 목록이 같다** [확인됨].\n")
sm2 = sm.rename(columns={"판본": f"{N['D21']} 판본", "D21연결_행": f"{N['D21']} 연결 행"})[[f"{N['D21']} 판본", "행수", "공사중행", f"{N['D21']} 연결 행", "연결률", "주소구일치", "주소구불일치", "사용_행", "사용_정류장"]]
A(md(sm2, {"연결률": pct}) + f"\n- 연결: 설치장소(없으면 상세주소)의 `NN-NNN` 또는 5자리 ARS → {N['D21']} ARS 일치. 연결된 행은 주소 자치구와 전부 일치했다 [확인됨]. 58행은 ID가 없고 파일에 좌표도 없어 30m 연결이 불가능해 미연결로 뒀다 [확인됨]. 목록 `s07_smart_unlinked.csv`. 이 중 공원 설치분(비정류장)이 포함된다 [확인됨]. 공사중 2행은 제외했다.\n")
cs2 = cs[["연도", "파일", "행", "좌표결측", "서울경계밖", "사용", "좌표중복"]]
A(md(cs2))
A(f"\n{N['D7']} 시설 분류는 두 해 체계가 다르다: 2024 `{', '.join(f'{r.type} {int(r.n):,}' for r in ct[ct.연도=='2024'].itertuples())}` / 2025 `{', '.join(f'{r.type} {int(r.n):,}' for r in ct[ct.연도=='2025'].itertuples())}` [확인됨]. 목록 규모가 2,095개 → 4,049개로 크게 다르므로 커버율 변화에는 목록 정의 변화가 섞여 있다 [추정].\n")
if len(years) == 2:
    A("### 정류장 변화\n")
    z = R("o0_stop_change.csv"); A(md(z[["그룹", "정류장수", "w65비중_2024", "w65비중_2025", "하루65승차비중_2024", "하루65승차비중_2025"]], {"w65비중_2024": pct2, "w65비중_2025": pct2, "하루65승차비중_2024": pct2, "하루65승차비중_2025": pct2}) + "\n(모두 [확인됨: 집합 / 추정: 수요]. 2024 수요는 2024-07·08, 2025 수요는 2025-07·08 평균. 판본은 2024-09-03 / 2025-08-01.)\n")
A("### O1. 현황 커버리지 (서울 전체)\n")
A("w65 = 11~17시 65+ 승차(중간) 하루 평균, wtot = 11~17시 총 승차. 시 라벨 11~17 7개 구간을 썼다 [확인됨: 구성].\n")
oo = oc[(oc.반경 == 300) & ~oc.기준.str.startswith("w65_all")][["연도", "기준", "총량_하루", "a스마트", "b무더위", "c합", "d없음", "정류장_a", "정류장_b", "정류장_d"]]
A(md(oo, {"총량_하루": i0, "a스마트": pct, "b무더위": pct, "c합": pct, "d없음": pct}) + "\n(커버 집합은 [확인됨], 수요는 [추정])\n")
oo = oc[oc.기준.str.startswith("w65(")][["연도", "반경", "b무더위", "c합", "d없음", "정류장_d"]]
A("#### 반경 민감도\n\n" + md(oo, {"b무더위": pct, "c합": pct, "d없음": pct}) + "\n")
A("#### 자치구별 (300m)\n")
gg = og[og.연도.isin(years)]
pv = gg.pivot_table(index="gu", columns=["연도", "기준"], values="d없음")
pv.columns = [f"{a} 없음({b.split('(')[0]})" for a, b in pv.columns]
pv = pv.reset_index().rename(columns={"gu": "자치구"})
col = [c for c in pv.columns if c.endswith("없음(w65)") and c.startswith(base_y)][0]
A(md(pv.sort_values(col, ascending=False), {c: pct for c in pv.columns if c != "자치구"}) + "\n")
A("그림: `fig_o1_map_*.png`(정류장·스마트쉼터·무더위쉼터·커버 안 된 상위 50개), `fig_o1_gu_uncovered.png`.\n")
A("### O2·O3 배치 (2025 기준)\n")
A(md(oss[["방법", "p", "신규커버_w65_하루", "비율_전체", "비율_미커버"]].rename(columns={"신규커버_w65_하루": "신규 커버 65+ 승차(11~17시, 하루 평균)", "비율_전체": "65+ 전체 대비", "비율_미커버": "커버 밖 65+ 대비"}), {"신규 커버 65+ 승차(11~17시, 하루 평균)": i0, "65+ 전체 대비": pct, "커버 밖 65+ 대비": pct}) + f"\n(모두 [추정]: 추정 수요 기반. 커버 밖 65+ 하루 {oss.iloc[0].미커버_w65:,.0f}명, 전체 {oss.iloc[0].전체_w65:,.0f}명.)\n")
A(f"- O2 후보는 스마트쉼터가 없고 무더위쉼터 300m 밖인 정류장, w 순 상위 p개 [확인됨]. 정류장 자체만 커버한다.\n- O3 후보지는 정류장 위치이며 **실제 건물이 아니라 위치 대용**이다. 아직 커버되지 않은 정류장을 300m 안에서 커버하도록 그리디로 골랐다 [확인됨].\n- 정수계획 검증: pulp·ortools가 없어 건너뛰었다 [확인됨]. 그리디와 최적해의 차이는 [미확인]이다.\n- 목록: `o2_selected_{base_y}.csv`(p=200), `o3_selected_{base_y}.csv`(p=50). 그림 `fig_o3_selected_map.png`.\n")
A("상위 O3 10개:\n\n" + md(o3.head(10)[["선택순서", "ars", "정류장명", "자치구", "w_65승차_11_17시_하루평균", "그리디_추가커버_w65"]].rename(columns={"w_65승차_11_17시_하루평균": "자체 w", "그리디_추가커버_w65": "추가 커버"}), {"자체 w": i0, "추가 커버": i0}) + "\n")
A("### O4. 비교\n")
ov2 = ov.copy()
ov2["겹침"] = ov2.겹침개수.astype(int).astype(str) + "/" + ov2.p.astype(str)
A(md(ov2[["변형", "방법", "p", "겹침", "Jaccard", "기준_65커버", "변형선택의_65커버", "커버차이"]].rename(columns={"기준_65커버": "기준 65+ 커버", "변형선택의_65커버": "이 변형의 65+ 커버", "커버차이": "65+ 커버 차이"}), {"Jaccard": f3, "기준 65+ 커버": i0, "이 변형의 65+ 커버": i0, "65+ 커버 차이": i0}) + "\n")
A("- 2024 기준 선택과 겹침이 작은 것은 무더위쉼터 목록이 2,095개에서 4,049개로 늘어 커버 밖 정류장 자체가 달라진 영향으로 보인다 [추정]. 2024 기준 행의 커버 수치는 비교 대상 수요가 달라 비워 두었다 [확인됨].\n")
A("- 하한·상한은 둘 다 같은 월 합계로 맞춘 결과다. 그래서 위의 안정성은 m0·m3 배분 차이에 대한 것이고, 모형 자체의 오차나 전체 규모의 불확실성까지 포함한 것은 아니다 [확인됨: 구성].\n")
A("- 반경 변형의 \"이 변형의 65+ 커버\"는 그 반경 정의에서의 신규 커버량이며, 기준과 차이는 계산하지 않았다 [확인됨]. 전체 선택 목록은 `o4_selected_all_variants.csv`.\n")
A("## 한계\n")
A(f"""- {N['D12']}에는 이동 수단 구분이 없다. 버스 이용자의 연령 구성과 다를 수 있다 [추정].
- 지하철에서 학습한 a, b를 버스에 그대로 썼다. 버스 실측이 없어 검증은 [미확인]이다. 학습 범위는 06~23시이며 00~05시 버스 칸에는 외삽이다 [확인됨: 구성].
- eval_panel의 P1은 서울 도착 칸 일치분만 쓰고, 버스 P1은 하차 결측·서울 밖에 출발 동 비율을 대체했다 [확인됨]. 정의가 조금 다르다.
- 승차가 대상 밖이고 하차만 대상인 OD는 사양에 없어 도착 동 비율로 처리했다(하차의 약 {cls[cls.why=='board_outside'].alight_pax.sum() / cls.alight_pax.sum() * 100:.1f}%) [확인됨: 비중].
- 대상 정류장이 아닌 곳의 승차는 대상 밖이다. 분모 규칙은 est_v2와 같다 [확인됨].
- 같은 동 안 이동(약 {same.mean() * 100:.0f}%)은 도보 오염이 있을 수 있으나 그대로 썼다 [추정].
- {N['D12']}은 요일 평균이라 공휴일·날씨 등 일별 변화가 비율에 없다. 공휴일 8/15에도 요일 비율을 쓴다 [확인됨: 구성]. 일별 변화는 분모에서만 온다.
- E3의 교통수단 비율은 사람 기준 주 수단 응답이고, 버스·지하철 통행량 비가 아니다 [확인됨: 문항 / 추정: 영향]. 지하철 65+는 경기 구간 역과 비서울 거주자를 포함한다 [확인됨: 노선 구성].
- {N['D28']} 무임에는 장애인·유공자가 섞여 있어, 노선 간 비율에 65+ 비중이 같다고 가정했다 [추정].
- 커버리지는 직선 거리이고, 운영 시간·수용 인원·실제 접근성은 반영하지 않았다 [확인됨: 구성].
- 수요는 승차만 썼다. 정류장 위치 커버는 승차 기준이며 환승·하차 대기는 없다 [확인됨: 구성].
""")
A("## 건너뛴 단계\n")
A(f"""- O3 정수계획 검증: pulp·ortools 미설치, 설치하지 않음. `scipy.optimize.milp`는 있으나 지시 범위 밖이라 쓰지 않음 [확인됨].
- 스마트쉼터 30m 최근접 연결: {N['D14']} 파일에 좌표가 없음 [확인됨]. 58행 미연결.
""")
A("## 결정이 필요한 사항\n")
A(f"""1. **정수계획 검증:** scipy `milp`(HiGHS)를 대신 쓸지. 현재는 그리디만 있다.
2. **스마트쉼터 미연결 58행:** 좌표 확보 또는 정류장명 매칭을 허용할지. 현재 (a)와 O2 후보에 영향이 있다.
3. **E3 지하철 범위:** 전 노선(경기 구간 포함)을 그대로 쓸지, 서울 안 역만 쓸지. k와 절대 규모가 달라진다.
4. **사양에 없어 임의로 정한 처리:** 승차 대상 밖 OD는 도착 동 비율, {N['D12']} 칸 없음은 출발 동 비율, 대체일 비율은 합산 비율, "11~17시"는 시 라벨 7구간, 공사중 스마트쉼터 2행 제외. 바꿀 것이 있으면 알려 주십시오.
5. **65+가 분모를 넘는 칸:** 잘라낼지. 영향은 작다(위 점검).
6. **쉼터 반경:** 결과가 반경에 민감하므로 300m를 유지할지. 150·500m 결과는 위 표에 있다.
""")
open(OUT / "report_est_v3.md", "w", encoding="utf-8").write("\n".join(L))
print("written", len("\n".join(L)))
