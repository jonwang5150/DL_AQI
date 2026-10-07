#!/usr/bin/env python3
"""驗證 AQI 爬蟲資料並寫入 PostgreSQL（Python 3.10+）。

安裝：python -m pip install "SQLAlchemy>=2.0,<2.1" "psycopg[binary]>=3,<4"
設定：修改 config.py 的資料庫連線網址與每批寫入筆數。
本模組由 crawl_to_db.py 呼叫，不讀寫中間檔案。

資料庫須先建立；程式會建立 public.air_quality_hourly 資料表。
日期保留來源資料的台灣當地時間，不進行時區轉換。
相同測站與日期會更新為最後讀到的資料（包含 NULL）。
每次 update_rows 呼叫會使用單一交易；任一筆失敗會全部回復。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable


COLUMNS = ["測站", "日期", "AQI", "空氣品質指標", "O3", "PM2.5", "PM10", "CO", "SO2", "NO2"]
MISSING = {"", "-", "--", "NA", "N/A", "NULL", "NAN"}

MODEL_COLUMNS = ["station", "observed_at", "aqi", "air_quality_indicator", "o3", "pm25", "pm10", "co", "so2", "no2"]


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


def parse_row(raw: dict[str, str]) -> dict:
    """將爬蟲取得的一列資料驗證並轉成資料庫欄位。"""
    if set(raw) != set(COLUMNS):
        raise ValueError("資料欄位與預期不符")
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
    return dict(zip(MODEL_COLUMNS, values))


def update_rows(rows: Iterable[dict], *, settings=None, batch_size: int | None = None) -> int:
    """在單一交易中新增或更新已驗證資料，回傳處理筆數。"""
    if settings is None:
        from config import settings
    if batch_size is None:
        batch_size = settings.batch_size
    if batch_size <= 0:
        raise ValueError("batch_size 必須大於 0")

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
                for row in rows:
                    batch.append(row)
                    total += 1
                    if len(batch) >= batch_size:
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
    return total
