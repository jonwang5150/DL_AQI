#!/usr/bin/env python3
"""將 AQI CSV 匯入 PostgreSQL（Python 3.10+）。

安裝：python -m pip install "SQLAlchemy>=2.0,<2.1" "psycopg[binary]>=3,<4"
設定：修改 config.py 的資料庫連線網址與 Settings 內的匯入設定。
執行：直接在 IDE 執行本檔，或 python csv_to_postgres.py。
匯入：python csv_to_postgres.py aqi_hour_concat.csv
檢查：python csv_to_postgres.py aqi_hour_concat.csv --dry-run

資料庫須先建立；程式會建立 public.air_quality_hourly 資料表。
日期保留 CSV 的台灣當地時間，不進行時區轉換。
相同測站與日期會更新為最後讀到的資料（包含 NULL）。
所有輸入檔案在同一交易內匯入；任一筆失敗會全部回復。
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator


COLUMNS = ["測站", "日期", "AQI", "空氣品質指標", "O3", "PM2.5", "PM10", "CO", "SO2", "NO2"]
MISSING = {"", "-", "--", "NA", "N/A", "NULL", "NAN"}

MODEL_COLUMNS = ["station", "observed_at", "aqi", "air_quality_indicator", "o3", "pm25", "pm10", "co", "so2", "no2"]
PROJECT_DIR = Path(__file__).resolve().parent


def database_url_from_settings(settings):
    """使用 config.py 的連線網址，統一採用 psycopg 3 驅動。"""
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import ArgumentError

    try:
        url = make_url(settings.database_url)
        if url.drivername not in {
            "postgres", "postgresql", "postgresql+psycopg", "postgresql+psycopg2",
        }:
            raise ValueError
        if not url.host or not url.username or not url.database:
            raise ValueError
        return url.set(drivername="postgresql+psycopg")
    except (ArgumentError, TypeError, ValueError) as exc:
        raise ValueError(
            "config.py 的 database_url 必須是包含主機、帳號與資料庫名稱的 PostgreSQL 網址。"
        ) from exc


def build_parser(settings) -> argparse.ArgumentParser:
    default_csv = Path(settings.csv_path)
    if not default_csv.is_absolute():
        default_csv = PROJECT_DIR / default_csv
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_files", nargs="*", type=Path, default=[default_csv])
    parser.add_argument("--encoding", default=settings.csv_encoding, help="覆蓋 config.py 的 CSV 編碼")
    parser.add_argument("--batch-size", type=int, default=settings.batch_size, help="覆蓋 config.py 的每批筆數")
    parser.add_argument(
        "--dry-run", action=argparse.BooleanOptionalAction, default=settings.dry_run,
        help="只驗證 CSV；--no-dry-run 可覆蓋設定並執行匯入",
    )
    return parser


def parse_number(value: str, column: str) -> Decimal | None:
    if value.upper() in MISSING:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{column} 不是有效數字：{value!r}") from exc
    if not number.is_finite():
        raise ValueError(f"{column} 不是有限數字：{value!r}")
    return number


def read_rows(path: Path, encoding: str = "utf-8-sig") -> Iterator[dict]:
    with path.open("r", encoding=encoding, newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError(f"{path}：CSV 沒有標題列")
        reader.fieldnames = [name.strip() for name in reader.fieldnames]
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"{path}：CSV 欄位名稱重複")
        if set(reader.fieldnames) != set(COLUMNS):
            raise ValueError(f"{path}：CSV 欄位必須為 {', '.join(COLUMNS)}")
        for raw in reader:
            try:
                if None in raw or any(value is None for value in raw.values()):
                    raise ValueError("資料欄位數量與標題列不符")
                row = {key: value.strip() for key, value in raw.items()}
                if not row["測站"]:
                    raise ValueError("測站不可空白")
                observed_at = datetime.strptime(row["日期"], "%Y/%m/%d %H:%M")
                indicator = row["空氣品質指標"]
                values = (
                    row["測站"], observed_at, parse_number(row["AQI"], "AQI"),
                    None if indicator.upper() in MISSING else indicator,
                    *(parse_number(row[column], column) for column in COLUMNS[4:]),
                )
                yield dict(zip(MODEL_COLUMNS, values))
            except ValueError as exc:
                raise ValueError(f"{path} 第 {reader.line_num} 行：{exc}") from exc


def main() -> int:
    from config import settings

    parser = build_parser(settings)
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size 必須大於 0")

    if args.dry_run:
        total = 0
        for path in args.csv_files:
            count = sum(1 for _ in read_rows(path, args.encoding))
            total += count
            print(f"驗證通過：{path}，{count:,} 筆")
        print(f"共 {total:,} 筆輸入資料；未連線資料庫。")
        return 0

    try:
        from sqlalchemy import create_engine
        from sqlalchemy.exc import SQLAlchemyError
        from sqlalchemy.orm import Session

        from db_models import Base, upsert_batch
        import psycopg  # noqa: F401：確認 PostgreSQL 驅動已安裝
    except ImportError as exc:
        raise RuntimeError('請先安裝套件：python -m pip install "SQLAlchemy>=2.0,<2.1" "psycopg[binary]>=3,<4"') from exc

    # 由 config.py 統一管理連線設定。
    total = 0
    engine = None
    try:
        url = database_url_from_settings(settings)
        engine = create_engine(url, connect_args={"connect_timeout": 10}, hide_parameters=True)
        # 建表與所有批次共用一個交易；Session 綁定同一連線。
        with engine.begin() as connection:
            Base.metadata.create_all(connection)
            with Session(bind=connection) as session:
                batch = []
                for path in args.csv_files:
                    for row in read_rows(path, args.encoding):
                        batch.append(row)
                        total += 1
                        if len(batch) >= args.batch_size:
                            upsert_batch(session, batch)
                            batch.clear()
                if batch:
                    upsert_batch(session, batch)
    except SQLAlchemyError as exc:
        # 不輸出連線字串或資料庫錯誤細節，避免洩漏認證資訊。
        raise RuntimeError(
            f"PostgreSQL 匯入未完成（{type(exc).__name__}）。"
            "請檢查連線設定、資料庫是否存在，以及建表／寫入權限和資料表結構。"
        ) from exc
    finally:
        if engine is not None:
            engine.dispose()
    print(f"匯入完成：處理 {total:,} 筆，已提交至 public.air_quality_hourly。")
    print("重複的測站與日期已更新，因此處理筆數不一定等於新增筆數。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, LookupError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        raise SystemExit(1)
