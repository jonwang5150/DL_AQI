#!/usr/bin/env python3
"""顯示最新 AQI 預測 CSV 的互動式圖表。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from feature_visualizations import show_prediction_visualization


PROJECT_DIR = Path(__file__).resolve().parent


def find_default_prediction_csv() -> Path:
    """選擇最近產生的日期區間預測檔。"""
    candidates = list(PROJECT_DIR.glob("*-*_predict.csv"))
    if not candidates:
        raise FileNotFoundError(
            f"找不到預測結果：{PROJECT_DIR / '*-*_predict.csv'}"
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        default=find_default_prediction_csv(),
        help="預測結果 CSV 路徑",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=7,
        help="圖表初始顯示最後幾天，預設為 7 天",
    )
    parser.add_argument(
        "--html",
        type=Path,
        default=PROJECT_DIR / "predict_2026_chart.html",
        help="互動式圖表 HTML 輸出路徑",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    html_path = show_prediction_visualization(
        args.data,
        initial_window_days=args.window_days,
        html_path=args.html,
    )
    print(f"互動式圖表已建立：{html_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        raise SystemExit(1)
