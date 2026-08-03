# eZollOnline Lokal-Automation

Lokales Python-Programm, das sich per Browser (Playwright) bei
[eZollOnline / aXesTS](https://zoll.ldv.at/ts/ts2/start_new.html) anmeldet,
AS400-Tasten sendet und Bildschirminhalte ausliest.

Läuft **auf deinem Rechner** (wichtig wegen IP-Freischaltung).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

In `.env` Benutzer und Passwort eintragen:

```env
EZOLL_USER=...
EZOLL_PASSWORD=...
EZOLL_HEADED=true
```

## Befehle

```bash
# Verbindung / Login testen (Browser sichtbar)
python -m ezoll login-test

# Aktuellen Screen speichern (artifacts/)
python -m ezoll screen

# Tasten senden
python -m ezoll send "F3"
python -m ezoll send "text:ABC123,Enter"

# Wert per Regex holen
python -m ezoll extract --pattern "Status\\s*[:=]\\s*(\\S+)"

# Periodisch auslesen
python -m ezoll watch --pattern "Status\\s*[:=]\\s*(\\S+)" --interval 30

# Makro ausführen
python -m ezoll macro macros/beispiel.macro
```

Screenshots und Screen-Dumps landen in `artifacts/`.

## Nächster Schritt

Schick eine Bildschirmaufnahme des gewünschten Ablaufs (Login → Maske → Feld).
Dann wird die Navigation als konkretes Makro hinterlegt und der Zielwert stabil ausgelesen.
