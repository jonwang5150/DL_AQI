"""Future AQI prediction."""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

try:
    from .model import LSTMModel
except ImportError:  # 支援直接執行 pipeline_v1 內的程式
    from model import LSTMModel


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
