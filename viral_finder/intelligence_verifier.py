"""
intelligence_verifier.py — Intelligence Transport Verifier for HotShort.

Enforces the contract:

    Every Evidence packet produced by the pipeline MUST end in exactly one of:

        CONSUMED          — it influenced a downstream decision
        EXPLICITLY_REJECTED — evaluated and intentionally discarded (reason recorded)
        ORPHANED          — reached end of pipeline without any consumer  ← BUG

An orphaned Evidence packet is not an acceptable outcome.
It means intelligence was generated, paid for (in CPU / LLM tokens), but ignored.

Usage (called at end of orchestrate()):

    from viral_finder.intelligence_verifier import IntelligenceVerifier

    verifier = IntelligenceVerifier()
    verifier.scan(final_candidates, all_candidates, rejected_candidates)
    report = verifier.render_report()
    log.info(report)
    print(report)
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from viral_finder.cognition import Evidence, IntelligenceArtifact

log = logging.getLogger("intelligence_verifier")


class IntelligenceVerifier:
    """
    Scans all Evidence objects that were produced during a pipeline run,
    classifies each one, and emits a report.
    """

    def __init__(self):
        # All (evidence, candidate_id, candidate_source) tuples found during scan
        self._packets: List[Tuple[Evidence, str, str]] = []
        # Summary counts
        self.consumed_count: int = 0
        self.rejected_count: int = 0
        self.orphaned_count: int = 0
        # Per-producer breakdown: producer -> {CONSUMED: n, EXPLICITLY_REJECTED: n, ORPHANED: n}
        self._by_producer: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"CONSUMED": 0, "EXPLICITLY_REJECTED": 0, "ORPHANED": 0}
        )
        # Per-type breakdown: type -> state -> count
        self._by_type: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"CONSUMED": 0, "EXPLICITLY_REJECTED": 0, "ORPHANED": 0}
        )
        # Orphan details for bug reporting
        self._orphans: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(
        self,
        final_candidates: List[Dict],
        all_candidates: Optional[List[Dict]] = None,
        rejected_candidates: Optional[List[Dict]] = None,
    ) -> "IntelligenceVerifier":
        """
        Walk every candidate (final, intermediate, rejected) and collect all
        Evidence objects from their IntelligenceArtifact.evidence_stream.
        Classify each one and build the report data.
        """
        self._packets.clear()
        self.consumed_count = 0
        self.rejected_count = 0
        self.orphaned_count = 0
        self._by_producer.clear()
        self._by_type.clear()
        self._orphans.clear()

        all_pools = [
            (final_candidates or [], "final"),
            (all_candidates or [], "intermediate"),
            (rejected_candidates or [], "rejected"),
        ]

        seen_evidence_ids: set = set()  # avoid counting same Evidence object twice

        for pool, source in all_pools:
            for cand in pool:
                if not isinstance(cand, dict):
                    continue
                cid = str(cand.get("cid", cand.get("id", "unknown")))
                artifact: Optional[IntelligenceArtifact] = cand.get("intelligence")
                if not isinstance(artifact, IntelligenceArtifact):
                    continue

                for ev in artifact.evidence_stream:
                    ev_id = id(ev)
                    if ev_id in seen_evidence_ids:
                        continue
                    seen_evidence_ids.add(ev_id)

                    self._packets.append((ev, cid, source))
                    state = ev.transport_state

                    # Totals
                    if state == "CONSUMED":
                        self.consumed_count += 1
                    elif state == "EXPLICITLY_REJECTED":
                        self.rejected_count += 1
                    else:  # ORPHANED
                        self.orphaned_count += 1
                        self._orphans.append({
                            "type": ev.type,
                            "value": ev.value,
                            "producer": ev.producer,
                            "confidence": ev.confidence,
                            "candidate_id": cid,
                            "candidate_source": source,
                        })

                    # By producer
                    self._by_producer[ev.producer][state] += 1
                    # By type
                    self._by_type[ev.type][state] += 1

        return self

    @property
    def has_orphans(self) -> bool:
        return self.orphaned_count > 0

    @property
    def total(self) -> int:
        return self.consumed_count + self.rejected_count + self.orphaned_count

    def render_report(self) -> str:
        """
        Returns a formatted log string suitable for printing to the pipeline log.
        """
        lines = []
        lines.append("")
        lines.append("=" * 60)
        lines.append("     INTELLIGENCE TRANSPORT VERIFIER — AUDIT REPORT")
        lines.append("=" * 60)

        total = self.total
        if total == 0:
            lines.append("  No Evidence packets found in any candidate.")
            lines.append("  (IntelligenceArtifact.evidence_stream was never populated.)")
            lines.append("=" * 60)
            return "\n".join(lines)

        # --- Summary ---
        lines.append("")
        lines.append("[SUMMARY]")
        lines.append(f"  Total Evidence Packets : {total}")
        lines.append(f"  CONSUMED               : {self.consumed_count}"
                     + (f"  ({self.consumed_count/total*100:.0f}%)" if total else ""))
        lines.append(f"  EXPLICITLY_REJECTED    : {self.rejected_count}"
                     + (f"  ({self.rejected_count/total*100:.0f}%)" if total else ""))
        lines.append(f"  ORPHANED               : {self.orphaned_count}"
                     + (" ← BUG" if self.orphaned_count > 0 else "  ✓"))

        # --- By producer ---
        if self._by_producer:
            lines.append("")
            lines.append("[BY PRODUCER]")
            for producer, counts in sorted(self._by_producer.items()):
                lines.append(
                    f"  {producer:<28} "
                    f"consumed={counts['CONSUMED']:>3}  "
                    f"rejected={counts['EXPLICITLY_REJECTED']:>3}  "
                    f"orphaned={counts['ORPHANED']:>3}"
                    + (" ← BUG" if counts["ORPHANED"] > 0 else "")
                )

        # --- By evidence type ---
        if self._by_type:
            lines.append("")
            lines.append("[BY EVIDENCE TYPE]")
            for ev_type, counts in sorted(self._by_type.items()):
                lines.append(
                    f"  {ev_type:<28} "
                    f"consumed={counts['CONSUMED']:>3}  "
                    f"rejected={counts['EXPLICITLY_REJECTED']:>3}  "
                    f"orphaned={counts['ORPHANED']:>3}"
                    + (" ← BUG" if counts["ORPHANED"] > 0 else "")
                )

        # --- Orphan detail (the bug list) ---
        if self._orphans:
            lines.append("")
            lines.append("[ORPHANED PACKETS — PIPELINE BUG REPORT]")
            lines.append("  These intelligence signals were produced but never consumed")
            lines.append("  or explicitly rejected. Each one is a silent information loss.")
            lines.append("")
            for o in self._orphans:
                lines.append(
                    f"  ✗ type={o['type']:<22} value={str(o['value']):<8} "
                    f"producer={o['producer']:<20} "
                    f"candidate={o['candidate_id']} ({o['candidate_source']})"
                )
        else:
            lines.append("")
            lines.append("  ✓ All Evidence packets were consumed or explicitly rejected.")
            lines.append("  ✓ No orphaned intelligence detected.")

        lines.append("")
        lines.append("=" * 60)

        # Final verdict
        if self.orphaned_count > 0:
            lines.append(f"  VERDICT: {self.orphaned_count} ORPHANED PACKET(S) — PIPELINE BUG(S) DETECTED")
        else:
            lines.append("  VERDICT: CLEAN — All intelligence accounted for.")
        lines.append("=" * 60)
        lines.append("")

        return "\n".join(lines)

    def get_bug_signals(self) -> List[Dict[str, Any]]:
        """Returns the list of orphaned Evidence dicts for programmatic use."""
        return list(self._orphans)


# ---------------------------------------------------------------------------
# Singleton for the current run (reset at start of orchestrate())
# ---------------------------------------------------------------------------

_active_verifier: Optional[IntelligenceVerifier] = None


def get_verifier() -> IntelligenceVerifier:
    global _active_verifier
    if _active_verifier is None:
        _active_verifier = IntelligenceVerifier()
    return _active_verifier


def reset_verifier() -> IntelligenceVerifier:
    global _active_verifier
    _active_verifier = IntelligenceVerifier()
    return _active_verifier
