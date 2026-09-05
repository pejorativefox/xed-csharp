# -*- coding: utf-8 -*-
"""Subsequence fuzzy matcher for the quick-open finder.

Headless-safe (no GTK imports) so unit tests run without a display.
Extracted from xedcsharp/xedcsharp/intelligence.py.
"""

from __future__ import annotations


#: Chars that start a new matchable segment (basename, extension, snake parts).
_FUZZY_SEPARATORS = frozenset("/\\-_ .")


def fuzzy_score(query: str, candidate: str) -> int | None:
    """Subsequence match score (lower is better), or None for no match.

    Rewards prefix/segment starts and consecutive runs, penalizes gaps;
    case-insensitive.
    """
    q = (query or "").lower()
    c = (candidate or "").lower()
    if not q:
        return 0
    total = 0
    idx = 0
    prev = -1
    for n, ch in enumerate(q):
        i = c.find(ch, idx)
        if i < 0:
            return None
        if n == 0:
            total += i
            if i == 0:
                total -= 2
        else:
            total += (i - prev - 1) * 2
            if i == prev + 1:
                total -= 1
        if i > 0 and c[i - 1] in _FUZZY_SEPARATORS:
            total -= 2
        prev = i
        idx = i + 1
    return total


def fuzzy_find(query: str, paths: list[str], limit: int = 50) -> list[str]:
    """Rank paths by fuzzy_score; ties break shorter-then-alphabetical."""
    q = (query or "").strip()
    if not q:
        return list(paths[:limit])
    scored = []
    for path in paths:
        score = fuzzy_score(q, path)
        if score is not None:
            scored.append((score, len(path), path))
    scored.sort(key=lambda item: (item[0], item[1], item[2]))
    return [path for _, _, path in scored[:limit]]
