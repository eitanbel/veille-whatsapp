"""
Tests locaux — Agent de veille WhatsApp
========================================
Vérifie la structure du projet sans envoyer de WhatsApp ni consommer de crédits API.

Usage :
    python test_local.py
"""

import os
import json
import sys
import traceback
from pathlib import Path
from datetime import datetime

# Chargement du .env si présent
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Utilitaires d'affichage
# ---------------------------------------------------------------------------

VERT  = "\033[92m"
ROUGE = "\033[91m"
JAUNE = "\033[93m"
RESET = "\033[0m"
GRAS  = "\033[1m"

resultats = []


def ok(test: str, detail: str = ""):
    msg = f"  {VERT}✓ PASS{RESET}  {test}"
    if detail:
        msg += f"  {JAUNE}({detail}){RESET}"
    print(msg)
    resultats.append(("PASS", test))


def echec(test: str, detail: str = ""):
    msg = f"  {ROUGE}✗ FAIL{RESET}  {test}"
    if detail:
        msg += f"\n         {ROUGE}→ {detail}{RESET}"
    print(msg)
    resultats.append(("FAIL", test))


def titre(texte: str):
    print(f"\n{GRAS}{texte}{RESET}")
    print("─" * len(texte))


# ---------------------------------------------------------------------------
# Test 1 : Variables d'environnement
# ---------------------------------------------------------------------------

VARS_REQUISES = [
    "ANTHROPIC_API_KEY",
    "TAVILY_API_KEY",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_WHATSAPP_FROM",
    "WHATSAPP_DEST",
]


def test_variables_env():
    titre("1. Variables d'environnement")
    for var in VARS_REQUISES:
        valeur = os.getenv(var, "")
        est_placeholder = not valeur or "xxx" in valeur.lower() or "xxxxxxxx" in valeur
        if not est_placeholder:
            ok(var, f"{valeur[:6]}…")
        else:
            echec(var, "Non définie ou valeur d'exemple — remplissez votre .env")


# ---------------------------------------------------------------------------
# Test 2 : Imports des dépendances
# ---------------------------------------------------------------------------

DEPS = [
    ("fastapi",   "FastAPI"),
    ("uvicorn",   "uvicorn"),
    ("anthropic", "Anthropic SDK"),
    ("requests",  "requests"),
    ("dotenv",    "python-dotenv"),
    ("schedule",  "schedule"),
    ("twilio",    "twilio"),
]


def test_imports():
    titre("2. Dépendances Python")
    for module, label in DEPS:
        try:
            __import__(module)
            ok(label)
        except ImportError:
            echec(label, f"pip install {module}")


# ---------------------------------------------------------------------------
# Test 3 : Fichiers du projet
# ---------------------------------------------------------------------------

FICHIERS_REQUIS = [
    "serveur_qa.py",
    "generer_rapport.py",
    "scheduler.py",
    "requirements.txt",
    ".env.example",
    "README.md",
]


def test_fichiers():
    titre("3. Fichiers du projet")
    base = Path(__file__).parent
    for fichier in FICHIERS_REQUIS:
        chemin = base / fichier
        if chemin.exists():
            taille = chemin.stat().st_size
            ok(fichier, f"{taille} octets")
        else:
            echec(fichier, "Fichier manquant")


# ---------------------------------------------------------------------------
# Test 4 : Syntaxe Python
# ---------------------------------------------------------------------------

SCRIPTS_PYTHON = ["serveur_qa.py", "generer_rapport.py", "scheduler.py"]


def test_syntaxe():
    titre("4. Syntaxe Python")
    base = Path(__file__).parent
    for script in SCRIPTS_PYTHON:
        chemin = base / script
        if not chemin.exists():
            echec(script, "Fichier introuvable")
            continue
        try:
            import ast
            source = chemin.read_text(encoding="utf-8")
            ast.parse(source)
            ok(script)
        except SyntaxError as e:
            echec(script, f"Erreur ligne {e.lineno} : {e.msg}")


# ---------------------------------------------------------------------------
# Test 5 : Rapport factice (logique de sauv/chargement)
# ---------------------------------------------------------------------------

RAPPORT_TEST = Path("rapport_du_jour.json")


def test_rapport_factice():
    titre("5. Sauvegarde / lecture du rapport")

    rapport_contenu = (
        "🗞️ *Revue de presse — TEST*\n\n"
        "🤖 *Tech & IA*\n"
        "• Point 1 test\n• Point 2 test\n• Point 3 test\n"
        "💬 _Répondez Q1, Q2 ou Q3_\n\n"
        "💼 *M&A & Finance*\n"
        "• Point 4 test\n• Point 5 test\n• Point 6 test\n"
        "💬 _Répondez Q4, Q5 ou Q6_\n\n"
        "🌍 *International*\n"
        "• Point 7 test\n• Point 8 test\n• Point 9 test\n"
        "💬 _Répondez Q7, Q8 ou Q9_"
    )

    # Sauvegarde
    try:
        data = {
            "rapport": rapport_contenu,
            "date": "mardi 1 janvier 2026",
            "raw": {},
            "sauvegarde_le": datetime.now().isoformat(),
        }
        RAPPORT_TEST.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        ok("Sauvegarde rapport_du_jour.json")
    except Exception as e:
        echec("Sauvegarde rapport_du_jour.json", str(e))
        return

    # Rechargement
    try:
        loaded = json.loads(RAPPORT_TEST.read_text(encoding="utf-8"))
        assert loaded["rapport"] == rapport_contenu
        assert loaded["date"] == "mardi 1 janvier 2026"
        ok("Lecture rapport_du_jour.json")
    except Exception as e:
        echec("Lecture rapport_du_jour.json", str(e))


# ---------------------------------------------------------------------------
# Test 6 : Endpoint /question (mock — sans appel API réel)
# ---------------------------------------------------------------------------

def test_endpoint_question_mock():
    titre("6. Endpoint /question (simulation sans API)")

    try:
        from fastapi.testclient import TestClient

        # Patch du client Anthropic pour éviter un vrai appel
        import unittest.mock as mock
        import serveur_qa

        reponse_simulee = "Voici une réponse simulée pour Q1 (test local)."

        with mock.patch.object(
            serveur_qa.client.messages,
            "create",
            return_value=mock.MagicMock(
                content=[mock.MagicMock(text=reponse_simulee)]
            ),
        ):
            client_test = TestClient(serveur_qa.app)

            # Vérification /health
            r = client_test.get("/health")
            assert r.status_code == 200
            ok("GET /health", f"statut {r.status_code}")

            # Vérification /question avec rapport disponible
            r = client_test.post("/question", json={"question": "Q1"})
            assert r.status_code == 200
            assert "reponse" in r.json()
            ok("POST /question", "réponse reçue")

    except ImportError:
        echec("fastapi[testclient]", "Installez : pip install httpx")
    except Exception as e:
        echec("Endpoint /question", traceback.format_exc(limit=3))


# ---------------------------------------------------------------------------
# Résumé final
# ---------------------------------------------------------------------------

def afficher_resume():
    passes = sum(1 for r in resultats if r[0] == "PASS")
    fails  = sum(1 for r in resultats if r[0] == "FAIL")
    total  = len(resultats)

    print(f"\n{'='*50}")
    print(f"{GRAS}Résumé des tests{RESET}")
    print(f"{'='*50}")
    print(f"  {VERT}✓ Réussis : {passes}/{total}{RESET}")
    if fails:
        print(f"  {ROUGE}✗ Échoués : {fails}/{total}{RESET}")
        print(f"\n  {JAUNE}Actions requises :{RESET}")
        for statut, test in resultats:
            if statut == "FAIL":
                print(f"    - {test}")
    else:
        print(f"\n  {VERT}{GRAS}Tout est prêt ! Lancez le serveur avec :{RESET}")
        print(f"    uvicorn serveur_qa:app --host 0.0.0.0 --port 8000 --reload")
        print(f"\n  Testez le rapport sans WhatsApp :")
        print(f"    python generer_rapport.py --dry-run")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"\n{GRAS}{'='*50}{RESET}")
    print(f"{GRAS}  Agent de veille WhatsApp — Tests locaux{RESET}")
    print(f"{GRAS}{'='*50}{RESET}")

    test_variables_env()
    test_imports()
    test_fichiers()
    test_syntaxe()
    test_rapport_factice()
    test_endpoint_question_mock()
    afficher_resume()

    # Code de sortie non-zero si des tests ont échoué
    if any(r[0] == "FAIL" for r in resultats):
        sys.exit(1)
