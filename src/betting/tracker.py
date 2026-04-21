"""
Theoretischer Wett-Tracker – "Was wäre wenn"-Simulation.
Speichert virtuelle Wetten in SQLite und berechnet Gewinn/Verlust und ROI.
Kein echtes Geld.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

DB_DIR = Path("data/betting")
DB_PATH = DB_DIR / "bets.db"
METRICS_PATH = Path("data/models/model_metrics.json")
DEFAULT_STAKE = 10.0


def _current_model_version() -> str:
    """Liest die aktive Modellversion aus model_metrics.json."""
    try:
        if METRICS_PATH.exists():
            with open(METRICS_PATH, encoding="utf-8") as f:
                m = json.load(f)
            name = m.get("model_name", "unknown")[:6]
            fc = m.get("feature_count", "?")
            trained_at = m.get("trained_at", "")
            if trained_at:
                return f"{name}_f{fc}_{trained_at[:10]}"
            acc = round(m.get("accuracy", 0) * 100)
            return f"{name}_f{fc}_a{acc}"
    except Exception:
        pass
    return "unknown"


@dataclass
class Bet:
    """Eine einzelne virtuelle Wette."""
    id: int
    home_team: str
    away_team: str
    bet_on: str
    bet_side: Literal["home", "away"]
    odds: float
    stake: float
    ml_prob: float
    odds_prob: float
    edge: float
    ev: float
    bet_rating: str
    status: Literal["open", "won", "lost"] = "open"
    actual_winner: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    payout: float = 0.0
    profit: float = 0.0
    placed_at: str = ""
    resolved_at: str | None = None
    model_version: str = "unknown"

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
    total_profit: float = 0.0
    roi: float = 0.0
    win_rate: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_bets":    self.total_bets,
            "open_bets":     self.open_bets,
            "won":           self.won,
            "lost":          self.lost,
            "total_staked":  round(self.total_staked, 2),
            "total_profit":  round(self.total_profit, 2),
            "roi":           round(self.roi, 2),
            "win_rate":      round(self.win_rate, 4),
        }


class BettingTracker:

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ══════════════════════════════════════════════════════════════════════
    #  CRUD
    # ══════════════════════════════════════════════════════════════════════

    def place_bet(
        self, home_team: str, away_team: str, bet_on: str,
        bet_side: str, odds: float, ml_prob: float,
        odds_prob: float, edge: float, ev: float,
        bet_rating: str, stake: float = DEFAULT_STAKE,
        model_version: str | None = None,
    ) -> Bet:
        now = datetime.now().isoformat(timespec="seconds")
        version = model_version or _current_model_version()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO bets (home_team,away_team,bet_on,bet_side,"
                "odds,stake,ml_prob,odds_prob,edge,ev,bet_rating,"
                "status,payout,profit,placed_at,model_version) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,'open',0,0,?,?)",
                (home_team, away_team, bet_on, bet_side, odds, stake,
                 ml_prob, odds_prob, edge, ev, bet_rating, now, version))
            bid = cur.lastrowid
        return Bet(
            id=bid, home_team=home_team, away_team=away_team,
            bet_on=bet_on, bet_side=bet_side, odds=odds, stake=stake,
            ml_prob=ml_prob, odds_prob=odds_prob, edge=edge, ev=ev,
            bet_rating=bet_rating, status="open", placed_at=now,
            model_version=version,
        )

    def resolve_bet(
        self, bet_id: int, actual_winner: str,
        home_score: int | None = None, away_score: int | None = None,
    ) -> Bet | None:
        bet = self.get_bet(bet_id)
        if not bet or bet.status != "open":
            return None
        won = (actual_winner.lower().strip() in bet.bet_on.lower().strip() or
               bet.bet_on.lower().strip() in actual_winner.lower().strip())
        status = "won" if won else "lost"
        payout = bet.stake * bet.odds if won else 0.0
        profit = payout - bet.stake
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "UPDATE bets SET status=?,actual_winner=?,home_score=?,away_score=?,"
                "payout=?,profit=?,resolved_at=? WHERE id=?",
                (status, actual_winner, home_score, away_score, payout, profit, now, bet_id))
        bet.status, bet.actual_winner = status, actual_winner
        bet.home_score, bet.away_score = home_score, away_score
        bet.payout, bet.profit, bet.resolved_at = payout, profit, now
        return bet

    def get_bet(self, bet_id: int) -> Bet | None:
        with self._connect() as c:
            row = c.execute("SELECT * FROM bets WHERE id=?", (bet_id,)).fetchone()
        return self._row_to_bet(row) if row else None

    def get_open_bets(self) -> list[Bet]:
        with self._connect() as c:
            rows = c.execute(
                "SELECT * FROM bets WHERE status='open' ORDER BY placed_at DESC"
            ).fetchall()
        return [self._row_to_bet(r) for r in rows]

    def get_all_bets(self, limit: int = 100, status: str | None = None) -> list[Bet]:
        q, p = "SELECT * FROM bets", []
        if status:
            q += " WHERE status=?"
            p.append(status)
        q += " ORDER BY placed_at DESC LIMIT ?"
        p.append(limit)
        with self._connect() as c:
            rows = c.execute(q, p).fetchall()
        return [self._row_to_bet(r) for r in rows]

    def delete_bet(self, bet_id: int) -> bool:
        with self._connect() as c:
            return c.execute("DELETE FROM bets WHERE id=?", (bet_id,)).rowcount > 0

    def reset(self) -> int:
        with self._connect() as c:
            n = c.execute("DELETE FROM bets").rowcount
        logger.warning("Alle %d Wetten gelöscht.", n)
        return n

    # ══════════════════════════════════════════════════════════════════════
    #  STATISTIKEN
    # ══════════════════════════════════════════════════════════════════════

    def get_stats(self) -> BettingStats:
        with self._connect() as c:
            rows = c.execute("SELECT * FROM bets ORDER BY placed_at ASC").fetchall()
        bets = [self._row_to_bet(r) for r in rows]
        if not bets:
            return BettingStats()
        resolved = [b for b in bets if b.status != "open"]
        won = [b for b in resolved if b.is_won]
        total_staked = sum(b.stake for b in resolved)
        total_profit = sum(b.profit for b in resolved)
        return BettingStats(
            total_bets=len(bets),
            open_bets=sum(1 for b in bets if b.is_open),
            won=len(won),
            lost=len(resolved) - len(won),
            total_staked=total_staked,
            total_profit=total_profit,
            roi=round(total_profit / total_staked * 100, 2) if total_staked else 0,
            win_rate=len(won) / len(resolved) if resolved else 0,
        )

    def get_profit_history(self) -> list[dict]:
        with self._connect() as c:
            rows = c.execute(
                "SELECT placed_at,profit,status,model_version FROM bets "
                "WHERE status!='open' ORDER BY resolved_at ASC"
            ).fetchall()
        history, cum = [], 0.0
        for r in rows:
            cum += r["profit"]
            history.append({
                "date":       r["placed_at"][:10],
                "profit":     round(r["profit"], 2),
                "cumulative": round(cum, 2),
                "result":     r["status"],
                "version":    r["model_version"],
            })
        return history

    # ══════════════════════════════════════════════════════════════════════
    #  INTERNE HELFER
    # ══════════════════════════════════════════════════════════════════════

    @contextlib.contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                home_team TEXT NOT NULL, away_team TEXT NOT NULL,
                bet_on TEXT NOT NULL, bet_side TEXT NOT NULL,
                odds REAL NOT NULL, stake REAL NOT NULL DEFAULT 10.0,
                ml_prob REAL NOT NULL, odds_prob REAL NOT NULL,
                edge REAL NOT NULL, ev REAL NOT NULL,
                bet_rating TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                actual_winner TEXT, home_score INTEGER, away_score INTEGER,
                payout REAL NOT NULL DEFAULT 0,
                profit REAL NOT NULL DEFAULT 0,
                placed_at TEXT NOT NULL, resolved_at TEXT,
                model_version TEXT NOT NULL DEFAULT 'unknown')""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_bets_status ON bets(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_bets_version ON bets(model_version)")
            self._migrate(c)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Fügt fehlende Spalten zu bestehenden DBs hinzu."""
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(bets)").fetchall()}
            if "model_version" not in cols:
                conn.execute(
                    "ALTER TABLE bets ADD COLUMN model_version TEXT NOT NULL DEFAULT 'legacy'")
            if "home_score" not in cols:
                conn.execute("ALTER TABLE bets ADD COLUMN home_score INTEGER")
                conn.execute("ALTER TABLE bets ADD COLUMN away_score INTEGER")
        except Exception as exc:
            logger.debug("Migration-Check: %s", exc)

    @staticmethod
    def _row_to_bet(row: sqlite3.Row) -> Bet:
        keys = set(row.keys())
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
            home_score=row["home_score"] if "home_score" in keys else None,
            away_score=row["away_score"] if "away_score" in keys else None,
            payout=row["payout"],
            profit=row["profit"],
            placed_at=row["placed_at"],
            resolved_at=row["resolved_at"],
            model_version=row["model_version"] if "model_version" in keys else "unknown",
        )
