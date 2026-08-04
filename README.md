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
EZOLL_FIRMA=100
EZOLL_HEADED=true
```

## Bürgschaft abfragen

Entspricht dem PDF „Abfrage Bürgschaft Schritt für Schritt“:

1. Login  
2. Firmennummer + Enter  
3. `2` Andere Zollverfahren + Enter  
4. `12` Archiv/Evidenz + Enter  
5. Datum ab (≥ ½ Jahr) + MsgTy `CC015C`, Enter, F10  
6. Bild-ab bis letzte Seite → **… EUR Bürgschaft**

```bash
python -m ezoll buergschaft
```

Nur den Betrag ausgeben bzw. periodisch:

```bash
python -m ezoll buergschaft
python -m ezoll buergschaft --watch 300
```

Optionen:

```bash
python -m ezoll buergschaft --firma 100 --datum-von 20260101 --msgty CC015C
```

Zwischenschritte landen als Screenshot/Text in `artifacts/` (`01-…` bis `06-…`).

Wenn der Filter nicht greift, Tab-Anzahl anpassen:

```env
EZOLL_MSGTY_TABS=2
```

## Weitere Befehle

```bash
python -m ezoll login-test
python -m ezoll screen
python -m ezoll send "F3"
python -m ezoll extract --pattern "([\\d.]+,\\d{2})\\s*EUR\\s*Bürgschaft"
python -m ezoll macro macros/buergschaft.macro
```
