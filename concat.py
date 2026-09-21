#!/usr/bin/env python3
"""依日期順序合併 search_v2.py 下載的 ODS 檔案。"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment]


DATE_IN_FILENAME = re.compile(r"^aqi_hour_(\d{8})_\d{8}\.ods$", re.IGNORECASE)


def file_date(path: Path) -> datetime:
    """取得檔名中的開始日期，讓排序不受檔案系統順序影響。"""
    match = DATE_IN_FILENAME.match(path.name)
    if match is None:
        raise ValueError(
            f"檔名格式錯誤：{path.name}；預期格式為 aqi_hour_YYYYMMDD_YYYYMMDD.ods"
        )
    return datetime.strptime(match.group(1), "%Y%m%d")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="依日期順序合併 AQI ODS 檔案為 CSV")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("downloads"),
        help="ODS 檔案所在目錄（預設：downloads）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("aqi_hour_concat.csv"),
        help="輸出的 CSV 路徑（預設：aqi_hour_concat.csv）",
    )
    return parser


def main() -> int:
    if pd is None:
        raise RuntimeError("缺少套件，請先執行：pip install pandas odfpy")

    args = build_parser().parse_args()
    if not args.input.is_dir():
        raise FileNotFoundError(f"找不到輸入目錄：{args.input}")

    files = sorted(
        (path for path in args.input.glob("*.ods") if path.is_file()),
        key=file_date,
    )
    if not files:
        raise FileNotFoundError(f"輸入目錄沒有 ODS 檔案：{args.input}")

    frames = []
    columns = None
    for path in files:
        frame = pd.read_excel(path, engine="odf")
        if columns is None:
            columns = list(frame.columns)
        elif list(frame.columns) != columns:
            raise ValueError(f"欄位與其他檔案不一致：{path}")
        frames.append(frame)

    result = pd.concat(frames, ignore_index=True)
    result.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"已合併 {len(files)} 個檔案、{len(result):,} 筆資料：{args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        raise SystemExit(1)