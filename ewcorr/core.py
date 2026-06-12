"""Core correlation engine for EWCORR.

The engine ingests passive EW/ELINT observation records and groups them into
candidate emitter clusters using a single-link agglomerative pass over a
three-dimensional similarity metric:

  * time      -- observations of one emitter recur within a coherence window
  * frequency -- center frequency (MHz) should match within a tolerance
  * bearing   -- line-of-bearing (degrees) should match within a tolerance,
                 with proper circular (wrap-around) distance handling

Two observations are "linked" when ALL three gates pass. Clusters are the
connected components of the resulting link graph (single-linkage), which is
the standard deinterleaving approach for sparse ELINT logs.
"""
from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Sequence


class EWCorrError(Exception):
    """Raised on malformed input or impossible correlation requests."""


@dataclass
class Observation:
    """A single passive EW/ELINT detection record."""

    obs_id: str
    timestamp: float          # epoch seconds (UTC)
    freq_mhz: float           # center frequency in MHz
    bearing_deg: float        # line-of-bearing 0..360 (degrees)
    sensor: str = ""
    power_dbm: float | None = None
    raw_time: str = ""        # original timestamp string, for display

    def as_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class CorrelationConfig:
    """Gating tolerances for linking two observations."""

    time_window_s: float = 30.0      # max seconds between linked detections
    freq_tol_mhz: float = 0.5        # max |df| in MHz
    bearing_tol_deg: float = 5.0     # max circular bearing delta in degrees

    def validate(self) -> None:
        if self.time_window_s <= 0:
            raise EWCorrError("time_window_s must be positive")
        if self.freq_tol_mhz < 0:
            raise EWCorrError("freq_tol_mhz must be non-negative")
        if not (0 <= self.bearing_tol_deg <= 180):
            raise EWCorrError("bearing_tol_deg must be in [0, 180]")


@dataclass
class EmitterCluster:
    """A correlated set of observations attributed to one candidate emitter."""

    emitter_id: str
    observations: list[Observation] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.observations)

    @property
    def first_seen(self) -> float:
        return min(o.timestamp for o in self.observations)

    @property
    def last_seen(self) -> float:
        return max(o.timestamp for o in self.observations)

    @property
    def duration_s(self) -> float:
        return self.last_seen - self.first_seen

    @property
    def freq_center_mhz(self) -> float:
        return sum(o.freq_mhz for o in self.observations) / self.count

    @property
    def freq_span_mhz(self) -> float:
        fs = [o.freq_mhz for o in self.observations]
        return max(fs) - min(fs)

    @property
    def bearing_mean_deg(self) -> float:
        """Circular mean of bearings, returned in [0, 360)."""
        sx = sum(math.sin(math.radians(o.bearing_deg)) for o in self.observations)
        sy = sum(math.cos(math.radians(o.bearing_deg)) for o in self.observations)
        ang = math.degrees(math.atan2(sx, sy))
        return ang % 360.0

    @property
    def bearing_spread_deg(self) -> float:
        """Max circular deviation of any bearing from the circular mean."""
        mean = self.bearing_mean_deg
        return max(_circular_delta(o.bearing_deg, mean) for o in self.observations)

    @property
    def sensors(self) -> list[str]:
        return sorted({o.sensor for o in self.observations if o.sensor})

    def confidence(self) -> float:
        """Heuristic 0..1 confidence the cluster is a single real emitter.

        More observations, a single bearing line, and a tight frequency
        raise confidence; wide spreads and singletons lower it.
        """
        if self.count <= 1:
            return 0.25
        n_factor = min(1.0, self.count / 5.0)
        b_factor = max(0.0, 1.0 - self.bearing_spread_deg / 30.0)
        f_factor = max(0.0, 1.0 - self.freq_span_mhz / 2.0)
        return round(0.2 + 0.8 * (0.5 * n_factor + 0.3 * b_factor + 0.2 * f_factor), 3)

    def as_dict(self) -> dict:
        return {
            "emitter_id": self.emitter_id,
            "count": self.count,
            "first_seen": _iso(self.first_seen),
            "last_seen": _iso(self.last_seen),
            "duration_s": round(self.duration_s, 3),
            "freq_center_mhz": round(self.freq_center_mhz, 4),
            "freq_span_mhz": round(self.freq_span_mhz, 4),
            "bearing_mean_deg": round(self.bearing_mean_deg, 2),
            "bearing_spread_deg": round(self.bearing_spread_deg, 2),
            "sensors": self.sensors,
            "confidence": self.confidence(),
            "observation_ids": [o.obs_id for o in self.observations],
        }


def _circular_delta(a: float, b: float) -> float:
    """Smallest absolute angular distance between two bearings (0..180)."""
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> float:
    """Accept epoch seconds or ISO-8601 timestamps; return epoch seconds."""
    value = value.strip()
    if not value:
        raise EWCorrError("empty timestamp")
    # Try numeric epoch first.
    try:
        return float(value)
    except ValueError:
        pass
    iso = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise EWCorrError(f"unparseable timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _to_float(value: str, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise EWCorrError(f"invalid {field_name}: {value!r}") from exc


def parse_observations(text: str) -> list[Observation]:
    """Parse a CSV log into Observation records.

    Expected header columns (case-insensitive, extra columns ignored):
        id, time, freq_mhz, bearing_deg, [sensor], [power_dbm]

    'time' may be epoch seconds or ISO-8601. Returns observations sorted by
    timestamp. Raises EWCorrError on missing required columns or bad rows.
    """
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise EWCorrError("input has no header row")
    cols = {c.strip().lower(): c for c in reader.fieldnames}
    required = ["id", "time", "freq_mhz", "bearing_deg"]
    missing = [c for c in required if c not in cols]
    if missing:
        raise EWCorrError(f"missing required columns: {', '.join(missing)}")

    out: list[Observation] = []
    for lineno, row in enumerate(reader, start=2):
        obs_id = (row.get(cols["id"]) or "").strip()
        if not obs_id:
            raise EWCorrError(f"line {lineno}: empty id")
        raw_time = (row.get(cols["time"]) or "").strip()
        ts = _parse_time(raw_time)
        freq = _to_float(row.get(cols["freq_mhz"], ""), f"freq_mhz (line {lineno})")
        bearing = _to_float(row.get(cols["bearing_deg"], ""), f"bearing_deg (line {lineno})")
        if freq <= 0:
            raise EWCorrError(f"line {lineno}: freq_mhz must be positive")
        bearing = bearing % 360.0
        sensor = (row.get(cols["sensor"], "") if "sensor" in cols else "").strip()
        power = None
        if "power_dbm" in cols:
            pv = (row.get(cols["power_dbm"]) or "").strip()
            if pv:
                power = _to_float(pv, f"power_dbm (line {lineno})")
        out.append(
            Observation(
                obs_id=obs_id,
                timestamp=ts,
                freq_mhz=freq,
                bearing_deg=bearing,
                sensor=sensor,
                power_dbm=power,
                raw_time=raw_time,
            )
        )
    if not out:
        raise EWCorrError("no observation rows found")
    out.sort(key=lambda o: o.timestamp)
    return out


def _linked(a: Observation, b: Observation, cfg: CorrelationConfig) -> bool:
    """True when two observations pass all three correlation gates."""
    if abs(a.timestamp - b.timestamp) > cfg.time_window_s:
        return False
    if abs(a.freq_mhz - b.freq_mhz) > cfg.freq_tol_mhz:
        return False
    if _circular_delta(a.bearing_deg, b.bearing_deg) > cfg.bearing_tol_deg:
        return False
    return True


def correlate(
    observations: Sequence[Observation],
    cfg: CorrelationConfig | None = None,
) -> list[EmitterCluster]:
    """Cluster observations into candidate emitters via single-link union-find.

    Observations are time-sorted; each is compared against recent prior
    observations still inside the time window (a sliding frontier), keeping
    the pass near O(n * w) rather than O(n^2) for long logs.
    """
    cfg = cfg or CorrelationConfig()
    cfg.validate()
    obs = sorted(observations, key=lambda o: o.timestamp)
    n = len(obs)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    frontier_start = 0
    for i in range(n):
        # Advance the frontier past observations now outside the time window.
        while frontier_start < i and obs[i].timestamp - obs[frontier_start].timestamp > cfg.time_window_s:
            frontier_start += 1
        for j in range(frontier_start, i):
            if _linked(obs[i], obs[j], cfg):
                union(i, j)

    groups: dict[int, list[Observation]] = {}
    for idx in range(n):
        groups.setdefault(find(idx), []).append(obs[idx])

    clusters: list[EmitterCluster] = []
    for members in groups.values():
        members.sort(key=lambda o: o.timestamp)
        clusters.append(EmitterCluster(emitter_id="", observations=members))

    # Stable, deterministic ordering: earliest first-seen, then frequency.
    clusters.sort(key=lambda c: (c.first_seen, c.freq_center_mhz))
    for n_, c in enumerate(clusters, start=1):
        c.emitter_id = f"EM-{n_:03d}"
    return clusters


def summarize(clusters: Sequence[EmitterCluster]) -> dict:
    """Roll up cluster statistics for reporting."""
    total_obs = sum(c.count for c in clusters)
    singletons = sum(1 for c in clusters if c.count == 1)
    return {
        "emitters": len(clusters),
        "observations": total_obs,
        "singletons": singletons,
        "multi_obs_emitters": len(clusters) - singletons,
        "clusters": [c.as_dict() for c in clusters],
    }
