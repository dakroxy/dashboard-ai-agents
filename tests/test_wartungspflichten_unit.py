"""Story 2.2 — Unit-Tests fuer steckbrief_wartungen Service.

Prueft:
  - get_due_severity (AC2)
  - validate_wartung_dates (AC1)
  - create_wartungspflicht Provenance (AC1)
  - delete_wartungspflicht AuditLog (AC3)
  - create_dienstleister AuditLog (AC4)
  - Policy-Cascade auf Wartungspflichten (AC3)
  - N+1-Verhinderung via selectin (AC2)
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import sqlalchemy as sa

from app.models import AuditLog, FieldProvenance, InsurancePolicy, Object, User, Wartungspflicht
from app.models.registry import Dienstleister
from app.services.steckbrief_wartungen import (
    create_dienstleister,
    create_wartungspflicht,
    delete_wartungspflicht,
    get_due_severity,
    validate_wartung_dates,
)
from app.services.steckbrief_policen import get_policen_for_object


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def obj(db):
    o = Object(id=uuid.uuid4(), short_code="WAR1", name="Test-Objekt Wartung")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


@pytest.fixture
def user(db):
    u = User(
        id=uuid.uuid4(),
        google_sub="google-sub-wart-unit",
        email="wart-unit@dbshome.de",
        name="Wart Unit User",
        permissions_extra=["objects:view", "objects:edit", "registries:edit"],
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def policy(db, obj):
    p = InsurancePolicy(id=uuid.uuid4(), object_id=obj.id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def dienstleister(db):
    d = Dienstleister(id=uuid.uuid4(), name="Muster Haustechnik GmbH", gewerke_tags=[])
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


# ---------------------------------------------------------------------------
# get_due_severity
# ---------------------------------------------------------------------------

def test_get_due_severity_critical():
    assert get_due_severity(date.today() + timedelta(days=15)) == "critical"


def test_get_due_severity_warning():
    assert get_due_severity(date.today() + timedelta(days=60)) == "warning"


def test_get_due_severity_far_future():
    assert get_due_severity(date.today() + timedelta(days=365)) is None


def test_get_due_severity_none_input():
    assert get_due_severity(None) is None


def test_get_due_severity_exactly_30_days():
    assert get_due_severity(date.today() + timedelta(days=30)) == "critical"


def test_get_due_severity_exactly_90_days():
    assert get_due_severity(date.today() + timedelta(days=90)) == "warning"


def test_get_due_severity_past_date():
    # Vergangene Faelligkeit: < today + 30d → critical
    assert get_due_severity(date.today() - timedelta(days=1)) == "critical"


# ---------------------------------------------------------------------------
# validate_wartung_dates
# ---------------------------------------------------------------------------

def test_validate_wartung_dates_ok():
    letzte = date(2024, 1, 1)
    naechste = date(2025, 1, 1)
    err = validate_wartung_dates(letzte, 12, naechste)
    assert err is None


def test_validate_wartung_dates_next_before_letzte():
    letzte = date(2024, 6, 1)
    naechste = date(2024, 5, 1)
    err = validate_wartung_dates(letzte, None, naechste)
    assert err is not None
    assert "muss nach" in err


def test_validate_wartung_dates_next_equals_letzte():
    d = date(2024, 6, 1)
    err = validate_wartung_dates(d, None, d)
    assert err is not None
    assert "muss nach" in err


def test_validate_wartung_dates_intervall_mismatch():
    letzte = date(2023, 1, 1)
    naechste = date(2025, 1, 1)  # ~24 Monate Abstand, Intervall=12 → stark abweichend
    err = validate_wartung_dates(letzte, 12, naechste)
    assert err is not None
    assert "weichen stark" in err


def test_validate_wartung_dates_all_none():
    assert validate_wartung_dates(None, None, None) is None


def test_validate_wartung_dates_only_next_due():
    assert validate_wartung_dates(None, None, date(2025, 1, 1)) is None


# ---------------------------------------------------------------------------
# create_wartungspflicht
# ---------------------------------------------------------------------------

def test_create_wartungspflicht_writes_provenance_for_all_fields(
    db, policy, user, dienstleister
):
    letzte = date(2024, 1, 1)
    naechste = date(2025, 1, 1)
    wart = create_wartungspflicht(
        db, policy, user, None,
        bezeichnung="Heizungswartung",
        dienstleister_id=dienstleister.id,
        intervall_monate=12,
        letzte_wartung=letzte,
        next_due_date=naechste,
    )
    db.flush()

    provs = (
        db.query(FieldProvenance)
        .filter(
            FieldProvenance.entity_type == "wartung",
            FieldProvenance.entity_id == wart.id,
            FieldProvenance.source == "user_edit",
        )
        .all()
    )
    field_names = {p.field_name for p in provs}
    assert len(provs) == 5, f"Erwartet 5 Provenance-Rows, got {len(provs)}: {sorted(field_names)}"
    assert field_names == {
        "bezeichnung", "dienstleister_id", "intervall_monate",
        "letzte_wartung", "next_due_date",
    }


def test_create_wartungspflicht_object_id_from_policy(db, policy, user):
    wart = create_wartungspflicht(
        db, policy, user, None,
        bezeichnung="Dachinspektion",
        dienstleister_id=None,
        intervall_monate=None,
        letzte_wartung=None,
        next_due_date=None,
    )
    db.flush()
    assert wart.object_id == policy.object_id


def test_create_wartungspflicht_skips_none_fields(db, policy, user):
    wart = create_wartungspflicht(
        db, policy, user, None,
        bezeichnung="Kaminkehrer",
        dienstleister_id=None,
        intervall_monate=None,
        letzte_wartung=None,
        next_due_date=None,
    )
    db.flush()

    provs = (
        db.query(FieldProvenance)
        .filter(FieldProvenance.entity_id == wart.id)
        .all()
    )
    field_names = {p.field_name for p in provs}
    assert "dienstleister_id" not in field_names
    assert "intervall_monate" not in field_names
    assert "letzte_wartung" not in field_names
    assert "next_due_date" not in field_names
    assert "bezeichnung" in field_names


# ---------------------------------------------------------------------------
# delete_wartungspflicht
# ---------------------------------------------------------------------------

def test_delete_wartungspflicht_writes_audit(db, policy, user):
    wart = create_wartungspflicht(
        db, policy, user, None,
        bezeichnung="Loeschanlage",
        dienstleister_id=None,
        intervall_monate=12,
        letzte_wartung=None,
        next_due_date=date(2025, 6, 1),
    )
    db.commit()
    db.refresh(wart)
    wart_id = wart.id

    delete_wartungspflicht(db, wart, user, None)
    db.flush()

    delete_log = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "wartung_deleted",
            AuditLog.entity_type == "wartung",
            AuditLog.entity_id == wart_id,
        )
        .first()
    )
    assert delete_log is not None, "Kein Delete-AuditLog-Entry gefunden"
    assert delete_log.details_json["bezeichnung"] == "Loeschanlage"

    still_there = db.get(Wartungspflicht, wart_id)
    assert still_there is None


# ---------------------------------------------------------------------------
# create_dienstleister
# ---------------------------------------------------------------------------

def test_create_dienstleister_writes_audit(db, user):
    d = create_dienstleister(
        db, user, None,
        name="Neue Haustechnik GmbH",
        gewerke_tags=["Sanitär", "Heizung"],
    )
    db.flush()

    log = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "registry_entry_created",
            AuditLog.entity_type == "dienstleister",
            AuditLog.entity_id == d.id,
        )
        .first()
    )
    assert log is not None
    assert log.details_json["name"] == "Neue Haustechnik GmbH"
    assert d.gewerke_tags == ["Sanitär", "Heizung"]


def test_create_dienstleister_empty_tags(db, user):
    d = create_dienstleister(db, user, None, name="Solo GmbH", gewerke_tags=[])
    db.flush()
    assert d.gewerke_tags == []


# ---------------------------------------------------------------------------
# Cascade: Police-Delete loescht Wartungspflichten
# ---------------------------------------------------------------------------

def test_delete_policy_cascades_wartungspflichten(db, policy, user):
    w1 = create_wartungspflicht(
        db, policy, user, None,
        bezeichnung="W1", dienstleister_id=None,
        intervall_monate=None, letzte_wartung=None, next_due_date=None,
    )
    w2 = create_wartungspflicht(
        db, policy, user, None,
        bezeichnung="W2", dienstleister_id=None,
        intervall_monate=None, letzte_wartung=None, next_due_date=None,
    )
    db.commit()
    w1_id = w1.id
    w2_id = w2.id

    # expire erzwingt Fresh-Load der Collection aus DB (Wartungen wurden via
    # policy_id direkt angelegt, nicht ueber die ORM-Relationship-Collection)
    db.expire(policy)
    _ = policy.wartungspflichten  # selectin-Load
    db.delete(policy)
    db.flush()

    assert db.get(Wartungspflicht, w1_id) is None
    assert db.get(Wartungspflicht, w2_id) is None


# ---------------------------------------------------------------------------
# N+1-Verhinderung via selectin
# ---------------------------------------------------------------------------

def test_get_policen_loads_wartungspflichten_without_n_plus_1(db, obj, user):
    """3 Policen mit je 2 Wartungspflichten — Query-Count muss <= 3 bleiben."""
    policies = []
    for i in range(3):
        p = InsurancePolicy(id=uuid.uuid4(), object_id=obj.id)
        db.add(p)
        db.flush()
        for j in range(2):
            wart = Wartungspflicht(
                id=uuid.uuid4(),
                policy_id=p.id,
                object_id=obj.id,
                bezeichnung=f"W{i}-{j}",
            )
            db.add(wart)
        policies.append(p)
    db.commit()

    query_count = 0

    def count_query(conn, cursor, statement, parameters, context, executemany):
        nonlocal query_count
        query_count += 1

    engine = db.get_bind()
    sa.event.listen(engine, "before_cursor_execute", count_query)
    try:
        loaded = get_policen_for_object(db, obj.id)
        # Zugriff auf wartungspflichten triggert selectin-Load (falls noetig)
        total_wartungen = sum(len(p.wartungspflichten) for p in loaded)
    finally:
        sa.event.remove(engine, "before_cursor_execute", count_query)

    assert total_wartungen == 6
    assert query_count <= 3, f"Zu viele Queries: {query_count} (N+1-Problem?)"
