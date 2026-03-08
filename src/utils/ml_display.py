"""
Ausgabe-Hilfsfunktionen für ML-Vorhersagen.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.ml.ml_predictor import MLPredictionResult
    from src.ml.model_trainer import ModelMetrics


def display_ml_prediction(result: "MLPredictionResult") -> None:
    """
    Gibt das vollständige ML-Vorhersageergebnis inkl. Methodenvergleich aus.

    Args:
        result: MLPredictionResult-Objekt.
    """
    home = result.home_team
    away = result.away_team
    ml_winner_name = home if result.ml_predicted_winner == "home" else away
    rule_winner_name = home if result.rule_predicted_winner == "home" else away
    consensus_name = home if result.consensus_winner == "home" else away

    print(f"\n{'='*65}")
    print(f"  🔮 KI-Vorhersage: {home} vs {away}")
    print(f"{'='*65}")

    # KI-Vorhersage
    print(f"\n  🤖 ML-Modell (Random Forest / Gradient Boosting)")
    print(f"  {'─'*60}")
    _print_probability_bar("  Heim", home, result.ml_home_win_probability)
    _print_probability_bar("  Ausw", away, 1.0 - result.ml_home_win_probability)
    print(f"  Vorhergesagter Sieger : {ml_winner_name}")
    print(f"  Konfidenz             : {result.ml_confidence}")

    # Regelbasierte Vorhersage
    print(f"\n  📐 Regelbasiertes Modell (Gewichtetes Scoring)")
    print(f"  {'─'*60}")
    _print_probability_bar("  Heim", home, result.rule_home_win_probability)
    _print_probability_bar("  Ausw", away, 1.0 - result.rule_home_win_probability)
    print(f"  Vorhergesagter Sieger : {rule_winner_name}")

    # Wettquoten
    if result.odds_home_win_probability is not None:
        odds_winner_name = home if result.odds_predicted_winner == "home" else away
        print(f"\n  📊 Wettquoten (The Odds API, Vig-bereinigt)")
        print(f"  {'─'*60}")
        _print_probability_bar("  Heim", home, result.odds_home_win_probability)
        _print_probability_bar("  Ausw", away, 1.0 - result.odds_home_win_probability)
        print(f"  Favorit lt. Quoten    : {odds_winner_name}")
    else:
        print(f"\n  📊 Wettquoten : nicht verfügbar (ODDS_API_KEY nicht gesetzt)")

    # Konsens
    agree_icon = "✅" if result.all_agree else "⚠️ "
    print(f"\n  {'─'*60}")
    print(f"  {agree_icon} Konsens ({result.consensus_agreement_count}/3 Methoden): "
          f"{consensus_name}")

    # Score-Schätzung
    print(f"\n  🏀 Geschätztes Ergebnis: "
          f"{home} {result.predicted_home_score:.0f} – "
          f"{result.predicted_away_score:.0f} {away}")

    print(f"{'='*65}\n")


def display_model_metrics(metrics: "ModelMetrics") -> None:
    """
    Gibt die Modell-Evaluationsmetriken aus.

    Args:
        metrics: ModelMetrics-Dict oder -Objekt.
    """
    if isinstance(metrics, dict):
        _display_metrics_from_dict(metrics)
        return

    print(f"\n{'='*60}")
    print(f"  📈 Gespeicherte Modell-Metriken: {metrics.model_name}")
    print(f"{'='*60}")
    print(f"  Accuracy          : {metrics.accuracy:.1%}")
    print(f"  ROC-AUC           : {metrics.roc_auc:.4f}")
    print(f"  Brier Score       : {metrics.brier_score:.4f}")
    print(f"  CV Accuracy       : {metrics.cv_accuracy_mean:.1%} ± {metrics.cv_accuracy_std:.1%}")
    print(f"  Trainingssamples  : {metrics.train_samples}")
    print(f"{'='*60}\n")


def _display_metrics_from_dict(metrics: dict) -> None:
    """Gibt Metriken aus einem Dictionary aus."""
    print(f"\n{'='*60}")
    print(f"  📈 Gespeicherte Modell-Metriken: {metrics.get('model_name', '?')}")
    print(f"{'='*60}")
    print(f"  Accuracy          : {metrics.get('accuracy', 0):.1%}")
    print(f"  ROC-AUC           : {metrics.get('roc_auc', 0):.4f}")
    print(f"  Brier Score       : {metrics.get('brier_score', 0):.4f}")
    print(f"  CV Accuracy       : {metrics.get('cv_accuracy_mean', 0):.1%} "
          f"± {metrics.get('cv_accuracy_std', 0):.1%}")
    print(f"  Trainingssamples  : {metrics.get('train_samples', '?')}")
    top = metrics.get("top_features", [])
    if top:
        print(f"\n  Top Features:")
        for item in top[:5]:
            name = item["feature"] if isinstance(item, dict) else item[0]
            imp = item["importance"] if isinstance(item, dict) else item[1]
            bar = "█" * int(imp * 80)
            print(f"    {name:<32} {imp:.3f}  {bar}")
    print(f"{'='*60}\n")


def _print_probability_bar(prefix: str, team: str, probability: float) -> None:
    """Gibt einen farbcodierten Wahrscheinlichkeitsbalken aus."""
    filled = round(probability * 30)
    bar = f"{'█' * filled}{'░' * (30 - filled)}"
    print(f"  {prefix}: [{bar}] {probability:5.1%}  {team}")
