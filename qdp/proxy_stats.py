"""Persistent proxy statistics: success/failure tracking, latency, scoring."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_STATS_DIR = os.path.join(
    os.environ.get("APPDATA") if os.name == "nt"
    else os.path.join(os.environ["HOME"], ".config"),
    "qobuz-dl",
)
STATS_FILE = os.path.join(_STATS_DIR, "proxy_stats.json")

_LOCK = threading.Lock()


@dataclass
class ProxyStat:
    total: int = 0
    success: int = 0
    failure: int = 0
    avg_latency_ms: float = 0.0
    last_success: str = ""
    last_failure: str = ""
    # transient runtime fields (not persisted)
    consecutive_failures: int = 0

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.success / self.total

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("consecutive_failures", None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ProxyStat":
        d = dict(d)
        d.pop("consecutive_failures", None)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _load_raw() -> dict:
    if not os.path.isfile(STATS_FILE):
        return {}
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("Failed to read proxy stats: %s", exc)
        return {}


def _save_raw(data: dict):
    os.makedirs(_STATS_DIR, exist_ok=True)
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        logger.debug("Failed to write proxy stats: %s", exc)


def load_stats() -> Dict[str, ProxyStat]:
    raw = _load_raw()
    return {url: ProxyStat.from_dict(d) for url, d in raw.items()}


def save_stats(stats: Dict[str, ProxyStat]):
    _save_raw({url: s.to_dict() for url, s in stats.items()})


def record_success(proxy: str, latency_ms: float = None):
    """Record a successful request for *proxy*.

    *latency_ms* is optional — when ``None`` (or 0), the running average is
    left untouched so that callers which cannot measure latency (e.g. the
    download pipeline) don't skew the stats.
    """
    with _LOCK:
        stats = load_stats()
        entry = stats.setdefault(proxy, ProxyStat())
        entry.total += 1
        entry.success += 1
        entry.consecutive_failures = 0
        # Only update running average when a real latency is provided.
        if latency_ms is not None and latency_ms > 0:
            if entry.avg_latency_ms == 0:
                entry.avg_latency_ms = latency_ms
            else:
                entry.avg_latency_ms = (
                    entry.avg_latency_ms * (entry.success - 1) + latency_ms
                ) / entry.success
        entry.last_success = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        save_stats(stats)


def record_failure(proxy: str):
    """Record a failed request for *proxy*."""
    with _LOCK:
        stats = load_stats()
        entry = stats.setdefault(proxy, ProxyStat())
        entry.total += 1
        entry.failure += 1
        entry.consecutive_failures += 1
        entry.last_failure = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        save_stats(stats)


def record_test_result(proxy: str, success: bool, latency_ms: float = 0.0):
    """Record a connectivity test result."""
    if success:
        record_success(proxy, latency_ms)
    else:
        record_failure(proxy)


# --- Scoring / ranking ---

_EXPLORATION_MIN_SAMPLES = 5
_EXPLORATION_BONUS = 0.9
_CONSECUTIVE_FAIL_THRESHOLD = 5
_CONSECUTIVE_FAIL_PENALTY = 0.3


def compute_score(stat: ProxyStat) -> float:
    """Score = success_rate * 0.7 + (1 - normalized_latency) * 0.3.

    * New proxies (total < 5) receive an exploration bonus.
    * Proxies with many consecutive failures are penalised.
    """
    if stat.total == 0:
        return _EXPLORATION_BONUS

    success_rate = stat.success_rate

    # Normalise latency: assume 0ms → 1.0, 5000ms → 0.0
    norm_latency = max(0.0, 1.0 - stat.avg_latency_ms / 5000.0)

    score = success_rate * 0.7 + norm_latency * 0.3

    # Exploration bonus for low-sample proxies
    if stat.total < _EXPLORATION_MIN_SAMPLES:
        score = max(score, _EXPLORATION_BONUS)

    # Penalty for consecutive failures
    if stat.consecutive_failures >= _CONSECUTIVE_FAIL_THRESHOLD:
        score *= _CONSECUTIVE_FAIL_PENALTY

    return score


def rank_proxies(proxies: List[str]) -> List[Tuple[str, float]]:
    """Return *proxies* sorted best-first with their scores."""
    stats = load_stats()
    scored = []
    for p in proxies:
        entry = stats.get(p, ProxyStat())
        scored.append((p, compute_score(entry)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def get_best_proxy(proxies: List[str]) -> Optional[str]:
    """Return the highest-scoring proxy from *proxies*, or None.

    Returns None when there is insufficient data to differentiate proxies
    (e.g. all proxies have zero samples), so the caller can fall back to
    round-robin selection.
    """
    ranked = rank_proxies(proxies)
    if not ranked:
        return None
    # If all proxies have the same score (e.g. all unexplored), return None
    # so the caller falls back to round-robin for fair distribution.
    scores = {score for _, score in ranked}
    if len(scores) == 1:
        # Check if any proxy has real data; if not, defer to round-robin.
        stats = load_stats()
        has_data = any(stats.get(p, ProxyStat()).total > 0 for p in proxies)
        if not has_data:
            return None
    return ranked[0][0]
