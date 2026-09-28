"""Run the complete AQI prediction pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

from data_cleaning import load_and_clean_data
from data_split import prepare_datasets
from model import LSTMModel, save_checkpoint
from predict import predict_next_hour
from train import evaluate_model, train_model
from visualization import show_visualizations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the AQI LSTM prediction pipeline")
    parser.add_argument("--data", type=Path, default=Path("aqi_hour_concat.csv"))
    parser.add_argument("--model", type=Path, default=Path("aqi_lstm_model.pth"))
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--window-size", type=int, default=24)
    parser.add_argument("--no-visualization", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    data, features = load_and_clean_data(args.data)

    if not args.no_visualization:
        show_visualizations(data)

    datasets = prepare_datasets(
        data,
        features,
        window_size=args.window_size,
    )
    model = LSTMModel(input_size=len(features))
    train_model(model, datasets.train_loader, epochs=args.epochs)
    evaluate_model(model, datasets.test_loader)
    predict_next_hour(
        model,
        datasets.test_df,
        data,
        datasets.features,
        datasets.window_size,
    )
    save_checkpoint(
        model,
        args.model,
        datasets.features,
        datasets.window_size,
        datasets.scaler,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
