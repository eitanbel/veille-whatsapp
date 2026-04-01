"""
Serveur Q&A interactif — Agent de veille WhatsApp
==================================================
Endpoints :
  POST /rapport        → reçoit et sauvegarde le rapport du jour (appelé par n8n)
  POST /question       → reçoit une question, retourne la réponse de Claude
  POST /twilio-webhook → webhook direct Twilio (TwiML), alternative à n8n pour le Q&A
  GET  /health         → statut du serveur + date du dernier rapport

Lancer : uvicorn serveur_qa:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import json
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse
import anthropic
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Agent de veille — Q&A interactif", version="1.0")

# Initialisation du client Anthropic
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

RAPPORT_FILE = Path("rapport_du_jour.json")
MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """Tu es un assistant de veille stratégique personnel.
Chaque matin, l'utilisateur reçoit un rapport sur WhatsApp avec 9 points numérotés :
- Q1, Q2, Q3 → Tech & IA
- Q4, Q5, Q6 → M&A & Finance
- Q7, Q8, Q9 → International

Quand l'utilisateur envoie "Q3" par exemple, tu dois approfondir le point 3 du rapport.
Quand il pose une question libre, tu réponds en t'appuyant sur le rapport du jour.

Règles de réponse :
- Toujours en français
- Format WhatsApp (*gras*, _italique_)
- Maximum 250 mots
- Concis, factuel, utile
- Si la question sort du rapport, dis-le clairement et réponds quand même si tu peux
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def charger_rapport() -> dict:
    """Charge le rapport du jour depuis le fichier JSON."""
    if not RAPPORT_FILE.exists():
        return {"rapport": None, "date": None}
    try:
        return json.loads(RAPPORT_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERREUR] Impossible de lire le rapport : {e}")
        return {"rapport": None, "date": None}


def sauvegarder_rapport(rapport: str, date_str: str, raw: dict = None):
    """Sauvegarde le rapport du jour dans rapport_du_jour.json."""
    data = {
        "rapport": rapport,
        "date": date_str,
        "raw": raw or {},
        "sauvegarde_le": str(date.today()),
    }
    RAPPORT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[INFO] Rapport sauvegardé pour le {date_str}")


def construire_prompt_utilisateur(question: str, rapport: str, date_str: str) -> str:
    """Construit le message utilisateur envoyé à Claude."""
    return (
        f"Rapport du {date_str} :\n\n"
        f"{rapport}\n\n"
        "---\n"
        f"Question de l'utilisateur : {question}\n\n"
        "Réponds en te basant sur ce rapport. "
        "Si c'est un raccourci (Q1 à Q9), identifie le point correspondant et approfondis-le."
    )


def appeler_claude(question: str, rapport: str, date_str: str) -> str:
    """Appelle Claude et retourne la réponse textuelle."""
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": construire_prompt_utilisateur(question, rapport, date_str),
                }
            ],
        )
        return response.content[0].text
    except anthropic.APIConnectionError:
        return "⚠️ Impossible de joindre l'API Anthropic. Vérifiez votre connexion."
    except anthropic.AuthenticationError:
        return "⚠️ Clé API Anthropic invalide. Vérifiez votre fichier .env."
    except Exception as e:
        return f"⚠️ Erreur lors de la génération de la réponse : {e}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {"service": "Agent de veille — Q&A interactif", "version": "1.0"}


@app.get("/health")
async def health():
    """Statut du serveur + informations sur le rapport disponible."""
    storage = charger_rapport()
    return {
        "status": "ok",
        "rapport_disponible": storage.get("rapport") is not None,
        "date_rapport": storage.get("date"),
        "sauvegarde_le": storage.get("sauvegarde_le"),
    }


@app.post("/rapport")
async def recevoir_rapport(request: Request):
    """
    Appelé par n8n après la génération du rapport matinal.
    Corps attendu : { "rapport": "...", "date": "...", "raw": {...} }
    """
    try:
        data = await request.json()
    except Exception:
        return {"status": "erreur", "message": "Corps JSON invalide"}, 400

    rapport = data.get("rapport", "").strip()
    if not rapport:
        return {"status": "erreur", "message": "Le champ 'rapport' est vide"}

    sauvegarder_rapport(
        rapport=rapport,
        date_str=data.get("date", str(date.today())),
        raw=data.get("raw", {}),
    )
    return {"status": "ok", "message": "Rapport sauvegardé avec succès"}


@app.post("/question")
async def repondre_question(request: Request):
    """
    Appelé par n8n quand l'utilisateur répond au message WhatsApp.
    Corps attendu : { "question": "Q3" }
    Retourne      : { "reponse": "..." }
    """
    try:
        data = await request.json()
    except Exception:
        return {"reponse": "❌ Corps JSON invalide."}

    question = data.get("question", "").strip()
    if not question:
        return {
            "reponse": "Je n'ai pas compris votre question. Essayez Q1 à Q9 ou posez une question directement."
        }

    storage = charger_rapport()
    rapport = storage.get("rapport")
    date_str = storage.get("date", "aujourd'hui")

    if not rapport:
        return {
            "reponse": "⚠️ Aucun rapport disponible pour aujourd'hui. Le prochain rapport sera envoyé demain à 9h."
        }

    reponse = appeler_claude(question, rapport, date_str)
    return {"reponse": reponse}


@app.post("/twilio-webhook")
async def twilio_webhook(request: Request):
    """
    Webhook direct Twilio (alternative à n8n pour la branche Q&A).
    Twilio envoie un formulaire multipart/form-data.
    On répond en TwiML pour que Twilio envoie la réponse directement en WhatsApp.
    """
    form = await request.form()
    question = form.get("Body", "").strip()

    storage = charger_rapport()
    rapport = storage.get("rapport")
    date_str = storage.get("date", "aujourd'hui")

    if not rapport:
        reponse = "⚠️ Aucun rapport disponible aujourd'hui. Revenez demain matin !"
    elif not question:
        reponse = "Envoyez Q1–Q9 pour approfondir un point, ou posez une question libre."
    else:
        reponse = appeler_claude(question, rapport, date_str)

    # Échapper les caractères XML spéciaux
    reponse_xml = (
        reponse
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f"    <Message>{reponse_xml}</Message>\n"
        "</Response>"
    )
    return PlainTextResponse(content=twiml, media_type="application/xml")


@app.post("/generer")
async def generer_rapport(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint appelé par cron-job.org chaque matin à 9h.
    Protégé par un token secret (variable CRON_SECRET dans .env).
    Lance la génération en arrière-plan et répond immédiatement.
    """
    cron_secret = os.getenv("CRON_SECRET", "")
    if cron_secret:
        token = request.headers.get("X-Cron-Secret", "")
        if token != cron_secret:
            return PlainTextResponse("Non autorisé", status_code=401)

    def lancer_generation():
        try:
            from generer_rapport import main
            main(dry_run=False)
        except Exception as e:
            print(f"[ERREUR] Génération du rapport échouée : {e}")

    background_tasks.add_task(lancer_generation)
    return {"status": "ok", "message": "Génération du rapport lancée en arrière-plan"}
