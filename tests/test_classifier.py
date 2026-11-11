"""
Unit tests for src/classifier/text_model.py, on tiny made-up data where we know the
right answer. No downloads or warehouse needed.

Run from the project folder:
    python -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "classifier"))
import text_model as tm  # noqa: E402


class CleanTextTest(unittest.TestCase):

    def test_redactions_removed_and_amounts_kept_as_a_token(self):
        cleaned = tm.clean_text("On XX/XX/XXXX I paid {$40,000.00} to XXXX Bank.")
        self.assertEqual(cleaned, "on i paid dollaramount to bank")

    def test_words_containing_xx_are_not_cut(self):
        self.assertEqual(tm.clean_text("Exxon"), "exxon")


class TimeSplitTest(unittest.TestCase):

    def setUp(self):
        self.df = pd.DataFrame({"date_received": pd.date_range("2025-10-01", "2026-01-31", freq="D")})

    def test_no_test_row_is_older_than_any_train_row(self):
        train, valid, test = tm.time_split(self.df, "2026-01-01", "2025-12-01")
        self.assertLess(train.date_received.max(), valid.date_received.min())
        self.assertLess(valid.date_received.max(), test.date_received.min())
        self.assertEqual(len(train) + len(valid) + len(test), len(self.df))

    def test_without_validation_train_is_everything_before_test(self):
        train, valid, test = tm.time_split(self.df, "2026-01-01")
        self.assertEqual(len(valid), 0)
        self.assertEqual(train.date_received.max(), pd.Timestamp("2025-12-31"))


class RepeatedTextTest(unittest.TestCase):

    def test_test_texts_seen_in_training_are_dropped(self):
        train = pd.DataFrame({"clean_text": ["form letter", "form letter", "my card was charged twice"]})
        test = pd.DataFrame({"clean_text": ["form letter", "a brand new story", "a brand new story"]})
        train_out, test_out = tm.drop_repeated_text(train, test)
        self.assertEqual(len(train_out), 2)
        self.assertEqual(list(test_out.clean_text), ["a brand new story"])


class KeywordBaselineTest(unittest.TestCase):

    def test_matches_whole_word_starts_only(self):
        # "please" contains "lease" but must not become a vehicle lease complaint.
        preds = tm.keyword_baseline(["please help me", "my car lease ended"], fallback="Debt collection")
        self.assertEqual(list(preds), ["Debt collection", "Vehicle loan/lease"])

    def test_first_matching_rule_wins(self):
        preds = tm.keyword_baseline(["my student loan servicer and my credit card"], fallback="x")
        self.assertEqual(preds[0], "Student loan")


class PipelineTest(unittest.TestCase):

    def test_learns_an_easy_split_and_routing_table_adds_up(self):
        texts = (["mortgage escrow payment house foreclosure"] * 10
                 + ["credit card annual fee interest charge"] * 10)
        labels = ["Mortgage"] * 10 + ["Credit card"] * 10
        pipe = tm.build_pipeline()
        pipe.named_steps["tfidf"].set_params(min_df=1, max_df=1.0)
        pipe.fit(texts, labels)
        self.assertEqual(list(pipe.predict(["escrow house", "annual fee"])), ["Mortgage", "Credit card"])

        proba = pipe.predict_proba(texts)
        table = tm.confidence_routing(labels, proba, pipe.named_steps["model"].classes_)
        everyone = table[table.min_confidence == 0].iloc[0]
        self.assertEqual(everyone.share_auto_routed, 1.0)
        self.assertEqual(everyone.accuracy_auto_routed, 1.0)
        self.assertTrue((np.diff(table.share_auto_routed) <= 0).all())


class MixAdjustmentTest(unittest.TestCase):

    def test_recovers_a_new_mix_without_labels(self):
        # A perfectly calibrated model on 2 groups, trained where A was 80%.
        # In the new data B is 70%. EM should find roughly 30/70 from probabilities alone.
        rng = np.random.default_rng(0)
        n = 4000
        is_b = rng.random(n) < 0.7
        signal = rng.normal(loc=np.where(is_b, 1.0, -1.0), scale=1.0)
        lik_a, lik_b = np.exp(-(signal + 1) ** 2 / 2), np.exp(-(signal - 1) ** 2 / 2)
        proba = np.column_stack([0.8 * lik_a, 0.2 * lik_b])
        proba /= proba.sum(axis=1, keepdims=True)
        adjusted, mix = tm.adjust_for_new_mix(proba, [0.8, 0.2])
        self.assertAlmostEqual(mix[1], 0.7, delta=0.03)
        np.testing.assert_allclose(adjusted.sum(axis=1), 1.0)


if __name__ == "__main__":
    unittest.main()
