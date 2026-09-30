"""多步 AQI 預測使用的資料清理。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


FEATURES_NEW = ["AQI", "O3", "PM2.5", "PM10", "CO", "SO2", "NO2"]


def load_and_clean_data_new(csv_path: str | Path) -> tuple[pd.DataFrame, list[str]]:
    """載入逐時資料，並以線性插值填補特徵缺值。"""
    data = pd.read_csv(csv_path, encoding="utf-8-sig")
    required = {"日期", *FEATURES_NEW}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"資料缺少欄位：{', '.join(sorted(missing))}")

    data["日期"] = pd.to_datetime(data["日期"], errors="raise")
    data = data.sort_values("日期").reset_index(drop=True)
    if data["日期"].duplicated().any():
        raise ValueError("資料含有重複的日期時間")

    data = data.drop(columns=["空氣品質指標", "測站"], errors="ignore")
    for column in FEATURES_NEW:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data[FEATURES_NEW] = data[FEATURES_NEW].astype(float)

    missing_before = int(data[FEATURES_NEW].isna().sum().sum())
    # 線性插值會利用缺口前後的觀測值，適合歷史資料訓練與回測。
    data.loc[:, FEATURES_NEW] = data[FEATURES_NEW].interpolate(method="linear")
    if data[FEATURES_NEW].isna().any().any():
        raise ValueError("線性插值後仍有空值；資料開頭必須具有完整觀測")

    expected = pd.date_range(data["日期"].min(), data["日期"].max(), freq="h")
    missing_times = expected.difference(data["日期"])
    print(f"資料期間：{data['日期'].min()} ～ {data['日期'].max()}")
    print(f"線性補值：{missing_before} 格；缺少整點：{len(missing_times)} 筆")
    return data, FEATURES_NEW.copy()
