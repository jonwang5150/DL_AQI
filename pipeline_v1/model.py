"""LSTM model definition and checkpoint persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch
import torch.nn as nn


class LSTMModel(nn.Module):
    def __init__(
        self,
        input_size: int = 6,
        hidden_size: int = 64,
        num_layers: int = 1,
    ) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
        )
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        output, _ = self.lstm(x)
        output = output[:, -1, :]
        return self.fc(output).squeeze()


def save_checkpoint(
    model: LSTMModel,
    path: str | Path,
    features: list[str],
    window_size: int,
    scaler: Any,
) -> None:
    """Save weights and preprocessing metadata needed for inference."""
    checkpoint = {
        "model_state_dict": model.state_dict(),
        "model_config": {
            "input_size": len(features),
            "hidden_size": 64,
            "num_layers": 1,
        },
        "features": features,
        "window_size": window_size,
        "scaler_mean": scaler.mean_,
        "scaler_scale": scaler.scale_,
    }
    torch.save(checkpoint, path)
    print(f"Model saved to: {path}")
