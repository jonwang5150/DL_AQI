"""AQI 未來預測結果的互動式視覺化。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def show_prediction_visualization(
    csv_path: str | Path,
    initial_window_days: int = 7,
    html_path: str | Path | None = None,
    auto_open: bool = True,
) -> Path:
    """建立可拖曳時間軸的 AQI 預測圖表，並以 HTML 開啟。"""
    if initial_window_days <= 0:
        raise ValueError("initial_window_days 必須大於 0")

    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"找不到預測結果：{path}")

    data = pd.read_csv(path, encoding="utf-8-sig")
    required_columns = {"日期", "預測AQI", "實際AQI"}
    missing_columns = required_columns.difference(data.columns)
    if missing_columns:
        raise ValueError(f"預測結果缺少欄位：{', '.join(sorted(missing_columns))}")

    data["日期"] = pd.to_datetime(data["日期"], errors="coerce")
    data["預測AQI"] = pd.to_numeric(data["預測AQI"], errors="coerce")
    data["實際AQI"] = pd.to_numeric(data["實際AQI"], errors="coerce")
    data = data.dropna(subset=["日期", "預測AQI"]).sort_values("日期")
    if data.empty:
        raise ValueError("預測結果沒有可繪製的資料")

    import plotly.graph_objects as go

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=data["日期"],
            y=data["預測AQI"],
            mode="lines",
            name="預測 AQI",
            line={"color": "#2563eb", "width": 1.5},
        )
    )
    figure.add_trace(
        go.Scatter(
            x=data["日期"],
            y=data["實際AQI"],
            mode="lines",
            name="實際 AQI",
            line={"color": "#f97316", "width": 1.2},
        )
    )

    last_time = data["日期"].max()
    first_visible = max(
        data["日期"].min(),
        last_time - pd.Timedelta(days=initial_window_days),
    )
    figure.update_layout(
        title="AQI 預測與實際值",
        xaxis_title="時間",
        yaxis_title="AQI",
        hovermode="x unified",
        template="plotly_white",
        legend={"orientation": "h", "y": 1.02, "x": 1, "xanchor": "right"},
        margin={"l": 60, "r": 30, "t": 80, "b": 60},
    )
    figure.update_xaxes(
        range=[first_visible, last_time],
        rangeslider={"visible": True},
        rangeselector={
            "buttons": [
                {"count": 1, "label": "1 天", "step": "day", "stepmode": "backward"},
                {"count": 7, "label": "7 天", "step": "day", "stepmode": "backward"},
                {"count": 1, "label": "1 個月", "step": "month", "stepmode": "backward"},
                {"step": "all", "label": "全部"},
            ]
        },
    )
    output_path = (
        Path(html_path)
        if html_path is not None
        else path.with_name(f"{path.stem}_chart.html")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(
        output_path,
        include_plotlyjs=True,
        full_html=True,
        auto_open=auto_open,
    )
    return output_path.resolve()
