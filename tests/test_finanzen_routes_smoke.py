"""Story 1.5 — Route-Smoke-Tests fuer die Finanzen-Sektion auf /objects/{id}.

Mockt `app.routers.objects.get_bank_balance` (kein echter Impower-Call;
Memory `reference_impower_api` haelt fest, dass es keinen Sandbox-Tenant
gibt). Verifiziert AC1 (Sektion gerendert + Live-Saldo + Sparkline),
AC2 (Graceful Fallback), AC3 (Write-Gate-Persistierung), AC4 (kein
Live-Pull ohne impower_property_id).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import FieldProvenance, Object, User
from app.services.steckbrief_write_gate import write_field_human


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def steckbrief_admin_user(db):
    """Reuse des steckbrief_admin_client-Users — fuer write_field_human-Aufrufe
    in Test-Setups, die einen User brauchen (z. B. user_edit-Provenance)."""
    user = db.query(User).filter(
        User.email == "steckbrief-admin@dbshome.de"
    ).first()
    if user is not None:
        return user
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-admin-finanzen-helper",
        email="steckbrief-admin@dbshome.de",
        name="Steckbrief Admin",
        permissions_extra=[
            "objects:view",
            "objects:edit",
            "objects:approve_ki",
            "objects:view_confidential",
            "registries:view",
            "registries:edit",
            "audit_log:view",
        ],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def make_finanzen_object(db):
    """Liefert einen Konstruktor fuer Objekte mit / ohne impower_property_id."""
    def _make(short_code: str, *, impower_property_id: str | None = None) -> Object:
        obj = Object(
            id=uuid.uuid4(),
            short_code=short_code,
            name=f"Finanzen-Objekt {short_code}",
            impower_property_id=impower_property_id,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj
    return _make


def _patch_get_bank_balance(monkeypatch, return_value):
    """Setzt einen async Mock fuer `get_bank_balance` im Router."""
    async def _fake(property_id: str):  # noqa: ARG001
        return return_value
    monkeypatch.setattr("app.routers.objects.get_bank_balance", _fake)


# ---------------------------------------------------------------------------
# AC4 — Kein Live-Pull ohne impower_property_id
# ---------------------------------------------------------------------------

def test_object_detail_finance_section_no_impower_id(
    db, steckbrief_admin_client, make_finanzen_object, monkeypatch
):
    obj = make_finanzen_object("FIN1", impower_property_id=None)

    called = {"n": 0}
    async def _fake(property_id: str):  # noqa: ARG001
        called["n"] += 1
        return {"balance": Decimal("1.00"), "currency": "EUR", "fetched_at": datetime.now(timezone.utc)}
    monkeypatch.setattr("app.routers.objects.get_bank_balance", _fake)

    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    body = response.text

    # Hinweistext im Saldo-Block
    assert "Kein Impower-Objekt verknuepft" in body
    # get_bank_balance wurde NICHT aufgerufen
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# AC1 + AC3 — Live-Pull-Erfolg + Persistierung via Write-Gate
# ---------------------------------------------------------------------------

def test_object_detail_finance_section_live_balance_success(
    db, steckbrief_admin_client, make_finanzen_object, monkeypatch
):
    obj = make_finanzen_object("FIN2", impower_property_id="HAM61")
    fixed_dt = datetime(2026, 4, 22, 13, 30, tzinfo=timezone.utc)
    _patch_get_bank_balance(
        monkeypatch,
        {"balance": Decimal("1234.56"), "currency": "EUR", "fetched_at": fixed_dt},
    )

    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    body = response.text

    assert "1234.56 EUR" in body
    assert 'data-section="finanzen"' in body
    assert 'data-balance-error="false"' in body
    assert "Stand:" in body
    assert "(Europe/Berlin)" in body

    # AC3: Write-Gate hat geschrieben → DB + Provenance-Row
    db.expire_all()
    refreshed = db.get(Object, obj.id)
    assert refreshed.last_known_balance == Decimal("1234.56")

    prov = (
        db.query(FieldProvenance)
        .filter(
            FieldProvenance.entity_type == "object",
            FieldProvenance.entity_id == obj.id,
            FieldProvenance.field_name == "last_known_balance",
        )
        .all()
    )
    assert len(prov) == 1
    assert prov[0].source == "impower_mirror"
    assert prov[0].source_ref == "HAM61"
    assert prov[0].user_id is None


# ---------------------------------------------------------------------------
# AC2 — Fallback bei Impower-Ausfall (Live-Pull liefert None)
# ---------------------------------------------------------------------------

def test_object_detail_finance_section_live_balance_fallback(
    db, steckbrief_admin_client, make_finanzen_object, monkeypatch,
    steckbrief_admin_user,
):
    obj = make_finanzen_object("FIN3", impower_property_id="HAM61")
    # Vorheriger bekannter Saldo (via Write-Gate, damit DB + Provenance konsistent).
    write_field_human(
        db, entity=obj, field="last_known_balance",
        value=Decimal("999.50"), source="impower_mirror", user=None,
        source_ref="HAM61",
    )
    db.commit()

    _patch_get_bank_balance(monkeypatch, None)

    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    body = response.text

    # Stammdaten-Sektion immer noch sichtbar (AC2 — Seite kein 500)
    assert "Stammdaten" in body
    # Fallback-Text + bekannter Saldo
    assert "Saldo aktuell nicht verfuegbar" in body
    assert "Zuletzt:" in body
    assert "999.50" in body
    assert 'data-balance-error="true"' in body


def test_object_detail_finance_section_live_balance_fallback_no_history(
    db, steckbrief_admin_client, make_finanzen_object, monkeypatch
):
    """Wenn weder Live-Pull noch `last_known_balance` Werte liefern, zeigt der
    Saldo-Block den Em-Dash-Placeholder + den Fehlertext."""
    obj = make_finanzen_object("FIN3B", impower_property_id="HAM61")
    _patch_get_bank_balance(monkeypatch, None)

    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    body = response.text
    assert "Saldo aktuell nicht verfuegbar" in body
    assert "&mdash;" in body


# ---------------------------------------------------------------------------
# AC2 — Commit-Fehler darf keinen 500er werfen
# ---------------------------------------------------------------------------

def test_object_detail_finance_section_commit_failure_no_500(
    db, steckbrief_admin_client, make_finanzen_object, monkeypatch
):
    obj = make_finanzen_object("FIN4", impower_property_id="HAM61")
    fixed_dt = datetime(2026, 4, 22, 13, 30, tzinfo=timezone.utc)
    _patch_get_bank_balance(
        monkeypatch,
        {"balance": Decimal("123.45"), "currency": "EUR", "fetched_at": fixed_dt},
    )

    # Erster Commit-Aufruf in der Request-Verarbeitung wirft. Subsequente
    # Commits (z. B. der Test-Cleanup) laufen normal weiter.
    original_commit = db.commit
    state = {"failed": False}
    def failing_commit():
        if not state["failed"]:
            state["failed"] = True
            raise RuntimeError("synthetic commit failure")
        return original_commit()
    monkeypatch.setattr(db, "commit", failing_commit)

    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    body = response.text

    # Kein 500, Saldo ist noch im HTML (live_balance war gesetzt vor write).
    assert "123.45" in body
    # Stammdaten-Sektion weiterhin sichtbar (AC2)
    assert "Stammdaten" in body
    # balance_error im Template-Marker reflektiert
    assert 'data-balance-error="true"' in body


# ---------------------------------------------------------------------------
# AC3 Ausnahme — Mirror-Guard schuetzt user_edit auf last_known_balance
# ---------------------------------------------------------------------------

def test_last_known_balance_user_edit_wins(
    db, steckbrief_admin_client, make_finanzen_object, monkeypatch,
    steckbrief_admin_user,
):
    """Wenn die letzte Provenance-Row fuer last_known_balance den Source
    `user_edit` traegt, darf der Live-Pull-Wert NICHT die DB-Spalte
    ueberschreiben (Mirror-Guard). Die UI zeigt trotzdem den Live-Wert
    fuer diesen Request — er ist nur nicht persistiert.
    """
    obj = make_finanzen_object("FIN5", impower_property_id="HAM61")
    # Existing user_edit setzt sowohl DB-Spalte als auch Provenance.
    write_field_human(
        db, entity=obj, field="last_known_balance",
        value=Decimal("999.00"), source="user_edit", user=steckbrief_admin_user,
    )
    db.commit()

    fixed_dt = datetime(2026, 4, 22, 13, 30, tzinfo=timezone.utc)
    _patch_get_bank_balance(
        monkeypatch,
        {"balance": Decimal("1234.56"), "currency": "EUR", "fetched_at": fixed_dt},
    )

    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    # UI zeigt den Live-Wert (kein Persistenz-Schritt vor dem Render)
    assert "1234.56" in response.text

    # DB bleibt UNVERAENDERT — der Mirror-Guard hat geblockt.
    db.expire_all()
    refreshed = db.get(Object, obj.id)
    assert refreshed.last_known_balance == Decimal("999.00")

    # Genau eine Provenance-Row (die urspruengliche user_edit), kein
    # zusaetzlicher impower_mirror-Eintrag.
    prov = (
        db.query(FieldProvenance)
        .filter(
            FieldProvenance.entity_type == "object",
            FieldProvenance.entity_id == obj.id,
            FieldProvenance.field_name == "last_known_balance",
        )
        .all()
    )
    assert len(prov) == 1
    assert prov[0].source == "user_edit"


# ---------------------------------------------------------------------------
# AC1 — Timestamp wird korrekt nach Europe/Berlin formatiert
# ---------------------------------------------------------------------------

def test_object_detail_finance_section_timestamp_europe_berlin(
    db, steckbrief_admin_client, make_finanzen_object, monkeypatch
):
    """fetched_at = 2026-04-22T15:30 UTC → MESZ (DST aktiv) = 17:30."""
    obj = make_finanzen_object("FIN6", impower_property_id="HAM61")
    fixed_dt = datetime(2026, 4, 22, 15, 30, tzinfo=timezone.utc)
    _patch_get_bank_balance(
        monkeypatch,
        {"balance": Decimal("1.00"), "currency": "EUR", "fetched_at": fixed_dt},
    )

    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    body = response.text
    assert "22.04.2026 17:30" in body
    assert "(Europe/Berlin)" in body


# ---------------------------------------------------------------------------
# AC1 — Mirror-Felder + Provenance-Pills in der Finanzen-Sektion
# ---------------------------------------------------------------------------

def test_object_detail_finance_section_mirror_fields_and_pills(
    db, steckbrief_admin_client, make_finanzen_object, monkeypatch,
    steckbrief_admin_user,
):
    obj = make_finanzen_object("FIN7", impower_property_id="HAM61")
    # Mirror-Werte fuer alle 3 angezeigten Felder via Write-Gate.
    write_field_human(
        db, entity=obj, field="reserve_current",
        value=Decimal("45000.00"), source="impower_mirror", user=None,
        source_ref="HAM61",
    )
    write_field_human(
        db, entity=obj, field="reserve_target",
        value=Decimal("50000.00"), source="impower_mirror", user=None,
        source_ref="HAM61",
    )
    write_field_human(
        db, entity=obj, field="wirtschaftsplan_status",
        value="beschlossen", source="impower_mirror", user=None,
        source_ref="HAM61",
    )
    db.commit()

    _patch_get_bank_balance(monkeypatch, None)
    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    body = response.text

    assert "45000.00 EUR" in body
    assert "50000.00 EUR" in body
    assert "beschlossen" in body
    # Pills mit data-field + data-source
    assert 'data-field="reserve_current"' in body
    assert 'data-field="reserve_target"' in body
    assert 'data-field="wirtschaftsplan_status"' in body
    assert 'data-source="impower_mirror"' in body


def test_object_detail_finance_section_sepa_mandates_table(
    db, steckbrief_admin_client, make_finanzen_object, monkeypatch,
):
    obj = make_finanzen_object("FIN8", impower_property_id="HAM61")
    # JSONB-List direkt schreiben (keine bestehende Mandate). NICHT via
    # write_field_human — wir wollen einfach den Render-Pfad durchspielen.
    obj.sepa_mandate_refs = [  # writegate: allow
        {"mandate_id": "777", "bank_account_id": 7000, "state": "BOOKED"},
    ]
    db.add(obj)
    db.commit()

    _patch_get_bank_balance(monkeypatch, None)
    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    body = response.text
    assert "777" in body
    assert "7000" in body
    assert "BOOKED" in body
    # AC1: Provenance-Pill fuer sepa_mandate_refs muss gerendert sein.
    assert 'data-field="sepa_mandate_refs"' in body


def test_object_detail_finance_section_sepa_empty(
    db, steckbrief_admin_client, make_finanzen_object, monkeypatch,
):
    obj = make_finanzen_object("FIN9", impower_property_id="HAM61")
    _patch_get_bank_balance(monkeypatch, None)
    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    assert "Keine SEPA-Mandate gespiegelt." in response.text


# ---------------------------------------------------------------------------
# AC5 — Sparkline aus Provenance-Historie
# ---------------------------------------------------------------------------

def test_object_detail_finance_section_sparkline_with_two_points(
    db, steckbrief_admin_client, make_finanzen_object, monkeypatch
):
    obj = make_finanzen_object("FIN10", impower_property_id="HAM61")
    # Zwei reserve_current-Mirror-Rows mit explizitem created_at.
    for value, days_ago in [("40000", 30), ("45000", 5)]:
        row = FieldProvenance(
            id=uuid.uuid4(),
            entity_type="object",
            entity_id=obj.id,
            field_name="reserve_current",
            source="impower_mirror",
            source_ref="HAM61",
            value_snapshot={"old": None, "new": value},
            created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )
        db.add(row)
    db.commit()

    _patch_get_bank_balance(monkeypatch, None)
    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    body = response.text
    # Sparkline-spezifische Marker (Sidebar-Icons nutzen viewBox 0 0 24 24).
    assert 'viewBox="0 0 120 40"' in body
    assert 'aria-label="Ruecklage-Verlauf' in body


def test_object_detail_finance_section_sparkline_placeholder_one_point(
    db, steckbrief_admin_client, make_finanzen_object, monkeypatch
):
    obj = make_finanzen_object("FIN11", impower_property_id="HAM61")
    row = FieldProvenance(
        id=uuid.uuid4(),
        entity_type="object",
        entity_id=obj.id,
        field_name="reserve_current",
        source="impower_mirror",
        source_ref="HAM61",
        value_snapshot={"old": None, "new": "45000"},
        created_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    db.add(row)
    db.commit()

    _patch_get_bank_balance(monkeypatch, None)
    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    # Kein Sparkline-SVG (viewBox 120x40 ist sparkline-spezifisch — Sidebar-Icons
    # nutzen 24x24).
    assert 'viewBox="0 0 120 40"' not in response.text


# ---------------------------------------------------------------------------
# AC2 — Stammdaten-Sektion bleibt sichtbar bei Live-Pull-Fehler
# ---------------------------------------------------------------------------

def test_object_detail_renders_stammdaten_when_live_pull_fails(
    db, steckbrief_admin_client, make_finanzen_object, monkeypatch
):
    obj = make_finanzen_object("FIN12", impower_property_id="HAM61")
    obj.full_address = "Hausstr. 1, 22769 Hamburg"  # writegate: allow
    db.add(obj)
    db.commit()

    _patch_get_bank_balance(monkeypatch, None)
    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    body = response.text
    assert "Stammdaten" in body
    assert "Hausstr. 1, 22769 Hamburg" in body
