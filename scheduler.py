"""
Scheduler — Agent de veille quotidienne
=========================================
Lance generer_rapport.py tous les jours à 9h00 (Europe/Paris).
Tourne en continu avec une boucle infinie.

Usage :
    python scheduler.py

Options :
    --run-now   → exécute immédiatement le rapport (pour tester sans attendre 9h)
"""

import argparse
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import schedule
import time

# ---------------------------------------------------------------------------
# Configuration des logs
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("scheduler.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

FUSEAU     = ZoneInfo("Europe/Paris")
SCRIPT     = Path(__file__).parent / "generer_rapport.py"
HEURE_RUN  = "09:00"


# ---------------------------------------------------------------------------
# Tâche planifiée
# ---------------------------------------------------------------------------

def lancer_rapport():
    """Exécute generer_rapport.py et journalise le résultat."""
    maintenant = datetime.now(FUSEAU)
    logger.info("=" * 60)
    logger.info(f"Démarrage du rapport — {maintenant.strftime('%A %d %B %Y à %H:%M')}")

    if not SCRIPT.exists():
        logger.error(f"Script introuvable : {SCRIPT}")
        return

    try:
        resultat = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=300,          # 5 minutes max
        )

        if resultat.returncode == 0:
            logger.info("Rapport généré avec succès.")
            if resultat.stdout.strip():
                for ligne in resultat.stdout.strip().splitlines():
                    logger.info(f"  {ligne}")
        else:
            logger.error(f"Le script a échoué (code {resultat.returncode})")
            if resultat.stderr.strip():
                for ligne in resultat.stderr.strip().splitlines():
                    logger.error(f"  {ligne}")

    except subprocess.TimeoutExpired:
        logger.error("Le script a dépassé le délai de 5 minutes.")
    except Exception as e:
        logger.exception(f"Erreur inattendue lors de l'exécution : {e}")

    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scheduler de veille quotidienne")
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Exécute le rapport immédiatement (sans attendre 9h)",
    )
    args = parser.parse_args()

    logger.info("Scheduler de veille démarré.")
    logger.info(f"Rapport programmé chaque jour à {HEURE_RUN} (Europe/Paris).")
    logger.info(f"Script cible : {SCRIPT}")

    # Planification quotidienne
    schedule.every().day.at(HEURE_RUN).do(lancer_rapport)

    # Exécution immédiate si --run-now
    if args.run_now:
        logger.info("--run-now détecté : exécution immédiate du rapport.")
        lancer_rapport()

    logger.info("En attente de la prochaine exécution planifiée... (Ctrl+C pour arrêter)\n")

    while True:
        schedule.run_pending()
        # Vérification toutes les 30 secondes
        time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Scheduler arrêté manuellement.")
        sys.exit(0)
