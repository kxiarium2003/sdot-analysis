"""s02_d25_long.py - D25 정류장·역사별 출발지/도착지 월 zip을 long parquet으로. 버스 승차(9자리) 행만. 인자: 월 목록(콤마).

출력(스크래치): d25long/YYYYMMDD.parquet (date, hour, board_id, alight_id, pax). 하차 결측은 '' 또는 '-' 그대로.
"""
import sys, os, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd, pyarrow as pa, pyarrow.parquet as pq

OUTD = SCRATCH / "d25long"; OUTD.mkdir(parents=True, exist_ok=True)
HC = [f"승객_수_{h:02d}시" for h in range(24)]
BID, AID = "승차_정류장/역사_ID", "하차_정류장/역사_ID"
for ym in sys.argv[1].split(","):
    z = zipfile.ZipFile(d25_zip(ym))
    for i in sorted(z.infolist(), key=lambda x: x.filename):
        if i.file_size < 10000:
            print("skip header-only", i.filename); continue
        with z.open(i) as f:
            d = pd.read_csv(f, encoding="cp949", dtype={BID: str, AID: str, "기준_날짜": str}, usecols=["기준_날짜", BID, AID] + HC)
        date = d["기준_날짜"].iloc[0]
        d = d[d[BID].str.len() == 9]
        a = np.nan_to_num(d[HC].to_numpy(dtype="float32"))
        ri, hi = np.nonzero(a)
        bid = d[BID].to_numpy(dtype=object); aid = d[AID].fillna("").to_numpy(dtype=object)
        t = pa.table({"date": pa.array(np.repeat(date, len(ri))), "hour": pa.array(hi.astype("int8")), "board_id": pa.array(bid[ri]), "alight_id": pa.array(aid[ri]), "pax": pa.array(a[ri, hi])})
        pq.write_table(t, OUTD / f"{date}.parquet", compression="zstd")
    print(ym, "done", flush=True)
