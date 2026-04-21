# Dashboard KI-Agenten — Handover / Projekt-Kontext

Interne Plattform der DBS Home GmbH fuer KI-gestuetzte Verwaltungs-Workflows.

User: Daniel Kroll (kroll@dbshome.de).

> **Code-abgeleitete Struktur-Doku** (Dateibaum, Datenmodell-Felder, Routen-Liste, Tech-Stack-Details) liegt in `docs/` — generiert per `bmad-document-project`. Diese Datei konzentriert sich auf **Status, Design-Entscheidungen, Session-Historie und User-Praeferenzen**, die aus dem Code allein nicht ableitbar sind.

## Projektziel

Zentrale Web-Plattform, auf der Mitarbeitende Dokumente hochladen und KI-Agenten damit Routineaufgaben erledigen — nach Human-in-the-Loop-Freigabe ueber einen Chat direkt auf der Website.

**Erstes Modul**: automatisiertes Pflegen von SEPA-Lastschriftmandaten aus eingescannten PDFs in die Impower-Hausverwaltungs-API. Ersetzt einen fehleranfaelligen manuellen Prozess.

**Langfristig**: Multi-Modul-Plattform. Neue Workflows werden als Plug-in-Module angedockt; gemeinsame Core-Services (Auth, Queue, Audit, Files, Notifications, LLM-Zugang, Impower-Connector) sind bewusst wiederverwendbar angelegt.

## Aktueller Status (2026-04-21)

- **M0–M2**: fertig, live verifiziert.
- **M3 SEPA-Schreibpfad**: Code fertig. Idempotenz-Zweig live OK (Floegel HAM61 → `already_present`). **Neuanlage-Zweig (Tilker GVE1 / Kulessa BRE11: PUT Contact mit neuem Bank-Account + POST Mandat + POST UCM-Array) noch nicht live verifiziert.**
- **M4 Elestio-Deployment**: **deprioritisiert** — erledigen wir irgendwann nebenbei, kein aktiver Meilenstein.
- **M5 Mietverwaltungs-Anlage**: **Code komplett (Pakete 1–8), Live-Tests komplett offen.** Multi-Doc-Workflow (Verwaltervertrag + Grundbuch + Mietvertraege + Mieterliste → Fall), typ-spezifische Extraktion, konsolidierter Case-State mit User-Overrides, Impower-Write in 8 Schritten (Contacts → Property → PROPERTY_OWNER-Contract → PUT Property + Buildings → Units → TENANT-Contracts → Exchange-Plan → Deposit), Delta-Patch-Chat am Case.
- **UI**: Sidebar-Layout (Dashboard · Workflows · Admin + User-Block unten); Workflow-Zugang nur ueber Dashboard-Kacheln mit Gradient-Header.
- **Git-Repo**: initialisiert, 2 Commits auf `main`, Remote `git@github.com:dakroxy/dashboard-ai-agents.git`.

### Naechste Schritte

1. **M5 Paket 7 Live-Test** — Fall mit Verwaltervertrag + Grundbuch + Mieterliste + ≥1 Mietvertrag komplett durchspielen → `POST /cases/{id}/write`. Besonders beobachten: Exchange-Plan-Step. Wenn Impower 400/422 wirft, muss der `templateExchanges[]`-Aufbau (MVP: 1 Plan mit 3 Positions-Typen COLD_RENT / OPERATING_COSTS / HEATING_COSTS) auf eine andere Granularitaet umgebaut werden (ggf. 1 Plan pro Position oder Summen-Eintrag mit Splits).
2. **M3 Neuanlage-Zweig** live verifizieren (Tilker GVE1 / Kulessa BRE11).

## Architektur (Module)

```
Dashboard (Web-UI)
  └─ Platform-Core: Auth · Rollen/Permissions · Audit · Files · Notifications
        ├─ Claude-API-Client (PDF-Extraktion, Chat-Agent)   ← M1
        └─ Impower-Connector (Read + Write)                 ← M2 (read) / M3 (write)
               │
               ├─ Modul 1: Lastschrift-Agent (M1–M3)              ← Single-Doc-Workflow
               ├─ Modul 2: Mietverwaltungs-Anlage (M5)            ← Multi-Doc-Fall (Case-Container)
               └─ Sub-Workflow: Contact-Create                    ← aus Modul 2 + spaetere Module aufrufbar
```

**Tech-Stack** (Kurzfassung, Details in `docs/architecture.md`): FastAPI 0.115 · Python 3.12 · Postgres 16 · SQLAlchemy 2.0 + Alembic · HTMX 2 + Jinja2 + Tailwind (CDN) · Authlib (Google Workspace OAuth) · Anthropic SDK (Opus 4.7 / Sonnet 4.6) · `schwifty` fuer IBAN/BIC · Docker Compose.

### Workflow-Konfiguration in DB

System-Prompt + Erkennungsmodell (`model`) + Chat-Modell (`chat_model`) + Lernnotizen pro KI-Agent sind editierbar (`/workflows/{key}`). Erkennungs- und Chat-Modell sind bewusst **getrennt** konfigurierbar — der Chat-Flow muss exakt Ziffern reproduzieren (IBANs), da scheitert Haiku empirisch; Default Chat-Modell ist Sonnet 4.6.

Drei Workflows geseedet: `sepa_mandate` (M1–M3), `mietverwaltung_setup` (M5), `contact_create` (Sub-Workflow, aus Mietverwaltung aufrufbar + standalone nutzbar). Default-Prompts / Default-Modelle stehen in `app/services/claude.py` (`DEFAULT_SYSTEM_PROMPT` / `DEFAULT_MIETVERWALTUNG_SYSTEM_PROMPT` / `DEFAULT_CONTACT_CREATE_SYSTEM_PROMPT` / `DEFAULT_MODEL` / `DEFAULT_CHAT_MODEL`) und werden beim App-Start via FastAPI-Lifespan geseedet (`_seed_default_workflow` in `main.py`), falls der Workflow fehlt — bestehende User-Aenderungen werden **nicht** ueberschrieben.

### Claude-Integration — Design-Entscheidungen

- **Modelle**: Erkennungsmodell Default `claude-opus-4-7`, Chat-Modell Default `claude-sonnet-4-6`. Verfuegbar: Opus 4.7, Sonnet 4.6, Haiku 4.5.
- **Haiku fuer Chat empirisch nicht tragfaehig** — scheitert an praeziser Ziffern-Reproduktion ueber 20+ Zeichen in freier JSON-Ausgabe (IBAN-Drop: verliert z. B. die letzte `0`). Sonnet ist der sichere Default, Opus Overkill fuer die Chat-Laenge.
- **IBAN-Guard im Chat-Flow**: vor Persistierung wird die IBAN **Unicode-NFKC-normalisiert** + auf reine Alphanumerik reduziert + per `schwifty` validiert. Hintergrund: Sonnet streut gelegentlich unsichtbare Zero-Width-Spaces (U+200B) in Ausgaben ein, die `replace(" ", "")` NICHT entfernt. Bei ungueltiger IBAN wird die Korrektur verworfen, der User bekommt im Chat-Antwort-Text einen `[Hinweis]`-Block.
- **API-Call**: `messages.create` (NICHT `messages.parse` — Grammar-Compilation-Timeout bei Optional-lastigen Pydantic-Schemas + PDF). Pydantic-Validierung client-seitig.
- **Prompt-Caching**: `cache_control: {type: "ephemeral"}` auf dem System-Block. Opus 4.7 hat 4096-Token-Mindestlaenge — mit aktuellem Prompt (~1000 Tokens) greift der Cache noch nicht; wirkt erst bei groesseren Prompts oder Lernnotizen.
- **Impower-Handling**: Antwortzeiten bis 60 s, transiente 503 vom Gateway; Client nutzt 120 s Timeout + 5xx-Retry mit Exponential-Backoff (2/5/15/30/60 s, max 5 Versuche).

### Secret-Management (1Password)

- Vault `KI` in "DBS Home GmbH". Items: `Google OAuth - HV Dashboard AI Agents` (username/credential), `Claude API Key - Lastschrift` (credential), `Impower API Token PowerAutomate` (credential).
- Service-Account-Token in macOS-Keychain als `op-service-account-ki`.
- Workflow: `.env.op` (committed, nur Refs) → `./scripts/env.sh` → `.env` (gitignored). `docker compose` liest `.env` physisch, deshalb inject-basiert statt `op run`.
- Dev-only Werte (`SECRET_KEY`, `POSTGRES_PASSWORD`) sind Klartext in `.env.op`; Prod bekaeme echte Werte ueber Env-Variablen.

Lokal starten:
```bash
./scripts/env.sh                  # .env aus 1Password bauen (einmalig)
docker compose up --build
```

## Meilensteine

| ID | Inhalt | Status |
|----|--------|--------|
| M0 | Grundgeruest (FastAPI + Postgres + Docker) | fertig |
| M1 | OAuth + Upload + Extraktion + Chat + Workflow-Einstellungen | fertig |
| M2 | Impower-Matching (Property + Contact, Read-Pfad) | fertig, live verifiziert (HAM61 Score 100 %) |
| M3 | Freigabe → Impower-Schreibpfad (Bank-Account, Mandat, Haken) | **Code fertig, Idempotenz-Zweig live OK — Neuanlage-Zweig noch live zu verifizieren** |
| M4 | Elestio-Deployment + DNS + TLS | **deprioritisiert** (irgendwann nebenbei) |
| M5 | Mietverwaltungs-Anlage (Multi-Doc → Impower, neuer Workflow) | **Code komplett (Pakete 1–8), Live-Tests offen** — insbesondere Impower-Write (Paket 7); Exchange-Plan-Schema muss ggf. nach erstem POST angepasst werden |

## Stand M3 (2026-04-19)

### Was gebaut / gefixt wurde

1. **`_ensure_bank_account` neu** — Bank-Account-Anlage laeuft via `GET /services/pmp-accounting/api/v1/contacts/{id}` → Duplicate-Check im `bankAccounts[]`-Array (normalisierter IBAN-Vergleich) → falls neu: Item anhaengen, Server-Felder (`id`, `created`, `createdBy`, `updated`, `updatedBy`, `domainId`, `casaviSyncData`) aus bestehenden Items strippen → `PUT /services/pmp-accounting/api/v1/contacts/{id}` → neue `bankAccountId` aus der PUT-Response via IBAN-Match extrahieren. Der urspruenglich vermutete `POST /v2/contacts/{id}/bank-accounts`-Endpunkt existiert nicht.
2. **`_create_direct_debit_mandate`** — `state`-Feld aus dem Payload raus; Impower setzt den Status selbst via UCM.
3. **`_create_unit_contract_mandates`** — ein einziger POST mit Array aller Eintraege statt Loop mit Einzelobjekten. Response ist ebenfalls ein Array mit IDs.
4. **Idempotenz-Check** — nach `_ensure_bank_account` wird `GET /api/v1/direct-debit-mandate?propertyId=X` geladen und gegen `{bankAccountId, state: "BOOKED"}` gefiltert. Treffer → Early-Return mit `WriteResult.already_present=True`, kein POST. `Document.status = "already_present"`, UI zeigt gruene Meldung.
5. **BIC-Auto-Ableitung via `schwifty`** — moderne SEPA-Mandate drucken oft keinen BIC, Impower besteht auf gueltigem BIC. Extract-seitig bleibt BIC optional; der Write-Pfad zieht bei leerem BIC das Register. Faellt durch auf klaren Fehler, wenn die BLZ im schwifty-Register nicht bekannt ist.
6. **IBAN-Validierung + Unicode-Normalize (Chat-Guard)** — siehe "Claude-Integration" oben; an zwei Stellen verdrahtet (`_normalize_iban` in `impower.py` + Chat-Guard in `claude.py`).
7. **Chat-Modell separat konfigurierbar** (Migration 0005), Default Sonnet 4.6.
8. **WriteResult.already_present** + neuer Doc-Status `already_present`. Chat-Korrekturen resetten `already_present` zurueck auf `extracted`, damit Re-Matching durchlaeuft.

### Live-Teststand (HAM61 Floegel)

- Matching 100 % (Property + Contact Score 100 %).
- Schreibpfad: Idempotenz-Zweig durchgelaufen — Floegel hat bereits ein BOOKED-Mandat auf dieser IBAN (Mandat-ID 283929, Bank-Account-ID 700509). UI zeigt "bereits eingetragen", keine ungewollten Writes.
- **Noch nicht verifiziert**: Neuanlage-Zweig. Kandidaten: Tilker (GVE1) oder Kulessa (BRE11).

### Sekundaerer Befund: IBAN-Wechsel ist der Normalfall

Floegel hatte keine `open_contract_ids` — alle Unit-Contracts waren bereits mit einem aelteren Mandat verknuepft. Das ist der **haeufigste Case**: Eigentuemer wechselt Bankverbindung. Fuer diesen Fall braucht es einen erweiterten Flow: altes Mandat via `PUT /api/v1/direct-debit-mandate/deactivate` deaktivieren, neues Mandat anlegen, Unit-Contract-Verknuepfungen umhaengen. **Nicht im MVP implementiert, vor Produktiv-Rollout noetig.**

### Offene Punkte fuer M3

1. **Neuanlage-Zweig live verifizieren** — Tilker (GVE1) oder Kulessa (BRE11) hochladen, extrahieren, approven. Erwartung: PUT Contact mit neu angehaengtem Bank-Account, POST Mandat, POST UCM-Array → Status `written`. Damit ist auch die schwifty-BIC-Ableitung live getestet (Floegel ging ueber den Idempotenz-Shortcut, da lief der PUT gar nicht).
2. **IBAN-Wechsel-Szenario** (pre-prod): wenn alle Unit-Contracts der Person schon BOOKED sind und das gesuchte IBAN-Mandat NICHT darunter ist, muss erst `PUT /direct-debit-mandate/deactivate` auf das alte Mandat laufen, dann das neue angelegt und die Verknuepfungen umgehaengt werden. Logik-Skizze: aus `matching_result.contact.open_contract_ids == []` + `impower_result.already_present == False` folgt Wechsel-Case → separate Handler-Funktion, evtl. zusaetzlicher Status `iban_wechsel_pending` mit User-Bestaetigung im Chat bevor deactivate/re-create ausgefuehrt wird.

## Stand M5 (Mietverwaltung) — 2026-04-21

Multi-Doc-Workflow fuer die Neuanlage einer Mietverwaltung in Impower. Session 2026-04-20 hat die Pakete 1–4 (Fundament + Extraktion) abgeschlossen, Session 2026-04-21 die Pakete 5–8 (Form-UI + Contact-Create + Impower-Write + Chat). **Code-seitig komplett; offen sind nur Live-Tests.**

### Gesamt-Flow (implementiert)

Ein "Fall" (Case) sammelt die Dokumente zu einer Mietverwaltungs-Anlage: Verwaltervertrag, Grundbuch, Mieterliste, n Mietvertraege. Pro Dokument-Typ erkennt Claude die relevanten Felder (typ-spezifischer Prompt); ein Merge-Service baut daraus einen konsolidierten Case-State mit Provenance pro Feld. Der Nutzer sieht eine strukturierte Eingabemaske mit Status-Pills (erkannt / manuell / leer) pro Feld, editierbar in allen 7 Sektionen (Objekt · Verwaltung · Rechnung · Eigentuemer · Gebaeude · Einheiten · Mietvertraege). User-Edits landen als `_overrides` im Case-State und haben Vorrang vor den Auto-Merge-Werten. Fehlt ein Eigentuemer- oder Mieter-Kontakt in Impower, wird der wiederverwendbare `contact_create`-Sub-Workflow aufgerufen (Button in der Eigentuemer-Sektion, mit Prefill aus dem Case). Parallel steht ein Chat-Drawer bereit, der Delta-Patches zum State vorschlaegt. Nach Freigabe laeuft der Write-Pfad als BackgroundTask: Contacts (Eigentuemer + Mieter) → Property-Minimalanlage → PROPERTY_OWNER-Contract → PUT Property mit Detail-Feldern (inkl. Buildings inline) → Units (Array-POST) → TENANT-Contracts (Array-POST) → Exchange-Plan (Miet-Positionen) → Deposit (Kaution). Idempotenz via `case.impower_result`.

### Paket-Status (Kurzfassung)

Alle 8 Pakete ✓ fertig:
1. Impower Write-API recherchiert (`memory/reference_impower_mietverwaltung_api.md`).
2. Datenmodell + Migration `0008_cases_and_document_types.py` + Workflow-Seeding.
3. Case-Entity + Multi-Doc-Upload-UI.
4. Extract-Pipeline pro PDF-Typ (Classifier + typ-spezifische Prompts + Pydantic-Schemas + Merge-Logik in `app/services/mietverwaltung.py`).
5. Editierbare Form-UI mit Status-Indikatoren pro Feld (`case_detail.html` komplett neu, 7 Sektionen, 13 Save-Routen, Override-Reset pro Sektion).
6. Contact-Create-Sub-Workflow (`contacts.py` Router + `contact_create.html`, zwei-Phasen-Flow mit Duplicate-Check).
7. Impower-Write-Pfad (`app/services/mietverwaltung_write.py`, 8-stufiger Flow, idempotent, Preflight, Live-Status-UI mit Meta-Refresh).
8. Case-Chat mit Delta-Patch-Support (`chat_about_case()`, Migration `0009_chat_messages_case_id.py`, Chat-Drawer unten rechts).

### Architektur-Entscheidungen

- **Ein Fall = n Dokumente**: Neue Tabelle `cases` als Container. `documents.case_id` ist **nullable**, damit SEPA-Workflow unveraendert bleibt. `documents.doc_type` ebenfalls nullable.
- **`case.state` als JSONB** enthaelt drei konzeptionelle Layer: (a) `_extractions` = Rohdaten pro Doc (Provenance), (b) Auto-Merge-Werte aus `merge_case_state()`, (c) `_overrides` = User-Edits. Beim Rendern gewinnt `_overrides` > Auto-Merge. `field_source()` liefert fuer jedes Feld im Template den Layer zurueck (Pill erkannt/manuell/leer).
- **Dict-Sektionen vs. List-Sektionen bei Overrides**: flache Sektionen (`property`, `management_contract`, `billing_address`, `owner`) werden **feldweise** gemerged — User kann einzelne Felder ueberschreiben, der Rest kommt weiterhin aus der Auto-Merge. Listen (`buildings`, `units`, `tenant_contracts`) werden **komplett** ersetzt, sobald der User sie bearbeitet (Bootstrap beim ersten Edit kopiert die aktuelle Auto-Liste in `_overrides`).
- **`contact_create` als eigener Workflow**: aus Mietverwaltung heraus als Sub-Flow aufrufbar (Eigentuemer-Neuanlage) und standalone nutzbar. Eigener `key` + Seed + editierbarer Prompt.
- **Mieter-Contacts im Write-Flow automatisch**: Paket 7 legt Mieter-Contacts ohne User-Intervention an. Der Contact-Create-Sub-Workflow (Paket 6) ist explizit **nicht** in die Write-Pipeline eingebunden — er bleibt dem Eigentuemer-Fall + manuellen Ad-hoc-Anlagen vorbehalten.
- **Prompts pro Doc-Typ im Code, nicht als separate Workflows**: `mietverwaltung_setup.system_prompt` ist ein Koordinator-/Meta-Prompt; die typ-spezifischen Extract-Prompts sind Code-Konstanten in `app/services/mietverwaltung.py`. Wenn der User spaeter pro Typ im UI tunen will, erweitern wir das Workflow-Model um `extraction_prompts: JSONB`.
- **Case-Chat liefert Delta-Patches, kein Full-JSON**: anders als der SEPA-Chat (Backlog-Punkt 5) gibt der Case-Chat nur geaenderte Sektionen zurueck; der Server merged sie in `_overrides`. Damit ist die Fehleroberflaeche bei langen Ziffernfolgen viel kleiner, und der Prompt bleibt unter Token-Budget.

### Offene fachliche Fragen

- **Exchange-Plan-Schema** (Miet-Positionen, Paket 7): MVP legt einen Exchange-Plan pro Mietvertrag mit einem `templateExchanges[]`-Array an, das je einen Eintrag fuer COLD_RENT / OPERATING_COSTS / HEATING_COSTS enthaelt (Fallback: TOTAL_RENT als Einzel-Eintrag). Schema-seitig nicht bestaetigt — wenn Impower 400/422 wirft, muss die Granularitaet umgebaut werden (Alternativen: 1 Plan pro Position, oder 1 Plan mit Summen-Eintrag plus Splits ueber `counterpartInstruction`). Entscheidung faellt beim ersten realen Write.
- **IBAN-Wechsel-Szenario** (aus M3 SEPA) ist auch fuer Mietverwaltungs-Lastschriften relevant, falls ein Mieter mit aktivem Mandat die Bank wechselt. Handler noch nicht implementiert.
- **Mieter-SEPA-Mandate im Write-Flow**: Wenn im Mietvertrag eine IBAN erkannt wird (`tenant_contracts[].contract.iban`), legt der Write-Pfad aktuell **kein** Mandat an — der User muss Mieter-Lastschriften manuell in Impower nachziehen. Fuer den Produktiv-Rollout nachtraeglich aufnehmen (Muster vorhanden via SEPA-Schreibpfad).

## Backlog — uebergreifende Themen (meilensteinunabhaengig)

Sammelstelle fuer Anforderungen, die quer zu den Modulen liegen. Werden beizeiten zu eigenen Meilensteinen hochgezogen.

1. **Rollen & Rechte fuer Logins.** Grundgeruest implementiert (Migration 0006 `roles` + `resource_access`, Admin-Views unter `/admin/*`). Offen: feinere Rechte pro Workflow pflegen, Admin-Flows testen. Neue User bekommen Default-Rolle `user`; Rollen-Upgrade ist immer manuell durch Daniel, keine Auto-Admin-Promotion ausser fuer `INITIAL_ADMIN_EMAILS`.
2. **Admin-Log / Audit-Trail sichtbar machen.** Grundgeruest implementiert (Migration 0007 generisch mit `entity_type` + `entity_id`, zentraler `audit()`-Helper in `services/audit.py`, `/admin/audit-log`-View). Noch offen: finaler UX-Feinschliff, Filter nach User / Event / Zeitraum schaerfen, CSV-Export fuer Datenschutz-Nachweise.
3. **Datenschutz-Pruefung Anthropic-Upload.** **AVV-Blocker ist raus** — AVV laeuft automatisch ueber die Commercial-API (siehe `memory/project_anthropic_avv_cleared.md`). Weiter offen fuer sauberen Produktiv-Rollout: (a) DSFA-Light dokumentieren, (b) Information der Betroffenen ueber Drittland-Uebermittlung formulieren, (c) EU-Endpoint/Bedrock-Option weiter im Blick behalten falls spaeter strengere Kundenanforderungen kommen.
4. **Zentraler User-Chat + Notification-Hub (Idee).** Statt pro Dokument einen isolierten Chat und pro Workflow eigene UIs: ein persistenter Chat-Kanal pro angemeldetem User als zentrale Anlaufstelle. Dort landen (a) System-Events aller Workflows, (b) proaktive Rueckfragen der Agenten, (c) freie User-Nachrichten an den Bot. Jede Nachricht referenziert ihr Quelldokument / Workflow via Chip mit Deep-Link. Datenmodell: `chat_messages` um `user_id` (Owner-Kanal) und `kind` (`user` / `assistant` / `system_notification`) erweitern. UI: Sidebar oder Bottom-Drawer, global in `base.html`, Realtime via SSE oder HTMX-Polling. Offene Fragen: (i) ersetzt der zentrale Chat den Doc-Chat oder laufen beide parallel? (ii) wie routet der Bot Kontext — letzte erwaehnte Doc-ID als "aktiver Fokus", oder explizites `@doc-123`-Tagging? (iii) Notification-Retention / Markieren-als-gelesen noetig?
5. **Chat-Korrekturen als Delta statt Full-JSON.** **Fuer den Case-Chat (M5 Paket 8) bereits umgesetzt** — `chat_about_case()` in `services/mietverwaltung.py` fordert nur geaenderte Sektionen im `overrides`-Block und mergt sie server-seitig. Offen: der SEPA-Chat (`chat_about_mandate()` in `services/claude.py`) schickt weiterhin das komplette Extraction-JSON zurueck. Bei naechster groesserer SEPA-Runde analog umbauen.
6. **IBAN-/BIC-Registry-Aktualitaet.** `schwifty` liefert die BLZ→BIC-Zuordnung aus einem gebundelten Datenfile, das je nach Version mehrere Monate alt sein kann. Bundesbank aktualisiert die offizielle BLZ-Datei quartalsweise. Risiko: neue Banken / Fusionen → BIC-Derivation faellt bei seltenen BLZ durch. Massnahmen: regelmaessiges `pip install -U schwifty` im CI, ggf. eigener BLZ-Import-Job gegen Bundesbank-Feed, Fallback-Chain User-Feedback → Service-Desk. Aktuell low prio, aber dokumentieren vor Produktiv-Rollout.
7. **OCR-/LLM-Robustheit bei Ziffernfolgen.** Heute abgedeckt: Schwifty-Validierung + Unicode-Normalize + Chat-Guard. Offen: proaktive Plausibilitaetspruefung beim Initial-Extract (IBAN gueltige Pruefziffer + bekannte BLZ → `high`, sonst Confidence runter). Ferner: bei mehrfach hintereinander abgelehnten Chat-Korrekturen automatisch auf das naechstgroessere Modell eskalieren (Sonnet → Opus).

## Externe Blocker

- **GitHub-Push**: User macht manuell. Remote: `git@github.com:dakroxy/dashboard-ai-agents.git`.
- *(M4-bezogen: Elestio-Projekt + DNS `dashboard.dbshome.de` bei All-Inkl — deprioritisiert, kein aktiver Blocker.)*

## Design-Regeln (verbindlich, vom User vorgegeben)

- **Dateinamen von Scans sind NICHT als Info-Quelle nutzen.** Auch wenn das aktuelle Benennungsschema strukturiert wirkt, ist es nicht verlaesslich. Nur der PDF-Inhalt zaehlt. (Im Prompt verankert.)
- **Pflichtfelder (SEPA)**: Objekt (WEG-Kuerzel oder WEG-Name+Adresse), Eigentuemer-Name, IBAN. Fehlt eines → `needs_review`, nicht blocken, nicht still ablehnen.
- **Einheit ist optional** (`unit_nr` darf null sein).
- **Bei Problemen fragt der Bot im Chat nach**, statt automatisch zu entscheiden.
- **Zwei Formular-Varianten (SEPA)**: neues Impower-Template mit "Objekt-Nr." und "Einheits-Nr.", und aelteres DBS-Formular ohne diese Felder. Prompt liest beide robust.

## Vorgehen und Defaults

- User will Tempo, keine ueberlangen Erklaerungen.
- Prototyp wurde bewusst uebersprungen — direkt Produktivcode.
- Bei offensichtlichen Defaults nicht zurueckfragen, direkt machen und transparent melden.
- Risiko-Actions (Force-Push, destruktiv, shared state) weiterhin nur mit Rueckfrage.
- Sprache im Chat: Deutsch; Code-Kommentare und Commit-Messages: Deutsch oder Englisch egal, aber konsistent pro Datei.

## Referenzen

- **Code-Struktur-Doku** (aus `bmad-document-project`): `docs/` — Architektur, Datenmodell-Felder, Routen-Liste, Komponenten-Inventar, Source-Tree-Analyse. Bei Code-Fragen zuerst dort.
- **Vorgaengerprojekt (Nightly-Check-Skript)**: `/Users/daniel/Desktop/Vibe Coding/Impower Lastschrift/` — komplette Impower-API-Doku, funktionierende Calls in `impower_lastschrift_check.py`.
- **Beispiel-Mandate** (zum Testen): `/Users/daniel/Downloads/OneDrive_1_18.4.2026/` (3 PDFs: Floegel HAM61, Tilker GVE1, Kulessa BRE11). Floegel wurde bereits erfolgreich extrahiert.
- **Glaeubiger-IDs** (aus den Beispielen): HAM61 → `DE71ZZZ00002822264`, BRE11 → `DE37ZZZ00000481199`.
- **Mockup Mietverwaltungs-Eingabemaske**: `mockups/mietverwaltung_setup.html` — standalone HTML-Prototyp; wurde in Paket 5 als `case_detail.html` umgesetzt.
- **UI-Vorbild Sidebar-Layout**: `/Users/daniel/Desktop/KI Workshop Screenshots/Dashboard - KI Mitarbeiter.png` (vom User vorgegeben).
- **Impower-Swagger-Specs** (beide ohne Auth abrufbar, JSON als Quelle der Wahrheit fuer DTOs + Pflichtfelder): `https://api.app.impower.de/v2/api-docs` (Read, 57 Pfade) und `https://api.app.impower.de/services/pmp-accounting/v2/api-docs` (Write, 358 Pfade, Swagger 2.0). Alle anderen pmp-Service-Praefixe wurden getestet und existieren nicht (alle 404).
- **GitHub-Repo**: `git@github.com:dakroxy/dashboard-ai-agents.git`.
- **Produktiv-URL (geplant)**: `https://dashboard.dbshome.de`.
