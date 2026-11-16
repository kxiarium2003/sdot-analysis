"""s01 - D24(2025-08) 일별 CSV와 D25(2025-08) 일별 CSV를 스크래치 parquet로 변환(읽기 전용).

D24: 원본 행 그대로(숫자 열 정수화) -> SCRATCH/d24/YYYYMMDD.parquet
D25: 승차ID x 시간대 합계만 -> SCRATCH/d25_board/YYYYMMDD.parquet (원 행은 저장하지 않음)
사용: python3 -I s01_d24_d25_to_parquet.py <SCRATCH>
"""
import sys, zipfile, io
from pathlib import Path
import pandas as pd, duckdb

ROOT = Path(__file__).resolve().parents[2]
SCR = Path(sys.argv[1])
(SCR / "d24").mkdir(parents=True, exist_ok=True)
(SCR / "d25_board").mkdir(parents=True, exist_ok=True)

D24 = ROOT / "data/raw/D24_stop_usertype_transfer/kscc_dx_trnsf_path_sum_202508.zip"
D25 = ROOT / "data/raw/D25_stop_mode_od/kscc_dx_ra_od_202508.zip"

con = duckdb.connect()
z = zipfile.ZipFile(D24)
for i in sorted(z.infolist(), key=lambda x: x.filename):
    day = i.filename[-12:-4]
    out = SCR / "d24" / f"{day}.parquet"
    if out.exists():
        continue
    df = pd.read_csv(io.BytesIO(z.read(i)), encoding="cp949", dtype=str)
    df.columns = ["date", "off_id", "on_id", "hh", "n", "n_gen", "n_kid", "n_teen", "n_eld", "n_dis",
                  "t", "t_gen", "t_kid", "t_teen", "t_eld", "t_dis"]
    for c in df.columns[4:]:
        df[c] = pd.to_numeric(df[c]).astype("float64")
    df["rowno"] = range(len(df))
    df.to_parquet(out, index=False)
    print("d24", day, len(df), flush=True)

z = zipfile.ZipFile(D25)
for i in sorted(z.infolist(), key=lambda x: x.filename):
    day = i.filename[-12:-4]
    out = SCR / "d25_board" / f"{day}.parquet"
    if out.exists():
        continue
    df = pd.read_csv(io.BytesIO(z.read(i)), encoding="cp949", dtype=str)
    on = df.columns[1]
    hcols = [c for c in df.columns if c.startswith("승객_수_") and c.endswith("시")]
    long = df[[on] + hcols].melt(id_vars=on, var_name="h", value_name="v")
    long["v"] = pd.to_numeric(long["v"]).fillna(0)
    long["hh"] = long["h"].str[-3:-1]
    g = long.groupby([on, "hh"], as_index=False)["v"].sum().rename(columns={on: "on_id"})
    g["date"] = day
    g.to_parquet(out, index=False)
    print("d25", day, len(df), int(g.v.sum()), flush=True)
