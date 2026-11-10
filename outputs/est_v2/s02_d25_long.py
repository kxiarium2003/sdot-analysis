"""s02_d25_long.py - D25 월 zip의 일별 CSV를 (날짜, 시, 승차ID, 하차ID, 인원) long parquet으로 변환.

인원이 0인 칸은 뺀다. 하차 ID 결측(빈칸, '-')은 값 그대로 둔다('' 또는 '-').
출력(스크래치): d25long/YYYYMMDD.parquet, 요약 s02_d25_long_days.csv
"""
import sys, os, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd, pyarrow as pa, pyarrow.parquet as pq
from multiprocessing import Pool

OUTD = SCRATCH / "d25long"; OUTD.mkdir(parents=True, exist_ok=True)
HC = [f"승객_수_{h:02d}시" for h in range(24)]
BID, AID = "승차_정류장/역사_ID", "하차_정류장/역사_ID"


def do_month(ym):
    z = zipfile.ZipFile(d25_zip(ym))
    rows = []
    for i in sorted(z.infolist(), key=lambda x: x.filename):
        if i.file_size < 10000:  # 헤더만 있는 파일(2025-07-01·02)
            rows.append(dict(ym=ym, file=i.filename, rows=0, long_rows=0, pax=0.0)); continue
        with z.open(i) as f:
            d = pd.read_csv(f, encoding="cp949", dtype={BID: str, AID: str, "기준_날짜": str}, usecols=["기준_날짜", BID, AID] + HC)
        date = d["기준_날짜"].iloc[0]
        d[AID] = d[AID].fillna("")
        a = np.nan_to_num(d[HC].to_numpy(dtype="float32"))
        ri, hi = np.nonzero(a)
        t = pa.table({"date": pa.array(np.repeat(date, len(ri))), "hour": pa.array(hi.astype("int8")),
                      "board_id": pa.array(d[BID].to_numpy(dtype=object)[ri]), "alight_id": pa.array(d[AID].to_numpy(dtype=object)[ri]),
                      "pax": pa.array(a[ri, hi])})
        pq.write_table(t, OUTD / f"{date}.parquet", compression="zstd")
        rows.append(dict(ym=ym, file=i.filename, rows=len(d), long_rows=len(ri), pax=float(a.sum())))
        print(date, len(d), len(ri), flush=True)
    return rows


if __name__ == "__main__":
    with Pool(3) as p:
        res = p.map(do_month, MONTHS)
    pd.DataFrame([r for x in res for r in x]).to_csv(OUT / "s02_d25_long_days.csv", index=False, encoding="utf-8-sig")
