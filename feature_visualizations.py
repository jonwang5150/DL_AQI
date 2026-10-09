"""AQI 未來預測結果的互動式視覺化。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, func, select

from config import settings
from db_models import AirQualityHourly, AirQualityPrediction, AirQualityPrediction8h
from update_db import database_url_from_settings


def load_prediction_data(station: str, source: str = "8h", horizon: int = 1) -> pd.DataFrame:
    """每個目標時間只取一筆；多個模型版本以最新寫入者為準。"""
    if source not in {"8h", "single"} or horizon not in range(1, 9):
        raise ValueError("source 必須為 8h 或 single，horizon 必須介於 1～8")
    if source == "8h":
        prediction = AirQualityPrediction8h
        ranked = select(
            prediction.station,
            prediction.target_at,
            prediction.predicted_aqi,
            prediction.model_version,
            func.row_number().over(
                partition_by=prediction.target_at,
                order_by=[prediction.created_at.desc(), prediction.model_version.asc()],
            ).label("rank"),
        ).where(
            prediction.station == station,
            prediction.horizon_hours == horizon,
        ).subquery()
        statement = (
            select(
                ranked.c.target_at.label("日期"),
                ranked.c.predicted_aqi.label("預測AQI"),
                AirQualityHourly.aqi.label("實際AQI"),
                ranked.c.model_version.label("模型版本"),
            )
            .outerjoin(AirQualityHourly, (
                (AirQualityHourly.station == ranked.c.station)
                & (AirQualityHourly.observed_at == ranked.c.target_at)
            ))
            .where(ranked.c.rank == 1)
            .order_by(ranked.c.target_at)
        )
    else:
        statement = (
            select(
                AirQualityPrediction.predicted_at.label("日期"),
                AirQualityPrediction.predicted_aqi.label("預測AQI"),
                func.coalesce(AirQualityHourly.aqi, AirQualityPrediction.actual_aqi).label("實際AQI"),
            )
            .outerjoin(AirQualityHourly, (
                (AirQualityHourly.station == AirQualityPrediction.station)
                & (AirQualityHourly.observed_at == AirQualityPrediction.predicted_at)
            ))
            .where(AirQualityPrediction.station == station)
            .order_by(AirQualityPrediction.predicted_at)
        )
    engine = create_engine(
        database_url_from_settings(settings),
        connect_args={"connect_timeout": 10},
        hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            return pd.read_sql(statement, connection)
    finally:
        engine.dispose()


def evaluate_prediction_data(datasets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """以所有模型共同具有有限預測與真實值的時間點評估，不補值。"""
    aligned = {}
    common = None
    for source, data in datasets.items():
        frame = data.set_index("日期")[["預測AQI", "實際AQI"]].apply(
            pd.to_numeric, errors="coerce")
        if frame.index.has_duplicates:
            raise ValueError("評估資料的目標時間不可重複")
        frame = frame.loc[np.isfinite(frame.to_numpy(dtype=float)).all(axis=1)]
        aligned[source] = frame
        common = frame.index if common is None else common.intersection(frame.index)
    rows = []
    for source, frame in aligned.items():
        paired = frame.loc[common]
        errors = (paired["預測AQI"] - paired["實際AQI"]).to_numpy(dtype=float)
        count = len(errors)
        rows.append({
            "來源": source, "有效筆數": count,
            "未納入筆數": len(datasets[source]) - count,
            "MAE": float(np.abs(errors).mean()) if count else np.nan,
            "RMSE": float(np.sqrt(np.mean(errors ** 2))) if count else np.nan,
            "Bias": float(errors.mean()) if count else np.nan,
            "評估開始": common.min() if count else pd.NaT,
            "評估結束": common.max() if count else pd.NaT,
        })
    return pd.DataFrame(rows)


def show_prediction_visualization(
    station: str = "木柵站",
    initial_window_days: int = 7,
    source: str = "both",
    horizon: int = 1,
) -> None:
    """直接在瀏覽器顯示可拖曳時間軸的 AQI 圖表，不輸出檔案。"""
    if initial_window_days <= 0:
        raise ValueError("initial_window_days 必須大於 0")

    if source not in {"both", "8h", "single"}:
        raise ValueError("source 必須為 both、8h 或 single")
    sources = ["single", "8h"] if source == "both" else [source]
    datasets = {}
    for selected in sources:
        data = load_prediction_data(station, source=selected, horizon=horizon)
        data["日期"] = pd.to_datetime(data["日期"], errors="coerce")
        data["預測AQI"] = pd.to_numeric(data["預測AQI"], errors="coerce")
        data["實際AQI"] = pd.to_numeric(data["實際AQI"], errors="coerce")
        data = data.dropna(subset=["日期", "預測AQI"]).sort_values("日期")
        if data.empty:
            raise ValueError(f"測站「{station}」的 {selected} 來源沒有可繪製的預測資料")
        datasets[selected] = data

    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    labels = {"single": "Pipeline v1（單步模型）", "8h": f"Pipeline v2（8h 模型，h{horizon}）"}
    colors = {"single": "#2563eb", "8h": "#16a34a"}
    metrics = evaluate_prediction_data(datasets)
    summary = metrics.copy()
    summary["來源"] = summary["來源"].map(labels)
    print("\n評估：全期間共同有效時間點；縮放圖表不會重算指標。")
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.4f}", na_rep="N/A"))
    print("MAE、RMSE 越小越好；Bias = 預測 − 實際，正值高估、負值低估。")
    figure = make_subplots(
        rows=3, cols=1, specs=[[{"type": "xy"}], [{"type": "xy"}], [{"type": "table"}]],
        row_heights=[0.53, 0.27, 0.20], vertical_spacing=0.12,
        subplot_titles=["逐時預測與實際 AQI", "誤差比較（全期間共同有效資料）", "評估明細"],
    )
    for selected, data in datasets.items():
        figure.add_trace(
            go.Scatter(
                x=data["日期"],
                y=data["預測AQI"],
                mode="lines",
                name=labels[selected],
                legendgroup=selected,
                customdata=data[["模型版本"]].to_numpy() if selected == "8h" else None,
                hovertemplate=(
                    "%{x}<br>預測 AQI：%{y:.2f}<br>模型：%{customdata[0]}<extra></extra>"
                    if selected == "8h" else None
                ),
                line={"color": "#16a34a" if selected == "8h" else "#2563eb", "width": 1.5},
            ), row=1, col=1,
        )
    # 取兩種預測期間的聯集，實際值只畫一條；優先保留非空觀測。
    actual = pd.concat([data[["日期", "實際AQI"]] for data in datasets.values()])
    actual = actual.groupby("日期", as_index=False)["實際AQI"].first().sort_values("日期")
    figure.add_trace(
        go.Scatter(
            x=actual["日期"],
            y=actual["實際AQI"],
            mode="lines",
            name="實際 AQI",
            line={"color": "#f97316", "width": 1.2},
        ), row=1, col=1,
    )

    for row in metrics.to_dict(orient="records"):
        selected = row["來源"]
        figure.add_trace(go.Bar(
            x=["MAE", "RMSE", "Bias"],
            y=[row[key] if pd.notna(row[key]) else None for key in ["MAE", "RMSE", "Bias"]],
            name=labels[selected], legendgroup=selected, showlegend=False,
            marker_color=colors[selected], texttemplate="%{y:.3f}", textposition="auto",
            hovertemplate="%{x}：%{y:.4f}<extra>%{fullData.name}</extra>",
        ), row=2, col=1)
    columns = ["來源", "有效筆數", "未納入筆數", "MAE", "RMSE", "Bias"]
    cells = []
    for column in columns:
        cells.append([
            (f"{value:.4f}" if pd.notna(value) else "N/A")
            if column in {"MAE", "RMSE", "Bias"} else value
            for value in summary[column]
        ])
    figure.add_trace(go.Table(
        columnwidth=[3, 1, 1, 1, 1, 1],
        header={"values": columns, "fill_color": "#e2e8f0", "align": "left"},
        cells={"values": cells, "align": "left", "height": 28},
    ), row=3, col=1)
    count = int(metrics.iloc[0]["有效筆數"])
    period = (f"{metrics.iloc[0]['評估開始']} ～ {metrics.iloc[0]['評估結束']}"
              if count else "無共同有效資料，指標為 N/A")
    figure.add_annotation(
        text=f"評估期間：{period}；{count} 筆<br>全期間指標，不隨縮放更新。MAE / RMSE 越低越好；Bias 正值高估、負值低估。",
        x=0, y=-0.06, xref="paper", yref="paper", showarrow=False, xanchor="left",
    )

    last_time = actual["日期"].max()
    first_visible = max(
        actual["日期"].min(),
        last_time - pd.Timedelta(days=initial_window_days),
    )
    figure.update_layout(
        title=f"{station} AQI 模型預測與實際值比較",
        xaxis_title="時間",
        yaxis_title="AQI",
        hovermode="x unified",
        template="plotly_white",
        height=1050,
        barmode="group",
        legend={"orientation": "h", "y": 1.02, "x": 1, "xanchor": "right"},
        margin={"l": 60, "r": 30, "t": 100, "b": 100},
    )
    figure.update_xaxes(
        range=[first_visible, last_time],
        rangeslider={"visible": True, "thickness": 0.04},
        rangeselector={
            "buttons": [
                {"count": 1, "label": "1 天", "step": "day", "stepmode": "backward"},
                {"count": 7, "label": "7 天", "step": "day", "stepmode": "backward"},
                {"count": 1, "label": "1 個月", "step": "month", "stepmode": "backward"},
                {"step": "all", "label": "全部"},
            ]
        }, row=1, col=1,
    )
    figure.update_yaxes(title_text="誤差（AQI）", zeroline=True, row=2, col=1)
    figure.show(renderer="browser")
