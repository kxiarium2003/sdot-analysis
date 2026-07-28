"""
SDOT File Inventory Generator (generate-inventory.py) - V3 (Final)

주요 개선 사항
1. 인코딩 우선순위 변경 (cp949 우선)
2. 연도 추출 로직 강화 (파일명 대신 상위 디렉토리명 우선 탐색)
3. 정렬 기준 변경 (year, start_date 기반 정렬)
4. 동적 스키마 버전 생성 (hash가 다르면 v2024_A, v2024_B 형태로 자동 증가)
5. date_column 메타데이터 추가 (merge-yearly.py의 편의성 극대화)
6. Pandas 2.x 표준에 맞춘 안전한 datetime 파싱 (format='mixed')
7. 처리 결과(Processed, Skipped, Failed) 요약 출력
"""

import argparse
import logging
import hashlib
import sys
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd
import openpyxl
from openpyxl.utils.dataframe import dataframe_to_rows

# 한국 공공데이터 특성을 반영한 인코딩 우선순위
SUPPORTED_ENCODINGS = ["cp949", "utf-8-sig", "utf-8", "euc-kr"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SDOT CSV 파일들의 최적화된 인벤토리를 생성합니다."
    )
    parser.add_argument(
        "--raw-dir",
        type=str,
        default="data/raw",
        help="Raw CSV 파일들이 위치한 디렉토리 경로 (기본값: data/raw)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="metadata/sdot-schema-mapping.xlsx",
        help="메타데이터를 저장할 엑셀 파일 경로 (기본값: metadata/sdot-schema-mapping.xlsx)",
    )
    return parser.parse_args()


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("generate-inventory-v3")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    return logger


def extract_year(file_path: Path) -> int:
    """부모 디렉토리명에서 연도를 먼저 찾고, 없으면 파일명에서 추출합니다."""
    # 1. 부모 디렉토리에서 탐색 (예: year_2024, 2024년_데이터)
    match_dir = re.search(r"(20\d{2})", file_path.parent.name)
    if match_dir:
        return int(match_dir.group(1))

    # 2. 파일명에서 탐색 (예: PUBDATA_202401.csv)
    match_file = re.search(r"(20\d{2})", file_path.name)
    if match_file:
        return int(match_file.group(1))

    return 9999  # 연도를 찾을 수 없는 경우 최하단으로 밀어내기 위해


def inspect_csv_header(
    file_path: Path, logger: logging.Logger
) -> Tuple[str, List[str]]:
    for enc in SUPPORTED_ENCODINGS:
        try:
            df_head = pd.read_csv(file_path, encoding=enc, nrows=100, dtype=str)
            return enc, list(df_head.columns)
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue

    raise ValueError(f"호환되는 인코딩을 찾을 수 없거나 파싱 에러가 발생했습니다.")


def get_schema_info(
    columns: List[str], year: int, schema_tracker: Dict[str, Dict[str, str]]
) -> Tuple[str, Optional[str], str]:
    """
    해시를 기반으로 동적으로 스키마 버전을 부여합니다 (예: v2024_A, v2024_B).
    """
    col_str = ",".join(columns)
    column_hash = hashlib.md5(col_str.encode("utf-8")).hexdigest()[:8]

    # 이미 분석된 해시라면 기존 정보 반환
    if column_hash in schema_tracker:
        return (
            schema_tracker[column_hash]["version"],
            schema_tracker[column_hash]["date_col"],
            column_hash,
        )

    # 새로운 해시인 경우
    date_col = next(
        (col for col in ["측정시간", "전송시간", "등록일시"] if col in columns), None
    )

    # 해당 연도에 이미 부여된 스키마가 몇 개인지 확인하여 접미사(A, B, C...) 결정
    existing_for_year = sum(
        1 for info in schema_tracker.values() if info["version"].startswith(f"v{year}")
    )
    suffix = chr(65 + existing_for_year)  # 0 -> A, 1 -> B ...
    schema_version = f"v{year}_{suffix}"

    # 트래커에 저장
    schema_tracker[column_hash] = {"version": schema_version, "date_col": date_col}

    return schema_version, date_col, column_hash


def calculate_period_type(start_date: pd.Timestamp, end_date: pd.Timestamp) -> str:
    if pd.isna(start_date) or pd.isna(end_date):
        return "unknown"
    days = (end_date - start_date).days
    if days >= 300:
        return "yearly"
    elif days >= 25:
        return "monthly"
    elif days >= 6:
        return "weekly"
    else:
        return "daily"


def process_file(
    file_path: Path,
    raw_dir: Path,
    schema_tracker: Dict[str, Dict[str, str]],
    logger: logging.Logger,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """파일을 처리하고 상태(Processed, Skipped, Failed)와 메타데이터를 반환합니다."""
    try:
        year = extract_year(file_path)

        try:
            encoding, columns = inspect_csv_header(file_path, logger)
        except ValueError as ve:
            logger.warning(f"[{file_path.name}] 스킵됨: {str(ve)}")
            return "Skipped", None

        schema_version, date_col, column_hash = get_schema_info(
            columns, year, schema_tracker
        )

        row_count = 0
        start_date_str = None
        end_date_str = None
        period_type = "unknown"
        remarks = ""

        if date_col:
            df_dates = pd.read_csv(
                file_path, encoding=encoding, usecols=[date_col], dtype=str
            )
            row_count = len(df_dates)

            if row_count > 0:
                raw_dates = df_dates[date_col].dropna()
                parsed_dates = pd.to_datetime(raw_dates, errors="coerce")
                if parsed_dates.isna().mean() > 0.5:
                    parsed_dates = pd.to_datetime(
                        raw_dates, format="%Y%m%d%H%M", errors="coerce"
                    )
                valid_dates = parsed_dates.dropna()

                if not valid_dates.empty:
                    s_date = valid_dates.min()
                    e_date = valid_dates.max()
                    start_date_str = s_date.strftime("%Y-%m-%d %H:%M:%S")
                    end_date_str = e_date.strftime("%Y-%m-%d %H:%M:%S")
                    period_type = calculate_period_type(s_date, e_date)
                else:
                    remarks = "날짜 데이터 파싱 불가 (포맷 불일치)"
        else:
            with open(file_path, "r", encoding=encoding) as f:
                row_count = sum(1 for _ in f) - 1
            remarks = "알 수 없는 스키마 구조 (Date 컬럼 없음)"

        record = {
            "year": year,
            "relative_path": str(file_path.relative_to(raw_dir)),
            "file_name": file_path.name,
            "file_size_mb": round(file_path.stat().st_size / (1024 * 1024), 2),
            "encoding": encoding,
            "row_count": row_count,
            "col_count": len(columns),
            "column_hash": column_hash,
            "schema_version": schema_version,
            "date_column": date_col,  # 추가된 필드
            "period_type": period_type,
            "start_date": start_date_str,
            "end_date": end_date_str,
            "remarks": remarks,
        }
        return "Processed", record

    except Exception as e:
        logger.error(f"[{file_path.name}] 파일 처리 중 에러 발생 (Failed): {str(e)}")
        return "Failed", None


def build_inventory(
    raw_dir: Path, logger: logging.Logger
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    records = []
    status_counts = {"Processed": 0, "Skipped": 0, "Failed": 0}
    schema_tracker = {}  # {hash: {'version': 'v2020_A', 'date_col': '전송시간'}}

    csv_files = list(raw_dir.rglob("*.csv"))

    if not csv_files:
        logger.warning(f"[{raw_dir}] 경로에 CSV 파일이 존재하지 않습니다.")
        return pd.DataFrame(), status_counts

    for idx, file_path in enumerate(csv_files, 1):
        logger.info(f"Processing ({idx}/{len(csv_files)}): {file_path.name}")

        status, record = process_file(file_path, raw_dir, schema_tracker, logger)
        status_counts[status] += 1

        if record:
            records.append(record)

    df = pd.DataFrame(records)

    if not df.empty:
        # start_date 기준으로 정렬 (None 값이 있을 경우 맨 뒤로)
        df = df.sort_values(by=["year", "start_date"], na_position="last").reset_index(
            drop=True
        )
        df["file_order"] = df.groupby("year").cumcount() + 1

        cols_order = [
            "year",
            "file_order",
            "relative_path",
            "file_name",
            "file_size_mb",
            "encoding",
            "row_count",
            "col_count",
            "column_hash",
            "schema_version",
            "date_column",
            "period_type",
            "start_date",
            "end_date",
            "remarks",
        ]
        df = df[cols_order]

    return df, status_counts


def update_excel(
    df_inventory: pd.DataFrame, output_path: Path, logger: logging.Logger
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet_name = "FileInventory"

    if output_path.exists():
        logger.info(f"기존 엑셀 파일을 로드합니다: {output_path}")
        wb = openpyxl.load_workbook(output_path)
        if sheet_name in wb.sheetnames:
            del wb[sheet_name]
        ws = wb.create_sheet(sheet_name, index=0)
    else:
        logger.info("새로운 메타데이터 엑셀 파일을 생성합니다.")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name

    for r in dataframe_to_rows(df_inventory, index=False, header=True):
        ws.append(r)

    for cell in ws[1]:
        cell.font = openpyxl.styles.Font(bold=True)

    wb.save(output_path)
    logger.info(f"엑셀 파일 업데이트 완료: {output_path}")


def print_summary(
    df_inventory: pd.DataFrame, status_counts: Dict[str, int], logger: logging.Logger
) -> None:
    print("\n" + "=" * 50)
    print(" SDOT File Inventory Generation Summary (V3)")
    print("=" * 50)
    print(f"Processed : {status_counts['Processed']}")
    print(f"Failed    : {status_counts['Failed']}")
    print(f"Skipped   : {status_counts['Skipped']}")
    print("-" * 50)

    if not df_inventory.empty:
        total_rows = df_inventory["row_count"].sum()
        schema_counts = df_inventory["schema_version"].value_counts().to_dict()

        print(f"Total rows (records)  : {total_rows:,} rows")
        print("Files per Schema Version:")
        for schema, count in sorted(schema_counts.items()):
            print(f"  - {schema}: {count} files")
    print("=" * 50 + "\n")


def main() -> None:
    args = parse_args()
    logger = setup_logging()

    raw_dir = Path(args.raw_dir)
    output_path = Path(args.output)

    if not raw_dir.exists() or not raw_dir.is_dir():
        logger.error(f"원본 디렉토리를 찾을 수 없습니다: {raw_dir.resolve()}")
        sys.exit(1)

    logger.info(f"SDOT File Inventory (V3) 생성을 시작합니다. (Target: {raw_dir})")

    df_inventory, status_counts = build_inventory(raw_dir, logger)

    if not df_inventory.empty:
        update_excel(df_inventory, output_path, logger)

    print_summary(df_inventory, status_counts, logger)


if __name__ == "__main__":
    main()
