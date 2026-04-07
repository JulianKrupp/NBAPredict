"""
Unit-Tests für ComparisonEntry – bet_rating-Guardrails, EV-Berechnung,
Methodenübereinstimmung und Vig-Normierung.

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
    """
    Erstellt einen ComparisonEntry direkt aus Werten – ohne API.

    Normiert die Quoten automatisch und leitet ml_winner / odds_winner ab.
    """
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


# ── Guardrail-Tests ───────────────────────────────────────────────────────────

class TestBetRatingGuardrails:
    """Tests für die Schutzregeln in bet_rating (Guardrail 1 & 2)."""

    def test_high_odds_with_insufficient_ml_confidence_returns_none(self):
        """
        Guardrail 1: Quote > 6.0 aber KI-Wahrscheinlichkeit < 70% → 'none'.

        Hintergrund: Bei einem krassen Außenseiter (Quote 7.0) muss das Modell
        sehr sicher sein. 60% ist zu wenig – könnte auf falschen Features basieren.
        """
        # bet_side=away (ev_away = 0.60 * 7.0 - 1 = 3.2 >> ev_home), bet_ml_prob=0.60
        entry = _make_entry(ml_home_prob=0.40, odds_home_raw=1.20, odds_away_raw=7.00)
        assert entry.bet_side == "away"
        assert entry.bet_odds_raw > 6.0
        assert entry.bet_ml_prob < 0.70
        assert entry.bet_rating == "none"

    def test_guardrail1_boundary_checks_ml_prob_not_just_odds(self):
        """
        Guardrail 1 prüft explizit die ML-Wahrscheinlichkeit (< 70%), nicht nur die Quote.

        Zwei Einträge mit identischen Quoten (>6.0), aber unterschiedlicher ML-Prob:
        - 0.60 < 0.70 → Guardrail 1 greift → "none"
        - In der Praxis greift danach immer noch Guardrail 2 (Methoden stimmen nicht überein),
          weil der Markt bei Quote >6.0 zwingend den Gegner favorisiert.
        Das System ist so designed: Außenseiter mit Quote >6.0 werden immer gefiltert.
        """
        # 60% Vertrauen für den Außenseiter → Guardrail 1 greift
        entry_low = _make_entry(ml_home_prob=0.40, odds_home_raw=1.20, odds_away_raw=7.00)
        assert entry_low.bet_odds_raw > 6.0
        assert entry_low.bet_ml_prob < 0.70
        assert entry_low.bet_rating == "none"

        # 75% Vertrauen – Guardrail 1 allein würde nicht greifen,
        # aber Guardrail 2 fängt es (methods disagree bei Außenseiter-Markt)
        entry_high = _make_entry(ml_home_prob=0.25, odds_home_raw=1.20, odds_away_raw=7.00)
        assert entry_high.bet_ml_prob >= 0.70  # Guardrail 1 Bedingung nicht erfüllt
        assert entry_high.methods_agree is False  # Guardrail 2 greift stattdessen
        assert entry_high.bet_rating == "none"  # Kombination beider Guardrails

    def test_methods_disagree_on_underdog_returns_none(self):
        """
        Guardrail 2: Quote > 3.5 und KI & Buchmacher sehen verschiedene Sieger → 'none'.

        KI sagt Home gewinnt (70%), Markt sagt Away gewinnt (Quote 3.8 für Home).
        Diese Diskrepanz ist ein Warnsignal – kein Value empfohlen.
        """
        # ml_winner="home", odds_winner="away" (hohe Quote für Home → Away ist Favorit)
        entry = _make_entry(ml_home_prob=0.70, odds_home_raw=3.80, odds_away_raw=1.30)
        assert entry.methods_agree is False
        assert entry.bet_odds_raw > 3.5
        assert entry.bet_rating == "none"

    def test_methods_agree_on_underdog_allows_rating(self):
        """
        Guardrail 2 greift NICHT wenn KI und Buchmacher einig sind.

        Beide sagen Away gewinnt. Home hat Quote 3.8 (Außenseiter),
        aber die Einigkeit macht die Empfehlung glaubwürdig.
        """
        # ml=0.30 → away, odds: Away-Favorit (odds_home=3.80) → odds_winner=away
        # Beide sagen away → methods_agree=True
        entry = _make_entry(ml_home_prob=0.30, odds_home_raw=3.80, odds_away_raw=1.30)
        assert entry.methods_agree is True
        # Guardrail 2 greift nicht → Rating basiert auf Edge (erwartet "slight")
        assert entry.bet_rating == "slight"

    def test_normal_odds_without_disagreement_evaluates_edge(self):
        """Bei normalen Quoten und Übereinstimmung entscheidet der Edge."""
        # Quoten < 3.5, kein Guardrail
        entry = _make_entry(ml_home_prob=0.65, odds_home_raw=1.80, odds_away_raw=2.10)
        assert entry.bet_odds_raw <= 3.5
        assert entry.bet_rating in ("strong", "good", "slight", "none")


# ── Edge-basierte Rating-Stufen ───────────────────────────────────────────────

class TestBetRatingEdgeLevels:
    """Tests für die vier Bewertungsstufen basierend auf dem Edge."""

    # Für diese Tests: odds_home_prob ≈ 0.539 (Quote 1.80/2.10, Vig-normiert)

    def test_edge_above_15_percent_returns_strong(self):
        """Edge >= 15% → 'strong' (Stark empfohlen)."""
        # edge = 0.70 - 0.539 = 0.161 >= 0.15
        entry = _make_entry(ml_home_prob=0.70, odds_home_raw=1.80, odds_away_raw=2.10)
        assert entry.edge >= 0.15
        assert entry.bet_rating == "strong"

    def test_edge_between_8_and_15_percent_returns_good(self):
        """8% <= Edge < 15% → 'good' (Empfohlen)."""
        # edge = 0.63 - 0.539 = 0.091
        entry = _make_entry(ml_home_prob=0.63, odds_home_raw=1.80, odds_away_raw=2.10)
        assert 0.08 <= entry.edge < 0.15
        assert entry.bet_rating == "good"

    def test_edge_between_4_and_8_percent_returns_slight(self):
        """4% <= Edge < 8% → 'slight' (Leicht positiv)."""
        # edge = 0.58 - 0.539 = 0.041
        entry = _make_entry(ml_home_prob=0.58, odds_home_raw=1.80, odds_away_raw=2.10)
        assert 0.04 <= entry.edge < 0.08
        assert entry.bet_rating == "slight"

    def test_edge_below_4_percent_returns_none(self):
        """Edge < 4% → 'none' (Kein Value)."""
        # edge = 0.55 - 0.539 = 0.011
        entry = _make_entry(ml_home_prob=0.55, odds_home_raw=1.80, odds_away_raw=2.10)
        assert entry.edge < 0.04
        assert entry.bet_rating == "none"


# ── Expected Value ────────────────────────────────────────────────────────────

class TestExpectedValue:
    """Tests für die EV-Berechnung (Expected Value = Erwartungswert)."""

    def test_ev_home_positive_when_ml_overestimates_home(self):
        """EV Home ist positiv, wenn KI Home stärker einschätzt als Quoten."""
        # ml sieht 80% für Home, Quoten 50/50 → EV = 0.80 * 2.0 - 1 = 0.60
        entry = _make_entry(ml_home_prob=0.80, odds_home_raw=2.00, odds_away_raw=2.00)
        assert entry.ev_home > 0.0

    def test_ev_home_negative_when_ml_underestimates_home(self):
        """EV Home ist negativ, wenn KI Home geringer einschätzt als Quoten."""
        # ml sieht 30% für Home, Quoten 50/50 → EV = 0.30 * 2.0 - 1 = -0.40
        entry = _make_entry(ml_home_prob=0.30, odds_home_raw=2.00, odds_away_raw=2.00)
        assert entry.ev_home < 0.0

    def test_best_ev_is_maximum_of_both_sides(self):
        """best_ev gibt immer den höheren der beiden EV-Werte zurück."""
        entry = _make_entry(ml_home_prob=0.70, odds_home_raw=1.80, odds_away_raw=2.10)
        assert entry.best_ev == pytest.approx(max(entry.ev_home, entry.ev_away))

    def test_ev_formula_is_ml_prob_times_odds_minus_one(self):
        """EV = (KI-Wahrscheinlichkeit × Dezimalquote) - 1."""
        entry = _make_entry(ml_home_prob=0.60, odds_home_raw=2.00, odds_away_raw=2.00)
        expected_ev_home = 0.60 * 2.00 - 1.0
        assert entry.ev_home == pytest.approx(expected_ev_home)

    def test_bet_side_is_home_when_home_has_better_ev(self):
        """bet_side ist 'home', wenn Home den besseren EV hat."""
        entry = _make_entry(ml_home_prob=0.70, odds_home_raw=1.80, odds_away_raw=2.10)
        assert entry.ev_home > entry.ev_away
        assert entry.bet_side == "home"

    def test_bet_side_is_away_when_away_has_better_ev(self):
        """bet_side ist 'away', wenn Away den besseren EV hat."""
        # ml sieht Away als klaren Sieger
        entry = _make_entry(ml_home_prob=0.25, odds_home_raw=1.80, odds_away_raw=2.10)
        assert entry.ev_away > entry.ev_home
        assert entry.bet_side == "away"


# ── Methodenübereinstimmung ───────────────────────────────────────────────────

class TestMethodsAgree:
    """Tests für die Übereinstimmung zwischen KI und Buchmacher."""

    def test_methods_agree_when_both_see_home_winning(self):
        """methods_agree ist True, wenn beide Home favorisieren."""
        entry = _make_entry(ml_home_prob=0.70, odds_home_raw=1.80, odds_away_raw=2.10)
        assert entry.ml_winner == "home"
        assert entry.odds_winner == "home"
        assert entry.methods_agree is True

    def test_methods_agree_when_both_see_away_winning(self):
        """methods_agree ist True, wenn beide Away favorisieren."""
        entry = _make_entry(ml_home_prob=0.30, odds_home_raw=2.10, odds_away_raw=1.80)
        assert entry.ml_winner == "away"
        assert entry.odds_winner == "away"
        assert entry.methods_agree is True

    def test_methods_disagree_when_ml_sees_home_but_odds_see_away(self):
        """methods_agree ist False bei entgegengesetzten Einschätzungen."""
        # ml: Home gewinnt (70%), Markt: Away ist Favorit (Quote 3.8 für Home)
        entry = _make_entry(ml_home_prob=0.70, odds_home_raw=3.80, odds_away_raw=1.30)
        assert entry.ml_winner == "home"
        assert entry.odds_winner == "away"
        assert entry.methods_agree is False


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
        """
        Typische Buchmacher-Quoten haben Vig (Summe implizierter Wahrsch. > 1).
        Nach Normierung ist die Summe exakt 1.0.
        """
        # 1/1.90 + 1/1.90 = 1.053 (5.3% Vig) → nach Normierung: 50/50
        home_p, away_p = OddsVsMLComparison._normalize_odds(1.90, 1.90)
        assert home_p + away_p == pytest.approx(1.0)
        assert home_p == pytest.approx(0.50)
