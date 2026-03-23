#!/usr/bin/env python3
"""
Cron-Job-Skript: Offene Wetten automatisch auflösen.

Dieses Skript wird auf dem Raspberry Pi per Cron regelmäßig ausgeführt
und prüft offene Wetten gegen tatsächliche Spielergebnisse.

Einrichten auf dem Raspberry Pi:
    crontab -e
    # Jeden Morgen um 9:00 Uhr (nach den meisten NBA-Spielen):
    0 9 * * * cd /home/pi/nba-tracker && /home/pi/nba-tracker/.venv/bin/python scripts/resolve_bets.py >> logs/resolve.log 2>&1

    # Oder alle 4 Stunden:
    0 */4 * * * cd /home/pi/nba-tracker && /home/pi/nba-tracker/.venv/bin/python scripts/resolve_bets.py >> logs/resolve.log 2>&1
"""

import sys
from pathlib import Path

# Projektverzeichnis zum Python-Pfad hinzufügen
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.config import Config
from src.utils.logger import setup_logger
from src.betting.resolver import BetResolver
from src.betting.tracker import BettingTracker


def main() -> None:
    config = Config()
    setup_logger(config.log_level, config.log_file)

    print(f"[resolve_bets] Starte Wettauflösung...")

    tracker = BettingTracker()
    resolver = BetResolver(config, tracker)
    result = resolver.resolve_all_open()

    print(f"[resolve_bets] Ergebnis:")
    print(f"  Aufgelöst:  {result['resolved']} ({result['won']}W / {result['lost']}L)")
    print(f"  Noch offen: {result['still_open']}")
    if result['errors']:
        print(f"  Fehler:     {result['errors']}")

    # Aktuelle Bilanz ausgeben
    stats = tracker.get_stats()
    if stats.total_bets > 0:
        print(f"\n[resolve_bets] Gesamtbilanz:")
        print(f"  Wetten: {stats.won}W / {stats.lost}L ({stats.win_rate:.0%})")
        print(f"  Profit: {stats.total_profit:+.2f} (ROI: {stats.roi:+.1f}%)")


if __name__ == "__main__":
    main()
