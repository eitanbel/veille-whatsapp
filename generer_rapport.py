"""
Générateur de rapport de veille matinal
========================================
1. Recherche les actualités sur 3 thèmes via l'API Tavily
2. Passe les résultats à Claude (claude-sonnet-4-6) pour rédiger le rapport
3. Envoie le rapport sur WhatsApp via Twilio
4. Sauvegarde le rapport dans rapport_du_jour.json

Usage :
    python generer_rapport.py            → génération + envoi WhatsApp
    python generer_rapport.py --dry-run  → affiche le rapport sans envoyer
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import anthropic
from twilio.rest import Client as TwilioClient
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RAPPORT_FILE = Path("rapport_du_jour.json")
MODEL = "claude-sonnet-4-6"
FUSEAU = ZoneInfo("Europe/Paris")

TAVILY_API_KEY     = os.getenv("TAVILY_API_KEY", "")
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
TWILIO_SID         = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN       = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM        = os.getenv("TWILIO_WHATSAPP_FROM", "")
WHATSAPP_DEST      = os.getenv("WHATSAPP_DEST", "")
SERVEUR_URL        = os.getenv("SERVEUR_URL", "")

THEMES = [
    {
        "cle":   "tech",
        "label": "Tech & IA",
        "emoji": "🤖",
        "query": "intelligence artificielle tech actualités du jour",
        "shortcodes": "Q1, Q2 ou Q3",
    },
    {
        "cle":   "ma",
        "label": "M&A & Finance",
        "emoji": "💼",
        "query": "fusions acquisitions M&A deals finance actualités",
        "shortcodes": "Q4, Q5 ou Q6",
    },
    {
        "cle":   "intl",
        "label": "International",
        "emoji": "🌍",
        "query": "international geopolitique business actualités du jour",
        "shortcodes": "Q7, Q8 ou Q9",
    },
]

SYSTEM_PROMPT_RAPPORT = (
    "Tu es un assistant de veille stratégique. "
    "Rédige une revue de presse matinale concise en français pour WhatsApp. "
    "Sois factuel et synthétique. Maximum 300 mots. "
    "Utilise le format WhatsApp (*gras*, _italique_)."
)


# ---------------------------------------------------------------------------
# Étape 1 : Recherche Tavily
# ---------------------------------------------------------------------------

def rechercher_tavily(query: str, max_results: int = 5) -> dict:
    """Appelle l'API Tavily et retourne les résultats JSON."""
    if not TAVILY_API_KEY:
        raise ValueError("TAVILY_API_KEY manquante dans le fichier .env")

    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "max_results": max_results,
        "include_answer": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        print(f"[ERREUR] Timeout lors de la recherche Tavily : '{query}'")
        return {"results": []}
    except requests.exceptions.HTTPError as e:
        print(f"[ERREUR] HTTP {e.response.status_code} pour Tavily : {e}")
        return {"results": []}
    except Exception as e:
        print(f"[ERREUR] Recherche Tavily échouée : {e}")
        return {"results": []}


def formater_resultats(data: dict, label: str) -> str:
    """Formate les résultats Tavily pour le contexte Claude."""
    resultats = data.get("results", [])
    if not resultats:
        return f"{label} : aucun résultat disponible."

    lignes = []
    for i, r in enumerate(resultats[:4], start=1):
        titre   = r.get("title", "Sans titre")
        url     = r.get("url", "")
        contenu = (r.get("content") or "")[:300]
        lignes.append(f"[{label}-{i}] {titre}\nSource : {url}\nRésumé : {contenu}...")

    return "\n\n".join(lignes)


# ---------------------------------------------------------------------------
# Étape 2 : Génération du rapport par Claude
# ---------------------------------------------------------------------------

def generer_rapport_claude(articles: dict, date_str: str) -> str:
    """Envoie les articles à Claude et retourne le rapport formaté."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY manquante dans le fichier .env")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Construction du prompt utilisateur
    sections = []
    for theme in THEMES:
        cle = theme["cle"]
        sections.append(f"=== {theme['label'].upper()} ===\n{articles[cle]}")

    date_section = "\n\n".join(sections)

    prompt = (
        f"Tu es un assistant de veille stratégique. Voici les actualités du {date_str}.\n\n"
        f"{date_section}\n\n"
        "Rédige une revue de presse matinale en français, concise et professionnelle, pour WhatsApp.\n\n"
        "Format EXACT à respecter :\n\n"
        f"🗞️ *Revue de presse — {date_str}*\n\n"
        "🤖 *Tech & IA*\n"
        "• [Point 1 — 1 phrase percutante]\n"
        "• [Point 2 — 1 phrase percutante]\n"
        "• [Point 3 — 1 phrase percutante]\n"
        "💬 _Répondez Q1, Q2 ou Q3 pour approfondir_\n\n"
        "💼 *M&A & Finance*\n"
        "• [Point 1]\n"
        "• [Point 2]\n"
        "• [Point 3]\n"
        "💬 _Répondez Q4, Q5 ou Q6 pour approfondir_\n\n"
        "🌍 *International*\n"
        "• [Point 1]\n"
        "• [Point 2]\n"
        "• [Point 3]\n"
        "💬 _Répondez Q7, Q8 ou Q9 pour approfondir_\n\n"
        "---\n"
        "_Bonne journée !_ 🚀\n\n"
        "Sois factuel, synthétique. Maximum 300 mots."
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT_RAPPORT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except anthropic.APIConnectionError:
        raise RuntimeError("Impossible de joindre l'API Anthropic. Vérifiez votre connexion.")
    except anthropic.AuthenticationError:
        raise RuntimeError("Clé API Anthropic invalide. Vérifiez votre fichier .env.")
    except Exception as e:
        raise RuntimeError(f"Erreur lors de la génération Claude : {e}")


# ---------------------------------------------------------------------------
# Étape 3 : Envoi WhatsApp via Twilio
# ---------------------------------------------------------------------------

def decouper_messages(rapport: str, limite: int = 1550) -> list:
    """
    Découpe le rapport en plusieurs messages si nécessaire.
    Coupe proprement entre les sections (🤖, 💼, 🌍).
    """
    if len(rapport) <= limite:
        return [rapport]

    separateurs = ["💼", "🌍", "---"]
    parties = [rapport]
    for sep in separateurs:
        nouvelles_parties = []
        for partie in parties:
            if len(partie) > limite and sep in partie:
                idx = partie.index(sep)
                nouvelles_parties.append(partie[:idx].rstrip())
                nouvelles_parties.append(partie[idx:])
            else:
                nouvelles_parties.append(partie)
        parties = nouvelles_parties

    return [p for p in parties if p.strip()]


def envoyer_whatsapp(message: str) -> bool:
    """Envoie le rapport sur WhatsApp via Twilio (découpe si > 1550 chars)."""
    for var, nom in [
        (TWILIO_SID,   "TWILIO_ACCOUNT_SID"),
        (TWILIO_TOKEN, "TWILIO_AUTH_TOKEN"),
        (TWILIO_FROM,  "TWILIO_WHATSAPP_FROM"),
        (WHATSAPP_DEST,"WHATSAPP_DEST"),
    ]:
        if not var:
            print(f"[ERREUR] Variable manquante : {nom}")
            return False

    try:
        twilio = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
        parties = decouper_messages(message)
        print(f"[INFO] Envoi en {len(parties)} message(s)...")

        for i, partie in enumerate(parties, 1):
            msg = twilio.messages.create(
                from_=TWILIO_FROM,
                to=WHATSAPP_DEST,
                body=partie,
            )
            print(f"[INFO] Message {i}/{len(parties)} envoyé — SID : {msg.sid}")

        return True
    except Exception as e:
        print(f"[ERREUR] Envoi WhatsApp échoué : {e}")
        return False


# ---------------------------------------------------------------------------
# Étape 4 : Sauvegarde locale
# ---------------------------------------------------------------------------

def sauvegarder_rapport(rapport: str, date_str: str, raw: dict):
    """Sauvegarde le rapport localement et l'envoie au serveur Render si configuré."""
    data = {
        "rapport": rapport,
        "date": date_str,
        "raw": raw,
        "sauvegarde_le": datetime.now(FUSEAU).isoformat(),
    }
    RAPPORT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[INFO] Rapport sauvegardé dans {RAPPORT_FILE}")

    # Envoi au serveur distant (Render) pour le Q&A WhatsApp
    if SERVEUR_URL:
        try:
            resp = requests.post(
                f"{SERVEUR_URL.rstrip('/')}/rapport",
                json={"rapport": rapport, "date": date_str},
                timeout=15,
            )
            if resp.status_code == 200:
                print(f"[INFO] Rapport envoyé au serveur distant : {SERVEUR_URL}")
            else:
                print(f"[ERREUR] Serveur distant a répondu {resp.status_code}")
        except Exception as e:
            print(f"[ERREUR] Impossible d'envoyer au serveur distant : {e}")


# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------

def main(dry_run: bool = False):
    """Pipeline complet : recherche → Claude → WhatsApp → sauvegarde."""
    maintenant = datetime.now(FUSEAU)
    date_str = maintenant.strftime("%A %d %B %Y")

    print(f"\n{'='*60}")
    print(f"[VEILLE] Génération du rapport — {date_str}")
    print(f"{'='*60}\n")

    # 1. Recherche des actualités
    articles_raw = {}
    articles_fmt = {}
    for theme in THEMES:
        print(f"[INFO] Recherche '{theme['label']}'...")
        data = rechercher_tavily(theme["query"])
        articles_raw[theme["cle"]] = data
        articles_fmt[theme["cle"]] = formater_resultats(data, theme["label"])

    # 2. Génération du rapport par Claude
    print("[INFO] Génération du rapport par Claude...")
    try:
        rapport = generer_rapport_claude(articles_fmt, date_str)
    except RuntimeError as e:
        print(f"[ERREUR FATALE] {e}")
        sys.exit(1)

    # 3. Affichage / envoi
    print("\n" + "─" * 60)
    print(rapport)
    print("─" * 60 + "\n")

    if dry_run:
        print("[DRY-RUN] Mode test — aucun message WhatsApp envoyé.")
    else:
        print("[INFO] Envoi du rapport sur WhatsApp...")
        envoyer_whatsapp(rapport)

    # 4. Sauvegarde
    sauvegarder_rapport(rapport, date_str, articles_raw)
    print("[OK] Pipeline terminé avec succès.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Génère et envoie le rapport de veille")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Génère le rapport sans envoyer le WhatsApp",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)
