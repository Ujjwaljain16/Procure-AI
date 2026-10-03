from __future__ import annotations

import pytest

from evaluation.stats import bootstrap_median_ci, exact_sign_test


class TestExactSignTest:
    def test_all_pairs_one_way_gives_the_textbook_p_value(self):
        # 6 of 6 in one direction: two-sided exact p = 2 * (1/64) = 0.03125
        result = exact_sign_test([2, 3, 4, 5, 6, 7], [1, 1, 1, 1, 1, 1])
        assert result["n_nonzero"] == 6
        assert result["p_two_sided"] == pytest.approx(0.03125)

    def test_balanced_pairs_are_not_significant(self):
        result = exact_sign_test([1, 2, 3, 4], [2, 1, 4, 3])
        assert result["p_two_sided"] > 0.5

    def test_ties_are_dropped(self):
        assert exact_sign_test([1, 2], [1, 2])["n_nonzero"] == 0

    def test_unequal_lengths_are_rejected(self):
        with pytest.raises(ValueError):
            exact_sign_test([1], [1, 2])


class TestBootstrapMedianCI:
    def test_interval_brackets_the_median(self):
        values = [10, 12, 13, 15, 40]
        ci = bootstrap_median_ci(values, resamples=2000)
        assert ci["low"] <= ci["median"] <= ci["high"]

    def test_is_reproducible_with_a_seed(self):
        values = [10, 12, 13, 15, 40]
        assert bootstrap_median_ci(values, resamples=2000, seed=7) == bootstrap_median_ci(values, resamples=2000, seed=7)

    def test_empty_input_is_rejected(self):
        with pytest.raises(ValueError):
            bootstrap_median_ci([])
