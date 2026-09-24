"""Load and clean AQI time-series data."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

FEATURES = ["O3", "PM2.5", "PM10", "CO", "SO2", "NO2"]


def load_and_clean_data(csv_path: str | Path) -> tuple[pd.DataFrame, list[str]]:
    """Load the concatenated CSV and prepare numeric hourly data."""
    data = pd.read_csv(csv_path, encoding="utf-8-sig")
    print(data.head())
    print("Null values before cleaning:")
    print(data.isnull().sum())
    print("Columns:", list(data.columns))

    data["日期"] = pd.to_datetime(data["日期"])
    data = data.sort_values("日期").reset_index(drop=True)
    print("Timestamps sorted:", data["日期"].is_monotonic_increasing)

    if "空氣品質指標" in data.columns:
        print("Air quality indicator values:", set(data["空氣品質指標"]))
    data = data.drop(columns=["空氣品質指標", "測站"], errors="ignore")

    missing_marker_rows = data[(data == "-").any(axis=1)]
    print("Rows containing '-':", len(missing_marker_rows))

    for column in FEATURES:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data[FEATURES] = data[FEATURES].interpolate(method="linear")

    expected = pd.date_range(
        start=data["日期"].min(),
        end=data["日期"].max(),
        freq="h",
    )
    missing_times = expected.difference(data["日期"])
    print("Expected timestamps:", len(expected))
    print("Actual rows:", len(data))
    print("Missing timestamps:", len(missing_times))
    print(missing_times)
    print("Time differences:")
    print(data["日期"].diff().value_counts())

    return data, FEATURES.copy()
