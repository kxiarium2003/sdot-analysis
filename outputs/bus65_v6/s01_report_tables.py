"""s01 - 서울시 대중교통 월보(data/reports/monthly_report_YYYYMM.pdf) 표 추출, 4개월.

pdftotext 가 이 환경에 없어 macOS PDFKit(s01_pdfwords.swift)로 단어별 좌표(쪽, y, x)를 뽑고,
쪽 번호가 아니라 표 제목(공백 제거 후 비교)으로 표를 찾는다. 값은 머리줄 열 좌표에 붙인다.
  (a) "①이용자유형별상세현황"        -> s01_report_types.csv     (ym, period, row, type, trips)  단위 목적통행
  (b) "○통행행태"                      -> s01_report_pattern.csv   (ym, pattern, type, pct, bus_boards)
  (c) "○시간대별이용건수(전체)" 유형별 -> s01_report_type_hour.csv (ym, hour, type, count)  hour=-1 은 전체 행
  (d) "○시간대별이용건수(전체/주중/주말)" 수단별 버스 열 -> s01_report_bus_total.csv (ym, daytype, bus_total, ...)
  (d') "○버스유형별일평균이용건수...(승차기준)" 표 전체 열(전체/주중/주말) -> 같은 파일 bus_total_bytype (대조용)
      (덧붙임) 버스 열 시간대 값 -> s01_report_bus_hour.csv (ym, daytype, hour, bus)
사용: python3 -I s01_report_tables.py <SCRATCH>
"""
import re, sys, subprocess
from pathlib import Path
import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
SCR = Path(sys.argv[1])
YMS = ["202407", "202408", "202507", "202508"]
TYPES = ["전체", "일반", "어린이", "청소년", "경로", "장애인", "기타"]
NUM = re.compile(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?")

tool = SCR / "tools" / "pdfwords"
if not tool.exists():
    tool.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["swiftc", "-O", str(OUT / "s01_pdfwords.swift"), "-o", str(tool)], check=True)


def lines_of(ym):
    f = SCR / "txt" / f"w_{ym}.tsv"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(tool), str(ROOT / f"data/reports/monthly_report_{ym}.pdf"), str(f)], check=True)
    w = pd.read_csv(f, sep="\t", dtype={"word": str}).dropna(subset=["word"])
    out = []
    for (p, y), g in w.groupby(["page", "y"], sort=True):
        g = g.sort_values("x0")
        out.append({"page": p, "y": y, "words": list(zip(g.x0, g.x1, g.word)),
                    "text": " ".join(g.word), "ns": "".join(g.word)})
    return out


def find_title(L, title, need=None):
    """제목 줄 색인들. need 가 있으면 같은 쪽에 need(공백 제거) 를 포함한 줄이 있는 경우만."""
    hits = []
    for i, l in enumerate(L):
        if title in l["ns"]:
            if need is None or any(need in m["ns"] for m in L if m["page"] == l["page"]):
                hits.append(i)
    return hits


def header_cols(l, names):
    """머리줄에서 names 순서대로 열 중심 x."""
    xs, j = [], 0
    for x0, x1, wd in l["words"]:
        if j < len(names) and wd == names[j]:
            xs.append((x0 + x1) / 2)
            j += 1
    assert j == len(names), (l["text"], names)
    return xs


def assign(l, xs, pat):
    """줄의 값 단어를 가장 가까운 머리 열에 붙인다. 붙은 단어가 여러 숫자로 이어져 있으면 쪼갠다."""
    vals = [None] * len(xs)
    toks = []
    for x0, x1, wd in l["words"]:
        parts = pat.findall(wd)
        if not parts or "▲" in wd or "▼" in wd:
            continue
        if len(parts) == 1:
            toks.append(((x0 + x1) / 2, parts[0]))
        else:  # 붙은 숫자: 폭을 글자 수 비율로 나눠 중심을 근사
            n = sum(len(p) for p in parts)
            c = x0
            for p in parts:
                wdt = (x1 - x0) * len(p) / n
                toks.append((c + wdt / 2, p))
                c += wdt
    for cx, v in toks:
        k = min(range(len(xs)), key=lambda i: abs(xs[i] - cx))
        assert vals[k] is None, ("열 충돌", l["text"])
        vals[k] = v
    return vals


rows_a, rows_b, rows_c, rows_d, rows_dh, rows_d2 = [], [], [], [], [], []
PAT_LAB = ["단독_소계", "단독_버스", "단독_지하철", "환승_소계",
           "2회_소계", "2회_버스2회", "2회_지하철2회", "2회_버스1회지하철1회",
           "3회_소계", "3회_버스3회", "3회_지하철3회", "3회_버스+지하철",
           "4회_소계", "4회_버스4회", "4회_지하철4회", "4회_버스+지하철",
           "5회_소계", "5회_버스5회", "5회_지하철5회", "5회_버스+지하철"]
PAT_KEY = ["소계", "버스", "지하철", "소계", "소계", "버스2회", "지하철2회", "버스1회,지하철1회",
           "소계", "버스3회", "지하철3회", "버스+지하철", "소계", "버스4회", "지하철4회", "버스+지하철",
           "소계", "버스5회", "지하철5회", "버스+지하철"]
BUS_N = {"단독_버스": 1, "2회_버스2회": 2, "2회_버스1회지하철1회": 1, "3회_버스3회": 3, "3회_버스+지하철": 1.5,
         "4회_버스4회": 4, "4회_버스+지하철": 2, "5회_버스5회": 5, "5회_버스+지하철": 2.5}
log = []

for ym in YMS:
    L = lines_of(ym)
    # ---------------- (a)
    ti = find_title(L, "이용자유형별상세현황")
    assert len(ti) == 1, (ym, "a", ti)
    page = L[ti[0]]["page"]
    hi = next(i for i in range(ti[0], len(L)) if L[i]["page"] == page and L[i]["ns"].startswith("구분전체일반어린이"))
    xs = header_cols(L[hi], ["구분"] + TYPES)[1:]
    vals = []
    for l in L[hi + 1:]:
        if l["page"] != page:
            break
        if "%" in l["text"] or "▲" in l["text"] or "▼" in l["text"]:
            continue
        v = assign(l, xs, NUM)
        if sum(x is not None for x in v) == 7:
            vals.append([int(x.replace(",", "")) for x in v])
    assert len(vals) == 12, (ym, "a rows", len(vals))
    mx_t = mx_m = 0
    for bi, period in enumerate(["월평균", "주중평균", "주말평균"]):
        blk = vals[bi * 4:(bi + 1) * 4]
        for r in blk:
            mx_t = max(mx_t, abs(r[0] - sum(r[1:])))
        for c in range(7):
            mx_m = max(mx_m, abs(blk[0][c] - sum(b[c] for b in blk[1:])))
        for rn, r in zip(["전체", "버스", "지하철", "버스+지하철"], blk):
            for t, v in zip(TYPES, r):
                rows_a.append((ym, period, rn, t, v))
    assert mx_t <= 3 and mx_m <= 3, (ym, "a 검산", mx_t, mx_m)
    log.append(f"{ym} (a) {page}쪽, 12행 x 7열, 최대 차: 전체-유형합 {mx_t}, 전체-수단합 {mx_m} (반올림)")

    # ---------------- (b)
    ti = find_title(L, "○통행행태")
    assert len(ti) == 1, (ym, "b", ti)
    page = L[ti[0]]["page"]
    hi = next(i for i in range(ti[0], len(L)) if L[i]["ns"].startswith("구분전체일반어린이"))
    xs = header_cols(L[hi], ["구분"] + TYPES)[1:]
    xcut = xs[0] - 25
    rows = []
    for l in L[hi + 1:]:
        if l["page"] != page or "이용요금" in l["ns"]:
            break
        v = [None] * 7
        lab = "".join(wd for x0, x1, wd in l["words"] if x1 < xcut)
        for x0, x1, wd in l["words"]:
            if x0 < xcut:
                continue
            m = re.fullmatch(r"(\d+\.\d)%|-", wd)
            assert m, (ym, "b 값", wd, l["text"])
            k = min(range(7), key=lambda i: abs(xs[i] - (x0 + x1) / 2))
            v[k] = float(m.group(1)) if m.group(1) else 0.0
        if any(x is not None for x in v):
            assert all(x is not None for x in v), (ym, "b 빈칸", l["text"])
            rows.append((lab, v))
    assert len(rows) == 20, (ym, "b rows", len(rows))
    for (lab, v), key, name in zip(rows, PAT_KEY, PAT_LAB):
        assert lab.endswith(key), (ym, lab, key)
        for t, x in zip(TYPES, v):
            rows_b.append((ym, name, t, x, BUS_N.get(name, 0)))
    # 소계 검산(반올림 허용)
    d = {n: v for (lab, v), n in zip(rows, PAT_LAB)}
    mx = 0
    for g, comp in [("단독_소계", ["단독_버스", "단독_지하철"]), ("2회_소계", PAT_LAB[5:8]), ("3회_소계", PAT_LAB[9:12]),
                    ("4회_소계", PAT_LAB[13:16]), ("5회_소계", PAT_LAB[17:20]), ("환승_소계", ["2회_소계", "3회_소계", "4회_소계", "5회_소계"])]:
        for c in range(7):
            mx = max(mx, abs(d[g][c] - sum(d[x][c] for x in comp)))
    log.append(f"{ym} (b) {page}쪽, 20행 x 7열, 소계-구성합 최대 차 {mx:.1f}%p ('-' 는 0)")

    # ---------------- (c), (d)
    for dt in ["전체", "주중", "주말"]:
        tis = find_title(L, f"○시간대별이용건수({dt})")
        for t0 in tis:
            page = L[t0]["page"]
            hi = next(i for i in range(t0, len(L)) if L[i]["page"] == page and L[i]["ns"].startswith(("합계일반", "버스지하철")))
            is_type = L[hi]["ns"].startswith("합계일반")
            names = ["합계", "일반", "어린이", "청소년", "경로", "장애인", "기타"] if is_type else ["버스", "지하철", "따릉이", "택시"] * 2  # 건수 4열 + 비율 4열
            xs = header_cols(L[hi], names)
            tab = {}
            for l in L[hi + 1:]:
                if l["page"] != page:
                    break
                m = re.match(r"(전체|(\d\d)[∼~](\d\d)시)", l["ns"])
                if not m:
                    continue
                h = -1 if m.group(1) == "전체" else int(m.group(2))
                ws = [w for w in l["words"] if not re.match(r"(전체|\d\d[∼~]\d\d시)", w[2])]
                v = assign({"words": ws, "text": l["text"]}, xs, NUM)
                tab[h] = [int(x.replace(",", "")) if x is not None else None for x in v[:7 if is_type else 4]]
            assert sorted(tab) == list(range(-1, 24)), (ym, dt, sorted(tab))
            if is_type:
                assert dt == "전체"
                mx1 = max(abs(v[0] - sum(v[1:])) for v in tab.values())
                mx2 = max(abs(tab[-1][c] - sum(tab[h][c] for h in range(24))) for c in range(7))
                assert mx1 <= 3 and mx2 <= 30, (ym, "c 검산", mx1, mx2)
                for h, v in tab.items():
                    for t, x in zip(["전체"] + TYPES[1:], v):
                        rows_c.append((ym, h, t, x))
                log.append(f"{ym} (c) {page}쪽, 25행 x 7열, 최대 차: 합계-유형합 {mx1}, 전체-시간합 {mx2}")
            else:
                bus = {h: v[0] for h, v in tab.items()}
                diff = bus[-1] - sum(bus[h] for h in range(24))
                rows_d.append((ym, dt, bus[-1], sum(bus[h] for h in range(24))))
                for h in range(24):
                    rows_dh.append((ym, dt, h, bus[h]))
                log.append(f"{ym} (d) {dt} {page}쪽 버스 전체 {bus[-1]:,}, 시간합과 차 {diff}")

    # ---------------- (d') 버스 유형별 일평균 이용건수(승차기준) 표의 전체 열: 전체/주중/주말
    ti = find_title(L, "버스유형별일평균이용건수")
    assert len(ti) == 1, (ym, "d'", ti)
    page = L[ti[0]]["page"]
    hi = next(i for i in range(ti[0], len(L)) if L[i]["page"] == page and L[i]["ns"].startswith("구분(일평균)전체간선"))
    xs = header_cols(L[hi], ["전체", "간선", "지선", "광역", "순환", "마을"])
    got = {}
    for l in L[hi + 1:]:
        m = re.match(r"(전체|주중|주말)", l["ns"])
        if l["page"] != page or len(got) == 3:
            break
        if m and m.group(1) not in got:
            ws = [w for w in l["words"] if not re.match(r"(전체|주중|주말)$", w[2])]
            if ws and ws[0][2].startswith(("전체", "주중", "주말")):  # 라벨이 숫자와 붙은 경우
                ws[0] = (ws[0][0], ws[0][1], ws[0][2][2:])
            v = assign({"words": ws, "text": l["text"]}, xs, NUM)
            v = [int(x.replace(",", "")) for x in v]
            assert abs(v[0] - sum(v[1:])) <= 0.005 * v[0], (ym, "d' 합", v)  # 표에 없는 노선 유형분 차이 허용
            got[m.group(1)] = v[0]
    assert len(got) == 3, (ym, got)
    for dt, v in got.items():
        rows_d2.append((ym, dt, v))
    log.append(f"{ym} (d') {page}쪽 버스 유형별(승차기준) 전체 {got['전체']:,} 주중 {got['주중']:,} 주말 {got['주말']:,}")

A = pd.DataFrame(rows_a, columns=["ym", "period", "row", "type", "trips"])
B = pd.DataFrame(rows_b, columns=["ym", "pattern", "type", "pct", "bus_boards"])
C = pd.DataFrame(rows_c, columns=["ym", "hour", "type", "count"])
D = pd.DataFrame(rows_d, columns=["ym", "daytype", "bus_total", "bus_hour_sum"])
DH = pd.DataFrame(rows_dh, columns=["ym", "daytype", "hour", "bus"])
assert len(D) == 12, len(D)
D = D.merge(pd.DataFrame(rows_d2, columns=["ym", "daytype", "bus_total_bytype"]), on=["ym", "daytype"])
D["hour_sum_minus_total"] = D.bus_hour_sum - D.bus_total
D["bytype_over_total"] = D.bus_total_bytype / D.bus_total
# 판정: 시간대 표 값이 같은 보고서 버스 유형별 표와 2% 넘게 다르거나, 시간합이 전체와 1% 넘게 다르면 이상
D["hour_table_ok"] = ((D.bytype_over_total - 1).abs() < 0.02) & (D.hour_sum_minus_total.abs() < 0.01 * D.bus_total)
D["total_ok"] = (D.bytype_over_total - 1).abs() < 0.02
# 진단 기준값: (d) 전체 행이 (d')와 맞으면 (d), 아니면 (d')
D["bus_ref"] = D.bus_total.where(D.total_ok, D.bus_total_bytype)
D["bus_ref_src"] = D.total_ok.map({True: "(d) 시간대별 표", False: "(d') 버스 유형별 표"})
DH = DH.merge(D[["ym", "daytype", "hour_table_ok"]], on=["ym", "daytype"])
kw = dict(index=False, encoding="utf-8-sig")
A.to_csv(OUT / "s01_report_types.csv", **kw)
B.to_csv(OUT / "s01_report_pattern.csv", **kw)
C.to_csv(OUT / "s01_report_type_hour.csv", **kw)
D.to_csv(OUT / "s01_report_bus_total.csv", **kw)
DH.to_csv(OUT / "s01_report_bus_hour.csv", **kw)

# ---------------- 2025-08 필수 검증
a = A[A.ym == "202508"].set_index(["period", "row", "type"]).trips
b = B[B.ym == "202508"].set_index(["pattern", "type"]).pct
c = C[C.ym == "202508"].set_index(["hour", "type"])["count"]
chk = [
    ("(a) 월평균 전체 일반", a["월평균", "전체", "일반"], 6951145), ("(a) 월평균 전체 어린이", a["월평균", "전체", "어린이"], 243896),
    ("(a) 월평균 전체 청소년", a["월평균", "전체", "청소년"], 228150), ("(a) 월평균 전체 경로", a["월평균", "전체", "경로"], 977658),
    ("(a) 월평균 전체 장애인", a["월평균", "전체", "장애인"], 224508),
    ("(a) 버스 경로 월평균", a["월평균", "버스", "경로"], 135335), ("(a) 버스 경로 주중", a["주중평균", "버스", "경로"], 147852),
    ("(a) 버스 경로 주말", a["주말평균", "버스", "경로"], 109048),
    ("(b) 경로 버스(단독)", b["단독_버스", "경로"], 11.3), ("(b) 경로 버스 2회", b["2회_버스2회", "경로"], 2.1),
    ("(b) 경로 버스 3회", b["3회_버스3회", "경로"], 0.3), ("(b) 경로 버스 4회", b["4회_버스4회", "경로"], 0.1),
    ("(c) 경로 전체", c[-1, "경로"], 1009687), ("(c) 경로 15~16시", c[15, "경로"], 85883),
    ("(d) 버스 전체", D.set_index(["ym", "daytype"]).bus_total["202508", "전체"], 4601837),
]
V = pd.DataFrame(chk, columns=["item", "extracted", "expected"])
V["match"] = (V.extracted - V.expected).abs() < 1e-9
V.to_csv(OUT / "s01_validation_202508.csv", **kw)
(OUT / "s01_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
print("\n".join(log))
print(V.to_string())
assert V.match.all(), "2025-08 검증 불일치"
