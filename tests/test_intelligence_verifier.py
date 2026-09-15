"""
tests/test_intelligence_verifier.py

Tests for the Intelligence Transport Contract:
    Every Evidence packet must be CONSUMED, EXPLICITLY_REJECTED, or ORPHANED.
    An orphaned packet is a bug.
"""
import pytest
from viral_finder.cognition import Evidence, IntelligenceArtifact
from viral_finder.intelligence_verifier import IntelligenceVerifier


# ---------------------------------------------------------------------------
# Evidence transport state unit tests
# ---------------------------------------------------------------------------

class TestEvidenceTransportState:
    def test_new_evidence_is_orphaned(self):
        ev = Evidence(type="stop_scroll", value=0.8, producer="groq_trigger")
        assert ev.transport_state == "ORPHANED"

    def test_consumed_evidence(self):
        ev = Evidence(type="stop_scroll", value=0.8, producer="groq_trigger")
        ev.consume("signal_enrichment")
        assert ev.transport_state == "CONSUMED"
        assert "signal_enrichment" in ev.consumed_by

    def test_explicitly_rejected_evidence(self):
        ev = Evidence(type="memorability", value=0.3, producer="groq_trigger")
        ev.reject("score_below_threshold", "ranking")
        assert ev.transport_state == "EXPLICITLY_REJECTED"

    def test_consumed_takes_priority_over_rejected(self):
        """If evidence was consumed (even after being rejected), it's CONSUMED."""
        ev = Evidence(type="stop_scroll", value=0.9, producer="groq_trigger")
        ev.reject("low_confidence", "validation")
        ev.consume("ranking")
        # consumed_by is set → state is CONSUMED
        assert ev.transport_state == "CONSUMED"

    def test_multiple_consumers(self):
        ev = Evidence(type="curiosity_peak", value=0.75, producer="curiosity_engine")
        ev.consume("ranking")
        ev.consume("arc_assembler")
        assert "ranking" in ev.consumed_by
        assert "arc_assembler" in ev.consumed_by
        assert ev.transport_state == "CONSUMED"

    def test_consume_returns_self_for_chaining(self):
        ev = Evidence(type="stop_scroll", value=0.8, producer="groq_trigger")
        result = ev.consume("test_consumer")
        assert result is ev


# ---------------------------------------------------------------------------
# IntelligenceArtifact helper methods
# ---------------------------------------------------------------------------

class TestIntelligenceArtifact:
    def test_get_max_value_no_consumer(self):
        artifact = IntelligenceArtifact()
        artifact.evidence_stream.append(
            Evidence(type="stop_scroll", value=0.9, producer="groq_trigger")
        )
        val = artifact.get_max_value("stop_scroll")
        assert abs(val - 0.9) < 0.001
        # Without consumer arg, evidence stays ORPHANED
        assert artifact.evidence_stream[0].transport_state == "ORPHANED"

    def test_get_max_value_with_consumer_marks_consumed(self):
        artifact = IntelligenceArtifact()
        artifact.evidence_stream.append(
            Evidence(type="stop_scroll", value=0.85, producer="groq_trigger")
        )
        val = artifact.get_max_value("stop_scroll", consumer="ranking")
        assert abs(val - 0.85) < 0.001
        assert artifact.evidence_stream[0].transport_state == "CONSUMED"
        assert "ranking" in artifact.evidence_stream[0].consumed_by

    def test_get_max_value_missing_type(self):
        artifact = IntelligenceArtifact()
        val = artifact.get_max_value("stop_scroll", default=0.5, consumer="ranking")
        assert val == 0.5

    def test_get_bool_with_consumer(self):
        artifact = IntelligenceArtifact()
        artifact.evidence_stream.append(
            Evidence(type="payoff_resolved", value=True, producer="payoff_engine")
        )
        result = artifact.get_bool("payoff_resolved", consumer="arc_assembler")
        assert result is True
        assert artifact.evidence_stream[0].transport_state == "CONSUMED"


# ---------------------------------------------------------------------------
# IntelligenceVerifier scan & report
# ---------------------------------------------------------------------------

def _make_candidate(cid: str, evidence_list: list) -> dict:
    artifact = IntelligenceArtifact()
    artifact.evidence_stream.extend(evidence_list)
    return {"cid": cid, "intelligence": artifact}


class TestIntelligenceVerifier:

    def test_all_consumed_clean(self):
        ev1 = Evidence("stop_scroll", 0.9, "groq_trigger")
        ev1.consume("ranking")
        ev2 = Evidence("memorability", 0.8, "groq_trigger")
        ev2.consume("ranking")
        cand = _make_candidate("c001", [ev1, ev2])

        verifier = IntelligenceVerifier()
        verifier.scan(final_candidates=[cand])
        assert verifier.consumed_count == 2
        assert verifier.orphaned_count == 0
        assert verifier.rejected_count == 0
        assert not verifier.has_orphans

    def test_orphaned_detected_as_bug(self):
        ev1 = Evidence("stop_scroll", 0.9, "groq_trigger")
        ev1.consume("ranking")
        ev_orphan = Evidence("usefulness", 0.6, "groq_trigger")  # never consumed
        cand = _make_candidate("c001", [ev1, ev_orphan])

        verifier = IntelligenceVerifier()
        verifier.scan(final_candidates=[cand])
        assert verifier.consumed_count == 1
        assert verifier.orphaned_count == 1
        assert verifier.has_orphans
        assert len(verifier.get_bug_signals()) == 1
        orphan = verifier.get_bug_signals()[0]
        assert orphan["type"] == "usefulness"
        assert orphan["producer"] == "groq_trigger"
        assert orphan["candidate_id"] == "c001"

    def test_explicitly_rejected_not_flagged_as_orphan(self):
        ev = Evidence("completeness", 0.4, "groq_trigger")
        ev.reject("score_below_threshold", "validation")
        cand = _make_candidate("c001", [ev])

        verifier = IntelligenceVerifier()
        verifier.scan(final_candidates=[cand])
        assert verifier.rejected_count == 1
        assert verifier.orphaned_count == 0
        assert not verifier.has_orphans

    def test_no_intelligence_artifact_skipped(self):
        """Candidates without IntelligenceArtifact should not crash the verifier."""
        cand = {"cid": "c001"}  # no intelligence key
        verifier = IntelligenceVerifier()
        verifier.scan(final_candidates=[cand])
        assert verifier.total == 0

    def test_deduplication_across_pools(self):
        """Same Evidence object in both final and intermediate pool counted once."""
        ev = Evidence("stop_scroll", 0.9, "groq_trigger")
        ev.consume("ranking")
        artifact = IntelligenceArtifact()
        artifact.evidence_stream.append(ev)
        cand = {"cid": "c001", "intelligence": artifact}

        verifier = IntelligenceVerifier()
        verifier.scan(
            final_candidates=[cand],
            all_candidates=[cand],  # same object in both pools
        )
        assert verifier.total == 1  # counted once

    def test_render_report_contains_verdict(self):
        ev_orphan = Evidence("memorability", 0.7, "groq_trigger")
        cand = _make_candidate("c001", [ev_orphan])

        verifier = IntelligenceVerifier()
        verifier.scan(final_candidates=[cand])
        report = verifier.render_report()
        assert "ORPHANED" in report
        assert "BUG" in report
        assert "memorability" in report
        assert "groq_trigger" in report

    def test_render_report_clean_verdict(self):
        ev = Evidence("stop_scroll", 0.9, "groq_trigger")
        ev.consume("ranking")
        cand = _make_candidate("c001", [ev])

        verifier = IntelligenceVerifier()
        verifier.scan(final_candidates=[cand])
        report = verifier.render_report()
        assert "CLEAN" in report
        assert "BUG" not in report

    def test_multiple_producers_tracked_separately(self):
        ev1 = Evidence("stop_scroll", 0.9, "groq_trigger")
        ev1.consume("ranking")
        ev2 = Evidence("curiosity_peak", 0.7, "curiosity_engine")
        # ev2 orphaned intentionally
        cand = _make_candidate("c001", [ev1, ev2])

        verifier = IntelligenceVerifier()
        verifier.scan(final_candidates=[cand])
        assert verifier._by_producer["groq_trigger"]["CONSUMED"] == 1
        assert verifier._by_producer["groq_trigger"]["ORPHANED"] == 0
        assert verifier._by_producer["curiosity_engine"]["ORPHANED"] == 1

    def test_rejected_candidates_pool_scanned(self):
        """Evidence in rejected candidate pool should also be tracked."""
        ev = Evidence("stop_scroll", 0.6, "groq_trigger")  # orphaned in rejected pool
        cand = _make_candidate("c999", [ev])

        verifier = IntelligenceVerifier()
        verifier.scan(final_candidates=[], rejected_candidates=[cand])
        assert verifier.total == 1
        assert verifier.orphaned_count == 1
