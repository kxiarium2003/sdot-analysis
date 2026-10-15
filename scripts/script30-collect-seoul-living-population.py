"""
script30-collect-seoul-living-population.py - 서울 생활인구(집계구 단위) 월별 수집 (하이브리드: 로컬 zip 우선, 없으면 자동 다운로드)

세 데이터셋(내국인 OA-14979 / 장기체류외국인 OA-14978 / 단기체류외국인 OA-14980),
2024-09 ~ 2026-07(23개월) 대상. datafile.seoul.go.kr 자동 다운로드가 너무
불안정(패킷 손실 심함)해서, 일부 달은 사용자가 웹사이트에서 직접 받아 아래
경로에 넣어두는 방식도 병행함:
  data/raw/D5_living_pop/{dataset}/{ZIP_PREFIX}_{YYYYMM}.zip
  (예: LOCAL_PEOPLE_202501.zip, LONG_FOREIGNER_202501.zip, TEMP_FOREIGNER_202501.zip)

각 (데이터셋, 월)에 대해 (30초 간격 폴링 루프 안에서):
0. 위 경로에 zip이 이미 있으면 다운로드를 건너뛰고 바로 1번으로.
   없으면 이 스크립트가 직접 다운로드한다:
   POST https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false
   body: infId={데이터셋ID}, seq={YYMM 4자리}, infSeq=1
1. zip 안의 일별 CSV를 압축 해제 없이 zipfile로 하나씩 읽어(파일 하나가
   ~130MB 텍스트라 한 달치를 한 번에 DataFrame으로 합치면 메모리 위험 -
   하루 단위로 즉시 parquet에 스트리밍 저장) 월별 parquet 생성
   -> data/interim/seoul_living_population/{dataset}/{YYYYMM}.parquet
2. rclone copy로 원본 zip을 Google Drive(googledrive:sdot-analysis/data1/
   D5_living_pop/{dataset}/)에 업로드
3. 업로드 성공을 로컬-원격 파일 크기 대조로 검증한 뒤에만 로컬 zip 삭제
   (rclone copy가 exit 0을 반환해도 무조건 믿지 않고 재확인 - 네트워크
   중간 실패나 부분 업로드를 놓치지 않기 위함)
4. parquet도 동일한 방식으로 Google Drive(googledrive:sdot-analysis/
   interim/seoul_living_population/{dataset}/)에 업로드 후 크기 대조로
   검증한 뒤에만 로컬 parquet 삭제(로컬 디스크 여유가 크지 않아 zip과
   마찬가지로 즉시 정리)
5. .done 마커(행 수 기록) 후 다음 대상으로. 모든 (데이터셋, 월) 조합이
   .done이면 종료. 자동 다운로드가 최종 실패해도 스크립트를 중단하지 않고
   해당 달만 건너뛴 뒤 다음 폴링 주기에 재시도(수동으로 zip을 넣어줄 시간을 줌).
   zip 업로드는 끝났지만 parquet 업로드가 안 된 채로 중단된 경우, 재실행 시
   존재하는 로컬 zip/parquet을 감지해서 다시 다운로드/변환하지 않고 남은
   단계(parquet 업로드)부터 이어서 진행한다.

값 마스킹 처리: 이 데이터는 소수 인원 보호를 위해 특정 인구수 값을 "*"로
마스킹한다(실측 확인: 단기체류외국인 파일에서 발견). "결측"과 "마스킹"은
다른 의미이므로 섞지 않는다 - 인구수 컬럼마다 원래 값(파싱 가능하면 float,
마스킹이면 NaN)과 별도로 {컬럼}_suppressed 불리언 플래그를 남긴다
(S-DoT 파이프라인의 flag_ 컬럼 관행과 동일한 "flag, don't drop" 원칙).

디스크 전략: zip은 처리(변환+업로드+검증) 즉시 삭제된다(직접 다운로드했든
사용자가 넣어줬든 동일).
"""
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / 'data' / 'raw' / 'D5_living_pop'
INTERIM_DIR = PROJECT_ROOT / 'data' / 'interim' / 'seoul_living_population'
RCLONE_REMOTE = 'googledrive:sdot-analysis/data1/D5_living_pop'
RCLONE_INTERIM_REMOTE = 'googledrive:sdot-analysis/interim/seoul_living_population'

# 기본 대상(최초 수집 범위). CLI 인자로 덮어쓸 수 있다:
#   --start YYYYMM --end YYYYMM --datasets long_term_foreigner,short_term_foreigner
# 인자를 주지 않으면 아래 기본값 그대로 동작한다(기존 동작 유지).
START_YM = (2024, 9)
END_YM = (2026, 7)
TARGET_DATASETS = None  # None이면 DATASETS 전체
POLL_INTERVAL_SEC = 30

ID_COLS = ['기준일ID', '행정동코드', '집계구코드']
HOUR_COL = '시간대구분'

DATASETS = {
    'native': {'inf_id': 'OA-14979', 'zip_prefix': 'LOCAL_PEOPLE'},
    'long_term_foreigner': {'inf_id': 'OA-14978', 'zip_prefix': 'LONG_FOREIGNER'},
    'short_term_foreigner': {'inf_id': 'OA-14980', 'zip_prefix': 'TEMP_FOREIGNER'},
}


def month_range(start, end):
    y, m = start
    while (y, m) <= end:
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def download_month_zip(inf_id: str, seq: str, dest_path: Path, max_retries: int = 3) -> None:
    url = 'https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false'
    data = {'infId': inf_id, 'seq': seq, 'infSeq': '1'}
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            with requests.post(url, data=data, stream=True, timeout=300,
                                headers={'User-Agent': 'Mozilla/5.0'}) as r:
                r.raise_for_status()
                content_type = r.headers.get('Content-Type', '')
                if 'text/html' in content_type:
                    raise RuntimeError(f"HTML 응답(에러 페이지로 추정), Content-Type={content_type}")
                tmp_path = dest_path.with_suffix('.part')
                with open(tmp_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
                tmp_path.rename(dest_path)
            if not zipfile.is_zipfile(dest_path):
                raise RuntimeError("다운로드된 파일이 유효한 zip이 아님")
            return
        except Exception as e:
            last_err = e
            print(f"    ! 다운로드 시도 {attempt}/{max_retries} 실패: {e}")
            dest_path.unlink(missing_ok=True)
            time.sleep(5)
    raise RuntimeError(f"다운로드 최종 실패 (infId={inf_id}, seq={seq}): {last_err}")


def convert_day_csv(raw: pd.DataFrame) -> pd.DataFrame:
    out = {}
    for col in ID_COLS:
        if col in raw.columns:
            out[col] = raw[col].astype(str).str.strip()
    if HOUR_COL in raw.columns:
        out[HOUR_COL] = pd.to_numeric(raw[HOUR_COL], errors='coerce').astype('Int64')

    count_cols = [c for c in raw.columns if c not in ID_COLS and c != HOUR_COL]
    for col in count_cols:
        s = raw[col].astype(str).str.strip()
        suppressed = s == '*'
        numeric = pd.to_numeric(s.where(~suppressed), errors='coerce').astype('float64')
        out[col] = numeric
        out[f'{col}_suppressed'] = suppressed

    return pd.DataFrame(out)


def read_and_write_month(zip_path: Path, out_parquet: Path) -> int:
    total_rows = 0
    writer = None
    with zipfile.ZipFile(zip_path) as z:
        names = sorted(n for n in z.namelist() if n.lower().endswith('.csv'))
        if not names:
            raise RuntimeError("zip 안에 csv 파일 없음")
        for name in names:
            raw = None
            for enc in ('utf-8', 'cp949'):
                try:
                    with z.open(name) as f:
                        raw = pd.read_csv(f, encoding=enc, dtype=str, index_col=False)
                    break
                except UnicodeDecodeError:
                    continue
            if raw is None:
                raise RuntimeError(f"{name}: utf-8/cp949 둘 다 디코딩 실패")
            raw.columns = [str(c).replace('"', '').lstrip('?').strip() for c in raw.columns]
            if len(raw) == 0:
                print(f"    {name}: 데이터 0행(헤더만 존재), 건너뜀", flush=True)
                continue

            df = convert_day_csv(raw)
            table = pa.Table.from_pandas(df, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(out_parquet, table.schema, compression='zstd')
            writer.write_table(table)
            total_rows += len(df)
            del raw, df, table
    if writer is not None:
        writer.close()
    return total_rows


def upload_and_verify(local_path: Path, remote_dir: str) -> bool:
    import subprocess
    r = subprocess.run(['rclone', 'copy', str(local_path), remote_dir,
                         '--tpslimit', '2', '--drive-pacer-min-sleep', '200ms'],
                        capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        print(f"    ! rclone copy 실패: {r.stderr}")
        return False

    remote_path = f"{remote_dir.rstrip('/')}/{local_path.name}"
    r2 = subprocess.run(['rclone', 'lsf', '--format', 's', remote_path],
                         capture_output=True, text=True, timeout=120)
    if r2.returncode != 0 or not r2.stdout.strip():
        print(f"    ! 업로드 검증 실패(원격 파일 확인 불가): {r2.stderr}")
        return False

    remote_size = int(r2.stdout.strip().splitlines()[0])
    local_size = local_path.stat().st_size
    if remote_size != local_size:
        print(f"    ! 업로드 검증 실패(크기 불일치): local={local_size} remote={remote_size}")
        return False
    return True


def all_targets():
    """(dataset_name, ym, raw_dir, interim_dir, remote_dir, interim_remote_dir, zip_prefix, inf_id, seq) 전체 목록."""
    targets = []
    selected = TARGET_DATASETS or list(DATASETS)
    for dataset_name in selected:
        cfg = DATASETS[dataset_name]
        raw_dir = RAW_DIR / dataset_name
        interim_dir = INTERIM_DIR / dataset_name
        raw_dir.mkdir(parents=True, exist_ok=True)
        interim_dir.mkdir(parents=True, exist_ok=True)
        remote_dir = f"{RCLONE_REMOTE}/{dataset_name}"
        interim_remote_dir = f"{RCLONE_INTERIM_REMOTE}/{dataset_name}"
        for y, m in month_range(START_YM, END_YM):
            ym = f"{y:04d}{m:02d}"
            seq = f"{y % 100:02d}{m:02d}"
            targets.append((dataset_name, ym, raw_dir, interim_dir, remote_dir, interim_remote_dir, cfg['zip_prefix'], cfg['inf_id'], seq))
    return targets


def is_valid_parquet(path: Path) -> bool:
    try:
        pq.ParquetFile(path)
        return True
    except Exception:
        return False


def process_one(dataset_name, ym, raw_dir, interim_dir, remote_dir, interim_remote_dir, zip_prefix, inf_id, seq) -> bool:
    zip_path = raw_dir / f"{zip_prefix}_{ym}.zip"
    out_parquet = interim_dir / f"{ym}.parquet"
    done_marker = interim_dir / f"{ym}.done"

    if out_parquet.exists() and not is_valid_parquet(out_parquet):
        print(f"  [{dataset_name}] {ym}: 기존 parquet이 손상됨(footer 없음), 삭제 후 재변환", flush=True)
        out_parquet.unlink()

    if out_parquet.exists():
        print(f"  [{dataset_name}] {ym}: parquet 이미 존재, 변환 건너뜀", flush=True)
    else:
        if zip_path.exists():
            print(f"  [{dataset_name}] {ym}: 로컬 zip 감지 ({zip_path.stat().st_size / 1024 / 1024:.1f}MB), 다운로드 건너뜀", flush=True)
        else:
            print(f"  [{dataset_name}] {ym}: 로컬 zip 없음, 다운로드 중 (seq={seq})...", flush=True)
            try:
                download_month_zip(inf_id, seq, zip_path)
            except Exception as e:
                print(f"  [{dataset_name}] {ym}: 다운로드 실패, 다음 폴링에서 재시도 - {e}")
                return False
            print(f"  [{dataset_name}] {ym}: 다운로드 완료 ({zip_path.stat().st_size / 1024 / 1024:.1f}MB)", flush=True)

        print(f"  [{dataset_name}] {ym}: parquet 변환 중...", flush=True)
        try:
            read_and_write_month(zip_path, out_parquet)
        except Exception as e:
            print(f"  [{dataset_name}] {ym}: parquet 변환 실패, 건너뜀 - {e}")
            out_parquet.unlink(missing_ok=True)
            return False
        print(f"  [{dataset_name}] {ym}: parquet 저장 완료", flush=True)

    if zip_path.exists():
        print(f"  [{dataset_name}] {ym}: zip Google Drive 업로드 중...", flush=True)
        if not upload_and_verify(zip_path, remote_dir):
            print(f"  [{dataset_name}] {ym}: zip 업로드 검증 실패, 로컬 zip 보존하고 다음으로 (다음 폴링에서 재시도)")
            return False
        print(f"  [{dataset_name}] {ym}: zip 업로드 검증 완료, 로컬 zip 삭제", flush=True)
        zip_path.unlink()

    print(f"  [{dataset_name}] {ym}: parquet Google Drive 업로드 중...", flush=True)
    if not upload_and_verify(out_parquet, interim_remote_dir):
        print(f"  [{dataset_name}] {ym}: parquet 업로드 검증 실패, 로컬 parquet 보존하고 다음으로 (다음 폴링에서 재시도)")
        return False

    n_rows = pq.ParquetFile(out_parquet).metadata.num_rows
    print(f"  [{dataset_name}] {ym}: parquet 업로드 검증 완료, 로컬 parquet 삭제 ({n_rows:,}행)", flush=True)
    out_parquet.unlink()

    done_marker.write_text(f"{n_rows}\n")
    return True


# Drive 업로드 확정(finalize) 단계에서 반복적으로 멈추는 항목은, 다른 모든
# 대상이 끝날 때까지 뒤로 미룬다. 다른 게 다 끝난 뒤 마지막으로 한 번 더
# 시도하고, 그마저 실패하면 .giveup 마커를 남기고 더는 재시도하지 않는다.
DEFER_UNTIL_LAST = {('long_term_foreigner', '202409')}


def is_resolved(interim_dir: Path, ym: str) -> bool:
    return interim_dir.joinpath(f"{ym}.done").exists() or interim_dir.joinpath(f"{ym}.giveup").exists()


def parse_args():
    """--start/--end/--datasets 로 대상 범위를 좁힐 수 있게 한다(미지정 시 기본값 유지)."""
    global START_YM, END_YM, TARGET_DATASETS
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == '--start':
            START_YM = (int(argv[i + 1][:4]), int(argv[i + 1][4:6]))
        elif a == '--end':
            END_YM = (int(argv[i + 1][:4]), int(argv[i + 1][4:6]))
        elif a == '--datasets':
            names = [s.strip() for s in argv[i + 1].split(',') if s.strip()]
            unknown = [n for n in names if n not in DATASETS]
            if unknown:
                raise SystemExit(f"알 수 없는 데이터셋: {unknown} (가능: {list(DATASETS)})")
            TARGET_DATASETS = names


def main():
    parse_args()
    selected = TARGET_DATASETS or list(DATASETS)
    targets = all_targets()
    n_months = len(targets) // len(selected) if selected else 0
    print(f"하이브리드 모드 시작 - 대상 {len(targets)}건 "
          f"(데이터셋 {len(selected)}종 x 월 {n_months}개, "
          f"{START_YM[0]:04d}-{START_YM[1]:02d}~{END_YM[0]:04d}-{END_YM[1]:02d})")
    print(f"로컬에 zip이 있으면 그걸 쓰고, 없으면 자동 다운로드합니다. {POLL_INTERVAL_SEC}초 간격 폴링:")
    for dataset_name in selected:
        print(f"  data/raw/D5_living_pop/{dataset_name}/")

    while True:
        pending = [t for t in targets if not is_resolved(t[3], t[1])]
        if not pending:
            print("\n전체 완료 - 모든 (데이터셋, 월) 조합이 .done 또는 .giveup으로 해소됨")
            break

        deferred = [t for t in pending if (t[0], t[1]) in DEFER_UNTIL_LAST]
        normal = [t for t in pending if (t[0], t[1]) not in DEFER_UNTIL_LAST]
        final_attempt = not normal
        remaining = normal if normal else deferred
        if final_attempt and deferred:
            print(f"\n나머지 전부 완료 - 보류했던 항목 마지막 시도: {[(t[0], t[1]) for t in deferred]}", flush=True)

        for dataset_name, ym, raw_dir, interim_dir, remote_dir, interim_remote_dir, zip_prefix, inf_id, seq in remaining:
            ok = False
            try:
                ok = process_one(dataset_name, ym, raw_dir, interim_dir, remote_dir, interim_remote_dir, zip_prefix, inf_id, seq)
            except Exception as e:
                print(f"  [{dataset_name}] {ym}: 예상치 못한 오류, 건너뛰고 다음 폴링에서 재시도 - {e}", flush=True)
            if not ok and final_attempt and (dataset_name, ym) in DEFER_UNTIL_LAST:
                interim_dir.joinpath(f"{ym}.giveup").write_text("마지막 시도도 실패, 포기\n")
                print(f"  [{dataset_name}] {ym}: 마지막 시도도 실패 - 포기하고 제외 처리", flush=True)

        time.sleep(POLL_INTERVAL_SEC)


if __name__ == '__main__':
    main()
