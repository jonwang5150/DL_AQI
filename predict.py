"""Future AQI prediction."""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from model import LSTMModel


def predict_period(
    model: LSTMModel,
    scaled_data: pd.DataFrame,
    features: list[str],
    window_size: int,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> pd.DataFrame:
    """Predict each hourly AQI in the half-open interval ``[start, end)``.

    ``scaled_data`` must contain the feature history immediately before the
    requested period.  Only windows made of consecutive hourly observations
    are accepted so a missing row cannot silently shift a prediction.
    """
    required_columns = {"日期", *features}
    missing_columns = required_columns.difference(scaled_data.columns)
    if missing_columns:
        raise ValueError(f"預測資料缺少欄位：{', '.join(sorted(missing_columns))}")
    if window_size <= 0:
        raise ValueError("window_size 必須大於 0")

    start_time = pd.Timestamp(start)
    end_time = pd.Timestamp(end)
    if start_time >= end_time:
        raise ValueError("預測開始時間必須早於結束時間")

    data = scaled_data.sort_values("日期").reset_index(drop=True)
    dates = pd.to_datetime(data["日期"])
    sequences = []
    prediction_dates = []

    for index in range(window_size, len(data)):
        target_time = dates.iloc[index]
        if target_time < start_time or target_time >= end_time:
            continue
        window_dates = dates.iloc[index - window_size:index]
        expected_dates = pd.date_range(
            end=target_time - pd.Timedelta(hours=1),
            periods=window_size,
            freq="h",
        )
        if not window_dates.reset_index(drop=True).equals(pd.Series(expected_dates)):
            continue
        sequences.append(data.iloc[index - window_size:index][features].to_numpy())
        prediction_dates.append(target_time)

    if not sequences:
        return pd.DataFrame(columns=["日期", "預測AQI"])

    inputs = torch.from_numpy(np.stack(sequences).astype(np.float32, copy=False))
    model.eval()
    with torch.no_grad():
        predictions = model(inputs).detach().cpu().numpy().reshape(-1)

    return pd.DataFrame({"日期": prediction_dates, "預測AQI": predictions})


def predict_next_hour(
    model: LSTMModel,
    scaled_test_data: pd.DataFrame,
    raw_data: pd.DataFrame,
    features: list[str],
    window_size: int,
) -> float:
    """Predict the hour immediately after the latest test-data window."""
    last_window = scaled_test_data.tail(window_size)[features].to_numpy(
        dtype=np.float32,
        copy=True,
    )
    if len(last_window) != window_size:
        raise ValueError(f"預測需要 {window_size} 筆歷史資料，實際只有 {len(last_window)} 筆")

    inputs = torch.from_numpy(last_window).unsqueeze(0)
    model.eval()
    with torch.no_grad():
        prediction = model(inputs).item()

    next_date = scaled_test_data["日期"].iloc[-1] + pd.Timedelta(hours=1)
    actual_rows = raw_data[raw_data["日期"] >= next_date]
    actual = actual_rows.iloc[0]["AQI"] if not actual_rows.empty else "N/A"
    print(f"Prediction for {next_date}: {prediction:.4f}; actual AQI: {actual}")
    return prediction
