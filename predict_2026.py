#!/usr/bin/env python3
"""從 PostgreSQL 載入資料，使用既有 checkpoint 預測指定期間的逐時 AQI。"""

from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError

import update_db
from config import settings
from db_models import AirQualityHourly
from pipeline_v1.model import LSTMModel
from predict_feture import predict_period


PROJECT_DIR = Path(__file__).resolve().parent
PREDICTION_START = pd.Timestamp("2026-01-01 00:00:00")
PREDICTION_END = pd.Timestamp("2026-08-01 00:00:00")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--station", default="木柵站", help="資料庫中的測站名稱")
    parser.add_argument(
        "--model",
        type=Path,
        default=PROJECT_DIR / "aqi_lstm_model.pth",
        help="模型 checkpoint 路徑",
    )
    return parser


def load_checkpoint(path: Path) -> tuple[LSTMModel, list[str], int, np.ndarray, np.ndarray]:
    if not path.is_file():
        raise FileNotFoundError(f"找不到模型檔：{path}")

    try:
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:  # 相容尚未提供 weights_only 參數的舊版 PyTorch
        checkpoint = torch.load(path, map_location="cpu")
    except pickle.UnpicklingError:
        # 專案既有 checkpoint 含 NumPy array；PyTorch 2.6 的安全模式不接受它。
        # 請只對可信任的本機模型使用此 fallback。
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)

    required = {
        "model_state_dict",
        "model_config",
        "features",
        "window_size",
        "scaler_mean",
        "scaler_scale",
    }
    # difference()：找出「存在於 required，但不存在於 checkpoint」的項目。
    missing = required.difference(checkpoint)
    if missing:
        raise ValueError(f"模型 checkpoint 缺少欄位：{', '.join(sorted(missing))}")

    features = list(checkpoint["features"])
    window_size = int(checkpoint["window_size"])
    scaler_mean = np.asarray(checkpoint["scaler_mean"], dtype=float)
    scaler_scale = np.asarray(checkpoint["scaler_scale"], dtype=float)
    if len(features) != len(scaler_mean) or len(features) != len(scaler_scale):
        raise ValueError("checkpoint 的 features 與 scaler 維度不一致")
    if np.any(scaler_scale == 0):
        raise ValueError("checkpoint 含有無效的 scaler_scale=0")

    model = LSTMModel(**checkpoint["model_config"])
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    return model, features, window_size, scaler_mean, scaler_scale


def load_database_data(station: str, query_start: pd.Timestamp) -> pd.DataFrame:
    columns = {
        "O3": AirQualityHourly.o3,
        "PM2.5": AirQualityHourly.pm25,
        "PM10": AirQualityHourly.pm10,
        "CO": AirQualityHourly.co,
        "SO2": AirQualityHourly.so2,
        "NO2": AirQualityHourly.no2,
    }
    statement = (
        select(
            AirQualityHourly.observed_at.label("日期"),
            AirQualityHourly.aqi.label("AQI"),
            *[column.label(name) for name, column in columns.items()],
        )
        .where(
            AirQualityHourly.station == station,
            AirQualityHourly.observed_at >= query_start.to_pydatetime(),
            AirQualityHourly.observed_at < PREDICTION_END.to_pydatetime(),
        )
        .order_by(AirQualityHourly.observed_at)
    )

    engine = create_engine(
        update_db.database_url_from_settings(settings),
        connect_args={"connect_timeout": 10},
        hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            return pd.read_sql(statement, connection)
    finally:
        engine.dispose()


def complete_hourly_timeline(
    data: pd.DataFrame,
    query_start: pd.Timestamp,
) -> tuple[pd.DataFrame, int]:
    """補齊缺少的整點列，並回傳補入的時間列數。"""
    if data.empty:
        raise ValueError("指定的測站與時段在資料庫中沒有資料")
    if data["日期"].duplicated().any():
        duplicates = data.loc[data["日期"].duplicated(), "日期"].dt.strftime("%Y-%m-%d %H:%M")
        raise ValueError(f"資料庫有重複時間：{', '.join(duplicates.head(5))}")

    expected = pd.date_range(query_start, PREDICTION_END, freq="h", inclusive="left")
    actual = pd.DatetimeIndex(data["日期"])
    missing = expected.difference(actual)
    completed = (
        data.set_index("日期")
        .reindex(expected)
        .rename_axis("日期")
        .reset_index()
    )
    return completed, len(missing)


def main() -> int:
    args = build_parser().parse_args()
    model, features, window_size, scaler_mean, scaler_scale = load_checkpoint(args.model)
    query_start = PREDICTION_START - pd.Timedelta(hours=window_size)

    data = load_database_data(args.station, query_start)
    data["日期"] = pd.to_datetime(data["日期"])
    data, missing_hours = complete_hourly_timeline(data, query_start)

    missing_features = set(features).difference(data.columns)
    if missing_features:
        raise ValueError(f"資料庫查詢結果缺少模型特徵：{', '.join(sorted(missing_features))}")
    for feature in features:
        data[feature] = pd.to_numeric(data[feature], errors="coerce")
    # 僅使用過去觀測值進行前向補值，避免補值時使用未來資料。
    missing_before = int(data[features].isna().sum().sum())
    data.loc[:, features] = data[features].ffill()
    
    if data[features].isna().any().any():
        raise ValueError("模型特徵補值後仍含空值，無法建立預測視窗")

 

    scaled_data = data.copy()
    scaled_data.loc[:, features] = (data[features].to_numpy(dtype=float) - scaler_mean) / scaler_scale
    predictions = predict_period(
        model,
        scaled_data,
        features,
        window_size,
        PREDICTION_START,
        PREDICTION_END,
    )

    period_actual = data.loc[
        (data["日期"] >= PREDICTION_START) & (data["日期"] < PREDICTION_END),
        ["日期", "AQI"],
    ]
    result = predictions.merge(period_actual, on="日期", how="left")
    result = result.rename(columns={"AQI": "實際AQI"})
    expected_count = len(pd.date_range(PREDICTION_START, PREDICTION_END, freq="h", inclusive="left"))
    if len(result) != expected_count:
        raise RuntimeError(f"預期產生 {expected_count} 筆預測，實際只有 {len(result)} 筆")

    prediction_rows = (
        update_db.parse_prediction_row({**raw, "測站": args.station})
        for raw in result.to_dict(orient="records")
    )
    written_count = update_db.update_prediction_rows(
        prediction_rows,
        settings=settings,
    )
    print(f"測站：{args.station}")
    print(f"預測時段：{PREDICTION_START} 至 {PREDICTION_END}（不含結束時間）")
    print(f"補齊缺少的逐時資料：{missing_hours} 筆")
    print(f"污染物欄位前向補值：{missing_before} 格")
    print(f"完成 {written_count} 筆逐時 AQI 預測，已寫入 public.air_quality_predictions。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ModuleNotFoundError as exc:
        if exc.name in {"psycopg", "psycopg2"}:
            print(
                '錯誤：缺少 PostgreSQL driver，請執行：pip install "psycopg[binary]>=3,<4"',
                file=sys.stderr,
            )
        else:
            print(f"錯誤：缺少 Python 套件 {exc.name}", file=sys.stderr)
        raise SystemExit(1)
    except (OSError, ValueError, RuntimeError, SQLAlchemyError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        raise SystemExit(1)
