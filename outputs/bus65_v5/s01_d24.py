"""s01 - D24 서울시 정류장별 사용자유형별 환승(OA-21221) 4개월 집계와 새 zip 업로드.

각 달: 일별 CSV(cp949)를 읽어 정류장->정류장(9자리->9자리), 승차 정류장 서울(ID 앞 3자리 100~124) 행만
  - 승차 정류장별 n(환승_수_합), eld(경로) 합 (같은 키 여러 행은 모두 더함)
  - 평일/주말(8월 15일은 평일) x 시간대별 n, eld 합
  - 품질: 행 수, 날짜 수, 총계>유형합 행, (날짜,하차,승차,시간) 중복 키 행
2025-08은 로컬 data/raw, 나머지는 SCRATCH/d24dl/ 의 새 zip. 새 zip은 집계 후 Drive data1/D24_stop_usertype_transfer/ 에 올리고 체크섬 대조 후 로컬 사본을 지운다.
사용: python3 -I s01_d24.py <SCRATCH>
"""
import sys, io, zipfile, subprocess
from pathlib import Path
import pandas as pd, duckdb

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SCR = Path(sys.argv[1])
MS = ["202407", "202408", "202507", "202508"]
stop_rows, hour_rows, qual = [], [], []
for ym in MS:
    zp = ROOT / "data/raw/D24_stop_usertype_transfer/kscc_dx_trnsf_path_sum_202508.zip" if ym == "202508" else SCR / f"d24dl/kscc_dx_trnsf_path_sum_{ym}.zip"
    z = zipfile.ZipFile(zp)
    assert z.testzip() is None, ym
    q = dict(ym=ym, zip=zp.name, zip_bytes=zp.stat().st_size, files=len(z.infolist()), rows=0, days=0, rows_n_gt_types=0, rows_in_dup_keys=0, header_only_files=0)
    dates = []
    for i in sorted(z.infolist(), key=lambda x: x.filename):
        df = pd.read_csv(io.BytesIO(z.read(i)), encoding="cp949", dtype=str)
        if len(df) == 0:
            q["header_only_files"] += 1
            continue
        df.columns = ["date", "off_id", "on_id", "hh", "n", "n_gen", "n_kid", "n_teen", "n_eld", "n_dis"] + list(df.columns[10:])
        for c in ["n", "n_gen", "n_kid", "n_teen", "n_eld", "n_dis"]:
            df[c] = pd.to_numeric(df[c]).fillna(0)
        q["rows"] += len(df)
        dates += list(df.date.unique())
        q["rows_n_gt_types"] += int((df.n > df[["n_gen", "n_kid", "n_teen", "n_eld", "n_dis"]].sum(axis=1)).sum())
        q["rows_in_dup_keys"] += int(df.duplicated(["date", "off_id", "on_id", "hh"], keep=False).sum())
        ss = df[(df.off_id.str.len() == 9) & (df.on_id.str.len() == 9) & df.on_id.str[:3].between("100", "124")]
        stop_rows.append(ss.groupby("on_id")[["n", "n_eld"]].sum().reset_index().assign(ym=ym, date=ss.date.iloc[0] if len(ss) else None))
        hour_rows.append(ss.groupby(["date", "hh"])[["n", "n_eld"]].sum().reset_index().assign(ym=ym))
    q["days"] = len(set(dates))
    q["date_min"], q["date_max"] = min(dates), max(dates)
    qual.append(q)
    print(q, flush=True)

st = pd.concat(stop_rows).groupby(["ym", "on_id"])[["n", "n_eld"]].sum().reset_index()
st["ratio"] = st.n_eld / st.n
st.to_csv(OUT / "s01_d24_stop_month.csv", index=False, encoding="utf-8-sig")
h = pd.concat(hour_rows)
d = pd.to_datetime(h.date)
h["daytype"] = ["주말" if w >= 5 else "평일" for w in d.dt.dayofweek]  # 8/15는 평일
h.groupby(["ym", "daytype", "hh"])[["n", "n_eld"]].sum().reset_index().to_csv(OUT / "s01_d24_hour.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(qual).to_csv(OUT / "s01_d24_quality.csv", index=False, encoding="utf-8-sig")

# 업로드 + 대조 + 로컬 사본 삭제
for ym in ["202407", "202408", "202507"]:
    zp = SCR / f"d24dl/kscc_dx_trnsf_path_sum_{ym}.zip"
    subprocess.run(["rclone", "copy", str(zp), "googledrive:sdot-analysis/data1/D24_stop_usertype_transfer/"], check=True)
    r = subprocess.run(["rclone", "check", str(zp.parent), "googledrive:sdot-analysis/data1/D24_stop_usertype_transfer/", "--include", zp.name, "--one-way"],
                       capture_output=True, text=True)
    print(ym, "check rc", r.returncode, r.stderr.strip().splitlines()[-1:], flush=True)
    if r.returncode == 0:
        zp.unlink()
