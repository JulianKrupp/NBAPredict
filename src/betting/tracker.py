"""
Theoretischer Wett-Tracker – "Was wäre wenn"-Simulation.

Speichert virtuelle Wetten in einer SQLite-Datenbank und berechnet
Gewinn/Verlust, ROI und umfassende Effektivitäts-Statistiken.
Kein echtes Geld.

v2: Modellversion-Tracking & Perioden-Vergleich
  - Jede Wette speichert die aktive Modellversion (z.B. "v3", "v4")
  - Perioden können "abgeschlossen" werden → Snapshot der Ergebnisse
  - Versionsvergleich: Accuracy, ROI, Brier pro Modellversion

Datenbank: data/betting/bets.db
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, date
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
            fc = m.get("feature_count", "?")
            acc = round(m.get("accuracy", 0) * 100)
            name = m.get("model_name", "unknown")[:6]
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
    payout: float = 0.0
    profit: float = 0.0
    placed_at: str = ""
    resolved_at: str | None = None
    model_version: str = "unknown"
    period_id: int | None = None

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
    roi: float = 0.0
    win_rate: float = 0.0
    avg_odds: float = 0.0
    avg_edge: float = 0.0
    best_streak: int = 0
    current_streak: int = 0
    profit_by_rating: dict[str, float] | None = None
    record_by_rating: dict[str, dict] | None = None

    def to_dict(self) -> dict:
        return {
            "total_bets": self.total_bets, "open_bets": self.open_bets,
            "won": self.won, "lost": self.lost,
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

    def resolve_bet(self, bet_id: int, actual_winner: str) -> Bet | None:
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
                "UPDATE bets SET status=?,actual_winner=?,payout=?,profit=?,resolved_at=? WHERE id=?",
                (status, actual_winner, payout, profit, now, bet_id))
        bet.status, bet.actual_winner = status, actual_winner
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
            c.execute("DELETE FROM periods")
        logger.warning("Alle %d Wetten und Perioden gelöscht.", n)
        return n

    # ══════════════════════════════════════════════════════════════════════
    #  PERIODEN: Wetten abschließen
    # ══════════════════════════════════════════════════════════════════════

    def close_period(self, label: str | None = None, notes: str = "") -> dict:
        """
        Schließt die aktuelle Wettperiode ab.

        Alle aufgelösten Wetten ohne period_id bekommen die neue Periode
        zugewiesen. Offene Wetten werden NICHT betroffen.

        Args:
            label: Optionaler Name (z.B. "v3-endstand", "v4-erste-woche").
                   Default: automatisch aus Modellversion + Datum.
            notes: Optionale Notizen zur Periode.

        Returns:
            Dict mit Perioden-Info und Zusammenfassung.
        """
        now = datetime.now().isoformat(timespec="seconds")
        version = _current_model_version()
        auto_label = label or f"{version}_{now[:10]}"

        with self._connect() as conn:
            # Periode erstellen
            cur = conn.execute(
                "INSERT INTO periods (label, model_version, closed_at, notes) "
                "VALUES (?, ?, ?, ?)",
                (auto_label, version, now, notes))
            period_id = cur.lastrowid

            # Alle aufgelösten Wetten ohne Periode zuordnen
            affected = conn.execute(
                "UPDATE bets SET period_id = ? "
                "WHERE status != 'open' AND period_id IS NULL",
                (period_id,)).rowcount

        # Zusammenfassung berechnen
        summary = self._period_summary(period_id)
        summary["period_id"] = period_id
        summary["label"] = auto_label
        summary["model_version"] = version
        summary["closed_at"] = now
        summary["notes"] = notes
        summary["bets_closed"] = affected

        logger.info(
            "Periode #%d abgeschlossen: %d Wetten (%s)",
            period_id, affected, auto_label,
        )
        return summary

    def get_periods(self) -> list[dict]:
        """Gibt alle abgeschlossenen Perioden mit Zusammenfassung zurück."""
        with self._connect() as c:
            rows = c.execute(
                "SELECT * FROM periods ORDER BY closed_at DESC"
            ).fetchall()

        periods = []
        for row in rows:
            pid = row["id"]
            summary = self._period_summary(pid)
            summary["period_id"] = pid
            summary["label"] = row["label"]
            summary["model_version"] = row["model_version"]
            summary["closed_at"] = row["closed_at"]
            summary["notes"] = row["notes"] or ""
            periods.append(summary)
        return periods

    def _period_summary(self, period_id: int) -> dict:
        """Berechnet die Zusammenfassung einer Periode."""
        with self._connect() as c:
            rows = c.execute(
                "SELECT * FROM bets WHERE period_id = ?", (period_id,)
            ).fetchall()

        bets = [self._row_to_bet(r) for r in rows]
        resolved = [b for b in bets if b.status != "open"]

        if not resolved:
            return {"bets": 0, "won": 0, "lost": 0, "win_rate": 0,
                    "profit": 0, "roi": 0, "avg_odds": 0, "avg_edge": 0,
                    "brier": 0}

        won = sum(1 for b in resolved if b.is_won)
        staked = sum(b.stake for b in resolved)
        profit = sum(b.profit for b in resolved)

        # Brier Score der Wetten (wie gut die ML-Wahrscheinlichkeiten waren)
        brier = self._calc_brier(resolved)

        return {
            "bets": len(resolved),
            "won": won,
            "lost": len(resolved) - won,
            "win_rate": round(won / len(resolved), 4),
            "profit": round(profit, 2),
            "roi": round(profit / staked * 100, 2) if staked else 0,
            "avg_odds": round(sum(b.odds for b in resolved) / len(resolved), 2),
            "avg_edge": round(sum(b.edge for b in resolved) / len(resolved), 4),
            "brier": round(brier, 4),
        }

    # ══════════════════════════════════════════════════════════════════════
    #  VERSIONSVERGLEICH
    # ══════════════════════════════════════════════════════════════════════

    def get_versions(self) -> list[dict]:
        """
        Listet alle Modellversionen mit Wett-Statistiken auf.

        Gruppiert ALLE aufgelösten Wetten (nicht nur abgeschlossene Perioden)
        nach model_version.
        """
        with self._connect() as c:
            rows = c.execute(
                "SELECT * FROM bets WHERE status != 'open' ORDER BY placed_at ASC"
            ).fetchall()

        bets = [self._row_to_bet(r) for r in rows]
        by_version: dict[str, list[Bet]] = defaultdict(list)
        for b in bets:
            by_version[b.model_version].append(b)

        versions = []
        for version, vbets in sorted(by_version.items()):
            won = sum(1 for b in vbets if b.is_won)
            staked = sum(b.stake for b in vbets)
            profit = sum(b.profit for b in vbets)
            brier = self._calc_brier(vbets)

            # Datumsbereich
            dates = [b.placed_at[:10] for b in vbets if b.placed_at]
            first = min(dates) if dates else "?"
            last = max(dates) if dates else "?"

            versions.append({
                "version": version,
                "bets": len(vbets),
                "won": won,
                "lost": len(vbets) - won,
                "win_rate": round(won / len(vbets), 4),
                "profit": round(profit, 2),
                "roi": round(profit / staked * 100, 2) if staked else 0,
                "avg_odds": round(sum(b.odds for b in vbets) / len(vbets), 2),
                "avg_edge": round(sum(b.edge for b in vbets) / len(vbets), 4),
                "brier": round(brier, 4),
                "first_bet": first,
                "last_bet": last,
            })
        return versions

    def get_version_comparison(self, v1: str, v2: str) -> dict:
        """
        Vergleicht zwei Modellversionen direkt.

        Args:
            v1: Erste Version (z.B. "LogReg_f46_a70")
            v2: Zweite Version (z.B. "LogReg_f45_a65")

        Returns:
            Dict mit Side-by-Side-Vergleich und Deltas.
        """
        with self._connect() as c:
            rows1 = c.execute(
                "SELECT * FROM bets WHERE model_version=? AND status!='open'",
                (v1,)).fetchall()
            rows2 = c.execute(
                "SELECT * FROM bets WHERE model_version=? AND status!='open'",
                (v2,)).fetchall()

        def stats_for(rows):
            bets = [self._row_to_bet(r) for r in rows]
            if not bets:
                return {"bets": 0, "won": 0, "lost": 0, "win_rate": 0,
                        "profit": 0, "roi": 0, "brier": 0, "avg_odds": 0,
                        "avg_edge": 0, "calibration": []}
            won = sum(1 for b in bets if b.is_won)
            staked = sum(b.stake for b in bets)
            profit = sum(b.profit for b in bets)
            return {
                "bets": len(bets),
                "won": won,
                "lost": len(bets) - won,
                "win_rate": round(won / len(bets), 4),
                "profit": round(profit, 2),
                "roi": round(profit / staked * 100, 2) if staked else 0,
                "brier": round(self._calc_brier(bets), 4),
                "avg_odds": round(sum(b.odds for b in bets) / len(bets), 2),
                "avg_edge": round(sum(b.edge for b in bets) / len(bets), 4),
                "calibration": self._calibration(bets),
            }

        s1 = stats_for(rows1)
        s2 = stats_for(rows2)

        # Deltas berechnen
        deltas = {}
        for key in ("win_rate", "profit", "roi", "brier", "avg_edge"):
            deltas[key] = round(s2[key] - s1[key], 4)

        return {
            "v1": {"version": v1, **s1},
            "v2": {"version": v2, **s2},
            "deltas": deltas,
            "better": v2 if deltas.get("profit", 0) > 0 else v1,
        }

    # ══════════════════════════════════════════════════════════════════════
    #  BASIS-STATISTIKEN
    # ══════════════════════════════════════════════════════════════════════

    def get_stats(self) -> BettingStats:
        bets = self._all_bets_sorted()
        if not bets:
            return BettingStats()
        resolved = [b for b in bets if b.status != "open"]
        won = [b for b in resolved if b.is_won]
        total_staked = sum(b.stake for b in resolved)
        total_payout = sum(b.payout for b in resolved)
        total_profit = total_payout - total_staked
        best_streak, current_streak = self._calc_streaks(resolved)

        record_by_rating, profit_by_rating = {}, {}
        for rat in ("strong", "good", "slight", "none"):
            rb = [b for b in resolved if b.bet_rating == rat]
            if rb:
                rw = sum(1 for b in rb if b.is_won)
                rp = sum(b.profit for b in rb)
                rs = sum(b.stake for b in rb)
                profit_by_rating[rat] = round(rp, 2)
                record_by_rating[rat] = {
                    "bets": len(rb), "won": rw, "lost": len(rb) - rw,
                    "win_rate": round(rw / len(rb), 4),
                    "profit": round(rp, 2),
                    "roi": round(rp / rs * 100, 2) if rs else 0}

        return BettingStats(
            total_bets=len(bets), open_bets=sum(1 for b in bets if b.is_open),
            won=len(won), lost=len(resolved) - len(won),
            total_staked=total_staked, total_payout=total_payout,
            total_profit=total_profit,
            roi=round(total_profit / total_staked * 100, 2) if total_staked else 0,
            win_rate=len(won) / len(resolved) if resolved else 0,
            avg_odds=sum(b.odds for b in resolved) / len(resolved) if resolved else 0,
            avg_edge=sum(b.edge for b in resolved) / len(resolved) if resolved else 0,
            best_streak=best_streak, current_streak=current_streak,
            profit_by_rating=profit_by_rating, record_by_rating=record_by_rating)

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
                "date": r["placed_at"][:10],
                "profit": round(r["profit"], 2),
                "cumulative": round(cum, 2),
                "result": r["status"],
                "version": r["model_version"],
            })
        return history

    # ══════════════════════════════════════════════════════════════════════
    #  ERWEITERTE ANALYTIK
    # ══════════════════════════════════════════════════════════════════════

    def get_analytics(self) -> dict:
        """Umfassende Effektivitäts-Analyse aller aufgelösten Wetten."""
        resolved = [b for b in self._all_bets_sorted() if b.status != "open"]
        if not resolved:
            return {"empty": True}

        won_list = [b for b in resolved if b.is_won]
        lost_list = [b for b in resolved if not b.is_won]

        return {
            "empty":              False,
            "profit_history":     self.get_profit_history(),
            "by_rating":          self._by_rating(resolved),
            "by_team":            self._by_team(resolved),
            "by_side":            self._by_side(resolved),
            "by_odds_range":      self._by_odds_range(resolved),
            "by_edge_range":      self._by_edge_range(resolved),
            "calibration":        self._calibration(resolved),
            "expected_vs_actual": self._expected_vs_actual(resolved),
            "weekly":             self._weekly(resolved),
            "kelly_analysis":     self._kelly(resolved),
            "avg_profit_won":     round(sum(b.profit for b in won_list) / len(won_list), 2) if won_list else 0,
            "avg_profit_lost":    round(sum(b.profit for b in lost_list) / len(lost_list), 2) if lost_list else 0,
        }

    # ══════════════════════════════════════════════════════════════════════
    #  ANALYSE-HELFER
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _calc_brier(bets: list[Bet]) -> float:
        """Berechnet den Brier Score für aufgelöste Wetten."""
        if not bets:
            return 0.0
        total = 0.0
        for b in bets:
            # ml_prob ist die Wahrscheinlichkeit für das gewettete Team
            actual = 1.0 if b.is_won else 0.0
            total += (b.ml_prob - actual) ** 2
        return total / len(bets)

    def _by_rating(self, resolved: list[Bet]) -> list[dict]:
        labels = {"strong": "Stark", "good": "Gut",
                  "slight": "Leicht", "none": "Kein"}
        result = []
        for rat in ("strong", "good", "slight", "none"):
            group = [b for b in resolved if b.bet_rating == rat]
            if not group:
                continue
            w = sum(1 for b in group if b.is_won)
            p = sum(b.profit for b in group)
            s = sum(b.stake for b in group)
            result.append({
                "rating": rat, "label": labels[rat],
                "bets": len(group), "won": w, "lost": len(group) - w,
                "win_rate": round(w / len(group), 4),
                "profit": round(p, 2),
                "roi": round(p / s * 100, 2) if s else 0,
                "avg_odds": round(sum(b.odds for b in group) / len(group), 2),
                "avg_edge": round(sum(b.edge for b in group) / len(group), 4),
            })
        return result

    def _by_team(self, resolved: list[Bet]) -> list[dict]:
        teams: dict[str, dict] = defaultdict(
            lambda: {"bets": 0, "won": 0, "staked": 0.0, "profit": 0.0})
        for b in resolved:
            t = teams[b.bet_on]
            t["bets"] += 1
            t["won"] += int(b.is_won)
            t["staked"] += b.stake
            t["profit"] += b.profit
        out = []
        for name, t in sorted(teams.items(), key=lambda x: x[1]["profit"], reverse=True):
            out.append({
                "team": name, "bets": t["bets"], "won": t["won"],
                "lost": t["bets"] - t["won"],
                "win_rate": round(t["won"] / t["bets"], 4),
                "profit": round(t["profit"], 2),
                "roi": round(t["profit"] / t["staked"] * 100, 2) if t["staked"] else 0})
        return out

    def _by_side(self, resolved: list[Bet]) -> dict:
        sides = {"home": {"b": 0, "w": 0, "s": 0.0, "p": 0.0},
                 "away": {"b": 0, "w": 0, "s": 0.0, "p": 0.0}}
        for b in resolved:
            x = sides.get(b.bet_side, sides["home"])
            x["b"] += 1; x["w"] += int(b.is_won)
            x["s"] += b.stake; x["p"] += b.profit
        out = {}
        for side, x in sides.items():
            out[side] = {
                "bets": x["b"], "won": x["w"], "lost": x["b"] - x["w"],
                "win_rate": round(x["w"] / x["b"], 4) if x["b"] else 0,
                "profit": round(x["p"], 2),
                "roi": round(x["p"] / x["s"] * 100, 2) if x["s"] else 0}
        return out

    def _by_odds_range(self, resolved: list[Bet]) -> list[dict]:
        return self._group_by_range(resolved, [
            ("1.00-1.50", 1.0, 1.5), ("1.50-2.00", 1.5, 2.0),
            ("2.00-2.50", 2.0, 2.5), ("2.50-3.50", 2.5, 3.5),
            ("3.50+", 3.5, 99.0)], key=lambda b: b.odds)

    def _by_edge_range(self, resolved: list[Bet]) -> list[dict]:
        return self._group_by_range(resolved, [
            ("0-5%", 0.0, 0.05), ("5-10%", 0.05, 0.10),
            ("10-15%", 0.10, 0.15), ("15-20%", 0.15, 0.20),
            ("20%+", 0.20, 1.0)], key=lambda b: b.edge)

    def _calibration(self, resolved: list[Bet]) -> list[dict]:
        """KI-Wahrscheinlichkeit vs tatsächliche Win-Rate (10%-Buckets)."""
        buckets: dict[str, list[Bet]] = defaultdict(list)
        for b in resolved:
            bk = max(0, min(90, int(b.ml_prob * 10) * 10))
            buckets[f"{bk}-{bk + 10}%"].append(b)
        out = []
        for label in sorted(buckets):
            g = buckets[label]
            w = sum(1 for b in g if b.is_won)
            avg_ml = sum(b.ml_prob for b in g) / len(g)
            actual = w / len(g)
            out.append({
                "range": label, "bets": len(g), "won": w,
                "predicted_wr": round(avg_ml, 4),
                "actual_wr": round(actual, 4),
                "diff": round(actual - avg_ml, 4)})
        return out

    def _expected_vs_actual(self, resolved: list[Bet]) -> dict:
        exp = sum(b.ev * b.stake for b in resolved)
        act = sum(b.profit for b in resolved)
        stk = sum(b.stake for b in resolved)
        return {
            "expected_profit": round(exp, 2),
            "actual_profit": round(act, 2),
            "difference": round(act - exp, 2),
            "expected_roi": round(exp / stk * 100, 2) if stk else 0,
            "actual_roi": round(act / stk * 100, 2) if stk else 0}

    def _weekly(self, resolved: list[Bet]) -> list[dict]:
        weeks: dict[str, dict] = defaultdict(
            lambda: {"bets": 0, "won": 0, "profit": 0.0, "staked": 0.0})
        for b in resolved:
            try:
                dt = datetime.fromisoformat(b.placed_at)
                ic = dt.isocalendar()
                wk = f"{ic.year}-W{ic.week:02d}"
            except (ValueError, AttributeError):
                wk = "?"
            w = weeks[wk]
            w["bets"] += 1; w["won"] += int(b.is_won)
            w["profit"] += b.profit; w["staked"] += b.stake
        out, cum = [], 0.0
        for wk in sorted(weeks):
            w = weeks[wk]; cum += w["profit"]
            out.append({
                "week": wk, "bets": w["bets"], "won": w["won"],
                "lost": w["bets"] - w["won"],
                "profit": round(w["profit"], 2),
                "cumulative": round(cum, 2),
                "roi": round(w["profit"] / w["staked"] * 100, 2) if w["staked"] else 0})
        return out

    def _kelly(self, resolved: list[Bet]) -> dict:
        """Kelly-Criterion-Simulation."""
        entries = []
        bankroll = 1000.0
        cum_kelly = 0.0
        cum_flat = 0.0

        for b in resolved:
            p, odds = b.ml_prob, b.odds
            if odds <= 1.0:
                kf = 0.0
            else:
                kf = max(0.0, min(0.25, (p * (odds - 1) - (1 - p)) / (odds - 1)))
            ks = round(bankroll * kf, 2)
            kp = ks * (odds - 1) if b.is_won else -ks
            cum_kelly += kp
            bankroll += kp
            cum_flat += b.profit

            entries.append({
                "bet_id": b.id, "team": b.bet_on, "odds": b.odds,
                "ml_prob": round(b.ml_prob, 3),
                "kelly_frac": round(kf, 4), "kelly_stake": ks,
                "flat_stake": b.stake,
                "kelly_profit": round(kp, 2), "flat_profit": round(b.profit, 2),
                "cum_kelly": round(cum_kelly, 2), "cum_flat": round(cum_flat, 2),
                "bankroll": round(bankroll, 2), "won": b.is_won})

        return {
            "start_bankroll": 1000.0,
            "end_bankroll": round(bankroll, 2),
            "kelly_total_profit": round(cum_kelly, 2),
            "flat_total_profit": round(cum_flat, 2),
            "entries": entries}

    # ══════════════════════════════════════════════════════════════════════
    #  INTERNE HELFER
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _group_by_range(bets, ranges, key) -> list[dict]:
        out = []
        for label, lo, hi in ranges:
            g = [b for b in bets if lo <= key(b) < hi]
            if not g:
                out.append({"range": label, "bets": 0, "won": 0, "lost": 0,
                            "win_rate": 0, "profit": 0, "roi": 0, "avg_odds": 0})
                continue
            w = sum(1 for b in g if b.is_won)
            p = sum(b.profit for b in g)
            s = sum(b.stake for b in g)
            out.append({
                "range": label, "bets": len(g), "won": w, "lost": len(g) - w,
                "win_rate": round(w / len(g), 4), "profit": round(p, 2),
                "roi": round(p / s * 100, 2) if s else 0,
                "avg_odds": round(sum(b.odds for b in g) / len(g), 2)})
        return out

    @staticmethod
    def _calc_streaks(resolved: list[Bet]) -> tuple[int, int]:
        if not resolved:
            return 0, 0
        best, cur = 0, 0
        for b in resolved:
            cur = (cur + 1 if cur > 0 else 1) if b.is_won else (cur - 1 if cur < 0 else -1)
            if cur > best:
                best = cur
        return best, cur

    def _all_bets_sorted(self) -> list[Bet]:
        with self._connect() as c:
            rows = c.execute("SELECT * FROM bets ORDER BY placed_at ASC").fetchall()
        return [self._row_to_bet(r) for r in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as c:
            # Bets-Tabelle (v1-kompatibel + v2-Spalten)
            c.execute("""CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                home_team TEXT NOT NULL, away_team TEXT NOT NULL,
                bet_on TEXT NOT NULL, bet_side TEXT NOT NULL,
                odds REAL NOT NULL, stake REAL NOT NULL DEFAULT 10.0,
                ml_prob REAL NOT NULL, odds_prob REAL NOT NULL,
                edge REAL NOT NULL, ev REAL NOT NULL,
                bet_rating TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                actual_winner TEXT, payout REAL NOT NULL DEFAULT 0,
                profit REAL NOT NULL DEFAULT 0,
                placed_at TEXT NOT NULL, resolved_at TEXT,
                model_version TEXT NOT NULL DEFAULT 'unknown',
                period_id INTEGER)""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_bets_status ON bets(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_bets_version ON bets(model_version)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_bets_period ON bets(period_id)")

            # Perioden-Tabelle (NEU in v2)
            c.execute("""CREATE TABLE IF NOT EXISTS periods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                model_version TEXT NOT NULL,
                closed_at TEXT NOT NULL,
                notes TEXT)""")

            # Migration: model_version + period_id zu bestehenden Wetten
            self._migrate_v2(c)

    @staticmethod
    def _migrate_v2(conn: sqlite3.Connection) -> None:
        """Fügt v2-Spalten hinzu falls sie fehlen (bestehende DB)."""
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(bets)").fetchall()}
            if "model_version" not in cols:
                conn.execute(
                    "ALTER TABLE bets ADD COLUMN model_version TEXT NOT NULL DEFAULT 'v3_legacy'")
                logger.info("Migration: model_version-Spalte zu bets hinzugefügt.")
            if "period_id" not in cols:
                conn.execute(
                    "ALTER TABLE bets ADD COLUMN period_id INTEGER")
                logger.info("Migration: period_id-Spalte zu bets hinzugefügt.")
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
            payout=row["payout"],
            profit=row["profit"],
            placed_at=row["placed_at"],
            resolved_at=row["resolved_at"],
            model_version=row["model_version"] if "model_version" in keys else "unknown",
            period_id=row["period_id"] if "period_id" in keys else None,
        )
