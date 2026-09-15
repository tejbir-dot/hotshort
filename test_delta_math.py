import math
import numpy as np
import pytest

from viral_finder.delta_math import (
    cosine_distance,
    rolling_zscore,
    audio_delta,
    fuse_scores,
)

# ---------------------------------------------------------------------------
# Cosine distance (semantic "snap")
# ---------------------------------------------------------------------------

class TestCosineDistance:
    def test_identical_vectors_have_zero_distance(self):
        v = np.array([0.5, 0.5, 0.5, 0.5])
        assert cosine_distance(v, v) == pytest.approx(0.0, abs=1e-6)

    def test_orthogonal_vectors_have_distance_one(self):
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert cosine_distance(a, b) == pytest.approx(1.0, abs=1e-6)

    def test_opposite_vectors_have_distance_two(self):
        a = np.array([1.0, 0.0])
        b = np.array([-1.0, 0.0])
        assert cosine_distance(a, b) == pytest.approx(2.0, abs=1e-6)

    def test_is_scale_invariant(self):
        a = np.array([1.0, 2.0, 3.0])
        b = a * 10.0
        assert cosine_distance(a, b) == pytest.approx(0.0, abs=1e-6)

    def test_zero_vector_does_not_crash(self):
        a = np.zeros(4)
        b = np.array([1.0, 0.0, 0.0, 0.0])
        result = cosine_distance(a, b)
        assert not math.isnan(result)
        assert not math.isinf(result)


# ---------------------------------------------------------------------------
# Rolling z-score normalization
# ---------------------------------------------------------------------------

class TestRollingZScore:
    def test_constant_series_normalizes_to_zero(self):
        values = [5.0] * 20
        z = rolling_zscore(values, window=5)
        assert all(abs(x) < 1e-6 for x in z)

    def test_single_spike_is_detected_above_threshold(self):
        values = [1.0] * 10 + [50.0] + [1.0] * 10
        z = rolling_zscore(values, window=5)
        spike_index = 10
        assert z[spike_index] > 2.0

    def test_output_same_length_as_input(self):
        values = list(np.random.rand(30))
        z = rolling_zscore(values, window=7)
        assert len(z) == len(values)

    def test_does_not_use_global_threshold(self):
        quiet_video = [2.0] * 20
        loud_video = [80.0] * 20
        z_quiet = rolling_zscore(quiet_video, window=5)
        z_loud = rolling_zscore(loud_video, window=5)
        assert all(abs(x) < 1e-6 for x in z_quiet)
        assert all(abs(x) < 1e-6 for x in z_loud)


# ---------------------------------------------------------------------------
# Audio delta (derivative of RMS energy)
# ---------------------------------------------------------------------------

class TestAudioDelta:
    def test_silence_to_scream_is_large_positive_delta(self):
        rms = [0.01, 0.01, 0.01, 0.9, 0.9]
        deltas = audio_delta(rms)
        assert max(deltas) > 0.5

    def test_scream_to_silence_is_large_magnitude_delta(self):
        rms = [0.9, 0.9, 0.01, 0.01]
        deltas = audio_delta(rms)
        assert max(abs(d) for d in deltas) > 0.5

    def test_flat_audio_has_near_zero_deltas(self):
        rms = [0.4] * 10
        deltas = audio_delta(rms)
        assert all(abs(d) < 1e-6 for d in deltas)

    def test_empty_or_silent_track_does_not_crash(self):
        rms = [0.0] * 10
        deltas = audio_delta(rms)
        assert all(not math.isnan(d) for d in deltas)


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------

class TestFuseScores:
    def test_all_modalities_high_scores_very_high(self):
        score = fuse_scores(semantic_delta=0.9, audio_delta=0.9, visual_delta=0.9)
        assert score > 0.8

    def test_all_modalities_low_scores_very_low(self):
        score = fuse_scores(semantic_delta=0.05, audio_delta=0.05, visual_delta=0.05)
        assert score < 0.2

    def test_single_dominant_spike_survives_despite_flat_other_modalities(self):
        score = fuse_scores(semantic_delta=0.95, audio_delta=0.02, visual_delta=0.02)
        assert score > 0.3

    def test_two_aligned_spikes_score_higher_than_one_spike_alone(self):
        one_spike = fuse_scores(semantic_delta=0.9, audio_delta=0.1, visual_delta=0.1)
        two_aligned_spikes = fuse_scores(semantic_delta=0.9, audio_delta=0.9, visual_delta=0.1)
        assert two_aligned_spikes > one_spike

    def test_score_is_bounded(self):
        score = fuse_scores(semantic_delta=1.0, audio_delta=1.0, visual_delta=1.0)
        assert 0.0 <= score <= 1.0

    def test_does_not_divide_by_zero_or_nan_on_all_zero_input(self):
        score = fuse_scores(semantic_delta=0.0, audio_delta=0.0, visual_delta=0.0)
        assert not math.isnan(score)
        assert not math.isinf(score)
        assert score >= 0.0

if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
