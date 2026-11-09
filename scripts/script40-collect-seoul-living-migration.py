"""
script40-collect-seoul-living-migration.py - 생활이동 raw zip을 월 단위로 받아 Google Drive에 보관하고 월별 parquet으로 변환

대상 (모두 서울 열린데이터광장, 로그인 없이 POST 다운로드):
- seoul_living_migration_admdong: 서울 생활이동 행정동 단위 (dataVisual/seoul/seoulLivingMigration.do)
    월 zip 1개. body: infId=DOWNLOAD, infSeq=2, seq=YYYYMM
    월×요일 합산, 7자리 통계청 행정동 코드. 모든 행이 서울 출발 또는 도착.
- oa22299_capital_migration_in: 수도권 생활이동 (연령별, 출발-도착지 기준)-내국인 (OA-22299)
    일 zip 1개. body: infId=OA-22299, infSeq=1, seq=YYMMDD
- oa22379_capital_migration_forn: 같은 데이터의 외국인 (OA-22379)
    일 zip 1개. body: infId=OA-22379, infSeq=1, seq=YYMMDD
    두 OA는 8자리 행안부 행정동 코드, 날짜 단위, 서울과 무관한 수도권 내부 이동도 포함.
서울 생활이동은 OA 두 데이터셋의 합·재집계가 아니다(2024-01 월요일 5일 합계 대조로 확인).

월 단위 처리(로컬에는 한 달치 이하만 남긴다):
1. 한 달치 세 데이터셋을 로컬 임시 폴더에 순차 다운로드(요청 간 REQUEST_GAP_SEC 대기).
   Drive에 같은 이름 파일이 이미 있으면 건너뛴다(재실행 시 이어받기).
2. rclone copy로 Drive에 업로드.
3. Drive의 파일 이름·크기를 로컬과 대조한다. 하나라도 다르면 로컬을 지우지 않고 중단한다.
4. 데이터셋별로 그 달 원본 전체를 월 parquet 1개(zstd)로 변환해 interim에 업로드·크기 대조.
   원본이 하루라도 누락된 달은 변환을 보류한다(불완전한 parquet이 '완료'로 남지 않게).
   Drive에 parquet이 이미 있으면 건너뛴다. 로컬에 원본 zip이 없으면(이전 실행에서 업로드 후 삭제)
   Drive에서 내려받아 변환한다.
5. 원본·parquet 대조가 모두 끝나면 그 달 로컬 임시본 전체 삭제.

parquet 변환 규칙(script30과 동일한 "flag, don't drop"):
- 모든 컬럼을 문자열로 읽고, 코드·시간대·날짜·국적 등은 문자열 그대로 둔다(0700 등 선행 0 보존).
- 수치 컬럼(NUMERIC_COLS)은 float64로 변환하고, '*'(3명 미만 마스킹)는 NaN + {컬럼}_suppressed=True.
  '*'·빈칸 외의 숫자가 아닌 값이 있으면 변환을 멈춘다.
- 컬럼 이름은 원본 그대로. CSV 인코딩은 utf-8 → cp949 순서로 시도.
중단 조건: 로컬 여유 공간 < MIN_FREE_GB, 또는 로그인·약관 동의·캡차로 보이는 HTML 응답.
어느 경우든 우회하지 않고 멈춘 뒤 collect_log.md에 이유를 남긴다.

Drive: googledrive:sdot-analysis/data1/
  D12_seoul_living_migration/생활이동_행정동_YYYYMM.zip
  D13_capital_region_living_migration/OA-22299_in/YYYY-MM/seoul_purpose_admdong4_in_YYYYMMDD.zip
  D13_capital_region_living_migration/OA-22379_forn/YYYY-MM/seoul_purpose_admdong4_forn_YYYYMMDD.zip
  collect_log.md는 D12·D13 두 폴더에 같은 내용으로 매 달 처리 후 갱신
parquet: googledrive:sdot-analysis/interim/seoul_living_migration/
  seoul_living_migration_admdong/YYYYMM.parquet, OA-22299_in/YYYYMM.parquet, OA-22379_forn/YYYYMM.parquet

사용법: python scripts/script40-collect-seoul-living-migration.py --start 2024-06 --end 2024-09
       [--skip seoul_living_migration_admdong:2024-01 ...]
  --skip: 받지 않을 (데이터셋:YYYY-MM). 서울 생활이동 2024-01은 ~/Downloads/생활이동_행정동_202401/에
          압축 해제본이 이미 있어 다시 받지 않는다(사용자 지시). 로그에 '건너뜀'으로 남긴다.
          LOCAL_SOURCES에 등록된 달은 원본 업로드 없이 그 로컬 CSV로 parquet만 만든다.
"""
import argparse
import calendar
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TMP_ROOT = PROJECT_ROOT / 'data' / 'tmp' / 'seoul_living_migration'
LOG_FILE = PROJECT_ROOT / 'data' / 'interim' / 'seoul_living_migration' / 'collect_log.md'
REMOTE_D12 = 'googledrive:sdot-analysis/data1/D12_seoul_living_migration'
REMOTE_D13 = 'googledrive:sdot-analysis/data1/D13_capital_region_living_migration'
LOG_REMOTES = [REMOTE_D12, REMOTE_D13]
REMOTE_PARQUET = 'googledrive:sdot-analysis/interim/seoul_living_migration'
# --skip으로 원본을 받지 않는 달 중, 사용자가 이미 받아둔 압축 해제본으로 parquet을 만들 수 있는 경우
LOCAL_SOURCES = {
    'seoul_living_migration_admdong:2024-01': Path.home() / 'Downloads' / '생활이동_행정동_202401',
}

DOWNLOAD_URL = 'https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false'
HEADERS = {'User-Agent': 'Mozilla/5.0'}
REQUEST_GAP_SEC = 3
MAX_RETRIES = 3
# 서울 생활이동 월 zip(~1GB)은 전송 중 끊기는 일이 잦고 서버가 Range(이어받기)를 지원하지 않아
# 처음부터 다시 받아야 하므로 재시도 횟수를 따로 늘린다.
MAX_RETRIES_MONTHLY = 8
RETRY_BACKOFF_SEC = [10, 30, 60, 60, 120, 120, 300, 300]
MIN_FREE_GB = 10
BLOCK_WORDS = ['로그인', 'login', '약관', '동의', 'captcha', '캡차', '자동등록방지']

DATASETS = {
    'seoul_living_migration_admdong': {'kind': 'monthly', 'inf_id': 'DOWNLOAD', 'inf_seq': '2',
                                       'retries': MAX_RETRIES_MONTHLY, 'remote': REMOTE_D12,
                                       'parquet': 'seoul_living_migration_admdong',
                                       'numeric': ['평균 이동 시간(분)', '이동인구(합)']},
    'oa22299_capital_migration_in': {'kind': 'daily', 'inf_id': 'OA-22299', 'inf_seq': '1',
                                     'name': 'seoul_purpose_admdong4_in_{ymd}.zip',
                                     'remote': f'{REMOTE_D13}/OA-22299_in', 'parquet': 'OA-22299_in',
                                     'numeric': ['move_dist', 'move_time', '0010_cnt', '2030_cnt', '4050_cnt',
                                                 '60plus_cnt', 'total_cnt']},
    'oa22379_capital_migration_forn': {'kind': 'daily', 'inf_id': 'OA-22379', 'inf_seq': '1',
                                       'name': 'seoul_purpose_admdong4_forn_{ymd}.zip',
                                       'remote': f'{REMOTE_D13}/OA-22379_forn', 'parquet': 'OA-22379_forn',
                                       'numeric': ['move_dist', 'move_time', 'short_forn_cnt', '0010_cnt',
                                                   '2030_cnt', '4050_cnt', '60plus_cnt', 'total_cnt']},
}


class StopCollection(Exception):
    """사람이 확인해야 하는 상황(로그인·캡차, 디스크 부족, 업로드 불일치)."""


def log(text):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(text + '\n')
    print(text, flush=True)


def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def free_gb():
    return shutil.disk_usage(PROJECT_ROOT).free / 1024 ** 3


def check_disk():
    gb = free_gb()
    if gb < MIN_FREE_GB:
        raise StopCollection(f"로컬 여유 공간 {gb:.1f}GB < {MIN_FREE_GB}GB")


def push_log():
    for remote in LOG_REMOTES:
        subprocess.run(['rclone', 'copyto', str(LOG_FILE), f"{remote}/collect_log.md"], capture_output=True)


def month_list(start, end):
    y, m = map(int, start.split('-'))
    ey, em = map(int, end.split('-'))
    while (y, m) <= (ey, em):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def remote_sizes(remote_dir):
    """Drive 폴더의 {파일명: 크기}. 폴더가 없으면 빈 dict."""
    r = subprocess.run(['rclone', 'lsf', '--format', 'ps', '--separator', '\t', '--files-only', remote_dir],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    out = {}
    for line in r.stdout.splitlines():
        name, size = line.rsplit('\t', 1)
        out[name] = int(size)
    return out


def download(inf_id, inf_seq, seq, dest_dir, fallback_name, max_retries=MAX_RETRIES):
    """한 파일을 받아 dest_dir에 저장하고 (경로, 재시도 횟수)를 반환. 실패 시 (None, 재시도 횟수)."""
    data = {'infId': inf_id, 'infSeq': inf_seq, 'seq': seq}
    for attempt in range(max_retries):
        check_disk()
        try:
            with requests.post(DOWNLOAD_URL, data=data, headers=HEADERS, stream=True, timeout=(30, 300)) as r:
                r.raise_for_status()
                ctype = r.headers.get('Content-Type', '')
                if 'html' in ctype:
                    body = r.text[:2000]
                    if any(w in body.lower() for w in BLOCK_WORDS):
                        raise StopCollection(f"{inf_id} seq={seq}: 로그인·약관·캡차로 보이는 응답")
                    raise RuntimeError(f"HTML 응답: {body[:120]!r}")
                name = fallback_name
                disp = r.headers.get('Content-Disposition', '')
                if 'filename="' in disp:
                    raw = disp.split('filename="', 1)[1].rstrip('"')
                    try:
                        name = raw.encode('latin-1').decode('utf-8')
                    except (UnicodeEncodeError, UnicodeDecodeError):
                        name = raw
                expected = int(r.headers.get('Content-Length', 0))
                path = dest_dir / name
                part = path.with_suffix('.part')
                with open(part, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
            if expected and part.stat().st_size != expected:
                raise RuntimeError(f"크기 불일치 {part.stat().st_size} != {expected}")
            if not zipfile.is_zipfile(part):
                raise RuntimeError("유효한 zip 아님")
            with zipfile.ZipFile(part) as z:
                bad = z.testzip()
                if bad:
                    raise RuntimeError(f"zip CRC 오류: {bad}")
            part.rename(path)
            return path, attempt
        except StopCollection:
            raise
        except Exception as e:
            log(f"  - 재시도 필요 {inf_id} seq={seq} (시도 {attempt + 1}/{max_retries}): {type(e).__name__}: {e}")
            for p in dest_dir.glob('*.part'):
                p.unlink()
            if attempt + 1 < max_retries:
                time.sleep(RETRY_BACKOFF_SEC[attempt])
    return None, max_retries


# Drive API 요청 한도 초과(rateLimitExceeded) 같은 일시적 실패는 기다렸다가 다시 시도한다.
UPLOAD_RETRY_WAIT_SEC = [300, 600, 1200]


def upload_and_verify(local_dir, remote_dir):
    for attempt in range(len(UPLOAD_RETRY_WAIT_SEC) + 1):
        r = subprocess.run(['rclone', 'copy', str(local_dir), remote_dir,
                            '--tpslimit', '2', '--drive-pacer-min-sleep', '200ms'],
                           capture_output=True, text=True)
        if r.returncode == 0:
            break
        if attempt == len(UPLOAD_RETRY_WAIT_SEC):
            raise StopCollection(f"rclone copy 실패: {local_dir.name} -> {remote_dir}: {r.stderr[-300:]}")
        wait = UPLOAD_RETRY_WAIT_SEC[attempt]
        reason = 'rateLimitExceeded' if 'rateLimitExceeded' in r.stderr else r.stderr.strip()[-120:]
        log(f"  - 업로드 재시도 대기 {wait}초 ({local_dir.name} -> {remote_dir}, 시도 {attempt + 1}): {reason}")
        time.sleep(wait)
    remote = remote_sizes(remote_dir)
    local = {p.name: p.stat().st_size for p in local_dir.iterdir() if p.is_file()}
    mismatch = {n: (s, remote.get(n)) for n, s in local.items() if remote.get(n) != s}
    if mismatch:
        raise StopCollection(f"Drive 대조 불일치 {remote_dir}: {mismatch}")
    return len(local), sum(local.values())


def read_csv_any(open_fn, label):
    for enc in ('utf-8', 'cp949'):
        try:
            with open_fn() as f:
                return pd.read_csv(f, encoding=enc, dtype=str, keep_default_na=False, index_col=False)
        except UnicodeDecodeError:
            continue
    raise StopCollection(f"{label}: utf-8/cp949 둘 다 디코딩 실패")


def convert_frame(raw, numeric_cols, label):
    raw.columns = [str(c).replace('"', '').lstrip('\ufeff').strip() for c in raw.columns]
    missing = [c for c in numeric_cols if c not in raw.columns]
    if missing:
        raise StopCollection(f"{label}: 수치 컬럼 없음 {missing} (컬럼: {list(raw.columns)})")
    out = {}
    for col in raw.columns:
        s = raw[col].str.strip()
        if col not in numeric_cols:
            out[col] = s
            continue
        suppressed = s == '*'
        numeric = pd.to_numeric(s.where(~suppressed & (s != '')), errors='coerce')
        bad = numeric.isna() & ~suppressed & (s != '')
        if bad.any():
            raise StopCollection(f"{label}: {col}에 숫자가 아닌 값 {s[bad].unique()[:5].tolist()}")
        out[col] = numeric.astype('float64')
        out[f'{col}_suppressed'] = suppressed
    return pd.DataFrame(out)


def iter_sources(paths):
    """(라벨, open 함수) 생성. zip이면 안의 csv 전부, csv면 그대로."""
    for path in paths:
        if path.suffix == '.zip':
            with zipfile.ZipFile(path) as z:
                for name in sorted(n for n in z.namelist() if n.lower().endswith('.csv')):
                    yield f"{path.name}/{name}", (lambda z=z, name=name: z.open(name))
        else:
            yield path.name, (lambda path=path: open(path, 'rb'))


def write_parquet(paths, numeric_cols, out_path):
    """원본 파일들을 하나의 parquet으로 스트리밍 저장하고 행 수를 반환."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer, schema, total = None, None, 0
    try:
        for label, open_fn in iter_sources(paths):
            df = convert_frame(read_csv_any(open_fn, label), numeric_cols, label)
            if len(df) == 0:
                continue
            table = pa.Table.from_pandas(df, preserve_index=False)
            if writer is None:
                schema = table.schema
                writer = pq.ParquetWriter(out_path, schema, compression='zstd')
            elif table.schema.names != schema.names:
                raise StopCollection(f"{label}: 컬럼 구성이 앞 파일과 다름 {table.schema.names}")
            writer.write_table(table.cast(schema))
            total += len(df)
            del df, table
    finally:
        if writer is not None:
            writer.close()
    if pq.ParquetFile(out_path).metadata.num_rows != total:
        raise StopCollection(f"{out_path.name}: parquet 행 수 불일치")
    return total


def make_parquet(ds, spec, ym, sources, month_tmp):
    """그 달 parquet을 만들어 interim에 올리고 대조. 로그 문자열 반환."""
    remote_dir = f"{REMOTE_PARQUET}/{spec['parquet']}"
    out_name = f"{ym.replace('-', '')}.parquet"
    if out_name in remote_sizes(remote_dir):
        return "parquet Drive에 이미 있음"
    check_disk()
    t0 = time.time()
    local_dir = month_tmp / 'parquet' / spec['parquet']
    rows = write_parquet(sources, spec['numeric'], local_dir / out_name)
    _, nbytes = upload_and_verify(local_dir, remote_dir)
    return f"parquet {rows:,}행 {nbytes / 1024 ** 2:.1f}MB 업로드·대조 ({time.time() - t0:.0f}초)"


def process_month(y, m, skip=()):
    ym = f"{y}-{m:02d}"
    month_tmp = TMP_ROOT / ym
    log(f"\n## {ym}\n\n- 시작: {now()} (로컬 여유 {free_gb():.1f}GB)")
    summary = {}
    for ds, spec in DATASETS.items():
        if f"{ds}:{ym}" in skip:
            src = LOCAL_SOURCES.get(f"{ds}:{ym}")
            note = '건너뜀 (--skip 지정)'
            if src is not None and src.is_dir():
                csvs = sorted(src.glob('*.csv'))
                note += f"; 로컬 {src} CSV {len(csvs)}개로 " + make_parquet(ds, spec, ym, csvs, month_tmp)
            log(f"- {ds}: 원본 {note}")
            summary[ds] = (0, 0, 0, ['원본 건너뜀'])
            continue
        if spec['kind'] == 'monthly':
            remote_dir = spec['remote']
            targets = [(f"{y}{m:02d}", f"생활이동_행정동_{y}{m:02d}.zip", ym)]
        else:
            remote_dir = f"{spec['remote']}/{ym}"
            days = [date(y, m, d) for d in range(1, calendar.monthrange(y, m)[1] + 1)]
            targets = [(d.strftime('%y%m%d'), spec['name'].format(ymd=d.strftime('%Y%m%d')), d.isoformat())
                       for d in days]
        on_drive = remote_sizes(remote_dir)
        local_dir = month_tmp / ds
        local_dir.mkdir(parents=True, exist_ok=True)
        for p in local_dir.glob('*.part'):  # 강제 종료로 남은 미완성 파일은 업로드 대상에서 제외
            p.unlink()
        ok, skipped, failed, retries = 0, 0, [], 0
        for seq, name, label in targets:
            if name in on_drive:
                skipped += 1
                continue
            if (local_dir / name).exists():
                ok += 1
                continue
            max_retries = spec.get('retries', MAX_RETRIES)
            path, n_retry = download(spec['inf_id'], spec['inf_seq'], seq, local_dir, name, max_retries)
            retries += n_retry if path else max_retries - 1
            if path is None:
                failed.append(label)
                log(f"  - 실패 {ds} {label}")
            else:
                ok += 1
            time.sleep(REQUEST_GAP_SEC)
        n_up, bytes_up = upload_and_verify(local_dir, remote_dir) if any(local_dir.iterdir()) else (0, 0)
        remote_now = remote_sizes(remote_dir)
        expected_names = [t[1] for t in targets]
        missing = [t[2] for t in targets if t[1] not in remote_now]
        summary[ds] = (len(expected_names), len(expected_names) - len(missing),
                       sum(remote_now.get(n, 0) for n in expected_names), missing)
        log(f"- {ds}: 대상 {len(targets)}, 신규 성공 {ok}, Drive에 이미 있음 {skipped}, 실패 {len(failed)}, "
            f"재시도 {retries}, 업로드·대조 {n_up}개 {bytes_up / 1024 ** 2:.1f}MB, "
            f"누락: {', '.join(missing) if missing else '없음'}")
        if missing:
            log(f"  - {ds}: 원본 누락이 있어 parquet 변환 보류")
            continue
        for name in expected_names:  # 이전 실행에서 업로드 후 지운 원본은 Drive에서 다시 받는다
            if not (local_dir / name).exists():
                check_disk()
                r = subprocess.run(['rclone', 'copyto', f"{remote_dir}/{name}", str(local_dir / name)],
                                   capture_output=True, text=True)
                if r.returncode != 0 or (local_dir / name).stat().st_size != remote_now[name]:
                    raise StopCollection(f"변환용 원본 내려받기 실패: {remote_dir}/{name}")
        log(f"  - {ds}: " + make_parquet(ds, spec, ym, [local_dir / n for n in expected_names], month_tmp))
    shutil.rmtree(month_tmp, ignore_errors=True)
    log(f"- 로컬 임시본(원본·parquet) 삭제 (Drive 대조 일치)\n- 종료: {now()}")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', required=True, help='YYYY-MM')
    ap.add_argument('--end', required=True, help='YYYY-MM')
    ap.add_argument('--skip', nargs='*', default=[], help='데이터셋:YYYY-MM')
    args = ap.parse_args()

    log(f"\n# 수집 실행 {now()} ({args.start} ~ {args.end})")
    results = {}
    try:
        for y, m in month_list(args.start, args.end):
            check_disk()
            results[f"{y}-{m:02d}"] = process_month(y, m, set(args.skip))
            push_log()
    except StopCollection as e:
        log(f"\n**중단: {e}** ({now()}). 로컬 임시 폴더 {TMP_ROOT}는 확인 전까지 그대로 둔다.")
        push_log()
        sys.exit(2)

    log("\n## 요약\n\n| 월 | 데이터셋 | 파일 수(Drive/대상) | 용량(MB) | 누락 |\n|---|---|---|---|---|")
    for ym, summ in results.items():
        for ds, (n_exp, n_ok, size, missing) in summ.items():
            log(f"| {ym} | {ds} | {n_ok}/{n_exp} | {size / 1024 ** 2:,.1f} | {', '.join(missing) or '-'} |")
    push_log()


if __name__ == '__main__':
    main()
