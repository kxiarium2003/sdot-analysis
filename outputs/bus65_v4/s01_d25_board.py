"""s01 - D25 서울시 정류장/역사별 수단 출발지/도착지(OA-21222) 한 달 -> 정류장(9자리) x 날짜 x 시간 승차.

2025-08은 로컬 zip, 나머지는 Drive data1/D25_stop_mode_od/ 에서 스크래치로 받아 변환 후 zip을 지운다.
출력: SCRATCH/d25/YYYYMM/YYYYMMDD.parquet (on_id, h00..h23)
사용: python3 -I s01_d25_board.py <SCRATCH> <YYYYMM>
"""
import sys, io, zipfile, subprocess
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCR, YM = Path(sys.argv[1]), sys.argv[2]
OUTD = SCR / "d25" / YM
OUTD.mkdir(parents=True, exist_ok=True)
if YM == "202508":
    zp = ROOT / "data/raw/D25_stop_mode_od/kscc_dx_ra_od_202508.zip"
else:
    dl = SCR / "dl"
    dl.mkdir(exist_ok=True)
    zp = dl / f"kscc_dx_ra_od_{YM}.zip"
    if not zp.exists():
        subprocess.run(["rclone", "copy", f"googledrive:sdot-analysis/data1/D25_stop_mode_od/kscc_dx_ra_od_{YM}.zip", str(dl)], check=True)
z = zipfile.ZipFile(zp)
log = []
for i in sorted(z.infolist(), key=lambda x: x.filename):
    day = i.filename[-12:-4]
    out = OUTD / f"{day}.parquet"
    if i.file_size < 2000:
        log.append((day, "header_only", i.file_size, 0, 0))
        continue
    if out.exists():
        continue
    df = pd.read_csv(io.BytesIO(z.read(i)), encoding="cp949", dtype=str)
    on = df.columns[1]
    hc = [c for c in df.columns if c.startswith("승객_수_") and c.endswith("시")]
    df = df[df[on].str.len() == 9]
    w = df[[on] + hc].copy()
    for c in hc:
        w[c] = pd.to_numeric(w[c]).fillna(0)
    g = w.groupby(on)[hc].sum().reset_index()
    g.columns = ["on_id"] + [f"h{c[-3:-1]}" for c in hc]
    g.to_parquet(out, index=False)
    log.append((day, "ok", i.file_size, len(g), float(g.iloc[:, 1:].to_numpy().sum())))
    print(YM, day, len(g), flush=True)
pd.DataFrame(log, columns=["date", "status", "bytes", "stops", "board"]).to_csv(OUTD / "_log.csv", index=False)
if YM != "202508":
    zp.unlink()
print("done", YM, flush=True)
