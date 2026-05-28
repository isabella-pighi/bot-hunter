from __future__ import annotations

from math import sqrt

from .data import ClickEvent

EIF_TREES = 100
EIF_EXTENSION_DIMS = 2
EIF_SAMPLE_SIZE = 4096


def _standardize(matrix: list[list[float]]) -> tuple[list[list[float]], list[float], list[float]]:
    cols = len(matrix[0])
    means = [sum(row[i] for row in matrix) / len(matrix) for i in range(cols)]
    stds: list[float] = []
    for i in range(cols):
        var = sum((row[i] - means[i]) ** 2 for row in matrix) / len(matrix)
        stds.append(sqrt(var) or 1.0)
    return [[(row[i] - means[i]) / stds[i] for i in range(cols)] for row in matrix], means, stds


def score_anomalies(events: list[ClickEvent]) -> str:
    try:
        score_with_extended_isolation_forest(events)
    except ImportError as exc:
        raise ValueError(
            "Extended Isolation Forest requires isotree; install with: uv sync --extra eif"
        ) from exc
    return "eif"


def score_with_extended_isolation_forest(events: list[ClickEvent], seed: int = 7) -> None:
    score_with_extended_isolation_forest_config(
        events,
        seed=seed,
        sample_size=EIF_SAMPLE_SIZE,
        ntrees=EIF_TREES,
        ndim=EIF_EXTENSION_DIMS,
    )


def score_with_extended_isolation_forest_config(
    events: list[ClickEvent],
    *,
    seed: int = 7,
    sample_size: int | str = EIF_SAMPLE_SIZE,
    ntrees: int = EIF_TREES,
    ndim: int = EIF_EXTENSION_DIMS,
) -> None:
    if not events:
        return
    import numpy as np
    from isotree import IsolationForest

    matrix = [_ml_features(event) for event in events]
    scaled, means, stds = _standardize(matrix)
    _apply_feature_weights(scaled, events[0].ml_feature_weights)
    scaled_array = np.asarray(scaled, dtype=float)
    model_sample_size = min(sample_size, len(scaled_array)) if isinstance(sample_size, int) else sample_size
    model = IsolationForest(
        sample_size=model_sample_size,
        ntrees=ntrees,
        ndim=min(ndim, scaled_array.shape[1]),
        missing_action="fail",
        standardize_data=False,
        random_seed=seed,
        nthreads=1,
    )
    model.fit(scaled_array)
    anomaly_scores = [float(score) for score in model.decision_function(scaled_array)]
    _assign_rank_scores(events, anomaly_scores)

    _ = (means, stds)


def _ml_features(event: ClickEvent) -> list[float]:
    return event.ml_features or event.features


def _apply_feature_weights(matrix: list[list[float]], weights: list[float]) -> None:
    if not matrix or not weights:
        return
    for row in matrix:
        for idx, weight in enumerate(weights[: len(row)]):
            row[idx] *= weight


def _assign_rank_scores(events: list[ClickEvent], anomaly_values) -> None:
    ordered = sorted(float(value) for value in anomaly_values)
    max_rank = max(len(ordered) - 1, 1)
    for event, value in zip(events, anomaly_values):
        rank = _upper_bound(ordered, float(value))
        event.ml_score = rank / max_rank


def _upper_bound(values: list[float], needle: float) -> int:
    low = 0
    high = len(values)
    while low < high:
        mid = (low + high) // 2
        if values[mid] <= needle:
            low = mid + 1
        else:
            high = mid
    return low - 1
