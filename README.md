# Agent de veille quotidienne — WhatsApp

Reçoit chaque matin à 9h un rapport de veille sur 3 thèmes (Tech & IA, M&A, International)
directement sur WhatsApp, et répond à vos questions en tapant Q1–Q9 ou une question libre.

```
Flux complet :
Tavily (actus) → Claude (rédaction) → Twilio (WhatsApp) → vous répondez → Claude répond
```

---

## Architecture

| Fichier | Rôle |
|---|---|
| `generer_rapport.py` | Recherche Tavily → Claude → envoi WhatsApp → sauvegarde |
| `serveur_qa.py` | Serveur FastAPI — reçoit vos réponses et interroge Claude |
| `scheduler.py` | Lance `generer_rapport.py` chaque jour à 9h (Europe/Paris) |
| `test_local.py` | Tests locaux sans appels API réels |
| `veille_workflow.json` | Workflow n8n alternatif (optionnel) |

---

## 1. Installation

```bash
# Clonez ou copiez le projet, puis :
cd veille-whatsapp

# Créez un environnement virtuel (recommandé)
python3 -m venv .venv
source .venv/bin/activate       # macOS / Linux
# .venv\Scripts\activate        # Windows

# Installez les dépendances
pip install -r requirements.txt
```

---

## 2. Configuration — fichier .env

```bash
cp .env.example .env
```

Éditez `.env` et remplissez chaque valeur :

| Variable | Où la trouver |
|---|---|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com/ |
| `TAVILY_API_KEY` | https://app.tavily.com/ |
| `TWILIO_ACCOUNT_SID` | https://console.twilio.com/ |
| `TWILIO_AUTH_TOKEN` | https://console.twilio.com/ |
| `TWILIO_WHATSAPP_FROM` | Votre numéro Twilio sandbox, ex: `whatsapp:+14155238886` |
| `WHATSAPP_DEST` | Votre numéro perso, ex: `whatsapp:+336XXXXXXXX` |

---

## 3. Configurer Twilio WhatsApp Sandbox

1. Ouvrez la [console Twilio](https://console.twilio.com/)
2. **Messaging → Try it out → Send a WhatsApp message**
3. Rejoignez le sandbox depuis votre téléphone en suivant les instructions
4. Dans **Sandbox Settings**, configurez le webhook entrant :
   ```
   WHEN A MESSAGE COMES IN : https://votre-domaine.com/twilio-webhook
   ```
   (ou votre URL ngrok en développement — voir section 5)

---

## 4. Lancer le projet

### Serveur Q&A (terminal 1)
```bash
uvicorn serveur_qa:app --host 0.0.0.0 --port 8000 --reload
```

### Scheduler (terminal 2)
```bash
python scheduler.py
```

---

## 5. Tester sans attendre 9h

### Générer un rapport maintenant (sans envoyer de WhatsApp)
```bash
python generer_rapport.py --dry-run
```

### Générer ET envoyer le rapport maintenant
```bash
python generer_rapport.py
```

### Lancer le scheduler et exécuter immédiatement
```bash
python scheduler.py --run-now
```

### Tester le serveur manuellement (curl)
```bash
# Vérifier l'état du serveur
curl http://localhost:8000/health

# Envoyer une question
curl -X POST http://localhost:8000/question \
     -H "Content-Type: application/json" \
     -d '{"question": "Q1"}'

# Injecter un rapport manuellement
curl -X POST http://localhost:8000/rapport \
     -H "Content-Type: application/json" \
     -d '{"rapport": "🗞️ *Test* ...", "date": "mardi 1 avril 2025"}'
```

### Exposer le serveur local avec ngrok (pour Twilio)
```bash
ngrok http 8000
# Copiez l'URL https://xxxx.ngrok.io et collez-la dans Twilio :
# https://xxxx.ngrok.io/twilio-webhook
```

---

## 6. Tests locaux

```bash
python test_local.py
```

Vérifie :
- Variables d'environnement définies
- Dépendances installées
- Fichiers présents
- Syntaxe Python valide
- Sauvegarde/lecture du rapport
- Endpoints FastAPI (mock sans appel API)

---

## 7. Workflow n8n (optionnel)

Le fichier `veille_workflow.json` est une alternative complète à Python pour générer
et envoyer le rapport depuis n8n.

1. Ouvrez votre instance n8n
2. **Workflows → Import from File** → sélectionnez `veille_workflow.json`
3. Configurez les credentials : `Anthropic` et `Twilio`
4. Activez le workflow

> Dans ce cas, `generer_rapport.py` et `scheduler.py` ne sont pas nécessaires.
> Seul `serveur_qa.py` reste utile pour le Q&A interactif.

---

## 8. Raccourcis Q1–Q9

| Raccourci | Thème |
|---|---|
| Q1, Q2, Q3 | Tech & IA |
| Q4, Q5, Q6 | M&A & Finance |
| Q7, Q8, Q9 | International |

Vous pouvez aussi envoyer n'importe quelle question libre en réponse au rapport.

---

## Dépannage

**"Aucun rapport disponible"** → Lancez d'abord `python generer_rapport.py`

**Twilio ne répond pas** → Vérifiez que l'URL webhook est bien configurée dans la console Twilio et que votre serveur est accessible depuis Internet (ngrok en local)

**Erreur Anthropic 401** → Vérifiez `ANTHROPIC_API_KEY` dans `.env`

**Erreur Tavily** → Vérifiez `TAVILY_API_KEY` et votre quota sur app.tavily.com
