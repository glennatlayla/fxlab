"""
Largest Triangle Three Buckets (LTTB) downsampling algorithm.

Purpose:
    Reduce a dense time-series to a target number of points while preserving
    the visual fidelity of the original data.  Used server-side to cap chart
    payloads at ≤ 2 000 wire points without sacrificing peak-to-trough accuracy.

Responsibilities:
    - Implement the LTTB algorithm (Steinarsson 2013).
    - Accept any (x, y) float-pair sequence and return a downsampled version.
    - Always preserve the first and last input points.

Does NOT:
    - Perform datetime conversion or unit handling.
    - Access databases, files, or network resources.
    - Handle unsorted input (caller must pre-sort by x).

Dependencies:
    - math (stdlib only).

Error conditions:
    - ValueError: if threshold < 2.
    - Returns input unchanged if len(points) <= threshold or <= 2.

Example:
    from libs.utils.lttb import lttb_downsample

    raw = [(float(i), float(i ** 2)) for i in range(10_000)]
    reduced = lttb_downsample(raw, threshold=2_000)
    assert len(reduced) <= 2_000
    assert reduced[0] == raw[0]
    assert reduced[-1] == raw[-1]
"""

from __future__ import annotations

import math


def lttb_downsample(
    points: list[tuple[float, float]],
    threshold: int,
) -> list[tuple[float, float]]:
    """
    Downsample ``points`` to at most ``threshold`` points using LTTB.

    Largest Triangle Three Buckets selects each retained point by maximising
    the area of the triangle it forms with the previously-selected point (A)
    and the average of the next bucket (C).  This greedily preserves visual
    extremes (peaks and troughs) rather than uniform spacing.

    Algorithm reference:
        Steinarsson, S. (2013).  Downsampling time series for visual
        representation. MSc thesis, University of Iceland.

    Args:
        points:    Sorted list of (x, y) float pairs.  Must be pre-sorted
                   by x (ascending).  May be empty.
        threshold: Maximum number of output points.  Must be >= 2 when the
                   input has more than 2 points.

    Returns:
        Downsampled list of (x, y) tuples.  Guaranteed:
        - len(result) <= threshold
        - result[0] == points[0]  (first point always retained)
        - result[-1] == points[-1]  (last point always retained)
        - If len(points) <= threshold or len(points) <= 2, returns a copy of
          the input unchanged (no downsampling performed).

    Raises:
        ValueError: If threshold < 2.

    Example:
        >>> pts = [(float(i), float(i) * 1.5) for i in range(5000)]
        >>> out = lttb_downsample(pts, threshold=100)
        >>> assert len(out) <= 100
        >>> assert out[0] == pts[0]
        >>> assert out[-1] == pts[-1]
    """
    if threshold < 2:
        raise ValueError(f"threshold must be >= 2, got {threshold}")

    n = len(points)
    if n == 0:
        return []
    if n <= 2 or n <= threshold:
        # No downsampling needed — return a copy so callers cannot mutate state.
        return list(points)

    # Always keep the first point.
    sampled: list[tuple[float, float]] = [points[0]]

    # Number of data buckets in the middle section (first and last excluded).
    # Bucket width may be fractional; floor/ceil are applied per index below.
    every: float = (n - 2) / (threshold - 2)

    # Index of the last appended point (starts at first point, index 0).
    a: int = 0

    for i in range(threshold - 2):
        # ---- Compute the average point (C) of the *next* bucket -------------
        # The next bucket feeds the "C" vertex of the maximised triangle.
        avg_range_start = int(math.floor((i + 1) * every)) + 1
        avg_range_end = int(math.floor((i + 2) * every)) + 1
        avg_range_end = min(avg_range_end, n)  # clamp to valid range

        avg_x = 0.0
        avg_y = 0.0
        bucket_size = avg_range_end - avg_range_start
        for j in range(avg_range_start, avg_range_end):
            avg_x += points[j][0]
            avg_y += points[j][1]
        avg_x /= bucket_size
        avg_y /= bucket_size

        # ---- Find the point in the *current* bucket maximising triangle area -
        range_start = int(math.floor(i * every)) + 1
        range_end = int(math.floor((i + 1) * every)) + 1
        range_end = min(range_end, n)  # clamp to valid range

        ax, ay = points[a]  # vertex A: previously selected point

        max_area = -1.0
        max_area_idx = range_start
        for j in range(range_start, range_end):
            bx, by = points[j]
            # Area of triangle with vertices A, B (candidate), C (bucket avg).
            # Formula: 0.5 * |ax(by − cy) + bx(cy − ay) + cx(ay − by)|
            # Simplified to avoid the 0.5 factor (monotone under max selection):
            area = abs((ax - avg_x) * (by - ay) - (ax - bx) * (avg_y - ay))
            if area > max_area:
                max_area = area
                max_area_idx = j

        sampled.append(points[max_area_idx])
        a = max_area_idx  # selected point becomes A for next iteration

    # Always keep the last point.
    sampled.append(points[-1])
    return sampled
