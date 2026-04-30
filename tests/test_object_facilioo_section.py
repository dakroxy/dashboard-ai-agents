"""Story 4.4 — Tests fuer Facilioo-Vorgaenge-Sektion am Objekt-Detail."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

import app.config
import app.routers.objects
from app.models import AuditLog, Object, User
from app.models.facilioo import FaciliooTicket
from tests.conftest import _TestSessionLocal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_object(db) -> Object:
    obj = Object(id=uuid.uuid4(), short_code="TST44", name="Testobjekt 4.4")
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _make_ticket(
    db,
    *,
    object_id: uuid.UUID,
    status: str = "open",
    title: str = "Defekt",
    days_ago: int = 0,
    is_archived: bool = False,
) -> FaciliooTicket:
    t = FaciliooTicket(
        id=uuid.uuid4(),
        object_id=object_id,
        facilioo_id=str(uuid.uuid4()),
        status=status,
        title=title,
        is_archived=is_archived,
        raw_payload={"contactName": "Max Mustermann"},
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_audit_finished(
    db,
    *,
    minutes_ago: int = 5,
    job: str = "facilioo_ticket_mirror",
) -> AuditLog:
    entry = AuditLog(
        id=uuid.uuid4(),
        user_email="system",
        action="sync_finished",
        details_json={"job": job, "run_id": str(uuid.uuid4())},
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.add(entry)
    db.commit()
    return entry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def view_only_client(db):
    """Client mit objects:view aber OHNE objects:view_confidential."""
    from fastapi.testclient import TestClient
    from app.auth import get_current_user, get_optional_user
    from app.db import get_db
    from app.main import app

    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-view-only",
        email="view-only@dbshome.de",
        name="View Only",
        permissions_extra=["objects:view"],
    )
    db.add(user)
    db.commit()

    def override_db():
        yield db

    def override_user():
        return user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def full_access_client(db):
    """Client mit objects:view + objects:view_confidential."""
    from fastapi.testclient import TestClient
    from app.auth import get_current_user, get_optional_user
    from app.db import get_db
    from app.main import app

    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-full-access",
        email="full-access@dbshome.de",
        name="Full Access",
        permissions_extra=["objects:view", "objects:view_confidential"],
    )
    db.add(user)
    db.commit()

    def override_db():
        yield db

    def override_user():
        return user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        yield c

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# AC1 — Tabelle + Links
# ---------------------------------------------------------------------------

def test_section_renders_open_tickets_with_link_to_facilioo(db, view_only_client, monkeypatch):
    monkeypatch.setattr(app.config.settings, "facilioo_mirror_enabled", True)
    _make_audit_finished(db, minutes_ago=5)
    obj = _make_object(db)
    t1 = _make_ticket(db, object_id=obj.id, title="Wasserrohrbruch")
    t2 = _make_ticket(db, object_id=obj.id, title="Fenster kaputt")
    t3 = _make_ticket(db, object_id=obj.id, title="Aufzug defekt")

    resp = view_only_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text
    assert "Wasserrohrbruch" in body
    assert "Fenster kaputt" in body
    assert "Aufzug defekt" in body
    assert f"https://app.facilioo.de/tickets/{t1.facilioo_id}" in body
    assert f"https://app.facilioo.de/tickets/{t2.facilioo_id}" in body
    assert f"https://app.facilioo.de/tickets/{t3.facilioo_id}" in body


def test_section_caps_at_10_with_extra_hint(db, view_only_client, monkeypatch):
    monkeypatch.setattr(app.config.settings, "facilioo_mirror_enabled", True)
    _make_audit_finished(db, minutes_ago=5)
    obj = _make_object(db)
    for i in range(12):
        _make_ticket(db, object_id=obj.id, title=f"Ticket {i}", days_ago=i)

    resp = view_only_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text
    assert "Weitere offene" in body
    # Genau 10 Titelzeilen: Ticket 0..9 (sortiert nach created_at DESC, neueste zuerst).
    # Cap-Bruch (12 statt 10) wuerde durch `>= 10` nicht erkannt — daher
    # explizit pruefen: alle Titles 0..9 vorhanden, 10/11 fehlen.
    for i in range(10):
        assert f"Ticket {i}\n" in body or f"Ticket {i}<" in body, (
            f"Ticket {i} fehlt im Body"
        )
    assert "Ticket 10" not in body
    assert "Ticket 11" not in body


def test_section_filters_archived_tickets(db, view_only_client, monkeypatch):
    monkeypatch.setattr(app.config.settings, "facilioo_mirror_enabled", True)
    _make_audit_finished(db, minutes_ago=5)
    obj = _make_object(db)
    _make_ticket(db, object_id=obj.id, title="Sichtbares Ticket")
    _make_ticket(db, object_id=obj.id, title="Archiviertes Ticket", is_archived=True)

    resp = view_only_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text
    assert "Sichtbares Ticket" in body
    assert "Archiviertes Ticket" not in body


def test_section_filters_closed_tickets(db, view_only_client, monkeypatch):
    monkeypatch.setattr(app.config.settings, "facilioo_mirror_enabled", True)
    _make_audit_finished(db, minutes_ago=5)
    obj = _make_object(db)
    _make_ticket(db, object_id=obj.id, title="Offenes Ticket", status="open")
    _make_ticket(db, object_id=obj.id, title="Geschlossenes Ticket", status="closed")
    _make_ticket(db, object_id=obj.id, title="Erledigtes Ticket", status="resolved")

    resp = view_only_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text
    assert "Offenes Ticket" in body
    assert "Geschlossenes Ticket" not in body
    assert "Erledigtes Ticket" not in body


def test_section_empty_state_when_zero_open_tickets_but_mirror_ran(db, view_only_client, monkeypatch):
    monkeypatch.setattr(app.config.settings, "facilioo_mirror_enabled", True)
    _make_audit_finished(db, minutes_ago=5)
    obj = _make_object(db)
    # Kein Ticket fuer dieses Objekt → Empty-State, NICHT Placeholder

    resp = view_only_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text
    assert "Keine offenen Vorgänge in Facilioo." in body
    assert "Ticket-Integration in Vorbereitung." not in body


# ---------------------------------------------------------------------------
# AC2 — Stale-Banner
# ---------------------------------------------------------------------------

def test_stale_banner_renders_after_threshold(db, view_only_client, monkeypatch):
    monkeypatch.setattr(app.config.settings, "facilioo_mirror_enabled", True)
    _make_audit_finished(db, minutes_ago=15)
    obj = _make_object(db)
    _make_ticket(db, object_id=obj.id, title="Ticket")

    resp = view_only_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text
    assert "bg-amber-50" in body
    assert "vor 15 Minuten" in body


def test_no_stale_banner_within_threshold(db, view_only_client, monkeypatch):
    monkeypatch.setattr(app.config.settings, "facilioo_mirror_enabled", True)
    _make_audit_finished(db, minutes_ago=5)
    obj = _make_object(db)
    _make_ticket(db, object_id=obj.id, title="Ticket")

    resp = view_only_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text
    # bg-amber-50 erscheint auch in anderen Sektionen (_obj_stammdaten) —
    # spezifischer pruefen ob das Facilioo-Banner fehlt.
    assert "Letzte Aktualisierung" not in body


def test_stale_hint_format_minutes_hours_days():
    from app.services.facilioo_tickets import format_stale_hint

    base = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
    cases = [
        (5, None),
        (11, "vor 11 Minuten"),
        (60, "vor 1 Stunde"),
        (125, "vor 2 Stunden"),
        (1440, "vor 1 Tag"),
        (2880, "vor 2 Tagen"),
    ]
    for mins, expected in cases:
        last_sync = base - timedelta(minutes=mins)
        result = format_stale_hint(last_sync, now=base)
        assert result == expected, f"minutes={mins}: erwartet {expected!r}, erhalten {result!r}"


def test_stale_query_error_is_swallowed(db, view_only_client, monkeypatch):
    monkeypatch.setattr(app.config.settings, "facilioo_mirror_enabled", True)
    obj = _make_object(db)
    _make_ticket(db, object_id=obj.id, title="Ticket bleibt sichtbar")

    # get_last_facilioo_sync soll werfen — Seite darf trotzdem rendern
    def _raise(db):
        raise RuntimeError("DB simuliert Down")

    monkeypatch.setattr(app.routers.objects, "get_last_facilioo_sync", _raise)

    resp = view_only_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text
    assert "Ticket bleibt sichtbar" in body
    # bg-amber-50 kann von anderen Sektionen kommen; Facilioo-Banner pruefen via Text
    assert "Letzte Aktualisierung" not in body


# ---------------------------------------------------------------------------
# AC3 — Platzhalter
# ---------------------------------------------------------------------------

def test_placeholder_when_mirror_disabled(db, view_only_client):
    # facilioo_mirror_enabled=False ist der Default in Tests (conftest env)
    obj = _make_object(db)
    _make_ticket(db, object_id=obj.id, title="Soll nicht sichtbar sein")

    resp = view_only_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text
    assert "Ticket-Integration in Vorbereitung." in body
    assert "Soll nicht sichtbar sein" not in body


def test_placeholder_when_no_tickets_and_no_sync_history(db, view_only_client, monkeypatch):
    monkeypatch.setattr(app.config.settings, "facilioo_mirror_enabled", True)
    obj = _make_object(db)
    # Keine Tickets, kein sync_finished-Audit → Placeholder

    resp = view_only_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    assert "Ticket-Integration in Vorbereitung." in resp.text


def test_no_placeholder_when_mirror_ran_but_object_has_zero_tickets(db, view_only_client, monkeypatch):
    monkeypatch.setattr(app.config.settings, "facilioo_mirror_enabled", True)
    _make_audit_finished(db, minutes_ago=5)
    obj = _make_object(db)
    # Kein Ticket fuer dieses Objekt, aber Mirror lief → Empty-State, NICHT Placeholder

    resp = view_only_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text
    assert "Keine offenen Vorgänge in Facilioo." in body
    assert "Ticket-Integration in Vorbereitung." not in body


# ---------------------------------------------------------------------------
# AC4 — Permissions
# ---------------------------------------------------------------------------

def test_section_visible_with_view_only_permission(db, view_only_client, monkeypatch):
    monkeypatch.setattr(app.config.settings, "facilioo_mirror_enabled", True)
    _make_audit_finished(db, minutes_ago=5)
    obj = _make_object(db)
    _make_ticket(db, object_id=obj.id, title="Vorgaenge-Ticket")

    resp = view_only_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text
    assert 'data-section="vorgaenge"' in body
    assert "Vorgänge (Facilioo)" in body
    # Menschen-Sektion ist NICHT sichtbar ohne view_confidential
    assert 'data-section="menschen"' not in body


def test_section_does_not_appear_in_menschen_block(db, full_access_client, monkeypatch):
    monkeypatch.setattr(app.config.settings, "facilioo_mirror_enabled", True)
    _make_audit_finished(db, minutes_ago=5)
    obj = _make_object(db)
    _make_ticket(db, object_id=obj.id, title="Nur im Vorgaenge-Block")

    resp = full_access_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text

    # Beide Sektionen vorhanden
    assert 'data-section="vorgaenge"' in body
    assert 'data-section="menschen"' in body

    # Ticket-Inhalt erscheint im vorgaenge-Block, nicht im menschen-Block
    vorgaenge_start = body.find('data-section="vorgaenge"')
    vorgaenge_end = body.find('data-section="menschen"')
    assert vorgaenge_start != -1
    assert vorgaenge_end != -1
    vorgaenge_block = body[vorgaenge_start:vorgaenge_end]
    assert "Nur im Vorgaenge-Block" in vorgaenge_block

    menschen_start = body.find('data-section="menschen"')
    menschen_block = body[menschen_start:]
    assert "Nur im Vorgaenge-Block" not in menschen_block


# ---------------------------------------------------------------------------
# Unit-Test: URL-Helper
# ---------------------------------------------------------------------------

def test_facilioo_ticket_url_helper_format():
    from app.services.facilioo_tickets import facilioo_ticket_url

    assert facilioo_ticket_url("ABC123") == "https://app.facilioo.de/tickets/ABC123"
    assert facilioo_ticket_url(None) == "#"
    assert facilioo_ticket_url("") == "#"
