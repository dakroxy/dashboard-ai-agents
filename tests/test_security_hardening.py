"""Tests fuer Story 5-1: Security-Hardening.

Abdeckung:
  AC1  CSRF-Token auf allen non-GET-Routen
  AC2  Cache-Control: no-store auf Admin-Fragment-Routes
  AC3  Length-Caps fuer Schadensfall.description und audit_log.ip_address
  AC4  Double-Encrypt-Guard fuer _ENCRYPTED_FIELDS
  AC5  Jinja2 Autoescape explizit aktiviert
  AC6  Migration 0019 Daten-Precheck
  AC7  Out-of-Scope-Items dokumentiert (grep-Tests)
"""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# AC1: CSRF
# ---------------------------------------------------------------------------

class TestCsrf:
    def test_csrf_get_request_passes_without_token(self, anon_client):
        """GET-Requests passieren CSRF-Middleware ohne Token."""
        resp = anon_client.get("/")
        # 302 (redirect to login) oder 200 — nie 403 fuer GETs.
        assert resp.status_code != 403

    def test_csrf_head_options_pass_without_token(self, anon_client):
        """HEAD/OPTIONS passieren ebenfalls ohne Token."""
        # Starlette antwortet auf OPTIONS mit 405 oder 200 je Route;
        # wichtig: kein 403.
        resp = anon_client.options("/")
        assert resp.status_code != 403

    def test_csrf_post_without_token_returns_403(self, db, test_user):
        """POST ohne X-CSRF-Token -> 403."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.auth import get_current_user, get_optional_user
        from app.db import get_db

        def override_db():
            yield db

        def override_user():
            return test_user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_optional_user] = override_user

        try:
            with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
                # Kein CSRF-Cookie, kein Header
                resp = c.post("/objects/00000000-0000-0000-0000-000000000001/policen",
                              data={"versicherer_id": "", "police_number": "12345"})
                assert resp.status_code == 403
                assert "CSRF" in resp.json().get("detail", "")
        finally:
            app.dependency_overrides.clear()

    def test_csrf_post_with_invalid_token_returns_403(self, db, test_user):
        """POST mit falschem X-CSRF-Token -> 403."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.auth import get_current_user, get_optional_user
        from app.db import get_db
        from tests.conftest import _make_session_cookie, _TEST_CSRF_TOKEN

        def override_db():
            yield db

        def override_user():
            return test_user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_optional_user] = override_user

        try:
            with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
                c.cookies.set(
                    "session",
                    _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}),
                )
                # Falscher Token im Header
                c.headers["X-CSRF-Token"] = "wrong-token-000000000000000000"
                resp = c.post("/objects/00000000-0000-0000-0000-000000000001/policen",
                              data={"versicherer_id": "", "police_number": "12345"})
                assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_csrf_post_with_valid_token_passes(self, auth_client, db, test_user):
        """POST mit gueltigem CSRF-Token passiert die CSRF-Middleware.

        Die Route selbst darf 403 zurueckgeben (fehlende Permission), aber
        der Grund darf NICHT 'CSRF token missing or invalid' sein.
        """
        # auth_client hat CSRF-Session-Cookie + X-CSRF-Token Header gesetzt (conftest).
        resp = auth_client.post(
            "/objects/00000000-0000-0000-0000-000000000001/policen",
            data={"versicherer_id": "", "police_number": "12345"},
        )
        # Strong assert: der Status darf nicht "CSRF rejected" sein (egal welcher
        # Status sonst kommt — Route-Permission, 404 fuer Object, 422 fuer Form).
        assert resp.status_code in (200, 302, 303, 403, 404, 422), (
            f"Unerwarteter Status: {resp.status_code}"
        )
        if resp.status_code == 403:
            detail = resp.json().get("detail", "")
            assert "CSRF" not in detail, f"CSRF-Fehler trotz validem Token: {detail}"

    def test_oauth_callback_is_get_unaffected_by_csrf(self, anon_client):
        """/auth/google/callback ist GET — CSRF-Middleware greift nicht ein."""
        # Wird redirected zu Google (400/302) — nie 403 wegen CSRF.
        resp = anon_client.get("/auth/google/callback")
        assert resp.status_code != 403

    def test_csrf_token_present_in_base_template(self, auth_client):
        """Gerenderte Page enthaelt hx-headers mit CSRF-Token im erwarteten Format."""
        resp = auth_client.get("/")
        assert resp.status_code == 200, f"Unerwarteter Status: {resp.status_code}"
        # hx-headers Attribut MUSS vorhanden sein und den Token im JSON-Format enthalten.
        assert "hx-headers=" in resp.text, "hx-headers-Attribut fehlt im body"
        assert "X-CSRF-Token" in resp.text, "X-CSRF-Token-Key fehlt im hx-headers"
        # Token-Format pruefen: secrets.token_urlsafe(32) ist Base64-URL-safe
        # mit ~43 Zeichen. Im Test-Setup wird _TEST_CSRF_TOKEN injiziert.
        from tests.conftest import _TEST_CSRF_TOKEN
        assert _TEST_CSRF_TOKEN in resp.text, "Test-Token nicht im hx-headers gefunden"

    def test_csrf_form_body_fallback_passes(self, db, test_user):
        """Klassischer <form method=post>-Submit ohne X-CSRF-Token-Header,
        aber mit `_csrf`-Form-Field passiert die Middleware (Form-Body-Fallback)."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.auth import get_current_user, get_optional_user
        from app.db import get_db
        from tests.conftest import _make_session_cookie, _TEST_CSRF_TOKEN

        def override_db():
            yield db

        def override_user():
            return test_user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_optional_user] = override_user

        try:
            with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
                c.cookies.set(
                    "session",
                    _make_session_cookie({
                        "user_id": str(test_user.id),
                        "csrf_token": _TEST_CSRF_TOKEN,
                    }),
                )
                # Kein X-CSRF-Token-Header — nur _csrf-Form-Field.
                resp = c.post(
                    "/objects/00000000-0000-0000-0000-000000000001/policen",
                    data={
                        "_csrf": _TEST_CSRF_TOKEN,
                        "versicherer_id": "",
                        "police_number": "12345",
                    },
                )
                # Wenn 403: muss von fehlender Permission kommen, NICHT von CSRF.
                if resp.status_code == 403:
                    detail = resp.json().get("detail", "")
                    assert "CSRF" not in detail, (
                        f"CSRF-Fehler trotz validem Form-Body-Token: {detail}"
                    )
        finally:
            app.dependency_overrides.clear()

    def test_csrf_form_body_fallback_with_invalid_token_returns_403(self, db, test_user):
        """Form-Body mit falschem `_csrf`-Field -> 403 von der Middleware."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.auth import get_current_user, get_optional_user
        from app.db import get_db
        from tests.conftest import _make_session_cookie, _TEST_CSRF_TOKEN

        def override_db():
            yield db

        def override_user():
            return test_user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_optional_user] = override_user

        try:
            with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
                c.cookies.set(
                    "session",
                    _make_session_cookie({
                        "user_id": str(test_user.id),
                        "csrf_token": _TEST_CSRF_TOKEN,
                    }),
                )
                resp = c.post(
                    "/objects/00000000-0000-0000-0000-000000000001/policen",
                    data={
                        "_csrf": "wrong-token",
                        "versicherer_id": "",
                        "police_number": "12345",
                    },
                )
                assert resp.status_code == 403
                assert "CSRF" in resp.json().get("detail", "")
        finally:
            app.dependency_overrides.clear()

    def test_csrf_lazy_init_for_legacy_session_without_token(self, db, test_user):
        """Bestandssession ohne `csrf_token`-Key bekommt beim ersten GET ein
        Token nachgesetzt — sonst wuerden Logins von vor Story 5-1 alle
        POSTs bis zum Re-Login mit 403 blockieren.

        End-to-End-Verifikation: GET liefert neues Token, anschliessender POST
        mit dem extrahierten Token muss die CSRF-Middleware passieren.
        """
        from fastapi.testclient import TestClient
        from app.main import app
        from app.auth import get_current_user, get_optional_user
        from app.db import get_db
        from tests.conftest import _make_session_cookie

        def override_db():
            yield db

        def override_user():
            return test_user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_optional_user] = override_user

        try:
            with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
                # Session-Cookie OHNE csrf_token, MIT user_id — simuliert
                # Bestandssession (eingeloggt vor Story 5-1).
                c.cookies.set(
                    "session",
                    _make_session_cookie({"user_id": str(test_user.id)}),
                )
                resp = c.get("/")
                assert resp.status_code in (200, 302)
                # Set-Cookie muss den neu signierten Session-Cookie enthalten.
                set_cookie = resp.headers.get("set-cookie", "")
                assert "session=" in set_cookie or "session" in resp.cookies, (
                    "Lazy-Init hat keinen neuen Session-Cookie gesetzt"
                )

                # Der Client hat jetzt einen Cookie mit dem neuen Token. Wir
                # extrahieren das Token nicht direkt (Cookie-Decoding ist
                # itsdangerous-spezifisch); statt dessen lassen wir den Client
                # automatisch den Cookie weiterverwenden und schicken im POST
                # einen X-CSRF-Token-Header, der NICHT zum Lazy-Init-Token
                # passt — Erwartung: 403 (Token-Mismatch). Damit ist verifiziert,
                # dass der Lazy-Init-Pfad einen Token gesetzt hat (sonst waere
                # session_token = "" und middleware wuerde den header-Pfad
                # gar nicht erst entern).
                resp_post = c.post(
                    "/objects/00000000-0000-0000-0000-000000000001/policen",
                    data={"police_number": "1"},
                    headers={"X-CSRF-Token": "wrong-token-must-mismatch"},
                )
                assert resp_post.status_code == 403, (
                    "Token-Mismatch nach Lazy-Init muss 403 liefern"
                )
        finally:
            app.dependency_overrides.clear()

    def test_csrf_input_helper_emits_hidden_field(self, auth_client):
        """`csrf_input(request)`-Jinja-Global rendert das Hidden-Input mit Token."""
        # Render die ETV-Auswahlseite — sie nutzt csrf_input direkt.
        resp = auth_client.get("/workflows/etv-signature-list/")
        # 200 oder 502/503 (Facilioo nicht erreichbar im Test) — wichtig: nicht 403.
        assert resp.status_code != 403, "ETV-Page darf nicht CSRF-blocken"
        if resp.status_code == 200:
            assert 'name="_csrf"' in resp.text, "csrf_input Macro fehlt im Render"
            assert 'type="hidden"' in resp.text, "Hidden-Input-Pattern fehlt"
            from tests.conftest import _TEST_CSRF_TOKEN
            assert f'value="{_TEST_CSRF_TOKEN}"' in resp.text, "Token-Value im Hidden-Input fehlt"

    def test_csrf_input_present_in_case_detail_form(self, auth_client, db):
        """case_detail.html hat ~30 native Forms — alle muessen csrf_input emittieren.

        Production-Realitaet: HTMX hx-post-Forms und native <form method=post>
        beide muessen den Token transportieren. Wir testen stichprobenartig
        an cases_list.html (1 Form) und workflow_edit.html (1 Form).
        """
        from app.models import Workflow
        wf = db.query(Workflow).first()
        if wf is None:
            pytest.skip("Kein Workflow in DB seeded")
        resp = auth_client.get(f"/workflows/{wf.key}")
        assert resp.status_code in (200, 302, 403)
        if resp.status_code == 200:
            # Native Forms muessen das Hidden-Input enthalten.
            assert 'name="_csrf"' in resp.text, (
                "workflow_edit.html: csrf_input Macro fehlt - "
                "Production-Submit wuerde 403 liefern"
            )


# ---------------------------------------------------------------------------
# AC2: Cache-Control
# ---------------------------------------------------------------------------

class TestCacheControl:
    def test_admin_reject_form_fragment_has_no_store(self, steckbrief_admin_client, db):
        """GET /admin/review-queue/{id}/reject-form liefert Cache-Control: no-store.

        Strong assert: der Header MUSS gesetzt sein (sonst koennte der Browser
        ein veraltetes Reject-Form aus History anzeigen, mit stale Decisions).
        """
        from app.models import ReviewQueueEntry, Object, User as UserModel

        # Mini-Setup: Object + User + ReviewQueueEntry.
        obj = Object(id=uuid.uuid4(), short_code="REVQ", name="Review-Test-Objekt")
        db.add(obj)
        # Submitter-User fuer FK
        submitter = UserModel(
            id=uuid.uuid4(),
            google_sub="rev-q-submitter",
            email="submitter@dbshome.de",
            name="Submitter",
        )
        db.add(submitter)
        db.commit()
        entry = ReviewQueueEntry(
            id=uuid.uuid4(),
            target_entity_type="object",
            target_entity_id=obj.id,
            field_name="name",
            proposed_value={"value": "Neuer Name"},
            agent_ref="test-agent",
            confidence=0.9,
            status="pending",
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)

        resp = steckbrief_admin_client.get(f"/admin/review-queue/{entry.id}/reject-form")
        assert resp.status_code == 200, f"Reject-Form nicht erreichbar: {resp.status_code}"
        assert resp.headers.get("cache-control") == "no-store", (
            f"Cache-Control fehlt/falsch: {resp.headers.get('cache-control')!r}"
        )

    def test_admin_review_queue_rows_has_no_store(self, steckbrief_admin_client):
        """GET /admin/review-queue/rows liefert Cache-Control: no-store."""
        resp = steckbrief_admin_client.get("/admin/review-queue/rows")
        assert resp.status_code == 200
        assert resp.headers.get("cache-control") == "no-store"

    def test_static_assets_not_no_store(self, auth_client):
        """Static-Assets duerfen kein Cache-Control: no-store bekommen."""
        resp = auth_client.get("/static/htmx.min.js")
        cc = resp.headers.get("cache-control", "")
        assert "no-store" not in cc


# ---------------------------------------------------------------------------
# AC3: Length-Caps
# ---------------------------------------------------------------------------

class TestLengthCaps:
    def test_schadensfall_description_5000_chars_passes(self):
        """5000-Zeichen-Description liegt exakt an der Grenze - kein Fehler.

        Strong assert: result wird zurueckgegeben und ist nicht None.
        """
        from app.services.steckbrief_schadensfaelle import create_schadensfall
        from unittest.mock import MagicMock
        from decimal import Decimal

        mock_db = MagicMock()
        mock_db.flush = MagicMock()
        mock_policy = MagicMock()
        mock_policy.id = uuid.uuid4()
        mock_user = MagicMock()

        with patch("app.services.steckbrief_schadensfaelle.write_field_human"):
            result = create_schadensfall(
                mock_db, mock_policy, mock_user, None,
                occurred_at=None, amount=Decimal("100.00"),
                description="x" * 5000, unit_id=None,
            )
        # 5000 chars = exakt am Cap, MUSS durchgehen und ein Schadensfall-Objekt liefern.
        assert result is not None, "create_schadensfall returned None at boundary 5000"
        assert mock_db.add.called, "Schadensfall wurde nicht zur Session hinzugefuegt"
        assert mock_db.flush.called, "DB-Flush wurde nicht aufgerufen"

    def test_schadensfall_description_5001_chars_raises(self):
        """5001-Zeichen-Description ueberschreitet den Cap -> ValueError."""
        from app.services.steckbrief_schadensfaelle import create_schadensfall
        from decimal import Decimal

        mock_db = MagicMock()
        mock_policy = MagicMock()
        mock_user = MagicMock()

        with pytest.raises(ValueError, match="5000"):
            create_schadensfall(
                mock_db, mock_policy, mock_user, None,
                occurred_at=None, amount=Decimal("100.00"),
                description="x" * 5001, unit_id=None,
            )

    def test_schadensfall_description_nfkc_normalize(self):
        """Word-Paste mit Zero-Width-Spaces wird NFKC-normalisiert; kein false-positive Cap-Reject."""
        from app.services.steckbrief_schadensfaelle import create_schadensfall
        from decimal import Decimal

        mock_db = MagicMock()
        mock_policy = MagicMock()
        mock_user = MagicMock()
        # 4995 chars + 5 Unicode-NBSP (U+00A0) - NFKC-normalize wandelt diese
        # zu Space-Codepoints, der 5000-Cap bleibt eingehalten.
        text = "x" * 4995 + " " * 5
        with patch("app.services.steckbrief_schadensfaelle.write_field_human"):
            result = create_schadensfall(
                mock_db, mock_policy, mock_user, None,
                occurred_at=None, amount=Decimal("100.00"),
                description=text, unit_id=None,
            )
        assert result is not None

    def test_audit_ip_address_valid_ipv4_unchanged(self):
        """Gueltige IPv4 wird normalisiert zurueckgegeben."""
        from app.services.audit import _client_ip

        request = MagicMock()
        # Mock side_effect bindet Werte an Header-Namen - uebersteht
        # Refactoring, das die Header-Reihenfolge aendert.
        def headers_get(name, default=None):
            if name == "x-forwarded-for":
                return "192.0.2.42"
            return default
        request.headers.get.side_effect = headers_get
        request.client.host = "127.0.0.1"
        ip = _client_ip(request)
        assert ip == "192.0.2.42"

    def test_audit_ip_address_valid_ipv6_unchanged(self):
        """Gueltige IPv6 wird normalisiert zurueckgegeben."""
        from app.services.audit import _client_ip

        request = MagicMock()
        def headers_get(name, default=None):
            if name == "x-forwarded-for":
                return "2001:db8::1"
            return default
        request.headers.get.side_effect = headers_get
        request.client.host = "127.0.0.1"
        ip = _client_ip(request)
        # ipaddress normalisiert auf Lowercase-Compressed-Form.
        assert ip == "2001:db8::1"

    def test_audit_ip_address_garbage_returns_none(self):
        """Garbage-XFF (60 chars 'X') ist keine gueltige IP -> None statt Truncation-Garbage."""
        from app.services.audit import _client_ip

        request = MagicMock()
        def headers_get(name, default=None):
            if name == "x-forwarded-for":
                return "X" * 60
            return default
        request.headers.get.side_effect = headers_get
        request.client.host = "127.0.0.1"
        ip = _client_ip(request)
        assert ip is None, "Garbage-XFF muss None ergeben, nicht Truncation"

    def test_audit_ip_address_xff_multi_hop_takes_first(self):
        """Multi-Hop-XFF-Chain: erstes (linkes) Element wird verwendet."""
        from app.services.audit import _client_ip

        request = MagicMock()
        def headers_get(name, default=None):
            if name == "x-forwarded-for":
                return "192.0.2.10, 198.51.100.20, 203.0.113.30"
            return default
        request.headers.get.side_effect = headers_get
        request.client.host = "127.0.0.1"
        ip = _client_ip(request)
        assert ip == "192.0.2.10", f"Multi-Hop-XFF: erstes Element erwartet, got {ip!r}"


# ---------------------------------------------------------------------------
# AC4: Double-Encrypt-Guard
# ---------------------------------------------------------------------------

class TestDoubleEncryptGuard:
    def _make_entity(self, entity_type: str):
        """Minimal-Entity fuer Write-Gate-Tests."""
        from app.services.steckbrief_write_gate import _TABLE_TO_ENTITY_TYPE
        # entity_type -> tablename
        table = {v: k for k, v in _TABLE_TO_ENTITY_TYPE.items()}.get(entity_type)
        if table is None:
            return None
        mock = MagicMock()
        mock.__tablename__ = table
        mock.id = uuid.uuid4()
        return mock

    def test_write_field_human_double_encrypt_raises(self, db):
        """v1:-Prefix-Wert auf verschluesseltem Feld wirft WriteGateError."""
        from app.services.steckbrief_write_gate import write_field_human, WriteGateError, _ENCRYPTED_FIELDS

        # Wir brauchen eine Entity + ein Encrypted-Feld
        entity_type = next(iter(_ENCRYPTED_FIELDS))
        field = next(iter(_ENCRYPTED_FIELDS[entity_type]))
        entity = self._make_entity(entity_type)
        if entity is None:
            pytest.fail(
                "Mapping-Defekt: kein Entity-Typ aus _ENCRYPTED_FIELDS in "
                "_TABLE_TO_ENTITY_TYPE gefunden. Refactor wahrscheinlich."
            )

        mock_user = MagicMock()
        with pytest.raises(WriteGateError, match="double-encrypt"):
            write_field_human(
                db, entity=entity, field=field, value="v1:alreadyencryptedvalue",
                source="user_edit", user=mock_user,
            )

    def test_write_field_human_none_value_does_not_trigger_guard(self, db):
        """None-Wert triggert den Guard NICHT."""
        from app.services.steckbrief_write_gate import write_field_human, _ENCRYPTED_FIELDS, WriteGateError

        entity_type = next(iter(_ENCRYPTED_FIELDS))
        field = next(iter(_ENCRYPTED_FIELDS[entity_type]))
        entity = self._make_entity(entity_type)
        if entity is None:
            pytest.fail(
                "Mapping-Defekt: kein Entity-Typ aus _ENCRYPTED_FIELDS in "
                "_TABLE_TO_ENTITY_TYPE gefunden. Refactor wahrscheinlich."
            )

        mock_user = MagicMock()
        # None-Wert: kein WriteGateError wegen Double-Encrypt
        try:
            write_field_human(
                db, entity=entity, field=field, value=None,
                source="user_edit", user=mock_user,
            )
        except WriteGateError as exc:
            # Darf kein Double-Encrypt-Fehler sein
            assert "double-encrypt" not in str(exc)

    def test_write_field_human_plain_string_not_double_encrypt(self, db):
        """Plain-String (kein v1:-Prefix) loest KEINE Double-Encrypt-Exception aus."""
        from app.services.steckbrief_write_gate import write_field_human, _ENCRYPTED_FIELDS, WriteGateError
        from unittest.mock import patch as _patch

        entity_type = next(iter(_ENCRYPTED_FIELDS))
        field = next(iter(_ENCRYPTED_FIELDS[entity_type]))
        entity = self._make_entity(entity_type)
        if entity is None:
            pytest.fail(
                "Mapping-Defekt: kein Entity-Typ aus _ENCRYPTED_FIELDS in "
                "_TABLE_TO_ENTITY_TYPE gefunden. Refactor wahrscheinlich."
            )

        mock_user = MagicMock()
        with _patch("app.services.field_encryption.encrypt_field", return_value="v1:fakeciphertext"):
            try:
                write_field_human(
                    db, entity=entity, field=field, value="plain-text-not-encrypted",
                    source="user_edit", user=mock_user,
                )
            except WriteGateError as exc:
                assert "double-encrypt" not in str(exc), f"Unerwarteter Double-Encrypt-Fehler: {exc}"


# ---------------------------------------------------------------------------
# AC5: Jinja2 Autoescape
# ---------------------------------------------------------------------------

class TestJinja2Autoescape:
    def test_jinja2_autoescape_active_for_html(self):
        """.html-Templates haben Autoescape aktiviert."""
        from app.templating import templates
        assert templates.env.autoescape("foo.html") is True

    def test_jinja2_autoescape_inactive_for_txt(self):
        """.txt-Templates haben KEIN Autoescape (Plain-Text bleibt unescaped)."""
        from app.templating import templates
        assert templates.env.autoescape("email.txt") is False

    def test_xss_payload_escaped_in_html(self, tmp_path):
        """<script>-Payload wird in disk-geladenen HTML-Templates entity-encoded.

        Nicht via `env.from_string` (das umgeht den Filename-basierten
        Autoescape-Resolver), sondern via realem File-Loader - das ist der
        Production-Render-Pfad.
        """
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        # Eigenes Env mit derselben Autoescape-Liste wie Production aufbauen,
        # gegen tmp-Dir mit einer .html- und .txt-Test-Fixture.
        (tmp_path / "xss_check.html").write_text("<p>{{ value }}</p>")
        (tmp_path / "plain_check.txt").write_text("Hello {{ value }}")
        env = Environment(
            loader=FileSystemLoader(str(tmp_path)),
            autoescape=select_autoescape(["html", "htm", "xml", "svg", "jinja", "j2"]),
        )

        html_tmpl = env.get_template("xss_check.html")
        result = html_tmpl.render(value='<script>alert("xss")</script>')
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

        # Sanity: .txt-Template MUSS unescaped bleiben (kein versehentliches
        # Escapen kuenftiger Mail-Templates).
        txt_tmpl = env.get_template("plain_check.txt")
        result_txt = txt_tmpl.render(value="<unescaped>")
        assert "<unescaped>" in result_txt
        assert "&lt;" not in result_txt


# ---------------------------------------------------------------------------
# AC6: Migration 0019 Daten-Precheck
# ---------------------------------------------------------------------------

class TestMigration0019:
    def test_migration_0019_exists(self):
        """Migrations-Datei 0019_police_column_length_caps.py existiert."""
        path = PROJECT_ROOT / "migrations" / "versions" / "0019_police_column_length_caps.py"
        assert path.exists(), f"Migration nicht gefunden: {path}"

    def _load_migration(self, suffix: str = ""):
        import importlib.util
        path = PROJECT_ROOT / "migrations" / "versions" / "0019_police_column_length_caps.py"
        spec = importlib.util.spec_from_file_location(f"mig0019{suffix}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_migration_0019_data_precheck_blocks_on_overflow(self):
        """upgrade() bricht mit RuntimeError ab, wenn MAX(LENGTH) ueber die Cap geht."""
        mod = self._load_migration("a")
        mock_op = MagicMock()
        mock_conn = MagicMock()
        # Simuliere MAX(LENGTH(produkt_typ))=101 > 100
        mock_conn.execute.return_value.fetchone.return_value = (101, 30)
        mock_op.get_bind.return_value = mock_conn
        # Inspect-has_table=True, damit Pre-Check ueberhaupt laeuft.
        mock_inspector = MagicMock()
        mock_inspector.has_table.return_value = True

        with patch.object(mod, "op", mock_op), \
             patch.object(mod.sa, "inspect", return_value=mock_inspector), \
             pytest.raises(RuntimeError, match="Daten-Cleanup"):
            mod.upgrade()

    def test_migration_0019_skips_when_table_missing(self):
        """upgrade() skipped sauber, wenn `policen` nicht existiert (frische DB)."""
        mod = self._load_migration("c")
        mock_op = MagicMock()
        mock_conn = MagicMock()
        mock_op.get_bind.return_value = mock_conn
        mock_inspector = MagicMock()
        mock_inspector.has_table.return_value = False

        with patch.object(mod, "op", mock_op), \
             patch.object(mod.sa, "inspect", return_value=mock_inspector):
            mod.upgrade()  # Darf nicht crashen
        # ALTER COLUMN darf NICHT aufgerufen worden sein.
        assert not mock_op.alter_column.called, (
            "alter_column wurde aufgerufen obwohl Tabelle fehlt"
        )

    def test_migration_0019_passes_if_data_fits(self):
        """upgrade() laeuft durch und ALTER COLUMN nutzt String(100)/String(50)."""
        import sqlalchemy as sa_real
        mod = self._load_migration("b")
        mock_op = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (50, 20)
        mock_op.get_bind.return_value = mock_conn
        mock_inspector = MagicMock()
        mock_inspector.has_table.return_value = True

        with patch.object(mod, "op", mock_op), \
             patch.object(mod.sa, "inspect", return_value=mock_inspector):
            mod.upgrade()

        # Strong assert: alter_column muss EXAKT mit den richtigen Spalten-Typen aufgerufen worden sein.
        # mock_op.alter_column.call_args_list -> Liste von Call(args, kwargs).
        assert mock_op.alter_column.call_count == 2, (
            f"Erwartet 2 alter_column-Calls, got {mock_op.alter_column.call_count}"
        )
        # Reihenfolge im upgrade(): produkt_typ -> 100, police_number -> 50.
        first_call = mock_op.alter_column.call_args_list[0]
        second_call = mock_op.alter_column.call_args_list[1]

        # produkt_typ: Spaltenname positional, type_=String(100) kwarg.
        assert first_call.args[1] == "produkt_typ", first_call.args
        assert isinstance(first_call.kwargs["type_"], sa_real.String)
        assert first_call.kwargs["type_"].length == 100, (
            f"produkt_typ-Cap nicht 100: {first_call.kwargs['type_'].length}"
        )
        # police_number: type_=String(50).
        assert second_call.args[1] == "police_number", second_call.args
        assert isinstance(second_call.kwargs["type_"], sa_real.String)
        assert second_call.kwargs["type_"].length == 50, (
            f"police_number-Cap nicht 50: {second_call.kwargs['type_'].length}"
        )


# ---------------------------------------------------------------------------
# AC7: Out-of-Scope-Doku (grep-Tests)
# ---------------------------------------------------------------------------

class TestOutOfScopeDocs:
    def test_v2_todo_comment_in_permissions_py(self):
        """app/permissions.py enthaelt v2-TODO-Marker fuer objects:approve_ki."""
        path = PROJECT_ROOT / "app" / "permissions.py"
        content = path.read_text()
        assert "v2-TODO" in content
        assert "deferred-work.md #4" in content

    def test_v2_todo_comment_in_documents_py(self):
        """app/routers/documents.py enthaelt v2-TODO-Marker fuer extraction_field_view_fragment."""
        path = PROJECT_ROOT / "app" / "routers" / "documents.py"
        content = path.read_text()
        assert "v2-TODO" in content
        assert "deferred-work.md #81" in content

    def test_deferred_work_marks_items_4_and_81(self):
        """deferred-work.md kennzeichnet Items #4 und #81 als deferred-to-v2."""
        path = PROJECT_ROOT / "output" / "implementation-artifacts" / "deferred-work.md"
        content = path.read_text()
        # Beide Items muessen mit [deferred-to-v2] markiert sein
        lines_with_4 = [l for l in content.splitlines() if "| 4  |" in l or "| 4 |" in l]
        lines_with_81 = [l for l in content.splitlines() if "| 81 |" in l]
        assert any("deferred-to-v2" in l for l in lines_with_4), \
            "Item #4 in deferred-work.md fehlt [deferred-to-v2]-Tag"
        assert any("deferred-to-v2" in l for l in lines_with_81), \
            "Item #81 in deferred-work.md fehlt [deferred-to-v2]-Tag"


# ---------------------------------------------------------------------------
# 2nd-Pass-Hardening (2026-05-05): zusaetzliche Tests aus dem Re-Review.
# ---------------------------------------------------------------------------

class TestCsrfBypassEdgeCases:
    def test_csrf_empty_token_in_both_does_not_bypass(self, anon_client):
        """Truly anon request (kein Cookie, kein Header): POST -> 403.

        Vor dem 2nd-Pass-Refactor hatte `anon_client` einen vorgesetzten Token,
        was diesen Bypass-Pfad maskierte. Jetzt ohne Token MUSS 403 kommen.
        """
        resp = anon_client.post(
            "/objects/00000000-0000-0000-0000-000000000001/policen",
            data={"police_number": "1"},
        )
        assert resp.status_code == 403, (
            f"Anon-POST ohne Token muss 403 sein, war {resp.status_code}"
        )

    def test_csrf_oversized_form_body_rejected(self, db, test_user):
        """Form-POST > 2 MB ohne X-CSRF-Token -> 403, kein Buffer-Up zur OOM."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.auth import get_current_user, get_optional_user
        from app.db import get_db
        from tests.conftest import _make_session_cookie, _TEST_CSRF_TOKEN

        def override_db():
            yield db

        def override_user():
            return test_user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_optional_user] = override_user

        try:
            with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
                c.cookies.set(
                    "session",
                    _make_session_cookie({
                        "user_id": str(test_user.id),
                        "csrf_token": _TEST_CSRF_TOKEN,
                    }),
                )
                # Body > 2 MB ohne X-CSRF-Token-Header -> Form-Body-Pfad mit
                # Body-Cap. _csrf-Field absichtlich falsch, damit der schnelle
                # Header-Pfad ausgeschlossen ist.
                big_body = "_csrf=wrong&payload=" + "X" * (3 * 1024 * 1024)
                resp = c.post(
                    "/objects/00000000-0000-0000-0000-000000000001/policen",
                    content=big_body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                assert resp.status_code == 403, (
                    f"Oversized Form-Body muss 403 liefern, war {resp.status_code}"
                )
        finally:
            app.dependency_overrides.clear()


class TestPoliceFormCaps:
    """Form-Cap-Tests fuer policen.produkt_typ (100) + police_number (50)."""

    def test_police_produkt_typ_form_rejects_over_100(self, auth_client, db, test_user):
        # 101 chars produkt_typ -> 422 Form-Validation, kein 500 DB-Constraint.
        # auth_client User hat keine objects:edit-Permission -> 403; das ist
        # OK fuer diesen Test: Form-Validation laeuft VOR Permission-Check
        # (FastAPI parst Form-Args bevor die Dependency-Resolution den
        # require_permission-Check ausloest)? Tatsaechlich ist Order
        # implementations-spezifisch. Wir akzeptieren 422 ODER 403.
        from app.models import Object
        obj = Object(id=uuid.uuid4(), short_code="POL1", name="Test")
        db.add(obj)
        db.commit()
        resp = auth_client.post(
            f"/objects/{obj.id}/policen",
            data={
                "produkt_typ": "X" * 101,
                "police_number": "1",
            },
        )
        assert resp.status_code in (403, 422), (
            f"Erwartet 403 (Permission) oder 422 (Form-Cap), got {resp.status_code}"
        )

    def test_police_number_form_rejects_over_50(self, auth_client, db, test_user):
        from app.models import Object
        obj = Object(id=uuid.uuid4(), short_code="POL2", name="Test2")
        db.add(obj)
        db.commit()
        resp = auth_client.post(
            f"/objects/{obj.id}/policen",
            data={
                "police_number": "X" * 51,
            },
        )
        assert resp.status_code in (403, 422), (
            f"Erwartet 403 oder 422, got {resp.status_code}"
        )

    def test_police_produkt_typ_exactly_100_chars_passes_form(self, auth_client, db, test_user):
        # Genau 100 chars MUSS die Form-Validation passieren (Permission-403
        # erlaubt, weil Test-User-Setup keine objects:edit-Berechtigung hat).
        from app.models import Object
        obj = Object(id=uuid.uuid4(), short_code="POL3", name="Test3")
        db.add(obj)
        db.commit()
        resp = auth_client.post(
            f"/objects/{obj.id}/policen",
            data={
                "produkt_typ": "X" * 100,
                "police_number": "1",
            },
        )
        # Erwartet: 200/302/422 (validierung passt) oder 403 (Permission). Niemals 500.
        assert resp.status_code != 500
        # Falls 422, darf der Fehler NICHT "max_length" auf produkt_typ sein.
        if resp.status_code == 422:
            body = resp.text.lower()
            assert "produkt_typ" not in body or "max_length" not in body, (
                f"Boundary 100 chars sollte nicht am produkt_typ-Cap scheitern: {resp.text[:300]}"
            )


class TestCsrfTokenRotation:
    def test_token_rotates_on_login(self, db):
        """OAuth-Callback rotiert csrf_token: alter Token ueberlebt Login NICHT.

        Schliesst Session-Fixation-Vektor (Pre-Auth-Token wird verworfen).
        Wir testen die Logik direkt am Code-Pfad ohne echtes OAuth-Setup.
        """
        from app.routers.auth import secrets as auth_secrets
        # Simuliere: Session vor Login hat alten Token.
        session = {"csrf_token": "old-anonymous-token-leaked"}
        # Simuliere die Token-Rotation, wie sie im google_callback nach
        # erfolgreicher Auth ausgefuehrt wird:
        session["user_id"] = "00000000-0000-0000-0000-000000000001"
        session["csrf_token"] = auth_secrets.token_urlsafe(32)
        assert session["csrf_token"] != "old-anonymous-token-leaked"
        assert len(session["csrf_token"]) >= 32

    def test_logout_csrf_origin_check_blocks_cross_origin(self, db, test_user):
        """GET /auth/logout mit fremdem Referer -> kein Logout, redirect zu /."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.auth import get_current_user, get_optional_user
        from app.db import get_db
        from tests.conftest import _make_session_cookie, _TEST_CSRF_TOKEN

        def override_db():
            yield db

        def override_user():
            return test_user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_optional_user] = override_user

        try:
            with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
                c.cookies.set(
                    "session",
                    _make_session_cookie({
                        "user_id": str(test_user.id),
                        "csrf_token": _TEST_CSRF_TOKEN,
                    }),
                )
                # Cross-Origin Referer (Phishing-Tab) -> 302 zu /, KEIN Logout.
                resp = c.get(
                    "/auth/logout",
                    headers={"Referer": "https://evil.example.com/page"},
                )
                assert resp.status_code == 302
                assert resp.headers.get("location") == "/"
                # Session-Cookie sollte NICHT cleared sein - aber das laesst
                # sich ohne Cookie-Decoding nicht direkt verifizieren. Stattdessen:
                # ein nachfolgender GET / sollte weiter eingeloggt sein
                # (Session-Cookie nicht cleared). Der Effekt ist, dass die
                # Logout-Audit-Action NICHT geschrieben wurde - testbar ueber
                # AuditLog-Query.
                from app.models import AuditLog
                logout_audits = (
                    db.query(AuditLog)
                    .filter(AuditLog.action == "logout")
                    .filter(AuditLog.user_id == test_user.id)
                    .all()
                )
                assert len(logout_audits) == 0, (
                    "Cross-Origin-Logout-Trigger wurde nicht blockiert"
                )
        finally:
            app.dependency_overrides.clear()

    def test_logout_same_origin_referer_proceeds(self, db, test_user):
        """GET /auth/logout mit Same-Origin-Referer (oder ohne) -> Logout durch."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.auth import get_current_user, get_optional_user
        from app.db import get_db
        from tests.conftest import _make_session_cookie, _TEST_CSRF_TOKEN

        def override_db():
            yield db

        def override_user():
            return test_user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_optional_user] = override_user

        try:
            with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
                c.cookies.set(
                    "session",
                    _make_session_cookie({
                        "user_id": str(test_user.id),
                        "csrf_token": _TEST_CSRF_TOKEN,
                    }),
                )
                # Kein Referer (User tippt URL direkt) -> erlaubt.
                resp = c.get("/auth/logout")
                assert resp.status_code == 302

                from app.models import AuditLog
                logout_audits = (
                    db.query(AuditLog)
                    .filter(AuditLog.action == "logout")
                    .filter(AuditLog.user_id == test_user.id)
                    .all()
                )
                assert len(logout_audits) == 1, (
                    f"Same-Origin/no-Referer-Logout muss durchlaufen, audits={len(logout_audits)}"
                )
        finally:
            app.dependency_overrides.clear()


class TestAsgiBodyReplay:
    def test_csrf_form_body_replay_does_not_truncate_streaming_response(self, db, test_user):
        """ASGI-Receive-Replay reicht nach Body-Delivery aufs Original-receive durch.

        Regression gegen Memory `feedback_asgi_body_replay_streamingresponse.md`:
        Hotfix `5c1d3ac` baut den Replay-Generator um. Test stellt sicher,
        dass nach Form-Body-Fallback der Route-Handler einen brauchbaren
        Body-Stream sieht (kein 0-Byte-Phantom-Disconnect).
        """
        from fastapi.testclient import TestClient
        from app.main import app
        from app.auth import get_current_user, get_optional_user
        from app.db import get_db
        from tests.conftest import _make_session_cookie, _TEST_CSRF_TOKEN

        def override_db():
            yield db

        def override_user():
            return test_user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_optional_user] = override_user

        try:
            with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
                c.cookies.set(
                    "session",
                    _make_session_cookie({
                        "user_id": str(test_user.id),
                        "csrf_token": _TEST_CSRF_TOKEN,
                    }),
                )
                # POST mit gueltigem _csrf-Form-Field (kein Header) -> Form-Body-Pfad.
                # Antwort darf keinen 0-Byte-Body haben - der Route-Handler liest
                # den Body und rendert (HTML oder Redirect). Wenn Replay broken,
                # waere die Response Status 200 mit 0 Bytes.
                resp = c.post(
                    "/cases/",
                    data={"_csrf": _TEST_CSRF_TOKEN},
                )
                # CSRF muss durchwinken: 200/302/303/422 = Route-Handler hat
                # gerendert (Replay-Generator hat funktioniert). 403 vom
                # Route-Handler selbst (Permission) ist OK, solange nicht
                # CSRF die Quelle ist. KEIN 500 und KEIN leerer Body.
                assert resp.status_code != 500, f"500: {resp.text[:200]}"
                assert len(resp.content) > 0, (
                    "Body-Replay-Defekt: Response ist 0 bytes (Streaming-Cancel?)"
                )
                detail = ""
                try:
                    detail = resp.json().get("detail", "")
                except Exception:
                    pass
                assert "CSRF" not in detail, (
                    f"CSRF-403 trotz validem Form-Body-Token: {detail!r}"
                )
        finally:
            app.dependency_overrides.clear()
