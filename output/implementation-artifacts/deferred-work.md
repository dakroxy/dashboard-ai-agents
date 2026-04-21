# Deferred Work

Sammelpunkt fuer Findings aus Code-Reviews, die bewusst nicht sofort gefixt werden.

## Deferred from: code review of story-1.1 (2026-04-21)

- **Multi-Worker-Race bei Erst-Boot des `_seed_default_roles`** [`app/main.py:119-137`] — Parallele Gunicorn-Worker koennen beide gleichzeitig in eine leere `roles`-Tabelle INSERT-en und auf UNIQUE `roles.key` einen `IntegrityError` werfen. Pre-existing, existierte schon vor Story 1.1. In Elestio bisher nicht aufgetreten (Healthcheck faengt Restarts ab), aber vor echtem Multi-Worker-Produktivbetrieb fixen: `INSERT ... ON CONFLICT DO NOTHING` oder Postgres-Advisory-Lock um den Seed herum.

- **`X-Robots-Tag` nicht setzbar bei mid-stream-Fehler** [`app/main.py:201-212`] — Wenn ein `StreamingResponse`/`FileResponse` (Dokumenten-Downloads) nach `http.response.start` im Body-Generator scheitert, ist der Status-Header-Block bereits raus. Die aktuelle Middleware kann den Header bzw. die 500 nicht mehr nachruesten. Bewusst akzeptiert in Story 1.1; waere mit ASGI-`send`-Wrapping loesbar, lohnt sich aber nur wenn Downloads tatsaechlich haeufig mid-stream scheitern.

- **Waise-Permission-Keys in `Role.permissions`** [`app/main.py:123-125`] — Die Merge-Logik macht `set |`, nie Intersection gegen `PERMISSION_KEYS`. Ein Key, der spaeter aus der Registry entfernt wird, bleibt fuer immer in der JSONB-Spalte. Aktuell kein Enforcement-Pfad betroffen (Admin-UI iteriert nur registrierte Keys), aber beim naechsten Permission-Cleanup mitbedenken.

## Deferred from: story-1.2 (2026-04-21)

- **AST-basierter Write-Gate-Coverage-Test (Stufe 2)** [`tests/test_write_gate_coverage.py`] — Aktuell ist nur die Textscan-Stufe (Stufe 1, MVP) implementiert. AST-Variante mit `ast.Assign`-Walker + Variablen-Type-Inferenz wurde bewusst verschoben. Triggern, falls die Textscan-Heuristik bei Story 1.3/1.6 mehr als ~10 % False Positives erzeugt. Datei waere `tests/test_write_gate_coverage_ast.py`. Architektur-Referenz: `architecture.md:243`.

## Deferred from: code review of story-1.2 (2026-04-21)

- **Coverage-Scanner-Luecken zusaetzlich zur AST-Stufe-2** [`tests/test_write_gate_coverage.py`] — Neben dem AST-Stretch oben: (a) Multi-Line-Konstruktor-Aufrufe werden nur in der ersten Zeile erkannt, (b) `setattr(obj, "field", value)` und `db.merge(Object(...))` werden komplett uebersehen, (c) Variable-Shadowing (Var wird spaeter einer anderen Klasse zugewiesen) gibt False-Positives, (d) der handgerollte Triple-Quote-Parser in `_strip_strings_and_comments` bricht bei mehreren `"""`-Bloecken auf einer Zeile. Sammelpunkt — fixen wenn AST-Stufe 2 kommt (Python `ast` loest alle vier sauber).
- **Approve-Race ohne Row-Lock** [`app/services/steckbrief_write_gate.py:1819`] — Zwei Admins approven dieselbe `ReviewQueueEntry` parallel → beide bestehen Status-Check, beide rufen `write_field_human`. Fuer v1 mit Hand-voll Admins niedriges Risiko. Fix via `db.get(ReviewQueueEntry, entry_id, with_for_update=True)`, sobald das Admin-UI (Story 3.5/3.6) live ist.
- **Stale-Proposal-Check beim Approve** [`app/services/steckbrief_write_gate.py:1804`] — Approve einer KI-Entry bypasst stumm einen User-Edit, der NACH Proposal-Erstellung kam. UX-Entscheidung fuer Story 3.5/3.6: Warnung zeigen, Entry-Status `stale`, oder explizites Force-Overwrite.
- **`_latest_provenance` Tie-Breaker per uuid4 ist nicht monoton** [`app/services/steckbrief_write_gate.py:1930`] — Bei zwei Provenance-Rows mit identischem `created_at` (Postgres `func.now()` ist statement-stable in einer Transaktion) entscheidet die random uuid4 DESC. Loesung: `sequence_no BigInt`-Spalte mit DB-Sequence oder `clock_timestamp()` statt `func.now()`. Schema-Change, daher Defer. Practical Impact heute niedrig — kein Caller schreibt dasselbe Feld zweimal innerhalb einer Transaktion.
- **Combined-Index `field_provenance(entity_type, entity_id, field_name, created_at DESC)`** [`migrations/versions/0011_steckbrief_governance.py`] — Aktueller `ix_field_provenance_entity_field` deckt Filter, nicht die ORDER BY. Bei 10k+ Provenance-Rows pro Object (Story 1.4 Nightly-Mirror) wird `_latest_provenance` langsam. Defer, sobald Volumen sichtbar.
- **FK-Semantik (`ON DELETE SET NULL`) nur metadata-getestet** [`tests/conftest.py`] — SQLite ohne `PRAGMA foreign_keys=ON` ignoriert FKs, `test_review_queue_source_doc_fk_on_delete_set_null` prueft nur Metadata-Ebene. Integration gegen echte Postgres via Testcontainer waere sauberer; groesserer Infrastruktur-Schritt.
- **`proposed_value`-Typ-Roundtrip fuer Decimal/Date** [`app/services/steckbrief_write_gate.py:1779`] — `_json_safe` serialisiert `Decimal` → String; beim Approve landet der String in der `Numeric`-Spalte. Ab Story 1.5 (Finanzen-KI-Proposals) relevant. Fix-Skizze: typisiertes Envelope `{"value": ..., "type": "decimal"}` + Parser im `approve_review_entry`.
- **Entry-Code `String`-Spalten ohne Length-Limit** [`migrations/versions/0010_steckbrief_core.py:132`] — wird mit Story 1.7 (Fernet-Encryption) umgebaut, dann max. 512 Zeichen.
- **`_ENCRYPTED_FIELDS` nur fuer `"object"`** [`app/services/steckbrief_write_gate.py:1573`] — Erweiterung auf `Unit`/`Mieter` in Story 1.7 muss diese Konstante nachziehen, sonst stille Klartext-Leaks in Provenance/Audit. Silent-Fail-Risiko, Memo als Docstring-Erinnerung reicht.
- **`docs/architecture.md` §8 Audit-Actions-Liste dupliziert gegen `KNOWN_AUDIT_ACTIONS`** [`docs/architecture.md`] — Langfristig auf Backlink umstellen. Nit.
