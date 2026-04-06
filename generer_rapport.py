"""
Générateur de rapport de veille matinal — v2
=============================================
Pipeline :
  1. 13 requêtes Tavily sur 5 thèmes
  2. 5 appels Claude distincts (un par thème), max_tokens=4000
  3. 1 message Sources + 1 message Statut
  4. Envoi des 7 messages WhatsApp via Twilio (pause 2s entre chaque)
  5. Sauvegarde rapport_du_jour.json + sync serveur Render

Usage :
    python generer_rapport.py            → génération + envoi WhatsApp
    python generer_rapport.py --dry-run  → affiche sans envoyer
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import anthropic
from twilio.rest import Client as TwilioClient
from dotenv import load_dotenv

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RAPPORT_FILE      = Path("rapport_du_jour.json")
MODEL             = "claude-sonnet-4-6"
FUSEAU            = ZoneInfo("Europe/Paris")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TAVILY_API_KEY    = os.getenv("TAVILY_API_KEY", "")
TWILIO_SID        = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN      = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM       = os.getenv("TWILIO_WHATSAPP_FROM", "")
WHATSAPP_DEST     = os.getenv("WHATSAPP_DEST", "")
SERVEUR_URL       = os.getenv("SERVEUR_URL", "")

# ---------------------------------------------------------------------------
# Définition des 5 thèmes et leurs requêtes Tavily
# ---------------------------------------------------------------------------

THEMES = [
    {
        "cle":    "geopolitique",
        "label":  "OSINT & Géopolitique internationale",
        "emoji":  "🌍",
        "queries": [
            "geopolitical analysis intelligence briefing today",
            "OSINT military diplomatic tensions conflict today",
            "international relations foreign policy breaking today",
        ],
    },
    {
        "cle":    "politique_fr",
        "label":  "Politique française",
        "emoji":  "🇫🇷",
        "queries": [
            "politique France gouvernement actualité aujourd'hui",
            "Assemblée nationale sénat réforme loi vote aujourd'hui",
            "partis politiques France polémique actualité aujourd'hui",
        ],
    },
    {
        "cle":    "economie",
        "label":  "Économie",
        "emoji":  "📊",
        "queries": [
            "économie France croissance indicateurs actualité aujourd'hui",
            "CAC40 entreprises françaises résultats aujourd'hui",
            "Federal Reserve US economy markets today",
            "China economy trade relations US GDP today",
        ],
    },
    {
        "cle":    "ma",
        "label":  "M&A",
        "emoji":  "🤝",
        "queries": [
            "fusion acquisition France deal transaction aujourd'hui",
            "M&A tech startup France levée de fonds rachat aujourd'hui",
            "major international M&A deal acquisition today",
        ],
    },
    {
        "cle":    "tech_ia",
        "label":  "Tech & IA",
        "emoji":  "💡",
        "queries": [
            "Anthropic Claude update new features release today",
            "artificial intelligence AI model release OpenAI Google today",
            "tech news Apple Microsoft startup innovation aujourd'hui",
        ],
    },
]

# ---------------------------------------------------------------------------
# Prompts Claude
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Tu es un analyste de veille stratégique senior. Tu produis une section de rapport quotidien : dense, sourcée, analytique.
RÈGLES ABSOLUES :
- Cite le nom du média inline après chaque fait important : (Reuters, 01/04)
- Ne jamais avancer un fait sans source
- Analyser, pas juste résumer : pourquoi c'est important, quelles implications
- Si l'information est insuffisante sur un point, dis-le explicitement
- Format WhatsApp strict : gras avec asterisques, pas de markdown complexe
- Longueur cible : 400-500 mots par section"""

PROMPTS_THEMES = {
    "geopolitique": (
        "Voici les données brutes du jour sur la géopolitique internationale :\n"
        "{resultats}\n\n"
        "Rédige la section OSINT & GÉOPOLITIQUE INTERNATIONALE pour le rapport de veille du {date}.\n"
        "Format attendu :\n"
        "🌍 GÉOPOLITIQUE & OSINT\n"
        "——————————————\n"
        "[Ton analyse ici, 400-500 mots, avec citations inline (Média, JJ/MM)]"
    ),
    "politique_fr": (
        "Voici les données brutes du jour sur la politique française :\n"
        "{resultats}\n\n"
        "Rédige la section POLITIQUE FRANÇAISE pour le rapport de veille du {date}.\n"
        "Format attendu :\n"
        "🇫🇷 POLITIQUE FRANÇAISE\n"
        "——————————————\n"
        "[Ton analyse ici, 400-500 mots, avec citations inline (Média, JJ/MM)]"
    ),
    "economie": (
        "Voici les données brutes du jour sur l'économie française et internationale :\n"
        "{resultats}\n\n"
        "Rédige la section ÉCONOMIE pour le rapport de veille du {date}.\n"
        "Structure en deux sous-parties clairement séparées :\n"
        "🇫🇷 France\n"
        "🌐 International (US & Chine)\n\n"
        "Format attendu :\n"
        "📊 ÉCONOMIE\n"
        "——————————————\n"
        "🇫🇷 France\n"
        "[Analyse France, 200-250 mots, citations inline]\n"
        "🌐 International\n"
        "[Analyse US & Chine, 200-250 mots, citations inline]"
    ),
    "ma": (
        "Voici les données brutes du jour sur les fusions-acquisitions :\n"
        "{resultats}\n\n"
        "Rédige la section M&A pour le rapport de veille du {date}.\n"
        "PRIORITÉ : Les deals français (tech + tous secteurs).\n"
        "N'inclure un deal international que s'il est particulièrement notable (montant très élevé, "
        "impact sur des acteurs français, signal stratégique fort). Si c'est le cas, indique clairement pourquoi tu l'as retenu.\n"
        "Si aucun deal notable aujourd'hui, dis-le explicitement.\n"
        "Format attendu :\n"
        "🤝 M&A\n"
        "——————————————\n"
        "[Ton analyse ici, 400-500 mots max, citations inline (Média, JJ/MM)]"
    ),
    "tech_ia": (
        "Voici les données brutes du jour sur la tech et l'intelligence artificielle :\n"
        "{resultats}\n\n"
        "Rédige la section TECH & IA pour le rapport de veille du {date}.\n"
        "ORDRE DE PRIORITÉ dans ta rédaction :\n"
        "1. Anthropic / Claude en premier (nouveautés, mises à jour, annonces)\n"
        "2. Autres modèles et acteurs IA (OpenAI, Google, Meta, Mistral...)\n"
        "3. Tech grand public (Apple, Microsoft, startups notables)\n\n"
        "Format attendu :\n"
        "💡 TECH & INTELLIGENCE ARTIFICIELLE\n"
        "——————————————\n"
        "[Ton analyse ici, 400-500 mots, citations inline (Média, JJ/MM)]"
    ),
}


# ---------------------------------------------------------------------------
# Étape 1 : Recherche Tavily
# ---------------------------------------------------------------------------

def rechercher_tavily(query: str) -> dict:
    """Lance une requête Tavily et retourne le JSON brut."""
    if not TAVILY_API_KEY:
        raise ValueError("TAVILY_API_KEY manquante dans le fichier .env")

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "max_results": 7,
        "include_answer": True,
    }
    try:
        resp = requests.post("https://api.tavily.com/search", json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        print(f"  [WARN] Timeout Tavily : '{query}'")
        return {"results": []}
    except Exception as e:
        print(f"  [ERREUR] Tavily échoué pour '{query}' : {e}")
        return {"results": []}


def agregger_theme(queries: list, label: str) -> tuple[str, list]:
    """
    Lance toutes les requêtes d'un thème, déduplique par URL,
    retourne (texte_formaté, liste_urls).
    """
    vus = set()
    tous_resultats = []

    for query in queries:
        print(f"  → '{query}'")
        data = rechercher_tavily(query)
        for r in data.get("results", []):
            url = r.get("url", "")
            if url and url not in vus:
                vus.add(url)
                tous_resultats.append(r)

    # Formatage pour Claude
    lignes = []
    urls = []
    for i, r in enumerate(tous_resultats, start=1):
        titre   = r.get("title", "Sans titre")
        url     = r.get("url", "")
        date_r  = r.get("published_date", "")
        extrait = (r.get("content") or "")[:500]
        source  = url.split("/")[2] if url else "inconnu"

        lignes.append(
            f"[{i}] Titre : {titre}\n"
            f"Source : {source}\n"
            f"URL : {url}\n"
            f"Date : {date_r}\n"
            f"Extrait : {extrait}"
        )
        urls.append({"titre": titre, "url": url})

    texte = (
        f"=== THÈME : {label} ===\n" +
        "\n\n".join(lignes) if lignes
        else f"=== THÈME : {label} ===\nAucun résultat disponible."
    )

    print(f"  → {len(tous_resultats)} articles uniques collectés")
    return texte, urls


# ---------------------------------------------------------------------------
# Étape 2 : Génération des sections par Claude (5 appels distincts)
# ---------------------------------------------------------------------------

def generer_section(cle: str, resultats: str, date_str: str) -> str:
    """Génère une section du rapport via un appel Claude dédié."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = PROMPTS_THEMES[cle].format(resultats=resultats, date=date_str)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except anthropic.APIConnectionError:
        raise RuntimeError("Impossible de joindre l'API Anthropic.")
    except anthropic.AuthenticationError:
        raise RuntimeError("Clé API Anthropic invalide.")
    except Exception as e:
        raise RuntimeError(f"Erreur Claude pour '{cle}' : {e}")


# ---------------------------------------------------------------------------
# Étape 3 : Construction du message Sources
# ---------------------------------------------------------------------------

def construire_message_sources(urls_par_theme: dict, date_str: str) -> str:
    """Construit le 6ème message WhatsApp avec les sources du jour."""
    lignes = [f"🔗 *SOURCES DU JOUR — {date_str}*\n——————————————"]

    emojis = {
        "geopolitique": "🌍 Géopolitique",
        "politique_fr": "🇫🇷 Politique",
        "economie":     "📊 Économie",
        "ma":           "🤝 M&A",
        "tech_ia":      "💡 Tech & IA",
    }

    for cle, label in emojis.items():
        urls = urls_par_theme.get(cle, [])[:5]
        if not urls:
            continue
        lignes.append(f"\n{label}")
        for item in urls:
            titre_court = item["titre"][:60] + ("…" if len(item["titre"]) > 60 else "")
            lignes.append(f"• {titre_court}\n  {item['url']}")

    return "\n".join(lignes)


# ---------------------------------------------------------------------------
# Étape 4 : Envoi WhatsApp
# ---------------------------------------------------------------------------

def decouper_en_blocs(texte: str, limite: int = 1500) -> list:
    """
    Découpe un texte long en blocs de max `limite` caractères.
    Coupe proprement sur les sauts de ligne pour ne pas tronquer au milieu d'une phrase.
    """
    if len(texte) <= limite:
        return [texte]

    blocs = []
    lignes = texte.split("\n")
    bloc_courant = ""

    for ligne in lignes:
        candidat = (bloc_courant + "\n" + ligne).strip() if bloc_courant else ligne
        if len(candidat) <= limite:
            bloc_courant = candidat
        else:
            if bloc_courant:
                blocs.append(bloc_courant)
            # Si une seule ligne dépasse la limite, on la force-coupe
            while len(ligne) > limite:
                blocs.append(ligne[:limite])
                ligne = ligne[limite:]
            bloc_courant = ligne

    if bloc_courant:
        blocs.append(bloc_courant)

    return blocs


def envoyer_whatsapp_simple(message: str, twilio: TwilioClient) -> bool:
    """Envoie un message WhatsApp — le découpe en plusieurs si > 1500 chars."""
    blocs = decouper_en_blocs(message)
    succes = True
    for i, bloc in enumerate(blocs, 1):
        suffixe = f" ({i}/{len(blocs)})" if len(blocs) > 1 else ""
        try:
            msg = twilio.messages.create(
                from_=TWILIO_FROM,
                to=WHATSAPP_DEST,
                body=bloc + suffixe,
            )
            print(f"  [OK] Bloc {i}/{len(blocs)} — SID : {msg.sid}")
            if len(blocs) > 1:
                time.sleep(1)
        except Exception as e:
            print(f"  [ERREUR] Bloc {i} échoué : {e}")
            succes = False
    return succes


# ---------------------------------------------------------------------------
# Étape 5 : Sauvegarde + sync Render
# ---------------------------------------------------------------------------

def sauvegarder_et_sync(rapport_complet: str, date_str: str, raw: dict):
    """Sauvegarde le rapport localement et le synchronise avec Render."""
    data = {
        "rapport": rapport_complet,
        "date": date_str,
        "raw": raw,
        "sauvegarde_le": datetime.now(FUSEAU).isoformat(),
    }
    RAPPORT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[INFO] Rapport sauvegardé dans {RAPPORT_FILE}")

    if SERVEUR_URL:
        try:
            resp = requests.post(
                f"{SERVEUR_URL.rstrip('/')}/rapport",
                json={"rapport": rapport_complet, "date": date_str},
                timeout=60,
            )
            if resp.status_code == 200:
                print(f"[INFO] Rapport synchronisé avec {SERVEUR_URL}")
            else:
                print(f"[WARN] Render a répondu {resp.status_code}")
        except Exception as e:
            print(f"[WARN] Sync Render échouée : {e}")


# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------

def main(dry_run: bool = False):
    debut = datetime.now(FUSEAU)
    # Date en français
    jours = ["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]
    mois  = ["janvier","février","mars","avril","mai","juin",
             "juillet","août","septembre","octobre","novembre","décembre"]
    date_str = f"{jours[debut.weekday()]} {debut.day} {mois[debut.month - 1]} {debut.year}"
    heure_str = debut.strftime("%H:%M")

    print(f"\n{'='*60}")
    print(f"[VEILLE] Rapport du {date_str} — démarrage à {heure_str}")
    print(f"{'='*60}\n")

    # ── Étape 1 : Tavily ──────────────────────────────────────────
    resultats_par_theme = {}
    urls_par_theme = {}
    total_sources = 0

    for theme in THEMES:
        print(f"[TAVILY] Thème : {theme['label']} ({len(theme['queries'])} requêtes)")
        texte, urls = agregger_theme(theme["queries"], theme["label"])
        resultats_par_theme[theme["cle"]] = texte
        urls_par_theme[theme["cle"]] = urls
        total_sources += len(urls)

    print(f"\n[INFO] Total sources collectées : {total_sources} articles uniques\n")

    # ── Étape 2 : Claude (5 appels) ───────────────────────────────
    sections = {}
    alertes = []
    total_mots = 0

    for theme in THEMES:
        cle = theme["cle"]
        print(f"[CLAUDE] Génération section : {theme['label']}...")
        try:
            section = generer_section(cle, resultats_par_theme[cle], date_str)
        except RuntimeError as e:
            print(f"  [ERREUR FATALE] {e}")
            sys.exit(1)

        nb_mots = len(section.split())
        total_mots += nb_mots
        print(f"  → {nb_mots} mots générés")

        if nb_mots < 200:
            alerte = f"⚠️ SECTION {theme['label'].upper()} TROP COURTE : {nb_mots} mots"
            print(f"  [WARNING] {alerte}")
            alertes.append(alerte)

        sections[cle] = section

    # ── Étape 3 : Message Sources ──────────────────────────────────
    msg_sources = construire_message_sources(urls_par_theme, date_str)

    # ── Étape 4 : Message Statut ───────────────────────────────────
    fin = datetime.now(FUSEAU)
    duree = int((fin - debut).total_seconds())
    alertes_str = "\n".join(alertes) if alertes else "Aucune"

    msg_statut = (
        f"✅ *Rapport généré — {date_str} à {heure_str}*\n"
        f"——————————————\n"
        f"⏱ Durée : {duree}s\n"
        f"📝 Mots : {total_mots}\n"
        f"🔍 Sources Tavily : {total_sources}/{len(THEMES) * 3} requêtes exploitées\n"
        f"⚠️ Alertes : {alertes_str}"
    )

    # ── Affichage terminal ─────────────────────────────────────────
    print(f"\n{'─'*60}")
    for theme in THEMES:
        print(sections[theme["cle"]])
        print()
    print(msg_sources)
    print()
    print(msg_statut)
    print(f"{'─'*60}\n")

    # ── Rapport complet pour le Q&A ────────────────────────────────
    rapport_complet = "\n\n".join(sections[t["cle"]] for t in THEMES)

    if dry_run:
        print("[DRY-RUN] Mode test — aucun message WhatsApp envoyé.")
    else:
        # Vérification des variables Twilio
        for var, nom in [
            (TWILIO_SID,   "TWILIO_ACCOUNT_SID"),
            (TWILIO_TOKEN, "TWILIO_AUTH_TOKEN"),
            (TWILIO_FROM,  "TWILIO_WHATSAPP_FROM"),
            (WHATSAPP_DEST,"WHATSAPP_DEST"),
        ]:
            if not var:
                print(f"[ERREUR] Variable manquante : {nom}")
                sys.exit(1)

        twilio = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
        ordre = [
            ("geopolitique", "🌍 Géopolitique"),
            ("politique_fr", "🇫🇷 Politique française"),
            ("economie",     "📊 Économie"),
            ("ma",           "🤝 M&A"),
            ("tech_ia",      "💡 Tech & IA"),
        ]

        print("[WHATSAPP] Envoi des messages...")
        for cle, label in ordre:
            print(f"  Envoi : {label}")
            envoyer_whatsapp_simple(sections[cle], twilio)
            time.sleep(2)

        print("  Envoi : Sources")
        envoyer_whatsapp_simple(msg_sources, twilio)
        time.sleep(2)

        print("  Envoi : Statut")
        envoyer_whatsapp_simple(msg_statut, twilio)

    # ── Sauvegarde ─────────────────────────────────────────────────
    sauvegarder_et_sync(rapport_complet, date_str, {
        t["cle"]: resultats_par_theme[t["cle"]] for t in THEMES
    })

    print(f"\n[OK] Pipeline terminé en {duree}s — {total_mots} mots — {total_sources} sources.\n")


def send_only():
    """Envoie le rapport_du_jour.json déjà généré sans rappeler Tavily ni Claude."""
    if not RAPPORT_FILE.exists():
        print("[ERREUR] Aucun rapport trouvé. Lancez d'abord sans --send-only.")
        sys.exit(1)

    data = json.loads(RAPPORT_FILE.read_text(encoding="utf-8"))
    rapport_complet = data.get("rapport", "")
    date_str = data.get("date", "aujourd'hui")

    if not rapport_complet:
        print("[ERREUR] Le rapport sauvegardé est vide.")
        sys.exit(1)

    print(f"[INFO] Rapport du {date_str} chargé ({len(rapport_complet.split())} mots)")

    for var, nom in [
        (TWILIO_SID,   "TWILIO_ACCOUNT_SID"),
        (TWILIO_TOKEN, "TWILIO_AUTH_TOKEN"),
        (TWILIO_FROM,  "TWILIO_WHATSAPP_FROM"),
        (WHATSAPP_DEST,"WHATSAPP_DEST"),
    ]:
        if not var:
            print(f"[ERREUR] Variable manquante : {nom}")
            sys.exit(1)

    twilio = TwilioClient(TWILIO_SID, TWILIO_TOKEN)

    # Découpe le rapport complet en sections sur les emojis de titre
    separateurs = ["🌍", "🇫🇷", "📊", "🤝", "💡"]
    messages = []
    reste = rapport_complet

    for sep in separateurs[1:]:
        if sep in reste:
            idx = reste.index(sep)
            partie = reste[:idx].strip()
            if partie:
                messages.append(partie)
            reste = reste[idx:]
    if reste.strip():
        messages.append(reste.strip())

    if not messages:
        messages = [rapport_complet]

    print(f"[WHATSAPP] Envoi de {len(messages)} message(s)...")
    for i, msg in enumerate(messages, 1):
        print(f"  Envoi message {i}/{len(messages)}...")
        envoyer_whatsapp_simple(msg, twilio)
        time.sleep(2)

    print("[OK] Rapport envoyé sur WhatsApp.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Génère et envoie le rapport de veille")
    parser.add_argument("--dry-run",   action="store_true", help="Génère sans envoyer")
    parser.add_argument("--send-only", action="store_true", help="Envoie le rapport déjà généré")
    args = parser.parse_args()

    if args.send_only:
        send_only()
    else:
        main(dry_run=args.dry_run)
