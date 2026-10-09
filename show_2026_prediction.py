#!/usr/bin/env python3
"""比較兩種 pipeline 的 AQI 曲線及 MAE、RMSE、Bias；8h 模型預設取 h1。"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.exc import SQLAlchemyError

from feature_visualizations import show_prediction_visualization


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["both", "8h", "single"], default="both",
                        help="both：同時比較兩種模型（預設）；8h：多步模型；single：單步模型")
    parser.add_argument("--horizon", type=int, choices=range(1, 9), default=1,
                        help="8h 模型的提前小時，預設 h1，每個目標時間只取一筆")
    parser.add_argument(
        "--station",
        default="木柵站",
        help="資料庫中的測站名稱，預設為木柵站",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=7,
        help="圖表初始顯示最後幾天，預設為 7 天",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    show_prediction_visualization(
        station=args.station,
        initial_window_days=args.window_days,
        source=args.source,
        horizon=args.horizon,
    )
    print("互動式圖表已在瀏覽器開啟")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, SQLAlchemyError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        raise SystemExit(1)
