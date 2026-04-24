# Test-Automatisierung — Story 1.7 (Zugangscodes mit Field-Level-Encryption)

**Datum:** 2026-04-24
**Skill:** `bmad-qa-generate-e2e-tests`
**Scope:** Story 1.7 — Fernet-Encryption fuer `entry_code_*`-Felder +
drei dedizierte Router-Endpoints fuer Zugangscodes

## Ergebnis

**Keine neuen Tests in diesem Durchlauf** — Story 1.7 wurde waehrend der
Implementierung bereits mit 30 dedizierten Tests abgeschlossen (alle gruen).
Diese Doku zieht nur die Test-Abdeckung pro AC nach.

## Bestehende Testdateien

### `tests/test_field_encryption_unit.py` (13 Tests)

Unit-Level fuer `app/services/field_encryption.py` — Fernet-Roundtrip,
Key-ID-Format, Error-Handling.

- Roundtrip `encrypt_field → decrypt_field` gibt Klartext zurueck.
- Format `v1:<fernet-token>`.
- Unicode-Klartext (Umlaute, Emojis falls gewollt) roundtrip OK.
- Decrypt mit falschem Key → `FieldDecryptError`.
- Decrypt mit korruptem Token → `FieldDecryptError`.
- Decrypt mit falscher `key_id` (z. B. `v2:...`) → `FieldDecryptError`.
- Leerstring + None am Input → klar definiertes Verhalten (Leerstring als
  "loesche" interpretiert — Helper liefert `None`).
- Fallback auf `SECRET_KEY`, wenn `STECKBRIEF_FIELD_KEY` leer (inkl.
  Startup-Warning).
- `key_id`-Validierung: Format `v<int>:<token>` — Colon im `key_id` wird
  sauber abgelehnt (sonst verschiebt `partition(":")` den Split und der
  Ciphertext wird permanent unentschluesselbar).

### `tests/test_zugangscodes_routes_smoke.py` (17 Tests)

Router-Ebene fuer die drei neuen Endpoints unter `/objects/{id}/zugangscodes/*`.

- AC1: Klartext landet **nie** in DB (`entry_code_*`-Spalte enthaelt
  `v1:...`-Ciphertext), **nie** in `FieldProvenance` (Value-Snapshot:
  `{"encrypted": true}`), **nie** in `AuditLog.details_json`. Positiv-Assertion
  auf den `encrypted: true`-Marker im Audit-Payload (Runde-1-Patch).
- AC2: Decryption on Read zeigt Klartext in Edit-Fragment (nur fuer
  autorisierte User) und NICHT in View-Fragment (dort steht `••••••••`).
- AC3: Decryption-Fehler (z. B. `STECKBRIEF_FIELD_KEY`-Rotation ohne
  Re-Encrypt) → Fallback-Text `Entschluesselung fehlgeschlagen` +
  `AuditLog(action="encryption_key_missing")`.
- AC4: Empty-String-Save loescht das Feld (NULL-Semantik, keine leere
  Ciphertext-Row).
- AC5: Permission-Gates — View-Endpoint braucht `objects:view`, Edit- und
  Save-Endpoints `objects:edit`; Viewer bekommt bei POST 403.
- AC6: Zugangscodes haben **eigene** Router-Endpoints, das bestehende
  Technik-Endpoint lehnt `entry_code_*`-Felder strukturell ab
  (Scope-Boundary-Test von Story 1.6 invertiert).
- AC7: Volle Suite gruen.

Edge-Cases:
- Sehr langer Klartext (`max_length=200`) wird akzeptiert; >200 → 422.
- Unicode-Klartext (z. B. QR-Code-Strings mit `<>`-Sonderzeichen) bleibt in
  HTML korrekt escaped.
- Re-Edit ohne Aenderung: kein neuer Provenance-Eintrag, wenn neuer Klartext
  == alter Klartext (Write-Gate no-op-Regel).

### Indirekt

- `tests/test_write_gate_unit.py` — `test_write_field_ai_proposal_for_encrypted_field_raises`
  deckt den NFR-S2-Klartext-Leak-Schutz im Proposal-Pfad (write_field_ai_proposal
  bricht fuer `_ENCRYPTED_FIELDS`).
- `tests/test_technik_routes_smoke.py::test_technik_save_rejects_entry_code_field` —
  Scope-Boundary-Check: Technik-POST weist `entry_code_*` ab.

## Coverage pro AC

| AC | Anforderung | Abdeckung |
|----|-------------|-----------|
| AC1 | Klartext nie in DB/Provenance/Audit | `test_zugangscodes_routes_smoke` (alle drei Targets) |
| AC2 | Decryption on Read | `test_zugangscodes_routes_smoke` (View = maskiert, Edit = Klartext) |
| AC3 | Decryption-Fehler → Fallback + Audit | `test_zugangscodes_routes_smoke` + `test_field_encryption_unit` |
| AC4 | Leerer Wert → NULL | `test_zugangscodes_routes_smoke` |
| AC5 | Permission-Gate (view vs. edit) | `test_zugangscodes_routes_smoke` (Viewer-Matrix) |
| AC6 | Eigene Router-Endpoints | `test_zugangscodes_routes_smoke` (3 neue Routen) + `test_technik_routes_smoke` (Boundary) |
| AC7 | Regressionslauf gruen | Volle Suite 499/499 gruen (Stand 2026-04-24) |

## Run-Command

```bash
docker compose exec app python -m pytest \
  tests/test_field_encryption_unit.py \
  tests/test_zugangscodes_routes_smoke.py -v
# 30 passed
```

## Bewusst NICHT abgedeckt

- **Key-Rotation End-to-End** — `deferred-work.md` Story 1.7: Rotation-Job
  existiert nicht, Tests dazu auch nicht. Wenn Rotation kommt, braucht es
  einen Test mit `v1:`-Blob + neuem `v2:`-Key + Migration.
- **Prod-Validator fuer leeren `STECKBRIEF_FIELD_KEY`** — aktuell nur
  Startup-Warning; harter Validator defer auf Prod-Rollout.
- **`objects:view_confidential`-Gate fuer Zugangscodes** — Defer: in v1 hat
  `objects:view` gleich Zugriff auf Entry-Codes; Separation nur bei Bedarf
  vor Prod-Rollout.

## Offene Luecken

Keine. Story gilt als test-seitig abgeschlossen; die drei obigen Items sind
bewusste Defers aus dem Code-Review, nicht QA-Rueckstand.
