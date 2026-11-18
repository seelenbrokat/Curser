# WOG Connect (Swiss Post Labels)

Produktives Deployment: `wog.connect.logistikberater.at` auf dem VPS (`/opt/wog-connect`).

## Fix 2026-07-30: Barcode `customer.name1` Pattern

Die CH-Post Barcode-API lehnt Apostrophe in `customer.name1` ab und erlaubt max. **25** Zeichen (Empfänger `name1`: 35).

`app/mapper.py` entfernt Apostrophe/Anführungszeichen, kürzt und splittet lange Namen auf `name1`/`name2`.

Deploy: Datei nach `/opt/wog-connect/app/mapper.py`, danach `systemctl restart wog-connect`.

## Kundenportal

Separater Login für Kunden (nur Erfassen + Label drucken): `/kunde`

Konfiguration in `.env`:

```
PORTAL_CUSTOMER_USERS=muparo:PASSWORT|Muparo AG|Bahnhofstrasse 34|9470|Buchs (SG)|CH
```

Mehrere Konten mit `;` trennen. Format: `user:password|Anzeigename|Strasse|PLZ|Ort|Land`
