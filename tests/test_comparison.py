"""
Unit-Tests für ComparisonEntry – EV-Berechnung, Edge und Vig-Normierung.

Testet die Kernlogik aus src/ml/comparison.py ohne API-Aufrufe.
"""

import pytest

from src.ml.comparison import ComparisonEntry, OddsVsMLComparison

# ── Hilfsfunktion ─────────────────────────────────────────────────────────────

def _make_entry(
    ml_home_prob: float,
    odds_home_raw: float,
    odds_away_raw: float,
) -> ComparisonEntry:
    """Erstellt einen ComparisonEntry direkt aus Werten – ohne API."""
    odds_home_prob, odds_away_prob = OddsVsMLComparison._normalize_odds(
        odds_home_raw, odds_away_raw
    )
    ml_winner = "home" if ml_home_prob >= 0.5 else "away"
    odds_winner = "home" if odds_home_prob >= 0.5 else "away"
    return ComparisonEntry(
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        ml_home_prob=ml_home_prob,
        ml_away_prob=1.0 - ml_home_prob,
        ml_winner=ml_winner,
        odds_home_prob=odds_home_prob,
        odds_away_prob=odds_away_prob,
        odds_winner=odds_winner,
        odds_home_raw=odds_home_raw,
        odds_away_raw=odds_away_raw,
        prob_difference=abs(ml_home_prob - odds_home_prob),
    )


# ── Expected Value ────────────────────────────────────────────────────────────

class TestExpectedValue:
    """Tests für die EV-Berechnung (Expected Value = Erwartungswert)."""

    def test_ev_home_positive_when_ml_overestimates_home(self):
        """EV Home ist positiv, wenn KI Home stärker einschätzt als Quoten."""
        entry = _make_entry(ml_home_prob=0.80, odds_home_raw=2.00, odds_away_raw=2.00)
        assert entry.ev_home > 0.0

    def test_ev_home_negative_when_ml_underestimates_home(self):
        """EV Home ist negativ, wenn KI Home geringer einschätzt als Quoten."""
        entry = _make_entry(ml_home_prob=0.30, odds_home_raw=2.00, odds_away_raw=2.00)
        assert entry.ev_home < 0.0

    def test_ev_formula_home(self):
        """EV Home = (KI-Wahrscheinlichkeit × Dezimalquote) - 1."""
        entry = _make_entry(ml_home_prob=0.60, odds_home_raw=2.00, odds_away_raw=2.00)
        assert entry.ev_home == pytest.approx(0.60 * 2.00 - 1.0)

    def test_ev_formula_away(self):
        """EV Away = (KI-Wahrscheinlichkeit Away × Dezimalquote Away) - 1."""
        entry = _make_entry(ml_home_prob=0.40, odds_home_raw=2.00, odds_away_raw=2.00)
        assert entry.ev_away == pytest.approx(0.60 * 2.00 - 1.0)

    def test_ev_home_zero_with_invalid_odds(self):
        """EV ist 0 wenn Quoten 0 sind."""
        entry = _make_entry(ml_home_prob=0.60, odds_home_raw=0.0, odds_away_raw=2.00)
        assert entry.ev_home == 0.0

    def test_both_ev_available(self):
        """Beide EV-Werte (home und away) sind immer berechenbar."""
        entry = _make_entry(ml_home_prob=0.65, odds_home_raw=1.80, odds_away_raw=2.10)
        assert isinstance(entry.ev_home, float)
        assert isinstance(entry.ev_away, float)


# ── Edge ──────────────────────────────────────────────────────────────────────

class TestEdge:
    """Tests für die Edge-Berechnung (KI-Prob minus Quoten-Prob)."""

    def test_edge_home_positive_when_ml_higher_than_odds(self):
        """Edge Home ist positiv wenn KI mehr Value sieht als Quoten."""
        entry = _make_entry(ml_home_prob=0.70, odds_home_raw=1.80, odds_away_raw=2.10)
        assert entry.edge_home > 0

    def test_edge_home_negative_when_ml_lower_than_odds(self):
        """Edge Home ist negativ wenn Quoten mehr Value sehen als KI."""
        entry = _make_entry(ml_home_prob=0.40, odds_home_raw=1.80, odds_away_raw=2.10)
        assert entry.edge_home < 0

    def test_edge_away_is_inverse_of_home(self):
        """Edge Away = -(Edge Home) bei symmetrischer Verteilung."""
        entry = _make_entry(ml_home_prob=0.65, odds_home_raw=2.00, odds_away_raw=2.00)
        assert entry.edge_home == pytest.approx(-entry.edge_away)

    def test_edge_formula_home(self):
        """Edge Home = ml_home_prob - odds_home_prob."""
        entry = _make_entry(ml_home_prob=0.65, odds_home_raw=1.80, odds_away_raw=2.10)
        expected = entry.ml_home_prob - entry.odds_home_prob
        assert entry.edge_home == pytest.approx(expected)


# ── Vig-Normierung ────────────────────────────────────────────────────────────

class TestNormalizeOdds:
    """Tests für OddsVsMLComparison._normalize_odds (Vig-Bereinigung)."""

    def test_equal_odds_give_fifty_fifty(self):
        """Gleiche Quoten (2.0 / 2.0) → 50% / 50%."""
        home_p, away_p = OddsVsMLComparison._normalize_odds(2.00, 2.00)
        assert home_p == pytest.approx(0.50)
        assert away_p == pytest.approx(0.50)

    def test_normalized_probs_sum_to_one(self):
        """Normierte Wahrscheinlichkeiten ergeben immer 1.0."""
        home_p, away_p = OddsVsMLComparison._normalize_odds(1.80, 2.10)
        assert home_p + away_p == pytest.approx(1.0)

    def test_lower_odds_get_higher_probability(self):
        """Niedrigere Quote = höhere implizite Wahrscheinlichkeit."""
        home_p, away_p = OddsVsMLComparison._normalize_odds(1.50, 2.80)
        assert home_p > away_p

    def test_invalid_zero_odds_returns_fifty_fifty(self):
        """Ungültige Quoten (0.0) → Fallback 50/50."""
        home_p, away_p = OddsVsMLComparison._normalize_odds(0.0, 2.00)
        assert home_p == pytest.approx(0.50)
        assert away_p == pytest.approx(0.50)

    def test_vig_is_removed(self):
        """Nach Normierung ist die Summe exakt 1.0."""
        home_p, away_p = OddsVsMLComparison._normalize_odds(1.90, 1.90)
        assert home_p + away_p == pytest.approx(1.0)
        assert home_p == pytest.approx(0.50)
