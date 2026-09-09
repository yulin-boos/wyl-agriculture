from __future__ import annotations

import torch


def allowed_indices_for_crop(labels: list[str], crop: str) -> list[int]:
    indices = [index for index, label in enumerate(labels) if label.partition("___")[0] == crop]
    if not indices:
        raise ValueError(f"Crop is not represented in the model taxonomy: {crop}")
    return indices


def constrain_probabilities(
    probabilities: torch.Tensor, allowed_indices: list[int]
) -> torch.Tensor:
    if probabilities.ndim != 1:
        raise ValueError("Expected one-dimensional class probabilities.")
    constrained = torch.zeros_like(probabilities)
    constrained[allowed_indices] = probabilities[allowed_indices]
    total = constrained.sum()
    if float(total.detach()) <= 0:
        raise ValueError("Allowed classes have zero probability mass.")
    return constrained / total
