"""
Unit-Tests für BettingTracker (src/betting/tracker.py).

Verwendet eine temporäre In-Memory-SQLite-Datenbank (tmp_path),
damit Tests isoliert laufen und die echte Wett-Datenbank nicht verändern.
"""

import pytest
from pathlib import Path

from src.betting.tracker import BettingTracker, Bet, BettingStats


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tracker(tmp_path: Path) -> BettingTracker:
    """Erstellt einen BettingTracker mit temporärer Testdatenbank."""
    db_path = tmp_path / "test_bets.db"
    return BettingTracker(db_path=db_path)


def _place_sample_bet(
    tracker: BettingTracker,
    home: str = "Los Angeles Lakers",
    away: str = "Boston Celtics",
    bet_on: str = "Los Angeles Lakers",
    bet_side: str = "home",
    odds: float = 1.85,
    ml_prob: float = 0.65,
    odds_prob: float = 0.54,
    edge: float = 0.11,
    ev: float = 0.20,
    bet_rating: str = "good",
    stake: float = 10.0,
) -> Bet:
    """Legt eine Beispiel-Wette an und gibt das Bet-Objekt zurück."""
    return tracker.place_bet(
        home_team=home,
        away_team=away,
        bet_on=bet_on,
        bet_side=bet_side,
        odds=odds,
        ml_prob=ml_prob,
        odds_prob=odds_prob,
        edge=edge,
        ev=ev,
        bet_rating=bet_rating,
        stake=stake,
    )


# ── place_bet ─────────────────────────────────────────────────────────────────

class TestPlaceBet:
    """Tests für das Anlegen von Wetten."""

    def test_place_bet_returns_bet_object(self, tracker):
        """place_bet gibt ein Bet-Objekt zurück."""
        bet = _place_sample_bet(tracker)
        assert isinstance(bet, Bet)

    def test_placed_bet_has_correct_teams(self, tracker):
        """Die angelegte Wette enthält die richtigen Team-Namen."""
        bet = _place_sample_bet(tracker, home="Lakers", away="Celtics")
        assert bet.home_team == "Lakers"
        assert bet.away_team == "Celtics"

    def test_placed_bet_status_is_open(self, tracker):
        """Neue Wetten haben immer Status 'open'."""
        bet = _place_sample_bet(tracker)
        assert bet.status == "open"
        assert bet.is_open is True

    def test_placed_bet_has_positive_id(self, tracker):
        """Das Bet-Objekt hat eine positive Datenbank-ID."""
        bet = _place_sample_bet(tracker)
        assert bet.id is not None
        assert bet.id > 0

    def test_placed_bet_ids_are_unique(self, tracker):
        """Zwei Wetten erhalten unterschiedliche IDs."""
        bet1 = _place_sample_bet(tracker)
        bet2 = _place_sample_bet(tracker)
        assert bet1.id != bet2.id

    def test_placed_bet_stores_correct_odds_and_stake(self, tracker):
        """Quoten und Einsatz werden korrekt gespeichert."""
        bet = _place_sample_bet(tracker, odds=2.10, stake=25.0)
        assert bet.odds == pytest.approx(2.10)
        assert bet.stake == pytest.approx(25.0)

    def test_placed_bet_model_version_is_set(self, tracker):
        """Jede Wette speichert die aktuelle Modellversion."""
        bet = _place_sample_bet(tracker)
        assert bet.model_version is not None
        assert len(bet.model_version) > 0


# ── get_bet ───────────────────────────────────────────────────────────────────

class TestGetBet:
    """Tests für das Abrufen einzelner Wetten."""

    def test_get_bet_returns_placed_bet(self, tracker):
        """get_bet gibt die angelegte Wette zurück."""
        bet = _place_sample_bet(tracker)
        retrieved = tracker.get_bet(bet.id)
        assert retrieved is not None
        assert retrieved.id == bet.id

    def test_get_bet_returns_none_for_nonexistent_id(self, tracker):
        """get_bet gibt None zurück, wenn die ID nicht existiert."""
        assert tracker.get_bet(99999) is None

    def test_get_bet_preserves_all_fields(self, tracker):
        """Alle Felder der Wette werden korrekt persistiert."""
        placed = _place_sample_bet(
            tracker, odds=1.95, ml_prob=0.67, edge=0.13, bet_rating="good"
        )
        retrieved = tracker.get_bet(placed.id)
        assert retrieved.odds == pytest.approx(1.95)
        assert retrieved.ml_prob == pytest.approx(0.67)
        assert retrieved.edge == pytest.approx(0.13)
        assert retrieved.bet_rating == "good"


# ── resolve_bet ───────────────────────────────────────────────────────────────

class TestResolveBet:
    """Tests für das Auflösen von Wetten."""

    def test_resolve_bet_won_sets_status_to_won(self, tracker):
        """Wenn der Favorit gewinnt, ist der Status 'won'."""
        bet = _place_sample_bet(tracker, bet_on="Los Angeles Lakers")
        resolved = tracker.resolve_bet(bet.id, actual_winner="Los Angeles Lakers")
        assert resolved.status == "won"
        assert resolved.is_won is True

    def test_resolve_bet_lost_sets_status_to_lost(self, tracker):
        """Wenn der Gegner gewinnt, ist der Status 'lost'."""
        bet = _place_sample_bet(tracker, bet_on="Los Angeles Lakers")
        resolved = tracker.resolve_bet(bet.id, actual_winner="Boston Celtics")
        assert resolved.status == "lost"
        assert resolved.is_won is False

    def test_resolve_bet_won_calculates_payout_correctly(self, tracker):
        """Gewinnausschüttung = Einsatz × Quote."""
        bet = _place_sample_bet(tracker, odds=2.00, stake=10.0, bet_on="Lakers")
        resolved = tracker.resolve_bet(bet.id, actual_winner="Lakers")
        assert resolved.payout == pytest.approx(20.0)  # 10 × 2.00
        assert resolved.profit == pytest.approx(10.0)  # 20 - 10

    def test_resolve_bet_lost_has_zero_payout(self, tracker):
        """Bei einer verlorenen Wette ist die Ausschüttung 0."""
        bet = _place_sample_bet(tracker, odds=2.00, stake=10.0, bet_on="Lakers")
        resolved = tracker.resolve_bet(bet.id, actual_winner="Celtics")
        assert resolved.payout == pytest.approx(0.0)
        assert resolved.profit == pytest.approx(-10.0)

    def test_resolve_bet_stores_final_score(self, tracker):
        """Der Endpunktstand wird bei der Auflösung gespeichert."""
        bet = _place_sample_bet(tracker, bet_on="Lakers")
        resolved = tracker.resolve_bet(
            bet.id, actual_winner="Lakers",
            home_score=112, away_score=105,
        )
        assert resolved.home_score == 112
        assert resolved.away_score == 105

    def test_resolve_bet_without_score_stores_none(self, tracker):
        """Ohne Score-Angabe bleiben home_score und away_score None."""
        bet = _place_sample_bet(tracker)
        resolved = tracker.resolve_bet(bet.id, actual_winner="Lakers")
        assert resolved.home_score is None
        assert resolved.away_score is None

    def test_resolve_bet_already_resolved_returns_none(self, tracker):
        """Eine bereits aufgelöste Wette kann nicht nochmal aufgelöst werden."""
        bet = _place_sample_bet(tracker)
        tracker.resolve_bet(bet.id, actual_winner="Lakers")
        result = tracker.resolve_bet(bet.id, actual_winner="Celtics")
        assert result is None

    def test_resolve_nonexistent_bet_returns_none(self, tracker):
        """resolve_bet mit ungültiger ID gibt None zurück."""
        result = tracker.resolve_bet(99999, actual_winner="Lakers")
        assert result is None

    def test_resolve_bet_is_persisted_in_database(self, tracker):
        """Der aufgelöste Status wird in der Datenbank gespeichert."""
        bet = _place_sample_bet(tracker)
        tracker.resolve_bet(bet.id, actual_winner="Los Angeles Lakers")
        retrieved = tracker.get_bet(bet.id)
        assert retrieved.status == "won"
        assert retrieved.actual_winner == "Los Angeles Lakers"

    def test_resolve_bet_partial_name_match(self, tracker):
        """Auch teilweise übereinstimmende Team-Namen werden erkannt."""
        bet = _place_sample_bet(tracker, bet_on="Los Angeles Lakers")
        # Verkürzter Name sollte trotzdem matchen
        resolved = tracker.resolve_bet(bet.id, actual_winner="Lakers")
        assert resolved.status == "won"


# ── get_open_bets ─────────────────────────────────────────────────────────────

class TestGetOpenBets:
    """Tests für das Abrufen offener Wetten."""

    def test_get_open_bets_returns_all_open(self, tracker):
        """get_open_bets gibt alle Wetten mit Status 'open' zurück."""
        _place_sample_bet(tracker)
        _place_sample_bet(tracker)
        open_bets = tracker.get_open_bets()
        assert len(open_bets) == 2

    def test_get_open_bets_excludes_resolved(self, tracker):
        """Aufgelöste Wetten erscheinen nicht in get_open_bets."""
        bet1 = _place_sample_bet(tracker)
        _place_sample_bet(tracker)  # bet2 bleibt offen

        tracker.resolve_bet(bet1.id, actual_winner="Lakers")

        open_bets = tracker.get_open_bets()
        assert len(open_bets) == 1
        assert open_bets[0].status == "open"

    def test_get_open_bets_returns_empty_when_none_open(self, tracker):
        """Keine offenen Wetten → leere Liste."""
        assert tracker.get_open_bets() == []


# ── get_stats ─────────────────────────────────────────────────────────────────

class TestGetStats:
    """Tests für die Statistikberechnung."""

    def test_get_stats_returns_betting_stats(self, tracker):
        """get_stats gibt ein BettingStats-Objekt zurück."""
        stats = tracker.get_stats()
        assert isinstance(stats, BettingStats)

    def test_stats_total_bets_matches_placed_count(self, tracker):
        """total_bets zählt alle angelegten Wetten."""
        _place_sample_bet(tracker)
        _place_sample_bet(tracker)
        _place_sample_bet(tracker)
        stats = tracker.get_stats()
        assert stats.total_bets == 3

    def test_stats_open_bets_counts_unresolved(self, tracker):
        """open_bets zählt nur nicht aufgelöste Wetten."""
        bet1 = _place_sample_bet(tracker)
        _place_sample_bet(tracker)
        tracker.resolve_bet(bet1.id, actual_winner="Lakers")
        stats = tracker.get_stats()
        assert stats.open_bets == 1

    def test_stats_won_and_lost_counts(self, tracker):
        """won und lost zählen korrekt."""
        bet1 = _place_sample_bet(tracker, bet_on="Lakers")
        bet2 = _place_sample_bet(tracker, bet_on="Lakers")
        tracker.resolve_bet(bet1.id, actual_winner="Lakers")   # won
        tracker.resolve_bet(bet2.id, actual_winner="Celtics")  # lost

        stats = tracker.get_stats()
        assert stats.won == 1
        assert stats.lost == 1

    def test_stats_roi_is_zero_with_no_resolved_bets(self, tracker):
        """ROI ist 0, wenn keine Wetten aufgelöst wurden."""
        _place_sample_bet(tracker)
        stats = tracker.get_stats()
        assert stats.roi == pytest.approx(0.0)

    def test_stats_win_rate_calculates_correctly(self, tracker):
        """Win-Rate = gewonnene Wetten / alle aufgelösten Wetten."""
        bet1 = _place_sample_bet(tracker, bet_on="Lakers")
        bet2 = _place_sample_bet(tracker, bet_on="Lakers")
        bet3 = _place_sample_bet(tracker, bet_on="Lakers")
        tracker.resolve_bet(bet1.id, actual_winner="Lakers")   # won
        tracker.resolve_bet(bet2.id, actual_winner="Lakers")   # won
        tracker.resolve_bet(bet3.id, actual_winner="Celtics")  # lost

        stats = tracker.get_stats()
        assert stats.win_rate == pytest.approx(2 / 3, abs=0.001)
