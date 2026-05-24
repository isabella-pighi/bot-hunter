from __future__ import annotations

import random
from math import sqrt

from .data import ClickEvent


def _standardize(matrix: list[list[float]]) -> tuple[list[list[float]], list[float], list[float]]:
    cols = len(matrix[0])
    means = [sum(row[i] for row in matrix) / len(matrix) for i in range(cols)]
    stds: list[float] = []
    for i in range(cols):
        var = sum((row[i] - means[i]) ** 2 for row in matrix) / len(matrix)
        stds.append(sqrt(var) or 1.0)
    return [[(row[i] - means[i]) / stds[i] for i in range(cols)] for row in matrix], means, stds


def _distance(a: list[float], b: list[float]) -> float:
    return sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _nearest(row: list[float], centers: list[list[float]]) -> tuple[int, float]:
    best_idx = 0
    best_dist = _distance(row, centers[0])
    for idx, center in enumerate(centers[1:], start=1):
        dist = _distance(row, center)
        if dist < best_dist:
            best_idx = idx
            best_dist = dist
    return best_idx, best_dist


def score_with_kmeans(
    events: list[ClickEvent],
    clusters: int = 8,
    iterations: int = 18,
    sample_size: int = 25000,
    seed: int = 7,
) -> None:
    if not events:
        return
    rng = random.Random(seed)
    matrix = [event.features for event in events]
    scaled, means, stds = _standardize(matrix)
    train = scaled if len(scaled) <= sample_size else rng.sample(scaled, sample_size)
    clusters = min(clusters, len(train))
    centers = rng.sample(train, clusters)

    for _ in range(iterations):
        buckets = [[] for _ in centers]
        for row in train:
            idx, _ = _nearest(row, centers)
            buckets[idx].append(row)
        new_centers: list[list[float]] = []
        for idx, bucket in enumerate(buckets):
            if not bucket:
                new_centers.append(centers[idx])
                continue
            new_centers.append([sum(row[col] for row in bucket) / len(bucket) for col in range(len(bucket[0]))])
        centers = new_centers

    distances = [_nearest(row, centers)[1] for row in scaled]
    ordered = sorted(distances)
    max_rank = max(len(ordered) - 1, 1)
    for event, dist in zip(events, distances):
        rank = _upper_bound(ordered, dist)
        event.ml_score = rank / max_rank

    # Keep variables visible to linters and readers; means/stds document that scoring is standardized.
    _ = (means, stds)


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

