"""
NBA Tracker – Hauptprogramm
Spielergebnisse, Statistiken, KI-Vorhersagen und Wettquoten-Vergleich.
"""

import argparse
import sys
import logging
from src.utils.logger import setup_logger
from src.utils.config import Config
from src.utils.display import display_games, display_prediction, display_standings
from src.utils.ml_display import display_ml_prediction, display_model_metrics
from src.api.nba_api_client import NBAApiClient
from src.api.odds_api_client import OddsApiClient
from src.prediction.predictor import GamePredictor
from src.ml.ml_predictor import MLPredictor
from src.ml.comparison import OddsVsMLComparison


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="NBA Tracker – Ergebnisse, KI-Vorhersagen & Wettquoten-Vergleich",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Verfügbare Befehle")

    subparsers.add_parser("live", help="Aktuelle Live-Spiele")
    scores_p = subparsers.add_parser("scores", help="Spielergebnisse eines Datums")
    scores_p.add_argument("--date", type=str, default=None, help="YYYY-MM-DD")
    subparsers.add_parser("standings", help="Tabellenstände")
    team_p = subparsers.add_parser("team", help="Teamstatistiken")
    team_p.add_argument("team_name", type=str)
    pred_p = subparsers.add_parser("predict", help="Regelbasierte Vorhersage")
    pred_p.add_argument("home_team", type=str)
    pred_p.add_argument("away_team", type=str)

    ml_p = subparsers.add_parser("ml-predict", help="KI-Vorhersage + Vergleich")
    ml_p.add_argument("home_team", type=str)
    ml_p.add_argument("away_team", type=str)

    train_p = subparsers.add_parser("train", help="ML-Modell trainieren")
    train_sub = train_p.add_subparsers(dest="train_command")
    coll_p = train_sub.add_parser("collect", help="Trainingsdaten sammeln")
    coll_p.add_argument("--seasons", nargs="+", type=int, default=[2023, 2024])
    coll_p.add_argument("--max-games", type=int, default=300)
    train_sub.add_parser("model", help="Modell trainieren")
    all_p = train_sub.add_parser("all", help="Daten + Training komplett")
    all_p.add_argument("--seasons", nargs="+", type=int, default=[2023, 2024])
    all_p.add_argument("--max-games", type=int, default=300)
    train_sub.add_parser("metrics", help="Modell-Metriken anzeigen")

    comp_p = subparsers.add_parser("compare", help="KI vs. Wettquoten Vergleich")
    comp_p.add_argument("--home", type=str, default=None)
    comp_p.add_argument("--away", type=str, default=None)

    return parser


def handle_live(nba_client):
    games = nba_client.get_live_games()
    if not games:
        print("Aktuell keine Live-Spiele.")
        return
    display_games(games, title="🏀 Live-Spiele")


def handle_scores(nba_client, game_date):
    games = nba_client.get_games_by_date(game_date)
    if not games:
        print(f"Keine Spiele für: {game_date or 'heute'}.")
        return
    display_games(games, title=f"📅 Spiele am {game_date or 'heute'}")


def handle_standings(nba_client):
    standings = nba_client.get_standings()
    if not standings:
        print("Keine Tabellendaten.")
        return
    display_standings(standings)


def handle_team(nba_client, team_name):
    stats = nba_client.get_team_stats(team_name)
    if not stats:
        print(f"Team '{team_name}' nicht gefunden.")
        return
    print(f"\n{'='*50}")
    print(f"📊 Team-Statistiken: {stats.name}")
    print(f"{'='*50}")
    print(f"  Siege / Niederlagen : {stats.wins} / {stats.losses}")
    print(f"  Win-Rate            : {stats.win_rate:.1%}")
    print(f"  Punkte Ø            : {stats.avg_points_scored:.1f}")
    print(f"  Gegenpunkte Ø       : {stats.avg_points_allowed:.1f}")
    print(f"  Punkt-Differenz Ø   : {stats.point_differential:.1f}")
    print(f"  Heimsieg-Rate       : {stats.home_win_rate:.1%}")
    print(f"  Auswärtssieg-Rate   : {stats.away_win_rate:.1%}")
    print(f"{'='*50}\n")


def handle_predict(nba_client, odds_client, home_name, away_name):
    home_stats = nba_client.get_team_stats(home_name)
    away_stats = nba_client.get_team_stats(away_name)
    if not home_stats or not away_stats:
        print("Fehler: Team nicht gefunden.")
        return
    odds = odds_client.get_odds(home_name, away_name)
    predictor = GamePredictor()
    result = predictor.predict(home_stats, away_stats, odds)
    display_prediction(result, home_stats.name, away_stats.name)


def handle_ml_predict(nba_client, odds_client, ml_predictor, home_name, away_name):
    home_stats = nba_client.get_team_stats(home_name)
    away_stats = nba_client.get_team_stats(away_name)
    if not home_stats or not away_stats:
        print("Fehler: Team nicht gefunden.")
        return

    if not ml_predictor.is_model_available():
        print("\n  ⚠️  Kein trainiertes ML-Modell gefunden.")
        print("  Führe zuerst 'python main.py train all' aus.\n")
        print("  Nutze regelbasierte Vorhersage als Fallback...\n")
        handle_predict(nba_client, odds_client, home_name, away_name)
        return

    odds = odds_client.get_odds(home_name, away_name)
    result = ml_predictor.predict(home_stats, away_stats, odds)
    display_ml_prediction(result)


def handle_train(config, args):
    from src.ml.data_collector import TrainingDataCollector
    from src.ml.model_trainer import NBAModelTrainer

    train_command = getattr(args, "train_command", None)

    if train_command == "collect":
        collector = TrainingDataCollector(config)
        count = collector.collect(seasons=args.seasons, max_games=args.max_games)
        print(f"✅ {count} Trainingssamples gespeichert.")

    elif train_command == "model":
        trainer = NBAModelTrainer()
        metrics = trainer.train()
        print(f"✅ Modell gespeichert (Accuracy: {metrics.accuracy:.1%})")

    elif train_command == "all":
        print("Schritt 1/2: Trainingsdaten sammeln...")
        collector = TrainingDataCollector(config)
        samples = collector.collect_with_progress(
            seasons=getattr(args, "seasons", [2023, 2024]),
            max_games=getattr(args, "max_games", 300),
        )
        if not samples:
            print("Fehler: Keine Trainingsdaten gesammelt.")
            return
        print(f"\nSchritt 2/2: Modell trainieren ({len(samples)} Samples)...")
        trainer = NBAModelTrainer()
        metrics = trainer.train(samples=samples)
        print(f"✅ Fertig! Modell bereit (Accuracy: {metrics.accuracy:.1%})")

    elif train_command == "metrics":
        trainer = NBAModelTrainer()
        metrics = trainer.load_metrics()
        if metrics:
            display_model_metrics(metrics)
        else:
            print("Kein Modell vorhanden. Führe 'python main.py train all' aus.")

    else:
        print("Verwendung: python main.py train [collect|model|all|metrics]")


def handle_compare(config, home_name, away_name):
    comparison = OddsVsMLComparison(config)
    if home_name and away_name:
        entry = comparison.run_comparison_for_teams(home_name, away_name)
        if entry:
            comparison.display_comparison_table([entry])
        else:
            print(f"Vergleich für {home_name} vs {away_name} nicht möglich.")
    else:
        entries = comparison.run_comparison()
        comparison.display_comparison_table(entries)


def main() -> int:
    config = Config()
    setup_logger(config.log_level, config.log_file)
    logger = logging.getLogger(__name__)

    for warning in config.validate():
        logger.warning(warning)

    parser = build_argument_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    try:
        nba_client = NBAApiClient(config)
        odds_client = OddsApiClient(config)
        ml_predictor = MLPredictor(config)

        dispatch = {
            "live":       lambda: handle_live(nba_client),
            "scores":     lambda: handle_scores(nba_client, args.date),
            "standings":  lambda: handle_standings(nba_client),
            "team":       lambda: handle_team(nba_client, args.team_name),
            "predict":    lambda: handle_predict(nba_client, odds_client,
                                                  args.home_team, args.away_team),
            "ml-predict": lambda: handle_ml_predict(nba_client, odds_client, ml_predictor,
                                                      args.home_team, args.away_team),
            "train":      lambda: handle_train(config, args),
            "compare":    lambda: handle_compare(config,
                                                  getattr(args, "home", None),
                                                  getattr(args, "away", None)),
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
        print(f"\n❌ Datei nicht gefunden: {exc}")
        return 1
    except ValueError as exc:
        print(f"\n❌ Fehler: {exc}")
        return 1
    except Exception as exc:
        logger.exception("Unerwarteter Fehler: %s", exc)
        print(f"\n❌ Unerwarteter Fehler: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
