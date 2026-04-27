"""
NBA Predict – CLI-Einstiegspunkt.

Subkommandos:
  live, scores, standings, team
  ml-predict
  train collect|model|all|metrics
  compare
"""

import argparse
import logging
import sys

from src.api.nba_api_client import NBAApiClient
from src.api.odds_api_client import OddsApiClient
from src.ml.comparison import OddsVsMLComparison
from src.ml.data_collector import DEFAULT_MAX_GAMES, default_training_seasons
from src.ml.ml_predictor import MLPredictor
from src.utils.config import Config
from src.utils.display import display_games, display_standings
from src.utils.logger import setup_logger
from src.utils.ml_display import display_ml_prediction, display_model_metrics


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="NBA Predict – Ergebnisse, KI-Vorhersagen & Quoten-Vergleich",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("live")
    scores_p = sub.add_parser("scores")
    scores_p.add_argument("--date", type=str, default=None)
    sub.add_parser("standings")
    team_p = sub.add_parser("team")
    team_p.add_argument("team_name")

    ml_p = sub.add_parser("ml-predict")
    ml_p.add_argument("home_team")
    ml_p.add_argument("away_team")

    _seasons = default_training_seasons()
    train_p  = sub.add_parser("train")
    train_sub = train_p.add_subparsers(dest="train_command")
    coll_p = train_sub.add_parser("collect")
    coll_p.add_argument("--seasons", nargs="+", type=int, default=_seasons)
    coll_p.add_argument("--max-games", type=int, default=DEFAULT_MAX_GAMES)
    train_sub.add_parser("model")
    all_p = train_sub.add_parser("all")
    all_p.add_argument("--seasons", nargs="+", type=int, default=_seasons)
    all_p.add_argument("--max-games", type=int, default=DEFAULT_MAX_GAMES)
    train_sub.add_parser("metrics")

    comp_p = sub.add_parser("compare")
    comp_p.add_argument("--home", type=str, default=None)
    comp_p.add_argument("--away", type=str, default=None)

    return parser


def handle_live(nba_client):
    games = nba_client.get_live_games()
    if not games:
        print("Keine Live-Spiele.")
        return
    display_games(games, "🏀 Live-Spiele")


def handle_scores(nba_client, game_date):
    games = nba_client.get_games_by_date(game_date)
    if not games:
        print(f"Keine Spiele für {game_date or 'heute'}.")
        return
    display_games(games, f"📅 Spiele – {game_date or 'heute'}")


def handle_standings(nba_client):
    standings = nba_client.get_standings()
    if not standings:
        print("Keine Tabellendaten verfügbar.")
        return
    display_standings(standings)


def handle_team(nba_client, team_name):
    stats = nba_client.get_team_stats(team_name)
    if not stats:
        print(f"Team '{team_name}' nicht gefunden.")
        return
    print(f"\n{'='*50}\n  {stats.name}\n{'='*50}")
    print(f"  Siege / Niederlagen : {stats.wins} / {stats.losses}")
    print(f"  Win-Rate            : {stats.win_rate:.1%}")
    print(f"  Punkte Ø            : {stats.avg_points_scored:.1f}")
    print(f"  Gegenpunkte Ø       : {stats.avg_points_allowed:.1f}")
    print(f"  Punktdifferenz Ø    : {stats.point_differential:+.1f}")
    print(f"  Heimsieg-Rate       : {stats.home_win_rate:.1%}")
    print(f"  Auswärtssieg-Rate   : {stats.away_win_rate:.1%}")
    if stats.has_recent_form_data:
        print(f"  Form (L5 / L10)     : {stats.last_5_win_rate:.1%} / {stats.last_10_win_rate:.1%}")
    print(f"{'='*50}\n")


def handle_ml_predict(nba_client, odds_client, ml_predictor, home_name, away_name):
    home = nba_client.get_team_stats(home_name)
    away = nba_client.get_team_stats(away_name)
    if not home or not away:
        print("Fehler: Team nicht gefunden.")
        return

    if not ml_predictor.is_model_available():
        print("\n  ⚠️  Kein Modell vorhanden. Erst 'python main.py train all' ausführen.\n")
        return

    odds   = odds_client.get_odds(home_name, away_name)
    result = ml_predictor.predict(home, away, odds)
    display_ml_prediction(result)


def handle_train(config, args):
    from src.ml.data_collector import TrainingDataCollector
    from src.ml.model_trainer import NBAModelTrainer

    cmd = getattr(args, "train_command", None)

    if cmd == "collect":
        collector = TrainingDataCollector(config)
        count = collector.collect(seasons=args.seasons, max_games=args.max_games)
        print(f"✅ {count} Samples gespeichert.")

    elif cmd == "model":
        metrics = NBAModelTrainer().train()
        print(f"✅ Modell gespeichert (Accuracy: {metrics.accuracy:.1%})")

    elif cmd == "all":
        print("Schritt 1/2: Trainingsdaten sammeln...")
        collector = TrainingDataCollector(config)
        samples = collector.collect_with_progress(
            seasons=getattr(args, "seasons", None),
            max_games=getattr(args, "max_games", DEFAULT_MAX_GAMES),
        )
        if not samples:
            print("Fehler: Keine Trainingsdaten gesammelt.")
            return
        print(f"\nSchritt 2/2: Modell trainieren ({len(samples)} Samples)...")
        metrics = NBAModelTrainer().train(samples=samples)
        print(f"✅ Fertig (Accuracy: {metrics.accuracy:.1%})")

    elif cmd == "metrics":
        metrics = NBAModelTrainer().load_metrics()
        if metrics:
            display_model_metrics(metrics)
        else:
            print("Kein Modell vorhanden. Erst 'python main.py train all' ausführen.")

    else:
        print("Verwendung: python main.py train [collect|model|all|metrics]")


def handle_compare(config, home_name, away_name):
    comparison = OddsVsMLComparison(config)
    if home_name and away_name:
        entry = comparison.run_comparison_for_teams(home_name, away_name)
        if entry:
            comparison.display_comparison_table([entry])
        else:
            print(f"Kein Vergleich möglich für {home_name} vs {away_name}.")
    else:
        comparison.display_comparison_table(comparison.run_comparison())


def main() -> int:
    config = Config()
    setup_logger(config.log_level, config.log_file)
    logger = logging.getLogger(__name__)

    for warning in config.validate():
        logger.warning(warning)

    parser = build_argument_parser()
    args   = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    try:
        nba_client   = NBAApiClient(config)
        odds_client  = OddsApiClient(config)
        ml_predictor = MLPredictor(config)

        dispatch = {
            "live":       lambda: handle_live(nba_client),
            "scores":     lambda: handle_scores(nba_client, args.date),
            "standings":  lambda: handle_standings(nba_client),
            "team":       lambda: handle_team(nba_client, args.team_name),
            "ml-predict": lambda: handle_ml_predict(nba_client, odds_client, ml_predictor, args.home_team, args.away_team),
            "train":      lambda: handle_train(config, args),
            "compare":    lambda: handle_compare(config, getattr(args, "home", None), getattr(args, "away", None)),
        }

        handler = dispatch.get(args.command)
        if handler:
            handler()
        else:
            logger.error("Unbekannter Befehl: %s", args.command)
            return 1

    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        return 0
    except FileNotFoundError as exc:
        print(f"\n❌ {exc}")
        return 1
    except ValueError as exc:
        print(f"\n❌ {exc}")
        return 1
    except Exception as exc:
        logger.exception("Unerwarteter Fehler: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
