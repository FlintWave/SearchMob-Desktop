"""Dependency-free string distance/similarity metrics for spell correction.

Pure ports of the Android on-device corrector's Kotlin helpers:

* `osa_distance` -- Optimal String Alignment distance (Damerau-Levenshtein restricted to
  adjacent transpositions), banded with an early cutoff so candidate generation can bail out
  cheaply when a word is obviously too far from the query term.
* `jaro_winkler` -- Jaro similarity boosted by a shared leading prefix, used as the final
  ranking score for surviving candidates.

Neither function does any I/O and neither raises for ordinary string input; they are the
arithmetic core that the corrector leans on, so they are kept small and exact.
"""

from __future__ import annotations

_MAX_INT = 2**31 - 1


def osa_distance(a: str, b: str, max_distance: int | None = None) -> int:
    """Optimal String Alignment distance between `a` and `b`.

    Like Damerau-Levenshtein but a substring may be edited at most once, so only adjacent
    transpositions count as a single operation. `max_distance` bands the computation: when the
    running minimum of a row exceeds it, the function returns `max_distance + 1` early instead of
    finishing the full table. A `None` cap means "no cap" (effectively unbounded).
    """
    cap = _MAX_INT if max_distance is None else max_distance

    if a == b:
        return 0

    len_a = len(a)
    len_b = len(b)
    if abs(len_a - len_b) > cap:
        return cap + 1
    if len_a == 0:
        return len_b
    if len_b == 0:
        return len_a

    # Three rolling rows: the one two back (for transpositions), the previous, and the current.
    prev_prev = [0] * (len_b + 1)
    prev = list(range(len_b + 1))
    curr = [0] * (len_b + 1)

    for i in range(1, len_a + 1):
        curr[0] = i
        row_min = curr[0]
        for j in range(1, len_b + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            value = min(
                prev[j] + 1,  # deletion
                curr[j - 1] + 1,  # insertion
                prev[j - 1] + cost,  # substitution
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                value = min(value, prev_prev[j - 2] + 1)  # transposition
            curr[j] = value
            if value < row_min:
                row_min = value
        if row_min > cap:
            return cap + 1
        prev_prev, prev, curr = prev, curr, prev_prev

    return prev[len_b]


def jaro_winkler(a: str, b: str) -> float:
    """Jaro-Winkler similarity in [0.0, 1.0].

    Computes the Jaro similarity, then adds a prefix bonus of `prefix * 0.1 * (1 - jaro)` where
    `prefix` is the length of the common leading run capped at 4 characters. Two empty strings
    score 1.0; exactly one empty string scores 0.0; no matched characters scores 0.0.
    """
    if a == b:
        return 1.0

    len_a = len(a)
    len_b = len(b)
    if len_a == 0 or len_b == 0:
        return 0.0

    match_window = max(len_a, len_b) // 2 - 1
    if match_window < 0:
        match_window = 0

    a_matched = [False] * len_a
    b_matched = [False] * len_b

    matches = 0
    for i in range(len_a):
        start = max(0, i - match_window)
        end = min(i + match_window + 1, len_b)
        for j in range(start, end):
            if b_matched[j]:
                continue
            if a[i] != b[j]:
                continue
            a_matched[i] = True
            b_matched[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    # Count transpositions: matched characters out of order.
    transpositions = 0
    k = 0
    for i in range(len_a):
        if not a_matched[i]:
            continue
        while not b_matched[k]:
            k += 1
        if a[i] != b[k]:
            transpositions += 1
        k += 1

    m = float(matches)
    jaro = (m / len_a + m / len_b + (m - transpositions / 2.0) / m) / 3.0

    prefix = 0
    for i in range(min(4, len_a, len_b)):
        if a[i] == b[i]:
            prefix += 1
        else:
            break

    return jaro + prefix * 0.1 * (1.0 - jaro)
