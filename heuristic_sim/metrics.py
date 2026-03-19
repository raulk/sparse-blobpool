from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SimulationResult:
    total_accepted: int = 0
    total_rejected: int = 0
    h1_rejections: int = 0
    h2_evictions: int = 0
    h4_disconnects: int = 0
    h5_disconnects: int = 0
    rate_limit_rejections: int = 0
    disconnects_by_behavior: dict[str, int] = field(default_factory=dict)
    false_positives: int = 0
    detection_latencies: dict[str, list[float]] = field(default_factory=dict)
    peer_scores: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    pool_occupancy: list[tuple[float, int]] = field(default_factory=list)
    peer_counts: dict[str, int] = field(default_factory=dict)
    bandwidth_by_behavior: dict[str, dict[str, int]] = field(default_factory=dict)
    log: list[dict[str, Any]] = field(default_factory=list)

    def detection_summary(self) -> dict[str, dict[str, Any]]:
        summary: dict[str, dict[str, Any]] = {}
        all_behaviors = set(self.disconnects_by_behavior.keys()) | {"honest"}
        for behavior in all_behaviors:
            summary[behavior] = {
                "detected": self.disconnects_by_behavior.get(behavior, 0),
            }
        return summary

    def summary_table(self) -> str:
        lines = [
            f"{'Behavior':<20} {'Peers':<8} {'Detected':<12} {'H1 Rej':<10} {'H2 Evict':<10} "
            f"{'H4 Disc':<10} {'H5 Disc':<10} {'FP':<5}",
            "-" * 85,
        ]
        summary = self.detection_summary()
        all_behaviors = set(self.peer_counts.keys()) | set(summary.keys())
        for behavior in sorted(all_behaviors):
            total = self.peer_counts.get(behavior, 0)
            detected = self.disconnects_by_behavior.get(behavior, 0)
            det_str = f"{detected}/{total}" if total > 0 else "0"
            h1 = str(self.h1_rejections) if behavior == "spammer" else "-"
            h2 = str(self.h2_evictions) if behavior == "selective_signaler" else "-"
            h4 = str(self.h4_disconnects) if behavior in ("withholder", "spoofer") else "-"
            h5 = str(self.h5_disconnects) if behavior in ("free_rider", "non_announcer") else "-"
            fp = str(self.false_positives) if behavior == "honest" else "-"
            lines.append(
                f"{behavior:<20} {total:<8} {det_str:<12} "
                f"{h1:<10} {h2:<10} {h4:<10} {h5:<10} {fp:<5}"
            )
        lines.append(f"\nTotal accepted: {self.total_accepted}")
        lines.append(f"Total rejected: {self.total_rejected}")
        if self.rate_limit_rejections:
            lines.append(f"Rate-limited: {self.rate_limit_rejections}")
        lines.append(f"Pool size at end: {self.pool_occupancy[-1][1] if self.pool_occupancy else 0}")
        if self.bandwidth_by_behavior:
            lines.append("\nBandwidth by behavior (bytes):")
            for beh, bw in sorted(self.bandwidth_by_behavior.items()):
                lines.append(f"  {beh:<20} in={bw['in']:>10,}  out={bw['out']:>10,}")
        return "\n".join(lines)
