"""Visualization functions for the AQI data."""

from __future__ import annotations

import pandas as pd


def show_visualizations(data: pd.DataFrame) -> None:
    """Open the AQI trend and feature relationship charts in a browser."""
    import plotly.express as px
    import plotly.io as pio

    pio.renderers.default = "browser"

    trend = px.line(data, x="日期", y="AQI", title="AQI Trend Over Time")
    trend.show()

    dimensions = ["AQI", "PM2.5", "PM10", "CO", "NO2"]
    matrix = px.scatter_matrix(
        data,
        dimensions=dimensions,
        title="Air Quality Relationships",
    )
    matrix.show()
