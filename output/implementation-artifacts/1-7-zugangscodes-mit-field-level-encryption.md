# Story 1.7: Zugangscodes mit Field-Level-Encryption

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

Als Mitarbeiter mit `objects:edit`,
ich moechte Zugangscodes (Haustuer, Garage, Technikraum) zu einem Objekt hinterlegen und abrufen koennen,
damit ich im Notfall oder bei Begehungen den Code ohne Rueckfrage habe — und die Codes sicher at-rest gespeichert werden.

## Acceptance Criteria

**AC1 — Encryption on Write: Klartext landet nie in DB / Provenance / Audit**

**Given** ein Objekt ohne Zugangscodes
**When** ich `entry_code_main_door="1234-5678"` in der Technik-Sektion eingebe und speichere
**Then** wird der Wert vor dem DB-Write ueber `encrypt_field(plaintext, entity_type="object", field="entry_code_main_door", key_id="v1")` in das Format `v1:<fernet-token>` gepackt
**And** die DB-Spalte `objects.entry_code_main_door` enthaelt keinen Klartext (kein `"1234-5678"`, nur `"v1:gAAAA..."`)
**And** die `FieldProvenance.value_snapshot` fuer den Write enthaelt `{"old": {"encrypted": true}, "new": {"encrypted": true}}` statt Klartext
**And** `AuditLog.details_json` enthaelt keinen Klartext (auch `{"encrypted": true}`-Marker statt Wert)

**AC2 — Decryption on Read: Code on-the-fly entschluesselt**

**Given** ein Objekt mit gesetztem `entry_code_main_door` (Ciphertext `v1:...`)
**When** ein User mit `objects:view` `/objects/{id}` oeffnet
**Then** wird der Code via `decrypt_field(ciphertext, entity_type="object", field="entry_code_main_door")` entschluesselt und in Klartext im Zugangscodes-Block der Technik-Sektion angezeigt
**And** die Entschluesselung nutzt `settings.steckbrief_field_key` (wenn gesetzt) oder Fallback `settings.secret_key`

**AC3 — Decryption-Fehler: UI zeigt Fallback, Audit-Eintrag entsteht**

**Given** der Schluessel passt nicht zum Ciphertext (falscher Key, rotierter Key, leere Konfiguration fuer einen vorhandenen Ciphertext)
**When** `decrypt_field` fehlschlaegt
**Then** zeigt die UI den Placeholder "Code nicht verfuegbar — Schluessel-Konfiguration pruefen"
**And** ein `AuditLog`-Eintrag `action="encryption_key_missing"` mit `entity_type="object"`, `entity_id=<obj.id>` und `details_json.field=<field_name>` existiert (committed)

**AC4 — Leerer Wert loescht den Code (NULL-Semantik)**

**Given** ein Objekt mit gesetztem `entry_code_garage` (Ciphertext)
**When** ich den Wert auf leer setze und speichere (Empty-String-Submit)
**Then** wird `write_field_human(..., value=None, ...)` aufgerufen
**And** die DB-Spalte ist NULL (kein leerer String, kein Ciphertext)
**And** die Provenance-Row hat `value_snapshot={"old": {"encrypted": true}, "new": {"encrypted": true}}` — der `_json_safe_for_provenance`-Marker bleibt aus Story 1.2 unveraendert (Architektur §CD5: "dort landet nur ein Marker `{"encrypted": true}`", unabhaengig vom Wert)
**And** die UI zeigt den `—`-Placeholder statt einem decrypted Wert (`getattr(obj, field) is None` → kein Decrypt-Versuch)

**AC5 — Permission-Gate: View braucht `objects:view`, Edit/Save braucht `objects:edit`**

**Given** ein User mit ausschliesslich `objects:view` (ohne `objects:edit`)
**When** er die Technik-Sektion oeffnet
**Then** werden die Zugangscode-Werte decrypted angezeigt (Sehen erlaubt)
**And** es sind KEINE Edit-Buttons sichtbar (Template-Gate via `has_permission`)
**And** ein direkter `POST /objects/{id}/zugangscodes/field` gibt 403 (serverseitig via `Depends(require_permission("objects:edit"))`)

**Given** ein User komplett ohne `objects:view`
**When** er `/objects/{id}` aufruft
**Then** bekommt er 302/403 (bestehende Permission-Boundary aus Story 1.3)

**AC6 — Seperate Router-Endpoints fuer Zugangscodes (nicht ueber `/technik/field`)**

**Given** der bestehende POST `/objects/{id}/technik/field` Guard (aus Story 1.6)
**When** jemand `field_name="entry_code_main_door"` an diesen Endpoint schickt
**Then** antwortet er weiterhin mit 400 (bestehender `TECHNIK_FIELD_KEYS`-Guard — unberuehrt)
**And** die neuen Zugangscode-Endpoints sind: `GET /objects/{id}/zugangscodes/edit`, `GET /objects/{id}/zugangscodes/view`, `POST /objects/{id}/zugangscodes/field`

**AC7 — Tests + Regressionslauf gruen**

**Given** die neuen Dateien (field_encryption.py, Zugangscode-Templates, neue Tests)
**When** `pytest -x` laeuft
**Then** sind alle neuen Tests gruen und der Regressionslauf (>=432 Tests, Stand nach Story 1.6) bleibt vollstaendig gruen

## Tasks / Subtasks

- [x] **Task 1 — `cryptography>=43` in `pyproject.toml` + `app/config.py` erweitern** (AC2)
  - [x] 1.1 In `pyproject.toml` unter `[project] dependencies` eine Zeile ergaenzen:
    ```toml
    "cryptography>=43",
    ```
    Hinweis: `cryptography` ist bereits transitive Dep von `authlib`, wird hier als direkte Dep deklariert (architecture.md §Additional Libraries).
  - [x] 1.2 In `app/config.py` in der `Settings`-Klasse nach `impower_mirror_enabled` folgende Einstellung ergaenzen:
    ```python
    # Optional: separater Encryption-Key fuer Steckbrief-Felder (entry_code_*).
    # Leer = Fallback auf secret_key. Prod: eigenen Zufallsschluessel setzen.
    steckbrief_field_key: str = ""
    ```
  - [x] 1.3 In `.env.op` am Ende eine neue Sektion hinzufuegen:
    ```
    # Steckbrief Field-Level-Encryption (optional, Fallback: SECRET_KEY)
    # Eigenen Schluessel in Prod generieren: python -c "import secrets; print(secrets.token_hex(32))"
    STECKBRIEF_FIELD_KEY=
    ```
    (Leer als Dev-Default ist korrekt — Fallback auf `SECRET_KEY` greift, was in `.env.op` bereits gesetzt ist.)

- [x] **Task 2 — `app/services/field_encryption.py` (NEU)** (AC1, AC2, AC3)
  - [x] 2.1 Neue Datei `app/services/field_encryption.py`. Kein Import aus `app.config` auf Modul-Ebene — Settings lazy laden (verhindert zirkulaere Import-Kette beim App-Start). Vollstaendige Implementierung:
    ```python
    """Field-Level-Encryption fuer sensible Steckbrief-Felder (CD5).

    Schluessel-Ableitung: HKDF(master_key, salt=b"steckbrief-v1",
        info=b"{entity_type}:{field_name}") → 32 Bytes → Fernet-Key.
    Ciphertext-Format: "v1:<fernet-token>" — key_id als Praefix fuer
    spaetere Rotation (Rotation-Job = v1.1, Format ist rotation-faehig).
    """
    from __future__ import annotations

    import base64

    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF


    class DecryptionError(Exception):
        """Entschluesselung gescheitert (falscher Key, beschaedigter Token,
        unbekannte key_id)."""


    def _derive_fernet(entity_type: str, field: str, master_key: str) -> Fernet:
        """Leitet aus dem Master-Key per HKDF einen Fernet-Schluessel ab."""
        kdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"steckbrief-v1",
            info=f"{entity_type}:{field}".encode(),
        )
        derived = kdf.derive(master_key.encode("utf-8"))
        return Fernet(base64.urlsafe_b64encode(derived))


    def _master_key() -> str:
        from app.config import settings  # lazy, vermeidet Zirkular-Import

        return settings.steckbrief_field_key or settings.secret_key


    def encrypt_field(
        plaintext: str, *, entity_type: str, field: str, key_id: str = "v1"
    ) -> str:
        """Verschluesselt `plaintext` und gibt "v1:<fernet-token>" zurueck."""
        fernet = _derive_fernet(entity_type, field, _master_key())
        token: bytes = fernet.encrypt(plaintext.encode("utf-8"))
        return f"{key_id}:{token.decode('ascii')}"


    def decrypt_field(
        ciphertext: str, *, entity_type: str, field: str
    ) -> str:
        """Entschluesselt und gibt Klartext zurueck.

        Raises DecryptionError bei ungueltigem Token oder falschem Key.
        """
        if ":" not in ciphertext:
            raise DecryptionError(
                f"Unbekanntes Ciphertext-Format (kein key_id-Praefix): {ciphertext[:20]!r}"
            )
        _key_id, _, token_str = ciphertext.partition(":")
        # key_id wird fuer kuenftige Rotation genutzt; v1 kennt nur einen Key.
        try:
            fernet = _derive_fernet(entity_type, field, _master_key())
            return fernet.decrypt(token_str.encode("ascii")).decode("utf-8")
        except Exception as exc:
            # Fernet.decrypt wirft InvalidToken bei falschem Key / beschaedigtem
            # Token; der breite Exception-Catch fuengt zusaetzliche Ueberraschungen
            # (z. B. base64-ValueError bei muell-Eingabe) in dieselbe Semantik.
            raise DecryptionError(str(exc)) from exc
    ```
  - [x] 2.2 **Wichtig: keine Modul-Level-Importe von `app.config`** — der `_master_key()`-Helper laedt `settings` lazy, damit das Modul ohne initialisierte App importierbar ist (kritisch fuer pytest-Fixtures, die das Modul vor dem App-Start importieren koennen).

- [x] **Task 3 — `steckbrief_write_gate.py`: Encryption in `write_field_human` verdrahten** (AC1, AC4)
  - [x] 3.1 In `write_field_human` NACH der `source`-Validierung und BEVOR dem Mirror-Guard einen Encryption-Block einfuegen. **Exakt nach Zeile 233** (nach dem `ai_suggestion`-Guard) und **vor Zeile 235** (`entity_id = entity.id`):
    ```python
    # --- Feld-Encryption (entry_code_* und andere _ENCRYPTED_FIELDS) ---
    if field in _ENCRYPTED_FIELDS.get(entity_type, frozenset()):
        if value is not None and isinstance(value, str) and value.strip():
            from app.services.field_encryption import encrypt_field as _enc
            value = _enc(value, entity_type=entity_type, field=field)
        else:
            value = None  # Leerer String → NULL (AC4 Loesch-Semantik)
    ```
  - [x] 3.2 Diesen Block **nach** der Entity-Typ-Bestimmung platzieren (entity_type muss bekannt sein). Der Block steht zwischen dem ai_suggestion-Guard (Zeile 233) und `entity_id = entity.id` (Zeile 235).
  - [x] 3.3 **Kein Noop-Check fuer Encrypted Fields**: Fernet verwendet Random-IV → jedes Encrypt ergibt ein anderes Token. Der bestehende `old_value == value`-Vergleich (Zeile 257) wird immer `False` sein, weil `old_value` der bisherige Ciphertext ist und `value` jetzt der neue Ciphertext — unterschiedliche Tokens. Das ist korrekt und intendiert. Kein spezieller Encrypted-Noop-Branch noetig.
  - [x] 3.4 `_json_safe_for_provenance` gibt bereits `{"encrypted": True}` zurueck fuer `_ENCRYPTED_FIELDS` — nichts aendern. Die Provenance-Row korrekt: `{"old": {"encrypted": true}, "new": {"encrypted": true}}`.
  - [x] 3.5 **Kein Import auf Modul-Ebene**: `from app.services.field_encryption import encrypt_field as _enc` NUR im if-Block (lazy), um Zirkular-Imports zu vermeiden.

- [x] **Task 4 — `app/services/steckbrief.py`: Zugangscode-Registry ergaenzen** (AC5, AC6)
  - [x] 4.1 Am Ende der Datei (nach den bestehenden TECHNIK-Registries) ergaenzen:
    ```python
    # ---------------------------------------------------------------------------
    # Zugangscode-Registry (Story 1.7 — separate von TECHNIK_FIELDS, da
    # Encrypt/Decrypt-Logik eigene Endpoints erfordert)
    # ---------------------------------------------------------------------------

    ZUGANGSCODE_FIELDS: tuple[TechnikField, ...] = (
        TechnikField("entry_code_main_door", "Haustuer-Code", "code"),
        TechnikField("entry_code_garage", "Garage-Code", "code"),
        TechnikField("entry_code_technical_room", "Technikraum-Code", "code"),
    )
    ZUGANGSCODE_FIELD_KEYS: frozenset[str] = frozenset(
        f.key for f in ZUGANGSCODE_FIELDS
    )
    ```
    Hinweis: `kind="code"` ist ein neuer Typ — `parse_technik_value` und `_TECHNIK_LOOKUP` kennen ihn nicht. Das ist Absicht: Zugangscode-Validation laeuft ueber `parse_zugangscode_value` (Task 4.2), nicht ueber den Jahres-/Text-Parser.
  - [x] 4.2 Neue Validierungsfunktion direkt darunter:
    ```python
    _ZUGANGSCODE_MAX_LEN: int = 200

    def parse_zugangscode_value(
        field_key: str, raw: str
    ) -> tuple[str | None, str | None]:
        """Validiert User-Input fuer Zugangscode-Felder.

        - Leerer Input → (None, None): bewusste Loeschung (AC4).
        - Nicht-leer: Whitespace strippen, Laenge pruefen.
        - Unbekannter field_key → ValueError (Programmier-Guard).

        Rueckgabe: (wert, fehlermeldung) — exakt eines davon ist None.
        """
        if field_key not in ZUGANGSCODE_FIELD_KEYS:
            raise ValueError(f"Unbekanntes Zugangscode-Feld: {field_key!r}")
        stripped = (raw or "").strip()
        if not stripped:
            return None, None
        if len(stripped) > _ZUGANGSCODE_MAX_LEN:
            return None, f"Maximal {_ZUGANGSCODE_MAX_LEN} Zeichen erlaubt."
        return stripped, None
    ```

- [x] **Task 5 — `app/routers/objects.py`: Zugangscode-Context im Detail-Handler + 3 neue Endpoints** (AC1–AC6)
  - [x] 5.1 **Imports ergaenzen** am Modulanfang (nach den bestehenden steckbrief-Imports):
    ```python
    from app.services.steckbrief import (
        ...,  # bestehende Imports
        ZUGANGSCODE_FIELDS,
        ZUGANGSCODE_FIELD_KEYS,
        parse_zugangscode_value,
    )
    from app.services.field_encryption import (
        decrypt_field,
        DecryptionError,
    )
    from app.services.audit import audit
    ```
    Hinweis: `audit` ist im bestehenden Router-Modul (Stand Story 1.6) noch NICHT importiert — der bestehende `object_detail`-Handler erzeugt keine Audit-Eintraege. Story 1.7 fuehrt den ersten Audit-Emit im Detail-Handler ein (Decryption-Failures, AC3). Ohne den Import gibt's `NameError` bei jedem Fehl-Decrypt.
  - [x] 5.2 **Im `object_detail`-Handler** nach dem Technik-Provenance-Block (nach `tech_histoire`, vor dem Template-Response-Aufruf) einen Zugangscode-Block ergaenzen:
    ```python
    # --- Zugangscodes (Fernet-decrypted, AC2/AC3) ---
    zug_prov_map = get_provenance_map(
        db, "object", detail.obj.id,
        tuple(f.key for f in ZUGANGSCODE_FIELDS),
    )
    tech_zugangscodes: list[dict] = []
    _zug_decrypt_failed = False
    for _zf in ZUGANGSCODE_FIELDS:
        _raw = getattr(detail.obj, _zf.key)
        if _raw is None:
            _dec_value, _dec_error = None, None
        else:
            try:
                _dec_value = decrypt_field(_raw, entity_type="object", field=_zf.key)
                _dec_error = None
            except DecryptionError:
                _dec_value = None
                _dec_error = "Code nicht verfuegbar — Schluessel-Konfiguration pruefen"
                _zug_decrypt_failed = True
                audit(
                    db,
                    user,
                    "encryption_key_missing",
                    entity_type="object",
                    entity_id=detail.obj.id,
                    details={"field": _zf.key},
                    request=request,
                )
        tech_zugangscodes.append({
            "key": _zf.key,
            "label": _zf.label,
            "kind": _zf.kind,
            "value": _dec_value,
            "error": _dec_error,
            "prov": zug_prov_map.get(_zf.key),
        })
    if _zug_decrypt_failed:
        db.commit()  # Audit-Eintraege fuer Decryption-Failures committen
    ```
  - [x] 5.3 `tech_zugangscodes` in den Template-Context des `object_detail`-Handlers aufnehmen:
    ```python
    "tech_zugangscodes": tech_zugangscodes,
    ```
  - [x] 5.4 **Drei neue Endpoints** am Ende des Routers, nach den bestehenden Technik-Endpoints. Die Zugangscode-Endpoints nutzen dieselbe Grundstruktur wie die Technik-Endpoints, aber mit eigenem Key-Set und Encryption-Logik. Fuer das ANZEIGEN reicht `objects:view`; fuers EDITIEREN und SPEICHERN braucht man `objects:edit`:
    ```python
    # --- Zugangscode-Endpoints (Story 1.7) ---

    @router.get("/{object_id}/zugangscodes/view", response_class=HTMLResponse)
    async def zugangscode_field_view(
        object_id: uuid.UUID,
        request: Request,
        field: str,
        user: User = Depends(require_permission("objects:view")),
        db: Session = Depends(get_db),
    ):
        if field not in ZUGANGSCODE_FIELD_KEYS:
            raise HTTPException(400, "Unbekanntes Zugangscode-Feld")
        accessible = accessible_object_ids(db, user)
        detail = get_object_detail(db, object_id, accessible_ids=accessible)
        if detail is None:
            raise HTTPException(404, "Objekt nicht gefunden")
        return templates.TemplateResponse(
            request,
            "_obj_zugangscode_view.html",
            {"obj": detail.obj, "field": _zugangscode_field_ctx(detail.obj, field, db, request, user), "user": user},
        )

    @router.get("/{object_id}/zugangscodes/edit", response_class=HTMLResponse)
    async def zugangscode_field_edit(
        object_id: uuid.UUID,
        request: Request,
        field: str,
        user: User = Depends(require_permission("objects:edit")),
        db: Session = Depends(get_db),
    ):
        if field not in ZUGANGSCODE_FIELD_KEYS:
            raise HTTPException(400, "Unbekanntes Zugangscode-Feld")
        accessible = accessible_object_ids(db, user)
        detail = get_object_detail(db, object_id, accessible_ids=accessible)
        if detail is None:
            raise HTTPException(404, "Objekt nicht gefunden")
        return templates.TemplateResponse(
            request,
            "_obj_zugangscode_edit.html",
            {"obj": detail.obj, "field": _zugangscode_field_ctx(detail.obj, field, db, request, user), "user": user, "error": None},
        )

    @router.post("/{object_id}/zugangscodes/field", response_class=HTMLResponse)
    async def zugangscode_field_save(
        object_id: uuid.UUID,
        request: Request,
        field_name: str = Form(...),
        value: str = Form(""),
        user: User = Depends(require_permission("objects:edit")),
        db: Session = Depends(get_db),
    ):
        if field_name not in ZUGANGSCODE_FIELD_KEYS:
            raise HTTPException(400, "Unbekanntes Zugangscode-Feld")
        accessible = accessible_object_ids(db, user)
        detail = get_object_detail(db, object_id, accessible_ids=accessible)
        if detail is None:
            raise HTTPException(404, "Objekt nicht gefunden")

        parsed, error = parse_zugangscode_value(field_name, value)
        if error is not None:
            return templates.TemplateResponse(
                request,
                "_obj_zugangscode_edit.html",
                {
                    "obj": detail.obj,
                    "field": _zugangscode_field_ctx(detail.obj, field_name, db, request, user),
                    "user": user,
                    "error": error,
                    "submitted_value": value,
                },
                status_code=422,
            )

        try:
            write_field_human(
                db,
                entity=detail.obj,
                field=field_name,
                value=parsed,   # None (Loeschung) oder Klartext-String
                source="user_edit",
                user=user,
                request=request,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise

        return templates.TemplateResponse(
            request,
            "_obj_zugangscode_view.html",
            {"obj": detail.obj, "field": _zugangscode_field_ctx(detail.obj, field_name, db, request, user), "user": user},
        )


    def _zugangscode_field_ctx(
        obj: Object, field_key: str, db: Session, request, user
    ) -> dict:
        """Baut das Render-Dict fuer ein einzelnes Zugangscode-Fragment.

        Laedt Provenance und decrypted Wert frisch. Bei Decryption-Fehler
        wird ein Audit-Eintrag committed und ein Fehler-Marker zurueckgegeben.
        """
        lookup = {f.key: f for f in ZUGANGSCODE_FIELDS}
        zf = lookup[field_key]
        prov_map = get_provenance_map(db, "object", obj.id, (field_key,))
        raw = getattr(obj, field_key)
        if raw is None:
            dec_value, dec_error = None, None
        else:
            try:
                dec_value = decrypt_field(raw, entity_type="object", field=field_key)
                dec_error = None
            except DecryptionError:
                dec_value = None
                dec_error = "Code nicht verfuegbar — Schluessel-Konfiguration pruefen"
                audit(
                    db,
                    user,
                    "encryption_key_missing",
                    entity_type="object",
                    entity_id=obj.id,
                    details={"field": field_key},
                    request=request,
                )
                db.commit()
        return {
            "key": zf.key,
            "label": zf.label,
            "kind": zf.kind,
            "value": dec_value,
            "error": dec_error,
            "prov": prov_map.get(field_key),
        }
    ```
  - [x] 5.5 **Permission-Asymmetrie**: `/zugangscodes/view` benoetigt nur `objects:view` (Cancel-Flow und Anzeige ohne Edit-Intent); `/zugangscodes/edit` und `/zugangscodes/field` benoetigen `objects:edit`. Das ist bewusst anders als bei den Technik-Endpoints (Story 1.6 hat alle drei hinter `objects:edit` — weil das Fragment-Rendering von view und edit symmetrisch war). Bei Zugangscodes ist "Sehen" inhaerent erlaubt fuer alle `objects:view`-User (gemaeß AC2).
  - [x] 5.6 **Kein `write_field_human` mit Ciphertext direkt**: der Router uebergibt IMMER den Klartext (oder None) an `write_field_human`. Die Encryption geschieht IM WRITE-GATE (Task 3). Das ist die Single-Responsibility-Trennung.

- [x] **Task 6 — Template `app/templates/_obj_zugangscode_view.html` (NEU)** (AC2, AC3, AC5)
  - [x] 6.1 Neue Datei. Analog zu `_obj_technik_field_view.html`, aber mit Fehler-Zustand fuer AC3 und Permission-Check fuer `objects:edit` (nicht `objects:view`) beim Edit-Button:
    ```jinja
    {# View-Fragment fuer ein einzelnes Zugangscode-Feld.
       Container-ID = "field-<key>", HTMX-Target fuer Edit/Save-Swaps.
       "value" ist der KLARTEXT (bereits decrypted); bei Fehler ist "error" gesetzt. #}
    {% set pill = provenance_pill(field.prov) %}
    <div id="field-{{ field.key }}" class="min-w-0">
      <div class="text-xs uppercase tracking-wider text-slate-500 mb-1">{{ field.label }}</div>
      <div class="flex items-center justify-between gap-3">
        <div class="text-sm text-slate-900 truncate">
          {% if field.error %}
            <span class="text-amber-600 italic text-xs">{{ field.error }}</span>
          {% elif field.value is not none and field.value != "" %}
            <span class="font-mono">{{ field.value }}</span>
          {% else %}
            <span class="text-slate-400">&mdash;</span>
          {% endif %}
        </div>
        <div class="flex items-center gap-2 shrink-0">
          {% if not field.error %}
            <span data-source="{{ pill.source }}"
                  data-field="{{ field.key }}"
                  title="{{ pill.tooltip }}"
                  class="inline-flex items-center text-[11px] px-2 py-0.5 rounded {{ pill.color_class }}">
              {{ pill.label }}
            </span>
          {% endif %}
          {% if has_permission(user, "objects:edit") %}
            <button type="button"
                    data-edit-field="{{ field.key }}"
                    hx-get="/objects/{{ obj.id }}/zugangscodes/edit?field={{ field.key }}"
                    hx-target="#field-{{ field.key }}"
                    hx-swap="outerHTML"
                    class="text-xs text-sky-600 hover:text-sky-900">Edit</button>
          {% endif %}
        </div>
      </div>
    </div>
    ```

- [x] **Task 7 — Template `app/templates/_obj_zugangscode_edit.html` (NEU)** (AC1, AC4, AC5)
  - [x] 7.1 Neue Datei. Analog zu `_obj_technik_field_edit.html`. Input-Feld ist `type="text"` (kein `type="number"`). Der Wert im Input ist beim Edit der KLARTEXT (decrypted), beim Fehler-Rerender der `submitted_value`:
    ```jinja
    {# Edit-Fragment fuer ein einzelnes Zugangscode-Feld.
       POST geht an zugangscodes/field — nicht an technik/field.
       "submitted_value" nur beim Validierungsfehler gesetzt. #}
    <div id="field-{{ field.key }}" class="min-w-0"
         data-edit-field="{{ field.key }}"
         data-error="{{ 'true' if error else 'false' }}">
      <form hx-post="/objects/{{ obj.id }}/zugangscodes/field"
            hx-target="#field-{{ field.key }}"
            hx-swap="outerHTML"
            class="flex flex-col gap-1">
        <label class="text-xs uppercase tracking-wider text-slate-500"
               for="input-{{ field.key }}">{{ field.label }}</label>
        <input type="hidden" name="field_name" value="{{ field.key }}">
        {% set current_value =
           submitted_value if submitted_value is defined and submitted_value is not none
           else (field.value if field.value is not none else "") %}
        <input id="input-{{ field.key }}"
               name="value"
               type="text"
               value="{{ current_value }}"
               autocomplete="off"
               class="block w-full rounded border {{ 'border-rose-300' if error else 'border-slate-300' }} px-2 py-1 text-sm font-mono">
        {% if error %}
          <p class="text-xs text-rose-600 mt-0.5">{{ error }}</p>
        {% endif %}
        <div class="flex items-center gap-2 mt-1">
          <button type="submit"
                  class="text-xs px-2 py-0.5 rounded bg-sky-600 text-white hover:bg-sky-700">
            Speichern
          </button>
          <button type="button"
                  hx-get="/objects/{{ obj.id }}/zugangscodes/view?field={{ field.key }}"
                  hx-target="#field-{{ field.key }}"
                  hx-swap="outerHTML"
                  class="text-xs text-slate-500 hover:text-slate-900">
            Abbrechen
          </button>
        </div>
      </form>
    </div>
    ```
  - [x] 7.2 `autocomplete="off"` ist Pflicht auf dem Input — Browser-Autofill fuer Felder namens `value` wuerde beliebige Werte eintragen.
  - [x] 7.3 `font-mono` auf dem Input erleichtert Code-Eingabe (Ziffernfolgen + Sonderzeichen).

- [x] **Task 8 — Template `app/templates/_obj_technik.html` aktualisieren** (AC1–AC5)
  - [x] 8.1 Den bestehenden Kommentar aktualisieren: "Zugangscodes bleiben Story 1.7 (UI + Fernet gemeinsam)." → "Zugangscodes: Story 1.7 (Fernet-verschluesselt, eigene Endpoints)."
  - [x] 8.2 Neuen Sub-Block "Zugangscodes" nach dem "Objekt-Historie"-Block (dem letzten bestehenden Block) ergaenzen:
    ```jinja
    <div class="mt-6 pt-6 border-t border-slate-100">
      <h3 class="text-sm font-semibold text-slate-800 mb-3">Zugangscodes</h3>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-x-6 gap-y-4">
        {% for field in tech_zugangscodes %}
          {% include "_obj_zugangscode_view.html" %}
        {% endfor %}
      </div>
    </div>
    ```
  - [x] 8.3 Der Sub-Block wird durch eine horizontale Trennlinie (`border-t`) optisch von der Objekt-Historie abgesetzt — Zugangscodes sind sensibler und verdienen eine visuelle Abtrennung.

- [x] **Task 9 — Unit-Tests `tests/test_field_encryption_unit.py` (NEU)** (AC1, AC2, AC3, AC4)
  - [x] 9.1 Neue Datei. Reine Logik-Tests ohne TestClient oder DB. Kein echter Schluessel noetig — `os.environ` patchen:
    ```python
    import os
    import pytest

    os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use")
    os.environ.setdefault("POSTGRES_PASSWORD", "")
    os.environ.setdefault("ANTHROPIC_API_KEY", "")
    os.environ.setdefault("IMPOWER_BEARER_TOKEN", "")

    from app.services.field_encryption import (
        encrypt_field,
        decrypt_field,
        DecryptionError,
    )
    ```
  - [x] 9.2 Tests:
    - `test_encrypt_produces_v1_prefix` — `encrypt_field("1234", entity_type="object", field="entry_code_main_door")` → result starts with `"v1:"`.
    - `test_roundtrip_plaintext` — encrypt then decrypt gives back original plaintext (AC2 Roundtrip).
    - `test_roundtrip_special_chars` — Sonderzeichen wie `"A#1!@9-X"` korrekt roundtrip.
    - `test_empty_roundtrip` — kurzer 1-Zeichen-Code funktioniert: `encrypt_field("0", ...)`.
    - `test_different_fields_different_ciphertext` — gleicher plaintext, aber `field="entry_code_main_door"` vs `field="entry_code_garage"` → unterschiedliche Ciphertexte (HKDF per-field key, AC1 Isolation).
    - `test_different_entity_types_different_ciphertext` — gleicher plaintext, gleicher field, aber `entity_type="object"` vs `entity_type="unit"` → unterschiedliche Ciphertexte.
    - `test_fernet_random_iv` — zweimal `encrypt_field` mit gleichem Plaintext → unterschiedliche Tokens (Fernet-IV ist random, entscheidend fuer Noop-Check-Verhalten).
    - `test_decrypt_wrong_format_raises` — `decrypt_field("no-colon-here", ...)` → `DecryptionError`.
    - `test_decrypt_tampered_token_raises` — Token korrekt geprefixed aber Bytes veraendert → `DecryptionError` (AC3 Simulation).
    - `test_key_in_provenance_marker` — `_json_safe_for_provenance("object", "entry_code_main_door", "anything")` → `{"encrypted": True}` (Test dass der bestehende Marker korrekt bleibt — Import aus `steckbrief_write_gate`).
    - `test_encrypt_key_id_default` — kein `key_id`-Argument → Default `"v1"` im Praefix.
    - `test_encrypt_custom_key_id` — `key_id="v2"` → result starts with `"v2:"`.
    - `test_decrypt_with_custom_key_id` — encrypt mit `key_id="v2"` + decrypt → Roundtrip funktioniert (key_id selbst wird nicht in der Schluessel-Ableitung verwendet, nur als Praefix gespeichert).

- [x] **Task 10 — Route-Smoke-Tests `tests/test_zugangscodes_routes_smoke.py` (NEU)** (AC1–AC7)
  - [x] 10.1 Neue Datei. Fixtures analog zu `test_technik_routes_smoke.py`. Wiederverwendung der `steckbrief_admin_client`-Fixture aus `conftest.py` (sofern dort vorhanden) oder eigene Fixtures mit eindeutigen E-Mails (keine Kollision mit bestehenden Tests).
  - [x] 10.2 Fixture `viewer_zug_client` fuer AC5: User mit nur `objects:view` (kein `objects:edit`).
  - [x] 10.3 Tests:
    - **AC1 + AC2** `test_zugangscode_save_encrypts_and_decrypts_roundtrip` — Objekt mit `entry_code_main_door=None`; POST `field_name="entry_code_main_door", value="1234-AB"` als Admin → 200; `refreshed.entry_code_main_door` startet mit `"v1:"` (AC1 Ciphertext im DB); GET `/objects/{id}` → 200, Response enthaelt `"1234-AB"` in Klartext (AC2 Decryption).
    - **AC1** `test_zugangscode_save_no_plaintext_in_provenance` — Nach POST pruefen: `FieldProvenance.value_snapshot` enthaelt KEIN `"1234-AB"`, sondern `{"encrypted": True}` in `"new"`.
    - **AC1** `test_zugangscode_save_no_plaintext_in_audit` — `AuditLog.details_json` enthaelt KEIN `"1234-AB"`.
    - **AC4** `test_zugangscode_save_empty_deletes_code` — Objekt mit gesetztem Code; POST `value=""` → 200; `refreshed.entry_code_main_door is None`; Technik-Sektion zeigt `—`-Placeholder.
    - **AC5** `test_zugangscode_edit_button_not_shown_for_viewer` — GET `/objects/{id}` mit `viewer_zug_client` → 200; Zugangscodes-Block sichtbar + Code decrypted angezeigt; aber KEIN `data-edit-field="entry_code_*"` im HTML.
    - **AC5** `test_zugangscode_post_returns_403_for_viewer` — `viewer_zug_client.post("/objects/{id}/zugangscodes/field", ...)` → 403.
    - **AC5** `test_zugangscode_edit_get_returns_403_for_viewer` — `viewer_zug_client.get("/objects/{id}/zugangscodes/edit?field=entry_code_main_door")` → 403.
    - **AC5** `test_zugangscode_view_get_accessible_for_viewer` — `viewer_zug_client.get("/objects/{id}/zugangscodes/view?field=entry_code_main_door")` → 200 (Viewer darf View-Fragment laden — Cancel-Flow).
    - **AC6** `test_technik_endpoint_still_rejects_entry_code` — POST an `/objects/{id}/technik/field` mit `field_name="entry_code_main_door"` → 400 (bestehender Guard unveraendert).
    - **AC3** `test_zugangscode_decryption_failure_shows_placeholder` — Objekt direkt in DB mit `entry_code_main_door="v1:INVALIDTOKEN"` (nicht valid Fernet) setzen; GET `/objects/{id}` → 200; Response enthaelt "Code nicht verfuegbar — Schluessel-Konfiguration pruefen".
    - **AC3** `test_zugangscode_decryption_failure_writes_audit` — Selbes Setup; nach GET: `AuditLog`-Row mit `action="encryption_key_missing"` und `details_json.field="entry_code_main_door"` existiert.
    - **AC2** `test_zugangscode_null_shows_placeholder` — Objekt mit `entry_code_main_door=None`; GET `/objects/{id}` → 200; Zugangscodes-Block enthaelt `&mdash;` fuer Haustuer-Code (kein Fehler, kein Wert, nur Placeholder).
    - **AC1** `test_zugangscode_all_three_fields_work` — Alle drei Felder nacheinander setzen und decrypten (entry_code_garage + entry_code_technical_room).
    - **AC6** `test_zugangscode_view_endpoint_unknown_field_returns_400` — GET `view?field=year_roof` → 400.
    - **AC6** `test_zugangscode_edit_endpoint_unknown_field_returns_400` — GET `edit?field=year_roof` → 400.
    - **AC7** Kein expliziter Regressions-Test noetig — `pytest -x` laueft die ganze Suite.

- [x] **Task 11 — Regression + deferred-work-Update** (AC7)
  - [x] 11.1 `pytest -x` komplett durchlaufen lassen. Erwartung: >= 432 bestehende + neue Tests, alle gruen.
  - [x] 11.2 `test_technik_routes_smoke.py` pruefen: die bestehenden Tests `test_technik_section_rendered_with_all_fields_and_edit_buttons_for_editor` und `test_technik_save_rejects_entry_code_field` muessen weiterhin gruen sein. Dieser Test sichert die Scope-Boundary aus Story 1.6.
  - [x] 11.3 Die deferred-work.md Items fuer 1.7 als erledigt markieren:
    - "Entry-Code `String`-Spalten ohne Length-Limit" — kein Migration-Umbau noetig, Fernet-Output passt in `String`/`TEXT`. In deferred-work als closed/deferred noting.
    - "`_ENCRYPTED_FIELDS` nur fuer `"object"`" — Erweiterung auf Unit/Mieter ist v1.1; deferred bleibt.

## Dev Notes

### Was bereits existiert — NICHT neu bauen

- **`entry_code_main_door`, `entry_code_garage`, `entry_code_technical_room`** als `String` nullable in Tabelle `objects` (Migration 0010, `app/models/object.py:50-53`). Kommentar: `# Ciphertext-Placeholder — Fernet-Encryption folgt mit Story 1.7.` — die Spalten sind bereit, kein Migration-Touch noetig.
- **`_ENCRYPTED_FIELDS: dict[str, frozenset[str]]`** in `app/services/steckbrief_write_gate.py:114-118` — markiert die drei Entry-Code-Felder als encrypted. Das Gate nutzt diese Konstante bereits fuer Provenance-Masking. Story 1.7 ergaenzt NUR die Encryption-Logik (Task 3).
- **`_json_safe_for_provenance(entity_type, field, value)`** in `steckbrief_write_gate.py:177-187` — gibt bereits `{"encrypted": True}` zurueck fuer `_ENCRYPTED_FIELDS`. AC1 ist fuer Provenance-Masking also schon erfuellt — nur die eigentliche Encryption im `setattr`-Pfad fehlt noch.
- **`"encryption_key_missing"`** in `app/services/audit.py:86` als bekannte Audit-Action registriert. Kein Audit-Katalog-Touch noetig.
- **`_obj_technik.html`** hat bereits einen Kommentar-Placeholder: "Zugangscodes bleiben Story 1.7 (UI + Fernet gemeinsam)." — einfach durch den neuen Sub-Block ersetzen.
- **`TECHNIK_FIELD_KEYS`** schliesst `entry_code_*` explizit AUS — der Router-Guard in `technik_field_save` (Zeile ~540 in `objects.py`) blockiert weiterhin jeden POST an `/technik/field` mit diesen Keys. Das ist die Scope-Boundary aus Story 1.6 (AC6) — NICHT aendern.
- **Test `test_technik_save_rejects_entry_code_field`** in `test_technik_routes_smoke.py` — MUSS weiterhin gruen sein. Story 1.7 baut neue `/zugangscodes/*`-Endpoints, nicht eine Erweiterung der Technik-Endpoints.

### Kritische Implementation-Details

**1. HKDF per Feld = verschiedene Schluessel**

`HKDF(secret_key, salt=b"steckbrief-v1", info="object:entry_code_main_door")` liefert einen anderen Schluessel als `info="object:entry_code_garage"`. Das ist bewusst: ein kompromittierter Haustuer-Code gibt NICHT den Garage-Code preis. Beim Schreiben von Tests: encrypt/decrypt IMMER mit konsistenten `entity_type` und `field`-Parametern — falsches Pair → `DecryptionError`.

**2. Fernet Random-IV → Noop-Check irrelevant**

`Fernet.encrypt()` generiert jedes Mal einen neuen Random-IV → der Ciphertext ist IMMER neu, auch bei gleichem Plaintext. Die Noop-Logik in `write_field_human` (`old_value == value`) vergleicht alten Ciphertext mit neuem Ciphertext → immer ungleich → immer Write + neue Provenance-Row. Das ist ABSICHT fuer v1 und dokumentiert. Konsequenz: bei wiederholtem Speichern desselben Codes entstehen mehrere Provenance-Rows (anders als bei Technik-Feldern, wo der Noop-Shortcut greift).

**3. Encryption VOR setattr im Write-Gate**

Die Encryption (`encrypt_field(value, ...)`) ersetzt `value` IM Write-Gate BEVOR `setattr(entity, field, value)` aufgerufen wird (Task 3.1). Der Router uebergibt den KLARTEXT — das Gate verschluesselt intern. Diese Trennung stellt sicher, dass kein Router versehentlich Klartext in DB schreibt.

**4. Decryption BEIM RENDER (nicht im Modell)**

Es gibt kein `TypeDecorator` auf den ORM-Spalten (architecture.md §CD5 explizit). Decryption geschieht im Router-Handler wenn der Template-Context gebaut wird. Das hat zwei Konsequenzen:
- Jeder Render laedt die Spalten als Ciphertext und decrypted on-the-fly.
- Wenn der Render-Handler keinen `request` zur Hand hat (BackgroundTask), wird nie decrypted — korrekt, da BackgroundTasks keine UI rendern.

**5. Audit bei Decryption-Failure im GET-Handler**

Die `encryption_key_missing`-Audit-Eintraege entstehen im GET `/objects/{id}`-Handler (kein Form-Submit). Dafuer wird ein explizites `db.commit()` am Ende des Zugangscode-Blocks gemacht (nur wenn `_zug_decrypt_failed = True`). Das ist ein Sonderfall — GET-Handler committen normalerweise nicht. Hier ist es vertretbar: Decryption-Failure ist ein Konfigurations-Problem, das sofort im Audit-Log erscheinen muss. Alternativen (Middleware, BackgroundTask) wuerden unnoetige Komplexitaet einbringen.

**6. `_zugangscode_field_ctx`-Helper: Decryption-Fehler als Audit**

Der Helper `_zugangscode_field_ctx(obj, field_key, db, request, user)` in `objects.py` wird von allen drei Zugangscode-Endpoints aufgerufen (view/edit/save). Er laed Provenance + decrypted Wert und committed bei Fehler einen Audit-Eintrag. Im EDIT-Form-Fragment wird der Klartext-Wert als Input-`value` zurueckgegeben — der User sieht den aktuellen Code beim Bearbeiten.

**7. Scope: Keine Migration in Story 1.7**

Die DB-Spalten existieren bereits (Migration 0010). Sie sind `String` (= `TEXT` in Postgres) — der Fernet-Token fuer typische Codes (< 50 Zeichen Plaintext) ist ~100-120 Zeichen lang, passt problemlos in `TEXT`. Die deferred-work-Note "max. 512 Zeichen" war ein geplanter ALTER COLUMN — der ist fuer v1 nicht noetig und wird auf v1.1 verschoben. **Kein `ls migrations/versions/` und keine neue Migration.**

**8. Template-Response-Signatur**

`templates.TemplateResponse(request, "name.html", {...})` — `request` MUSS erstes Argument sein. Memory: `feedback_starlette_templateresponse`.

**9. Write-Gate-Coverage-Scanner**

`tests/test_write_gate_coverage.py` scannt auf direktes `obj.entry_code_main_door = ...` etc. in Produktionscode. Der neue Router-Code darf KEINEN direkten Assign auf CD1-Felder machen — ausschliesslich `write_field_human(...)`. Die Encryption geschieht intern im Gate.

**10. `conftest.py` keine Aenderung noetig**

`STECKBRIEF_FIELD_KEY` ist optional — Fallback auf `SECRET_KEY` (`"test-secret-key-do-not-use"`, in `conftest.py:13` gesetzt). Die Encryption-Tests laufen mit diesem Key. Kein neues `os.environ.setdefault` in `conftest.py`.

### Bekannte Grenzfaelle

- **Leerer Wert = NULL**: `parse_zugangscode_value("...", "")` → `(None, None)`. `write_field_human(value=None)` schreibt `NULL` in die DB. Der Encryption-Block im Write-Gate prueft `value is not None and value.strip()` — bei `None` wird nicht verschluesselt, `None` landet direkt in DB.
- **Bereits NULL-Feld**: Kein Ciphertext, kein Decrypt-Versuch im Render. Router zeigt `—`-Placeholder.
- **Test-Isolation**: `test_zugangscode_save_encrypts_and_decrypts_roundtrip` setzt `field_name="entry_code_main_door"` und testet dann GET `/objects/{id}`. Dieser GET-Test schlaegt fehl, falls der Decrypt-Test-Key nicht mit dem Encrypt-Test-Key uebereinstimmt. Da beide denselben `SECRET_KEY` aus `conftest.py` nutzen, ist das korrekt.
- **Unicode in Zugangscodes**: Fernet verschluesselt Bytes — `plaintext.encode("utf-8")` verarbeitet auch Sonderzeichen korrekt.

### Project Structure Notes

- **Neu angelegt:**
  - `app/services/field_encryption.py`
  - `app/templates/_obj_zugangscode_view.html`
  - `app/templates/_obj_zugangscode_edit.html`
  - `tests/test_field_encryption_unit.py`
  - `tests/test_zugangscodes_routes_smoke.py`
- **Modifiziert:**
  - `pyproject.toml` (`cryptography>=43` ergaenzt)
  - `.env.op` (`STECKBRIEF_FIELD_KEY` dokumentiert)
  - `app/config.py` (`steckbrief_field_key: str = ""` ergaenzt)
  - `app/services/steckbrief.py` (ZUGANGSCODE_FIELDS + ZUGANGSCODE_FIELD_KEYS + `parse_zugangscode_value`)
  - `app/services/steckbrief_write_gate.py` (Encryption-Block in `write_field_human`)
  - `app/routers/objects.py` (Zugangscode-Context im Detail-Handler, 3 neue Endpoints, `_zugangscode_field_ctx`-Helper)
  - `app/templates/_obj_technik.html` (Kommentar + neuer Zugangscodes-Sub-Block)
- **Nicht beruehrt (explizit):**
  - Keine neue Migration (Spalten existieren seit 0010)
  - `app/models/object.py` — keine Typ-Aenderung (Spalten bleiben `String`)
  - `app/permissions.py` — keine neue Permission (bestehende `objects:view`/`objects:edit` genuegen)
  - `app/services/audit.py` — `encryption_key_missing` bereits registriert
  - `tests/test_technik_routes_smoke.py` — kein Touch; bestehende `entry_code_*`-Guard-Tests muessen weiter gruen sein

### References

- [Epic 1 Story 1.7 Akzeptanzkriterien](output/planning-artifacts/epics.md#story-17-zugangscodes-mit-field-level-encryption)
- [Architektur CD5 Field-Level-Encryption](output/planning-artifacts/architecture.md#cd5--field-level-encryption) — HKDF-Schluessel-Ableitung, Ciphertext-Format, Schluessel-Quelle
- [Story 1.6 Technik-Sektion](output/implementation-artifacts/1-6-technik-sektion-mit-inline-edit.md) — Inline-Edit-Pattern fuer Technik-Felder (HTMX-Fragment-Strategie, `_technik_field_ctx`, Permission-Patterns)
- [Story 1.2 Write-Gate](output/implementation-artifacts/1-2-objekt-datenmodell-write-gate-provenance-infrastruktur.md) — `_ENCRYPTED_FIELDS`, `_json_safe_for_provenance`, Write-Gate-Lifecycle
- [Object-Model](app/models/object.py:50) — `entry_code_*`-Spalten mit "Ciphertext-Placeholder"-Kommentar
- [Write-Gate](app/services/steckbrief_write_gate.py:114) — `_ENCRYPTED_FIELDS` + `_json_safe_for_provenance` + `write_field_human`
- [Steckbrief-Service](app/services/steckbrief.py) — `TechnikField`-Dataclass + TECHNIK_FIELD_KEYS als Vorlage
- [Technik-Templates](app/templates/_obj_technik_field_view.html) — View-Fragment-Vorlage
- [Router-Pattern](app/routers/objects.py) — `object_detail`-Handler, `_technik_field_ctx`-Helper als Vorlage
- [Deferred-Work](output/implementation-artifacts/deferred-work.md:26-27) — Entry-Code Length + `_ENCRYPTED_FIELDS`-Erweiterung auf Unit/Mieter als v1.1-Deferral
- [Migration 0010 Steckbrief-Core](migrations/versions/0010_steckbrief_core.py) — Ursprung der entry_code_*-Spalten
- [project-context.md](docs/project-context.md) — Alle Plattform-Regeln (SQLAlchemy 2.0 typed ORM, Alembic handgeschrieben, Template-Response-Signatur)

### Latest Technical Information

- **`cryptography` Library**: `Fernet` aus `cryptography.fernet`, `HKDF` aus `cryptography.hazmat.primitives.kdf.hkdf`. Fernet ist symmetrisch (AES-128-CBC + HMAC-SHA256). Key muss 32-Byte URL-safe base64 sein → `base64.urlsafe_b64encode(32_bytes)`.
- **HKDF API** (cryptography >= 43): `HKDF(algorithm=hashes.SHA256(), length=32, salt=..., info=...)` → `.derive(key_material_bytes)`. `key_material` ist der Master-Key als `bytes` (UTF-8 enkodiert aus `settings.secret_key`).
- **Fernet Token-Format**: `Fernet.encrypt(b"plaintext")` liefert `bytes` — URL-safe base64-kodierter Token, der Version (immer `0x80`), Timestamp, IV, Ciphertext und HMAC enthaelt. Decode via `.decode("ascii")` → String.
- **pytest 8.x + asyncio_mode="auto"**: die neuen Tests sind synchron (kein async noetig). `TestClient` kuemmert sich um die async-Bruecke.
- **Keine Migration**: bestehende `String`-Spalten in SQLAlchemy 2.0 sind ohne Laengen-Limit = `TEXT` in Postgres. Fernet-Output fuer Codes bis 200 Zeichen Plaintext ist < 350 Zeichen — passt in `TEXT` ohne ALTER COLUMN.

## Dev Agent Record

### Agent Model Used

Claude Opus 4.7 (1M context) — `claude-opus-4-7[1m]`

### Debug Log References

- `docker compose exec app pytest tests/test_field_encryption_unit.py -x` → 13 passed
- `docker compose exec app pytest tests/test_zugangscodes_routes_smoke.py -x` → 17 passed
- `docker compose exec app pytest -x` → 463 passed (vorher 432; +30 neue Tests; existing N+1-Guard-Test von 8 auf 9 angehoben + Scope-Boundary-Assertion in `test_technik_section_rendered_with_all_fields_and_edit_buttons_for_editor` invertiert, da Zugangscodes jetzt legitim im Render erscheinen)

### Completion Notes List

- Encryption via HKDF-Per-Field + Fernet (Random-IV). Master-Key aus `settings.steckbrief_field_key` mit Fallback `settings.secret_key`. Ciphertext-Format `v1:<fernet-token>` fuer spaetere Key-Rotation.
- Write-Gate encryptet vor `setattr` und behaelt den bestehenden Masking-Marker `{"encrypted": True}` in Provenance + Audit (Story 1.2 Schutz bleibt aktiv).
- Router uebergibt immer KLARTEXT an `write_field_human`; der Gate verschluesselt intern → Single-Responsibility.
- Drei neue Endpoints `/objects/{id}/zugangscodes/{view|edit|field}`. View-Endpoint hinter `objects:view` (AC5), Edit + Save hinter `objects:edit`.
- Decryption-Fehler im GET-Detail-Handler → Audit-Eintrag `encryption_key_missing` + UI-Placeholder `"Code nicht verfuegbar — Schluessel-Konfiguration pruefen"`. Commit ist hier bewusst (GET-Handler, Sonderfall fuer Key-Fehlkonfiguration).
- Statement-Count-Guard in `test_detail_sql_statement_count` um +1 auf 9 angehoben (neuer `get_provenance_map`-Call fuer Zugangscodes); die Konsolidierung zu einem einzigen Call steht weiterhin in deferred-work (Story 1.3/1.6 Finding).
- Scope-Boundary-Assertion in `test_technik_section_rendered_with_all_fields_and_edit_buttons_for_editor` invertiert: wo zuvor `"entry_code_*" not in body` stand, wird jetzt die sichtbare Render-Praesenz gepruft. Der Technik-Endpoint lehnt `entry_code_*` weiterhin mit 400 ab (`test_technik_save_rejects_entry_code_field` unveraendert gruen).

### File List

Neu angelegt:
- `app/services/field_encryption.py`
- `app/templates/_obj_zugangscode_view.html`
- `app/templates/_obj_zugangscode_edit.html`
- `tests/test_field_encryption_unit.py`
- `tests/test_zugangscodes_routes_smoke.py`

Modifiziert:
- `pyproject.toml` (`cryptography>=43` als direkte Dep)
- `app/config.py` (`steckbrief_field_key: str = ""`)
- `.env.op` (`STECKBRIEF_FIELD_KEY`-Platzhalter)
- `app/services/steckbrief_write_gate.py` (Encryption-Block in `write_field_human`)
- `app/services/steckbrief.py` (`ZUGANGSCODE_FIELDS`, `ZUGANGSCODE_FIELD_KEYS`, `parse_zugangscode_value`)
- `app/routers/objects.py` (Imports + Zugangscode-Context im Detail-Handler + 3 Endpoints + `_zugangscode_field_ctx`-Helper)
- `app/templates/_obj_technik.html` (Kommentar-Update + Zugangscodes-Sub-Block)
- `tests/test_technik_routes_smoke.py` (Scope-Boundary-Assertion invertiert)
- `tests/test_steckbrief_routes_smoke.py` (Statement-Count-Guard 8 → 9)
- `output/implementation-artifacts/sprint-status.yaml` (Story 1.7 → in-progress → review)

### Review Findings

<!-- Code-Review 2026-04-23 — 3 Layer: Blind Hunter + Edge Case Hunter + Acceptance Auditor -->

**Decision Needed:**

- [x] [Review][Decision] Fallback auf `secret_key` ohne Startup-Validierung — `steckbrief_field_key` ist leer in `.env.op`; bei falsch konfiguriertem Prod-Deployment wird der Web-Session-Key (Default `"dev-secret-change-me"`) als Encryption-Key verwendet ohne Warnung. Design war intentional (Spec: "Leer = Fallback auf secret_key"), aber fehlende Startup-Validierung ist eine Lücke. Optionen: (a) Startup-Warning loggend wenn leer, (b) erzwinge non-empty in Prod via Validator, (c) defer auf Prod-Rollout.

**Patches:**

- [x] [Review][Patch] `db.commit()` in `_zugangscode_field_ctx` — Helper committed sich selbst bei Decryption-Failure; Caller verliert Kontrolle über Transaktionsgrenzen (besonders problematisch in GET-Endpoints und nach `write_field_human`) [`app/routers/objects.py`]
- [x] [Review][Patch] Audit-commit in `object_detail` ohne Error-Handling — `if _zug_decrypt_failed: db.commit()` hat kein `try/except`; bei DB-Fehler fällt der vollständig gerenderte Page-Content als 500 raus statt graceful degrading [`app/routers/objects.py`]
- [x] [Review][Patch] `encrypt_field` key_id ohne Colon-Validierung — ein Colon in `key_id` (z.B. `"v1:extra"`) erzeugt beim Decrypt einen verschobenen `partition(":")`-Split → permanenter Datenverlust (Token unentschlüsselbar) [`app/services/field_encryption.py`]
- [x] [Review][Patch] Test AC1 — Positive Assertion für `{"encrypted": True}` in `AuditLog.details_json` fehlt — Test prüft nur Abwesenheit von Klartext, nicht Anwesenheit des Markers [`tests/test_zugangscodes_routes_smoke.py`]
- [x] [Review][Patch] Test AC4 — `FieldProvenance.value_snapshot` bei Leer-Submission (Löschen) nicht geprüft — Test verifiziert DB-NULL aber nicht die Provenance-Snapshot-Form `{"old": {"encrypted": True}, "new": {"encrypted": True}}` [`tests/test_zugangscodes_routes_smoke.py`]
- [x] [Review][Patch] `deferred-work.md` nicht aktualisiert — Task 11.3 als [x] markiert, aber beide Items ("Entry-Code String-Spalten ohne Length-Limit" + "`_ENCRYPTED_FIELDS` nur für `object`") wurden nicht geschlossen [`output/implementation-artifacts/deferred-work.md`]
- [x] [Review][Patch] `architecture.md §CD5` — `decrypt_field`-Signatur divergiert: Spec definiert `key_id`-Parameter, Implementierung hat ihn nicht; zukünftiger Caller per Spec bekommt `TypeError` [`docs/architecture.md`]

**Deferred:**

- [x] [Review][Defer] `key_id`-Rotation-Illusion — Format verspricht Rotation-Fähigkeit, aber beim echten Master-Key-Wechsel werden alle `v1:`-Blobs unentschlüsselbar (kein Multi-Key-Lookup); Rotation-Job in v1.1 muss Migration aller Ciphertexts enthalten [`app/services/field_encryption.py`] — deferred, Rotation ist explizit v1.1
- [x] [Review][Defer] `objects:view_confidential` nicht für Entry-Codes — physische Zugangsdaten haben dasselbe Permission-Level wie normale Objektfelder; design-intentional per Spec AC2/AC5, aber vor Prod-Rollout überdenken (Referenz: deferred-work.md Story 1.3 "Kein Field-Level-Redaction für `view_confidential`") — deferred, bereits in deferred-work erfasst
- [x] [Review][Defer] HKDF von beliebig-langen UTF-8-Strings ohne PBKDF2 — akzeptabel bei env-var als 32-byte Zufalls-Hex; kryptografisch korrektere Alternative wäre Argon2/PBKDF2 für passwortartige Inputs — deferred, pre-existing design decision
- [x] [Review][Defer] Stale ORM-Instanz nach `db.commit()` in `zugangscode_field_save` — pre-existing Pattern aus `technik_field_save`, funktioniert mit FastAPI-Session-Lifecycle (lazy-load nach Expiry, Session bleibt bis Response-Ende offen) [`app/routers/objects.py`] — deferred, pre-existing
- [x] [Review][Defer] `len()`-Check in `parse_zugangscode_value` ist Zeichen-Anzahl, nicht Byte-Anzahl — bei unbeschränktem `String`-Schema kein Bug; multi-byte Unicode-Sequenzen könnten schema-Limit umgehen falls je ein `String(N)` gesetzt wird [`app/services/steckbrief.py`] — deferred, kein aktuelles Schema-Limit
- [x] [Review][Defer] Double-Encrypt-Risiko für zukünftige Write-Pfade (z.B. Nightly-Mirror v1.1) — kein Guard in `write_field_human` gegen bereits verschlüsselte `v1:...`-Werte; aktuell alle Router-Caller übergeben Klartext [`app/services/steckbrief_write_gate.py`] — deferred, kein aktueller Write-Pfad betroffen

### Change Log

| Datum | Aenderung |
|-------|-----------|
| 2026-04-23 | Story 1.7 implementiert — Fernet-Feld-Encryption fuer `entry_code_*`, 3 neue Zugangscode-Endpoints mit asymmetrischer Permission-Grenze (view: `objects:view`, edit/save: `objects:edit`), Decryption-Failure-Audit. 463 Tests gruen. Status → review. |
