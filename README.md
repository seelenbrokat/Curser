# Fahrzeugverleih - Digitale Inspektion

Eine moderne Webanwendung für den Fahrzeugverleih mit digitaler Fahrzeuginspektion und KI-gestützter Bildanalyse.

## Funktionen

### Kundenseite
- **Link-basierter Zugang**: Kunden erhalten einen einmaligen Zugangslink für ihr zugewiesenes Fahrzeug
- **Foto-Dokumentation**: Aufnahme von Fotos aus allen vier Seiten des Fahrzeugs
- **KI-Bildanalyse**: Automatische Überprüfung der Fotos auf Qualität und Fahrzeugzuordnung
- **Kilometerstand-Erfassung**: Fotografische Dokumentation des Kilometerstands
- **Digitaler Mietvertrag**: Online-Vertragsunterzeichnung
- **Rückgabe-Prozess**: Gleicher Inspektionsprozess bei Fahrzeugrückgabe

### Admin-Bereich
- **Fahrzeugverwaltung**: Verwaltung der Fahrzeugflotte
- **Vermietungsverwaltung**: Erstellung und Überwachung von Vermietungen
- **Zugangslinks**: Automatische Generierung sicherer Zugangslinks
- **Inspektionsübersicht**: Einsicht in alle Inspektionsfotos und -daten
- **Vertragsverwaltung**: Übersicht über alle Mietverträge

## Technologie-Stack

- **Frontend**: Next.js 16, React 19, TypeScript, Tailwind CSS
- **Backend**: Next.js API Routes
- **Datenbank**: SQLite mit Prisma ORM
- **Authentifizierung**: NextAuth.js
- **Bildanalyse**: Serverbasierte Analyse (erweiterbar mit KI-Modellen)

## Installation

1. **Dependencies installieren**:
```bash
npm install
```

2. **Datenbank initialisieren**:
```bash
npx prisma generate
npx prisma db push
```

3. **Seed-Daten einfügen** (optional):
```bash
npx tsx lib/seed.ts
```

Dies erstellt:
- Admin-User: `admin@example.com` / `admin123`
- Zwei Beispielfahrzeuge

4. **Umgebungsvariablen konfigurieren**:

Die `.env` Datei ist bereits vorkonfiguriert. Für Produktion sollten Sie folgende Werte ändern:
- `NEXTAUTH_SECRET`: Generieren Sie einen sicheren Secret-Key
- `NEXTAUTH_URL`: Setzen Sie die Produktions-URL

## Entwicklung

```bash
npm run dev
```

Die Anwendung ist unter [http://localhost:3000](http://localhost:3000) erreichbar.

## Verwendung

### Admin-Bereich

1. Melden Sie sich unter `/auth/signin` mit den Admin-Zugangsdaten an
2. Erstellen Sie Fahrzeuge unter "Neues Fahrzeug"
3. Erstellen Sie eine Vermietung unter "Neue Vermietung"
4. Kopieren Sie den generierten Zugangslink und senden Sie ihn an den Kunden

### Kunden-Workflow

1. Kunde öffnet den erhaltenen Zugangslink
2. Fotografiert das Fahrzeug von allen vier Seiten
3. KI analysiert die Fotos automatisch
4. Fotografiert den Kilometerstand
5. Unterzeichnet den Mietvertrag digital
6. Bei Rückgabe: Admin initiiert Rückgabe-Inspektion
7. Kunde durchläuft den gleichen Foto-Prozess erneut

## KI-Bildanalyse

Die aktuelle Implementierung verwendet eine regelbasierte Bildanalyse, die:
- Bildgröße und -qualität prüft
- Feedback zur Bildqualität gibt
- Validierung durchführt

### Erweiterung mit echten KI-Modellen

Die Bildanalyse kann leicht mit echten Vision-Modellen erweitert werden:

1. **OpenAI GPT-4 Vision**:
```typescript
// In lib/image-analysis.ts
import OpenAI from 'openai';
const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
```

2. **Hugging Face Inference API** (kostenlos):
```typescript
// Verwenden Sie Modelle wie BLIP, ViT, oder ähnliche
```

3. **Lokale Modelle mit Ollama**:
```bash
ollama run llava
```

## Projektstruktur

```
├── app/
│   ├── admin/              # Admin-Dashboard und Verwaltung
│   ├── api/                # API Routes
│   ├── auth/               # Authentifizierungs-Seiten
│   ├── contract/           # Mietvertrags-Seiten
│   └── inspection/         # Inspektions-Workflow
├── components/             # React-Komponenten
├── lib/                    # Utilities und Helper
├── prisma/                 # Datenbank-Schema
└── public/                 # Statische Dateien
```

## Deployment

### Vercel (empfohlen)

1. Pushen Sie das Repository zu GitHub
2. Verbinden Sie es mit Vercel
3. Konfigurieren Sie die Umgebungsvariablen
4. Deployen Sie die Anwendung

### Andere Plattformen

Die Anwendung ist kompatibel mit allen Next.js-Hosting-Plattformen (Netlify, AWS, etc.).

## Sicherheit

- Alle Zugangslinks sind einmalig und sicher
- Passwörter werden mit bcrypt gehasht
- Session-basierte Authentifizierung
- CSRF-Schutz durch NextAuth.js

## Lizenz

ISC

## Support

Bei Fragen oder Problemen öffnen Sie bitte ein Issue im Repository.
