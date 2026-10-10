"""Quantize antialiased previews while preserving their required colors and opacity.

[Palette reduction reasoning](../../../docs/algorithms/preview-palette.md)
explains the contract and correctness argument.
"""

from __future__ import annotations

import dataclasses
import heapq
import itertools
import math

import numpy as np
import numpy.typing as npt
import PIL.Image


type Colors = npt.NDArray[np.uint8]
type Features = npt.NDArray[np.float64]
type Indices = npt.NDArray[np.int64]
RESERVED = np.array(
    (
        (0, 0, 0, 0),
        (255, 0, 0, 255),
        (255, 255, 0, 255),
        (255, 255, 255, 255),
        (0, 0, 0, 255),
    ),
    dtype=np.uint8,
)
COLOR_LIMIT = 256
ITERATION_LIMIT = 100
ALPHA_WEIGHT = math.sqrt(3) * 127.5
OPAQUE = 255


@dataclasses.dataclass(frozen=True, kw_only=True)
class Quantized:
    """Retain reserved working-palette entries even when the image doesn't use them."""

    image: PIL.Image.Image
    palette: Colors


def features(colors: Colors) -> Features:
    """Measure visible error on both light and dark backgrounds.

    Args:
        colors: Straight RGBA entries.

    Returns:
        Alpha-weighted color and opacity coordinates for clustering.
    """
    values = colors.astype(float)
    alpha = values[:, 3:4] / 255
    return np.concatenate(
        (alpha * (values[:, :3] - 127.5), alpha * ALPHA_WEIGHT),
        axis=1,
    )


def colors_from_centers(centers: Features, *, opaque: bool) -> Colors:
    """Keep opaque interiors opaque and antialiased edges partially transparent.

    Args:
        centers: Cluster centers in the alpha-aware feature space.
        opaque: Whether these clusters represent fully opaque pixels.

    Returns:
        Integer RGBA candidates in the same opacity class as their source pixels.
    """
    alpha = centers[:, 3] / ALPHA_WEIGHT
    rgb = centers[:, :3] / alpha[:, None] + 127.5
    opacity = (
        np.full(len(centers), 255)
        if opaque
        else np.clip(np.floor(alpha * 255 + 0.5), 1, 254)
    )
    return np.column_stack((np.clip(np.floor(rgb + 0.5), 0, 255), opacity)).astype(
        np.uint8,
    )


def mean_error(
    values: Features,
    weights: Features,
    indices: Indices,
) -> tuple[Features, float]:
    """Weight frequent fill colors more strongly than isolated fringe pixels.

    Args:
        values: Unique source colors in feature space.
        weights: Their pixel counts.
        indices: The source colors in this cluster.

    Returns:
        The weighted center and total squared visible error.
    """
    selected, counts = values[indices], weights[indices]
    center = np.sum(selected * counts[:, None], axis=0) / np.sum(counts)
    error = np.sum(counts[:, None] * (selected - center) ** 2)
    return center, float(error)


def split_cluster(
    values: Features,
    weights: Features,
    indices: Indices,
) -> tuple[Indices, Indices]:
    """Allocate dynamic colors where splitting removes the most visible error.

    Args:
        values: Unique source colors in feature space.
        weights: Their pixel counts.
        indices: At least two colors to divide along their principal axis.

    Returns:
        Two nonempty source-color clusters.
    """
    selected, counts = values[indices], weights[indices]
    center, _ = mean_error(values, weights, indices)
    difference = selected - center
    _, vectors = np.linalg.eigh((difference * counts[:, None]).T @ difference)
    order = np.argsort(selected @ vectors[:, -1], kind="stable")
    ordered = indices[order]
    cumulative_weights = np.cumsum(weights[ordered])
    cumulative_values = np.cumsum(values[ordered] * weights[ordered, None], axis=0)
    scores = np.sum(cumulative_values[:-1] ** 2, axis=1) / cumulative_weights[
        :-1
    ] + np.sum((cumulative_values[-1] - cumulative_values[:-1]) ** 2, axis=1) / (
        cumulative_weights[-1] - cumulative_weights[:-1]
    )
    cut = int(np.argmax(scores)) + 1
    return ordered[:cut], ordered[cut:]


def initial_clusters(
    values: Features,
    weights: Features,
    groups: dict[bool, Indices],
) -> list[tuple[float, int, bool, Indices]]:
    """Share the dynamic color budget between opaque fills and transparent edges.

    Args:
        values: Unique source colors in feature space.
        weights: Their pixel counts.
        groups: Opaque and partial colors, excluding the reserved colors.

    Returns:
        At most 251 weighted clusters, with their opacity classes intact.
    """
    heap: list[tuple[float, int, bool, Indices]] = []
    counter = itertools.count()
    for opaque, indices in groups.items():
        if len(indices):
            heapq.heappush(
                heap,
                (
                    -mean_error(values, weights, indices)[1],
                    next(counter),
                    opaque,
                    indices,
                ),
            )
    while heap and len(heap) < COLOR_LIMIT - len(RESERVED):
        error, _, opaque, indices = heapq.heappop(heap)
        if len(indices) == 1:
            heapq.heappush(heap, (error, next(counter), opaque, indices))
            break
        for part in split_cluster(values, weights, indices):
            heapq.heappush(
                heap,
                (
                    -mean_error(values, weights, part)[1],
                    next(counter),
                    opaque,
                    part,
                ),
            )
    return heap


def refine_colors(
    target: Features,
    weights: Features,
    centers: Features,
    *,
    opaque: bool,
) -> tuple[Colors, Indices]:
    """Keep red, yellow, white, and black available as frozen opaque candidates.

    Args:
        target: Unique source colors for one opacity class.
        weights: Their pixel counts.
        centers: Initial dynamic cluster centers.
        opaque: Whether the candidates must be fully opaque.

    Returns:
        Rounded palette candidates and each source color's nearest candidate.
    """
    fixed = RESERVED[1:] if opaque else np.empty((0, 4), dtype=np.uint8)
    frozen = features(fixed)
    centers = np.concatenate((frozen, centers))
    previous = None
    for _ in range(ITERATION_LIMIT):
        candidates = colors_from_centers(centers, opaque=opaque)
        candidates[: len(fixed)] = fixed
        rounded = features(candidates)
        distances = np.sum((target[:, None] - rounded[None, :]) ** 2, axis=2)
        labels = np.argmin(distances, axis=1)
        if previous is not None and np.array_equal(labels, previous):
            break
        previous = labels
        centers = rounded
        for index in range(len(fixed), len(centers)):
            selected = labels == index
            if np.any(selected):
                centers[index] = np.sum(
                    target[selected] * weights[selected, None],
                    axis=0,
                ) / np.sum(weights[selected])
    candidates = colors_from_centers(centers, opaque=opaque)
    candidates[: len(fixed)] = fixed
    distances = np.sum((target[:, None] - features(candidates)[None, :]) ** 2, axis=2)
    return candidates, np.argmin(distances, axis=1)


def palette_group(
    values: Features,
    weights: Features,
    indices: Indices,
    clusters: list[tuple[float, int, bool, Indices]],
    palette_length: int,
    *,
    opaque: bool,
) -> tuple[Colors, Indices]:
    """Assign indices without spending dynamic entries on the reserved colors.

    Args:
        values: All unique source colors in feature space.
        weights: Their pixel counts.
        indices: The colors in this opacity class.
        clusters: Initial clusters for both opacity classes.
        palette_length: The entries already allocated to the working palette.
        opaque: Whether these pixels are fully opaque.

    Returns:
        Additional palette colors and the source colors' final palette indices.
    """
    centers = np.array([
        mean_error(values, weights, part)[0]
        for _, _, category, part in clusters
        if category == opaque
    ]).reshape(-1, 4)
    candidates, labels = refine_colors(
        values[indices],
        weights[indices],
        centers,
        opaque=opaque,
    )
    fixed_count = len(RESERVED) - 1 if opaque else 0
    destination = np.arange(
        palette_length,
        palette_length + len(candidates) - fixed_count,
    )
    if opaque:
        destination = np.concatenate((np.arange(1, len(RESERVED)), destination))
    return candidates[fixed_count:], destination[labels]


def quantize(image: PIL.Image.Image) -> Quantized:
    """Use at most 256 RGBA entries without dithering or invented visible pixels.

    Args:
        image: The antialiased RGBA fire map.

    Returns:
        Quantized pixels and the working palette, including all five reserved entries.
    """
    source = np.asarray(image)
    colors, inverse, counts = np.unique(
        source.reshape(-1, 4),
        axis=0,
        return_inverse=True,
        return_counts=True,
    )
    values, weights = features(colors), counts.astype(float)
    fixed_source = np.any(np.all(colors[:, None] == RESERVED[None, 1:], axis=2), axis=1)
    groups = {
        False: np.flatnonzero((colors[:, 3] > 0) & (colors[:, 3] < OPAQUE)),
        True: np.flatnonzero(colors[:, 3] == OPAQUE),
    }
    clusters = initial_clusters(
        values,
        weights,
        {opaque: indices[~fixed_source[indices]] for opaque, indices in groups.items()},
    )
    palette = RESERVED.copy()
    mapping = np.zeros(len(colors), dtype=np.int64)
    for opaque, indices in groups.items():
        if not len(indices):
            continue
        additional, mapping[indices] = palette_group(
            values,
            weights,
            indices,
            clusters,
            len(palette),
            opaque=opaque,
        )
        palette = np.concatenate((palette, additional))
    pixels = palette[mapping[inverse]].reshape(source.shape)
    return Quantized(image=PIL.Image.fromarray(pixels), palette=palette)
