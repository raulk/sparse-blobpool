"""Country-based latency model loaded from JSON data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

type Country = str


def _compute_jitter_ratio(base_ms: float) -> float:
    """Distance-based jitter: higher for longer distances."""
    if base_ms < 30:
        return 0.05
    elif base_ms < 80:
        return 0.10
    else:
        return 0.15


@dataclass(frozen=True)
class LatencyParams:
    """Parameters for modeling network latency between countries."""

    base_ms: float
    jitter_ratio: float


class CountryLatencyModel:
    """Country-to-country latency lookup loaded from JSON.

    The JSON format is:
    {
        "country_a": {
            "country_b": latency_ms,
            "default": fallback_latency_ms
        },
        ...
    }
    """

    def __init__(self, data: dict[str, dict[str, float]]) -> None:
        self._raw = data
        self._cache: dict[tuple[Country, Country], LatencyParams] = {}

        countries: set[Country] = set()
        for country, destinations in data.items():
            if country != "default":
                countries.add(country)
            for dest in destinations:
                if dest != "default":
                    countries.add(dest)
        self._countries = frozenset(countries)

    @classmethod
    def load(cls, path: Path | None = None) -> CountryLatencyModel:
        if path is None:
            path = Path(__file__).parent.parent / "country_latencies.json"
        with path.open() as f:
            data = json.load(f)
        return cls(data)

    def get_latency(self, from_: Country, to: Country) -> LatencyParams:
        """Lookup latency with fallback to 'default' values."""
        key = (from_, to)
        if key in self._cache:
            return self._cache[key]

        # Direct lookup
        if from_ in self._raw and to in self._raw[from_]:
            base_ms = float(self._raw[from_][to])
        # Try fallback for source country
        elif from_ in self._raw and "default" in self._raw[from_]:
            base_ms = float(self._raw[from_]["default"])
        # Try reverse lookup (matrix may not be symmetric)
        elif to in self._raw and from_ in self._raw[to]:
            base_ms = float(self._raw[to][from_])
        # Try reverse fallback
        elif to in self._raw and "default" in self._raw[to]:
            base_ms = float(self._raw[to]["default"])
        # Global fallback
        else:
            base_ms = 100.0

        params = LatencyParams(base_ms, _compute_jitter_ratio(base_ms))
        self._cache[key] = params
        return params

    @property
    def countries(self) -> frozenset[Country]:
        return self._countries


@dataclass(frozen=True)
class CountryWeights:
    """Node distribution weights by country.

    Loaded from weights.json, which maps country names to node counts.
    Only countries in this file are used for node placement (whitelist).
    """

    weights: dict[Country, int]

    @classmethod
    def load(cls, path: Path | None = None) -> CountryWeights:
        if path is None:
            path = Path(__file__).parent.parent / "weights.json"
        with path.open() as f:
            data: dict[str, int] = json.load(f)
        return cls(weights=data)

    @property
    def countries(self) -> list[Country]:
        return list(self.weights.keys())

    @property
    def total(self) -> int:
        return sum(self.weights.values())

    def normalized(self) -> dict[Country, float]:
        """Return probabilities summing to 1.0."""
        total = self.total
        return {country: count / total for country, count in self.weights.items()}


# Module-level singletons loaded once
LATENCY_MODEL = CountryLatencyModel.load()
COUNTRY_WEIGHTS = CountryWeights.load()
