"""
Unit-Tests für die erweiterte Teambewertung (Team + Predictor v2).
"""

import pytest
from src.models.team import Team
from src.prediction.predictor import GamePredictor, PredictionResult, FACTOR_WEIGHTS


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def make_team(
    name: str = "Test Team",
    wins: int = 40,
    losses: int = 20,
    **kwargs,
) -> Team:
    """Erzeugt ein Team mit sinnvollen Defaults."""
    defaults = dict(
        team_id=1,
        abbreviation=name[:3].upper(),
        avg_points_scored=112.0,
        avg_points_allowed=109.0,
        home_wins=22,
        home_losses=8,
        away_wins=18,
        away_losses=12,
    )
    defaults.update(kwargs)
    return Team(name=name, wins=wins, losses=losses, **defaults)


# ══════════════════════════════════════════════════════════════════════════════
#  Team – Neue Properties
# ══════════════════════════════════════════════════════════════════════════════


class TestTeamStreak:
    """Tests für current_streak."""

    def test_positive_streak_on_consecutive_wins(self):
        team = make_team(recent_game_results=[False, True, True, True])
        assert team.current_streak == 3

    def test_negative_streak_on_consecutive_losses(self):
        team = make_team(recent_game_results=[True, False, False])
        assert team.current_streak == -2

    def test_streak_zero_on_empty_results(self):
        team = make_team(recent_game_results=[])
        assert team.current_streak == 0

    def test_single_game_streak(self):
        team = make_team(recent_game_results=[True])
        assert team.current_streak == 1

    def test_all_losses_streak(self):
        team = make_team(recent_game_results=[False, False, False, False])
        assert team.current_streak == -4


class TestTeamFormRating:
    """Tests für die erweiterte form_rating (L3/L5/L10)."""

    def test_form_uses_three_windows(self):
        # 10 Spiele: 7W, 3L – letzte 3 alle Siege
        results = [True, False, True, False, True, False, True, True, True, True]
        team = make_team(recent_game_results=results)
        # L3 = 1.0, L5 = 0.8, L10 = 0.7
        expected = 0.30 * 1.0 + 0.40 * 0.8 + 0.30 * 0.7
        assert team.form_rating == pytest.approx(expected)

    def test_form_fallback_to_win_rate(self):
        team = make_team(wins=30, losses=30, recent_game_results=[])
        assert team.form_rating == pytest.approx(0.5)

    def test_last_3_win_rate(self):
        team = make_team(recent_game_results=[True, False, True, True, False])
        # Letzte 3: True, True, False → 2/3
        assert team.last_3_win_rate == pytest.approx(2 / 3)


class TestTeamFatigue:
    """Tests für fatigue_score und is_back_to_back."""

    def test_back_to_back_detected(self):
        team = make_team(days_rest=0)
        assert team.is_back_to_back is True
        assert team.fatigue_score > 0.5

    def test_well_rested_detected(self):
        team = make_team(days_rest=4)
        assert team.is_well_rested is True
        assert team.fatigue_score == pytest.approx(0.0, abs=0.01)

    def test_fatigue_increases_with_game_density(self):
        light = make_team(days_rest=1, games_last_7_days=2)
        heavy = make_team(days_rest=1, games_last_7_days=4)
        assert heavy.fatigue_score > light.fatigue_score

    def test_fatigue_in_valid_range(self):
        for rest in range(5):
            for density in range(1, 6):
                team = make_team(days_rest=rest, games_last_7_days=density)
                assert 0.0 <= team.fatigue_score <= 1.0


class TestTeamInjury:
    """Tests für injury_impact."""

    def test_healthy_team_has_zero_impact(self):
        team = make_team(injured_players_count=0, injured_salary_ratio=0.0)
        assert team.injury_impact == pytest.approx(0.0)

    def test_multiple_injuries_increase_impact(self):
        mild = make_team(injured_players_count=1, injured_salary_ratio=0.05)
        severe = make_team(injured_players_count=4, injured_salary_ratio=0.30)
        assert severe.injury_impact > mild.injury_impact

    def test_star_injury_weighs_more_than_count(self):
        # 1 Star-Verletzung (hoher Gehaltsanteil)
        star_out = make_team(injured_players_count=1, injured_salary_ratio=0.25)
        # 3 Bankdrücker (niedriger Gehaltsanteil)
        bench_out = make_team(injured_players_count=3, injured_salary_ratio=0.08)
        assert star_out.injury_impact > bench_out.injury_impact

    def test_injury_impact_capped_at_one(self):
        team = make_team(injured_players_count=15, injured_salary_ratio=1.0)
        assert team.injury_impact <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
#  Predictor – Neue Faktoren
# ══════════════════════════════════════════════════════════════════════════════


class TestPredictorFactors:
    """Tests für die erweiterten Vorhersagefaktoren."""

    def setup_method(self):
        self.predictor = GamePredictor()

    def test_factor_weights_sum_to_one(self):
        total = sum(FACTOR_WEIGHTS.values())
        assert total == pytest.approx(1.0)

    def test_all_factors_present_in_result(self):
        home = make_team("Home")
        away = make_team("Away")
        result = self.predictor.predict(home, away)
        for factor_name in FACTOR_WEIGHTS:
            assert factor_name in result.factors, f"Faktor '{factor_name}' fehlt"

    def test_all_factors_in_valid_range(self):
        home = make_team("H", wins=50, losses=10)
        away = make_team("A", wins=15, losses=45)
        result = self.predictor.predict(home, away)
        for name, val in result.factors.items():
            assert 0.0 <= val <= 1.0, f"Faktor '{name}' = {val} außerhalb [0,1]"

    def test_fatigue_factor_favors_rested_team(self):
        rested = make_team("Rested", days_rest=3, games_last_7_days=2)
        tired = make_team("Tired", days_rest=0, games_last_7_days=4)
        result = self.predictor.predict(rested, tired)
        assert result.factors["Ruhetage"] > 0.55

    def test_injury_factor_favors_healthy_team(self):
        healthy = make_team("Healthy", injured_players_count=0, injured_salary_ratio=0.0)
        injured = make_team("Injured", injured_players_count=3, injured_salary_ratio=0.25)
        result = self.predictor.predict(healthy, injured)
        assert result.factors["Verletzungen"] > 0.55

    def test_streak_factor_favors_winning_team(self):
        hot = make_team("Hot", recent_game_results=[True] * 8)
        cold = make_team("Cold", recent_game_results=[False] * 5)
        result = self.predictor.predict(hot, cold)
        assert result.factors["Streak"] > 0.55

    def test_defense_factor_favors_stingy_team(self):
        good_def = make_team("GoodDef", avg_points_allowed=104.0)
        bad_def = make_team("BadDef", avg_points_allowed=118.0)
        result = self.predictor.predict(good_def, bad_def)
        assert result.factors["Defensiv-Stärke"] > 0.55

    def test_form_uses_real_data_when_available(self):
        """Wenn recent_game_results vorhanden, nutzt der Predictor echte Form."""
        hot_form = make_team(
            "Hot", wins=30, losses=30,
            recent_game_results=[True, True, True, True, True],
        )
        cold_form = make_team(
            "Cold", wins=30, losses=30,
            recent_game_results=[False, False, False, False, False],
        )
        result = self.predictor.predict(hot_form, cold_form)
        # Beide Teams haben gleiche Win-Rate, aber Form unterscheidet sich
        assert result.factors["Aktuelle Form"] > 0.6

    def test_back_to_back_reduces_predicted_score(self):
        """Ein B2B-Team bekommt weniger vorhergesagte Punkte."""
        normal = make_team("Normal", days_rest=2)
        b2b = make_team("B2B", days_rest=0, games_last_7_days=4)
        # Gleiche Stats, aber B2B für Home
        result_normal = self.predictor.predict(normal, normal)
        result_b2b = self.predictor.predict(b2b, normal)
        # B2B-Team sollte tendenziell niedrigeren Predicted-Score bekommen
        assert result_b2b.predicted_home_score <= result_normal.predicted_home_score


class TestPredictorEdgeCases:
    """Grenzfälle für den Predictor."""

    def setup_method(self):
        self.predictor = GamePredictor()

    def test_identical_teams_predict_near_even(self):
        home = make_team("A")
        away = make_team("B")
        result = self.predictor.predict(home, away)
        # Heimvorteil macht leichten Unterschied, aber nah an 50 %
        assert 0.45 <= result.win_probability <= 0.65

    def test_extreme_mismatch_stays_within_bounds(self):
        strong = make_team("Strong", wins=70, losses=2, home_wins=38, home_losses=0,
                           avg_points_scored=125.0, avg_points_allowed=100.0,
                           recent_game_results=[True] * 15)
        weak = make_team("Weak", wins=5, losses=67, away_wins=1, away_losses=35,
                         avg_points_scored=98.0, avg_points_allowed=122.0,
                         recent_game_results=[False] * 15,
                         injured_players_count=4, injured_salary_ratio=0.35)
        result = self.predictor.predict(strong, weak)
        assert result.win_probability <= 0.90
        assert result.win_probability >= 0.10

    def test_no_games_played_still_works(self):
        home = make_team("New1", wins=0, losses=0, avg_points_scored=0, avg_points_allowed=0)
        away = make_team("New2", wins=0, losses=0, avg_points_scored=0, avg_points_allowed=0)
        result = self.predictor.predict(home, away)
        assert 0.1 <= result.win_probability <= 0.9
