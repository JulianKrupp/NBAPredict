"""
Unit-Tests für das Vorhersage-Modul (GamePredictor).
"""

import pytest
from src.models.team import Team
from src.api.odds_api_client import GameOdds
from src.prediction.predictor import GamePredictor, PredictionResult


def make_team(
    name: str = "Team A",
    wins: int = 40,
    losses: int = 20,
    avg_pts: float = 113.0,
    avg_allowed: float = 108.0,
    home_wins: int = 22,
    home_losses: int = 10,
    away_wins: int = 18,
    away_losses: int = 10,
) -> Team:
    """Hilfsfunktion: Erstellt ein Team-Objekt mit konfigurierbaren Werten."""
    return Team(
        team_id=1,
        name=name,
        abbreviation="TST",
        wins=wins,
        losses=losses,
        avg_points_scored=avg_pts,
        avg_points_allowed=avg_allowed,
        home_wins=home_wins,
        home_losses=home_losses,
        away_wins=away_wins,
        away_losses=away_losses,
    )


class TestGamePredictor:
    """Tests für die GamePredictor-Klasse."""

    def setup_method(self):
        """Erstellt einen frischen Predictor vor jedem Test."""
        self.predictor = GamePredictor()

    def test_predict_returns_prediction_result(self):
        """predict gibt ein PredictionResult-Objekt zurück."""
        home = make_team("Lakers")
        away = make_team("Celtics")
        result = self.predictor.predict(home, away)
        assert isinstance(result, PredictionResult)

    def test_predicted_winner_is_home_or_away(self):
        """predicted_winner ist entweder 'home' oder 'away'."""
        home = make_team("A")
        away = make_team("B")
        result = self.predictor.predict(home, away)
        assert result.predicted_winner in ("home", "away")

    def test_win_probability_is_in_valid_range(self):
        """win_probability liegt immer zwischen 0.5 und 1.0."""
        home = make_team("A")
        away = make_team("B")
        result = self.predictor.predict(home, away)
        assert 0.5 <= result.win_probability <= 1.0

    def test_strong_home_team_is_favored(self):
        """Ein deutlich stärkeres Heimteam wird als Sieger vorhergesagt."""
        strong_home = make_team("Strong", wins=60, losses=10, avg_pts=120.0, avg_allowed=100.0,
                                home_wins=35, home_losses=2)
        weak_away = make_team("Weak", wins=10, losses=60, avg_pts=100.0, avg_allowed=120.0,
                              away_wins=2, away_losses=35)
        result = self.predictor.predict(strong_home, weak_away)
        assert result.predicted_winner == "home"
        assert result.win_probability >= 0.65

    def test_strong_away_team_can_win(self):
        """Ein deutlich stärkeres Auswärtsteam kann trotz Heimvorteil als Sieger vorhergesagt werden."""
        weak_home = make_team("Weak", wins=10, losses=60, avg_pts=100.0, avg_allowed=120.0)
        strong_away = make_team("Strong", wins=60, losses=10, avg_pts=120.0, avg_allowed=100.0)
        result = self.predictor.predict(weak_home, strong_away)
        assert result.predicted_winner == "away"

    def test_predicted_scores_are_positive(self):
        """Die vorhergesagten Punktzahlen sind größer als 0."""
        home = make_team()
        away = make_team()
        result = self.predictor.predict(home, away)
        assert result.predicted_home_score > 0
        assert result.predicted_away_score > 0

    def test_predicted_scores_are_realistic(self):
        """Die vorhergesagten Punktzahlen liegen in einem realistischen NBA-Bereich."""
        home = make_team(avg_pts=115.0, avg_allowed=110.0)
        away = make_team(avg_pts=112.0, avg_allowed=108.0)
        result = self.predictor.predict(home, away)
        assert 85 <= result.predicted_home_score <= 140
        assert 85 <= result.predicted_away_score <= 140

    def test_winner_always_has_higher_predicted_score(self):
        """
        Der vorhergesagte Sieger hat immer mehr Punkte als der Verlierer –
        unabhängig vom historischen Durchschnitt der Teams.

        Regressionstest: Denver (119 Ø Punkte) bekam mehr Punkte vorhergesagt
        als OKC (114 Ø), obwohl OKC mit 88% Wahrscheinlichkeit gewonnen hätte,
        weil die Schätzung früher auf avg_points_scored basierte.
        """
        okc   = make_team("OKC", wins=55, losses=10, avg_pts=114.0, avg_allowed=106.0,
                          home_wins=30, home_losses=2, away_wins=25, away_losses=8)
        denver = make_team("DEN", wins=30, losses=35, avg_pts=119.0, avg_allowed=118.0,
                           home_wins=18, home_losses=18, away_wins=12, away_losses=17)
        result = self.predictor.predict(okc, denver)
        assert result.predicted_winner == "home", "OKC sollte Favorit sein"
        assert result.predicted_home_score > result.predicted_away_score, (
            f"Sieger OKC hat weniger Punkte: "
            f"{result.predicted_home_score} vs {result.predicted_away_score}"
        )

    def test_score_difference_scales_with_probability(self):
        """Höhere Siegwahrscheinlichkeit → größere Punktedifferenz."""
        close_home = make_team("A", wins=35, losses=25)
        close_away = make_team("B", wins=30, losses=30)
        close = self.predictor.predict(close_home, close_away)
        close_diff = abs(close.predicted_home_score - close.predicted_away_score)

        clear_home = make_team("C", wins=60, losses=5, home_wins=35, home_losses=1)
        clear_away = make_team("D", wins=10, losses=55, away_wins=3, away_losses=32)
        clear = self.predictor.predict(clear_home, clear_away)
        clear_diff = abs(clear.predicted_home_score - clear.predicted_away_score)

        assert clear_diff > close_diff, (
            f"Klarerer Favorit sollte größere Punktedifferenz haben: "
            f"{clear_diff:.1f} vs {close_diff:.1f}"
        )

    def test_factors_dict_contains_all_keys(self):
        """Das factors-Dictionary enthält alle definierten Faktoren."""
        from src.prediction.predictor import FACTOR_WEIGHTS
        home = make_team()
        away = make_team()
        result = self.predictor.predict(home, away)
        for factor_name in FACTOR_WEIGHTS:
            assert factor_name in result.factors

    def test_factors_are_in_valid_range(self):
        """Alle Faktorwerte liegen zwischen 0.0 und 1.0."""
        home = make_team()
        away = make_team()
        result = self.predictor.predict(home, away)
        for factor_name, value in result.factors.items():
            assert 0.0 <= value <= 1.0, f"Faktor '{factor_name}' außerhalb [0,1]: {value}"

    def test_odds_are_included_in_result_when_provided(self):
        """Wettquoten werden im Ergebnis gespeichert, wenn sie übergeben werden."""
        home = make_team()
        away = make_team()
        odds = GameOdds(home_team="A", away_team="B", odds_home=1.80, odds_away=2.10)
        result = self.predictor.predict(home, away, odds=odds)
        assert result.odds_home == pytest.approx(1.80)
        assert result.odds_away == pytest.approx(2.10)

    def test_odds_are_none_when_not_provided(self):
        """odds_home und odds_away sind None, wenn keine Quoten übergeben wurden."""
        home = make_team()
        away = make_team()
        result = self.predictor.predict(home, away, odds=None)
        assert result.odds_home is None
        assert result.odds_away is None

    def test_heavy_favorite_with_odds_increases_confidence(self):
        """Sehr niedrige Wettquoten (starker Favorit) erhöhen die Vorhersagesicherheit."""
        home = make_team(wins=55, losses=15)
        away = make_team(wins=20, losses=50)
        odds_neutral = GameOdds(home_team="H", away_team="A", odds_home=1.5, odds_away=2.8)
        result = self.predictor.predict(home, away, odds=odds_neutral)
        assert result.predicted_winner == "home"

    def test_confidence_label_returns_string(self):
        """confidence_label gibt einen nicht-leeren String zurück."""
        home = make_team()
        away = make_team()
        result = self.predictor.predict(home, away)
        assert isinstance(result.confidence_label, str)
        assert len(result.confidence_label) > 0

    def test_equal_teams_result_in_near_fifty_percent(self):
        """Zwei gleichwertige Teams führen zu einer Wahrscheinlichkeit nahe 50 %."""
        team = make_team(wins=41, losses=41, avg_pts=113.0, avg_allowed=113.0,
                         home_wins=20, home_losses=20, away_wins=21, away_losses=21)
        result = self.predictor.predict(team, team)
        # Heimvorteil → leicht über 0.5, aber sollte unter 0.70 bleiben
        assert 0.50 <= result.win_probability <= 0.70


class TestPredictionResult:
    """Tests für die PredictionResult-Dataclass."""

    def test_confidence_label_very_confident(self):
        pr = PredictionResult("home", 0.80, 112.0, 104.0, {})
        assert pr.confidence_label == "Sehr sicher"

    def test_confidence_label_confident(self):
        pr = PredictionResult("home", 0.65, 110.0, 106.0, {})
        assert pr.confidence_label == "Sicher"

    def test_confidence_label_slight_favorite(self):
        pr = PredictionResult("home", 0.55, 109.0, 108.0, {})
        assert pr.confidence_label == "Leicht bevorzugt"

    def test_confidence_label_tossup(self):
        pr = PredictionResult("home", 0.51, 110.0, 109.0, {})
        assert pr.confidence_label == "Unentschieden / Knapp"


class TestPredictorInternals:
    """Tests für interne Hilfsmethoden des GamePredictor."""

    def test_factor_weights_sum_to_one(self):
        """Die Summe aller Faktor-Gewichte muss exakt 1.0 ergeben."""
        from src.prediction.predictor import FACTOR_WEIGHTS
        assert sum(FACTOR_WEIGHTS.values()) == pytest.approx(1.0)

    def test_compare_stats_equal_values_return_half(self):
        """Gleiche Heim- und Auswärtswerte → Score von 0.5."""
        assert GamePredictor._compare_stats(0.5, 0.5) == pytest.approx(0.5)

    def test_compare_stats_higher_home_gives_above_half(self):
        """Höherer Heimwert → Score > 0.5."""
        assert GamePredictor._compare_stats(0.7, 0.3) > 0.5

    def test_compare_stats_zero_zero_returns_half(self):
        """Beide Werte = 0 → Fallback auf 0.5."""
        assert GamePredictor._compare_stats(0.0, 0.0) == pytest.approx(0.5)

    def test_normalize_probability_clamps_to_minimum(self):
        """Raw-Score von 0.0 wird auf Minimum 0.10 begrenzt."""
        result = GamePredictor()._normalize_to_probability(0.0)
        assert result == pytest.approx(0.10)

    def test_normalize_probability_clamps_to_maximum(self):
        """Raw-Score von 1.0 wird auf Maximum 0.90 begrenzt."""
        result = GamePredictor()._normalize_to_probability(1.0)
        assert result == pytest.approx(0.90)

    def test_normalize_probability_half_gives_half(self):
        """Raw-Score von 0.5 → Wahrscheinlichkeit 0.5."""
        result = GamePredictor()._normalize_to_probability(0.5)
        assert result == pytest.approx(0.5)

    def test_fatigued_home_team_scores_fewer_points(self):
        """Ein B2B-Heimteam (days_rest=0) erzielt weniger Punkte als ein ausgeruhtes."""
        from src.models.team import Team
        # Ausgeruht: 3 Ruhetage, normale Spieldichte → fatigue_score ≈ 0.0
        fresh = Team(team_id=1, name="Fresh", abbreviation="FRS",
                     wins=40, losses=20, days_rest=3, games_last_7_days=2)
        # Ermüdet: Back-to-Back, hohe Spieldichte → fatigue_score = 1.0
        tired = Team(team_id=2, name="Tired", abbreviation="TRD",
                     wins=40, losses=20, days_rest=0, games_last_7_days=4)
        opponent = Team(team_id=3, name="Opponent", abbreviation="OPP",
                        wins=40, losses=20, days_rest=2, games_last_7_days=3)

        predictor = GamePredictor()
        result_fresh = predictor.predict(fresh, opponent)
        result_tired = predictor.predict(tired, opponent)
        assert result_fresh.predicted_home_score > result_tired.predicted_home_score
