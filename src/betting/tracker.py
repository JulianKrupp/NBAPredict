"""
Theoretischer Wett-Tracker – "Was wäre wenn"-Simulation.

Speichert virtuelle Wetten in einer SQLite-Datenbank und berechnet
Gewinn/Verlust, ROI und weitere Statistiken. Kein echtes Geld.

Datenbank: data/betting/bets.db
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

DB_DIR = Path("data/betting")
DB_PATH = DB_DIR / "bets.db"

# Standard-Einsatz pro Wette (virtuelle Einheiten)
DEFAULT_STAKE = 10.0


@dataclass
class Bet:
    """Eine einzelne virtuelle Wette."""
    id: int
    home_team: str
    away_team: str
    bet_on: str                          # Teamname, auf den gewettet wird
    bet_side: Literal["home", "away"]    # 'home' oder 'away'
    odds: float                          # Dezimalquote zum Zeitpunkt der Wette
    stake: float                         # Virtueller Einsatz
    ml_prob: float                       # KI-Wahrscheinlichkeit zum Wettzeitpunkt
    odds_prob: float                     # Quoten-Wahrscheinlichkeit
    edge: float                          # ml_prob - odds_prob
    ev: float                            # Expected Value (ml_prob * odds - 1)
    bet_rating: str                      # 'strong', 'good', 'slight', 'none'

    # Ergebnis (erst nach Auflösung gesetzt)
    status: Literal["open", "won", "lost"] = "open"
    actual_winner: str | None = None
    payout: float = 0.0                  # 0 bei Verlust, stake * odds bei Gewinn
    profit: float = 0.0                  # payout - stake

    placed_at: str = ""                  # ISO-Zeitstempel
    resolved_at: str | None = None

    @property
    def is_open(self) -> bool:
        return self.status == "open"

    @property
    def is_won(self) -> bool:
        return self.status == "won"


@dataclass
class BettingStats:
    """Aggregierte Statistiken über alle Wetten."""
    total_bets: int = 0
    open_bets: int = 0
    won: int = 0
    lost: int = 0
    total_staked: float = 0.0
    total_payout: float = 0.0
    total_profit: float = 0.0
    roi: float = 0.0                     # profit / staked * 100
    win_rate: float = 0.0
    avg_odds: float = 0.0
    avg_edge: float = 0.0
    best_streak: int = 0
    current_streak: int = 0              # positiv = Gewinnserie, negativ = Verlustserie
    profit_by_rating: dict[str, float] | None = None
    record_by_rating: dict[str, dict] | None = None

    def to_dict(self) -> dict:
        return {
            "total_bets": self.total_bets,
            "open_bets": self.open_bets,
            "won": self.won,
            "lost": self.lost,
            "total_staked": round(self.total_staked, 2),
            "total_payout": round(self.total_payout, 2),
            "total_profit": round(self.total_profit, 2),
            "roi": round(self.roi, 2),
            "win_rate": round(self.win_rate, 4),
            "avg_odds": round(self.avg_odds, 2),
            "avg_edge": round(self.avg_edge, 4),
            "best_streak": self.best_streak,
            "current_streak": self.current_streak,
            "profit_by_rating": self.profit_by_rating or {},
            "record_by_rating": self.record_by_rating or {},
        }


class BettingTracker:
    """
    Verwaltet virtuelle Wetten in einer SQLite-Datenbank.

    Methoden:
      - place_bet()     → Neue Wette platzieren
      - resolve_bet()   → Wette auflösen (gewonnen/verloren)
      - get_open_bets() → Alle offenen Wetten
      - get_all_bets()  → Alle Wetten (mit Filter)
      - get_stats()     → Aggregierte Statistiken
      - delete_bet()    → Einzelne Wette löschen
      - reset()         → Alle Wetten löschen
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── Öffentliche Methoden ──────────────────────────────────────────────

    def place_bet(
        self,
        home_team: str,
        away_team: str,
        bet_on: str,
        bet_side: str,
        odds: float,
        ml_prob: float,
        odds_prob: float,
        edge: float,
        ev: float,
        bet_rating: str,
        stake: float = DEFAULT_STAKE,
    ) -> Bet:
        """
        Platziert eine neue virtuelle Wette.

        Returns:
            Das erstellte Bet-Objekt mit ID.
        """
        now = datetime.now().isoformat(timespec="seconds")

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO bets (
                    home_team, away_team, bet_on, bet_side,
                    odds, stake, ml_prob, odds_prob, edge, ev, bet_rating,
                    status, payout, profit, placed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', 0, 0, ?)
                """,
                (home_team, away_team, bet_on, bet_side,
                 odds, stake, ml_prob, odds_prob, edge, ev, bet_rating,
                 now),
            )
            bet_id = cursor.lastrowid

        logger.info(
            "Wette #%d platziert: %s auf %s @ %.2f (Edge: %.1f%%)",
            bet_id, stake, bet_on, odds, edge * 100,
        )

        return Bet(
            id=bet_id, home_team=home_team, away_team=away_team,
            bet_on=bet_on, bet_side=bet_side, odds=odds, stake=stake,
            ml_prob=ml_prob, odds_prob=odds_prob, edge=edge, ev=ev,
            bet_rating=bet_rating, status="open", placed_at=now,
        )

    def resolve_bet(self, bet_id: int, actual_winner: str) -> Bet | None:
        """
        Löst eine offene Wette auf.

        Args:
            bet_id:        ID der Wette.
            actual_winner: Name des tatsächlichen Gewinners.

        Returns:
            Aktualisiertes Bet-Objekt oder None wenn nicht gefunden.
        """
        bet = self.get_bet(bet_id)
        if not bet or bet.status != "open":
            return None

        won = actual_winner.lower().strip() in bet.bet_on.lower().strip() or \
              bet.bet_on.lower().strip() in actual_winner.lower().strip()

        status = "won" if won else "lost"
        payout = bet.stake * bet.odds if won else 0.0
        profit = payout - bet.stake
        now = datetime.now().isoformat(timespec="seconds")

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE bets
                SET status = ?, actual_winner = ?, payout = ?, profit = ?, resolved_at = ?
                WHERE id = ?
                """,
                (status, actual_winner, payout, profit, now, bet_id),
            )

        logger.info(
            "Wette #%d aufgelöst: %s → %s (Profit: %+.2f)",
            bet_id, status, actual_winner, profit,
        )

        bet.status = status
        bet.actual_winner = actual_winner
        bet.payout = payout
        bet.profit = profit
        bet.resolved_at = now
        return bet

    def get_bet(self, bet_id: int) -> Bet | None:
        """Gibt eine einzelne Wette zurück."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
        return self._row_to_bet(row) if row else None

    def get_open_bets(self) -> list[Bet]:
        """Gibt alle offenen Wetten zurück."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM bets WHERE status = 'open' ORDER BY placed_at DESC"
            ).fetchall()
        return [self._row_to_bet(r) for r in rows]

    def get_all_bets(self, limit: int = 100, status: str | None = None) -> list[Bet]:
        """Gibt alle Wetten zurück (optional gefiltert nach Status)."""
        query = "SELECT * FROM bets"
        params: list = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY placed_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_bet(r) for r in rows]

    def get_stats(self) -> BettingStats:
        """Berechnet aggregierte Statistiken über alle aufgelösten Wetten."""
        with self._connect() as conn:
            all_rows = conn.execute(
                "SELECT * FROM bets ORDER BY placed_at ASC"
            ).fetchall()

        bets = [self._row_to_bet(r) for r in all_rows]
        if not bets:
            return BettingStats()

        resolved = [b for b in bets if b.status != "open"]
        open_bets = [b for b in bets if b.status == "open"]
        won = [b for b in resolved if b.status == "won"]
        lost = [b for b in resolved if b.status == "lost"]

        total_staked = sum(b.stake for b in resolved)
        total_payout = sum(b.payout for b in resolved)
        total_profit = total_payout - total_staked

        # Serien berechnen
        best_streak, current_streak = self._calc_streaks(resolved)

        # Profit nach Rating
        ratings = ["strong", "good", "slight", "none"]
        profit_by_rating = {}
        record_by_rating = {}
        for rating in ratings:
            r_bets = [b for b in resolved if b.bet_rating == rating]
            if r_bets:
                r_won = sum(1 for b in r_bets if b.status == "won")
                r_profit = sum(b.profit for b in r_bets)
                r_staked = sum(b.stake for b in r_bets)
                profit_by_rating[rating] = round(r_profit, 2)
                record_by_rating[rating] = {
                    "bets": len(r_bets),
                    "won": r_won,
                    "lost": len(r_bets) - r_won,
                    "win_rate": round(r_won / len(r_bets), 4) if r_bets else 0,
                    "profit": round(r_profit, 2),
                    "roi": round(r_profit / r_staked * 100, 2) if r_staked else 0,
                }

        return BettingStats(
            total_bets=len(bets),
            open_bets=len(open_bets),
            won=len(won),
            lost=len(lost),
            total_staked=total_staked,
            total_payout=total_payout,
            total_profit=total_profit,
            roi=round(total_profit / total_staked * 100, 2) if total_staked else 0,
            win_rate=len(won) / len(resolved) if resolved else 0,
            avg_odds=sum(b.odds for b in resolved) / len(resolved) if resolved else 0,
            avg_edge=sum(b.edge for b in resolved) / len(resolved) if resolved else 0,
            best_streak=best_streak,
            current_streak=current_streak,
            profit_by_rating=profit_by_rating,
            record_by_rating=record_by_rating,
        )

    def get_profit_history(self) -> list[dict]:
        """Gibt den kumulativen Profitverlauf zurück (für Chart)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT placed_at, profit, status FROM bets "
                "WHERE status != 'open' ORDER BY resolved_at ASC"
            ).fetchall()

        history = []
        cumulative = 0.0
        for row in rows:
            cumulative += row["profit"]
            history.append({
                "date": row["placed_at"][:10],
                "profit": round(row["profit"], 2),
                "cumulative": round(cumulative, 2),
                "result": row["status"],
            })
        return history

    def delete_bet(self, bet_id: int) -> bool:
        """Löscht eine Wette."""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM bets WHERE id = ?", (bet_id,))
        return cursor.rowcount > 0

    def reset(self) -> int:
        """Löscht ALLE Wetten. Gibt die Anzahl gelöschter Wetten zurück."""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM bets")
        logger.warning("Alle %d Wetten gelöscht.", cursor.rowcount)
        return cursor.rowcount

    # ── Private Methoden ──────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # Besser für Raspberry Pi
        return conn

    def _init_db(self) -> None:
        """Erstellt die Tabelle falls noch nicht vorhanden."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bets (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    home_team     TEXT NOT NULL,
                    away_team     TEXT NOT NULL,
                    bet_on        TEXT NOT NULL,
                    bet_side      TEXT NOT NULL,
                    odds          REAL NOT NULL,
                    stake         REAL NOT NULL DEFAULT 10.0,
                    ml_prob       REAL NOT NULL,
                    odds_prob     REAL NOT NULL,
                    edge          REAL NOT NULL,
                    ev            REAL NOT NULL,
                    bet_rating    TEXT NOT NULL,
                    status        TEXT NOT NULL DEFAULT 'open',
                    actual_winner TEXT,
                    payout        REAL NOT NULL DEFAULT 0,
                    profit        REAL NOT NULL DEFAULT 0,
                    placed_at     TEXT NOT NULL,
                    resolved_at   TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_bets_status ON bets(status)
            """)

    @staticmethod
    def _row_to_bet(row: sqlite3.Row) -> Bet:
        return Bet(
            id=row["id"],
            home_team=row["home_team"],
            away_team=row["away_team"],
            bet_on=row["bet_on"],
            bet_side=row["bet_side"],
            odds=row["odds"],
            stake=row["stake"],
            ml_prob=row["ml_prob"],
            odds_prob=row["odds_prob"],
            edge=row["edge"],
            ev=row["ev"],
            bet_rating=row["bet_rating"],
            status=row["status"],
            actual_winner=row["actual_winner"],
            payout=row["payout"],
            profit=row["profit"],
            placed_at=row["placed_at"],
            resolved_at=row["resolved_at"],
        )

    @staticmethod
    def _calc_streaks(resolved: list[Bet]) -> tuple[int, int]:
        """Berechnet beste Gewinnserie und aktuelle Serie."""
        if not resolved:
            return 0, 0

        best_win = 0
        current = 0

        for bet in resolved:
            if bet.status == "won":
                current = current + 1 if current > 0 else 1
            else:
                current = current - 1 if current < 0 else -1
            if current > best_win:
                best_win = current

        return best_win, current
