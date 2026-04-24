"""Story 2.1 — Unit-Tests fuer steckbrief_policen Service.

Prueft:
  - Datumsvalidierung (AC4)
  - Write-Gate-Provenance fuer create_police (AC1)
  - update_police Provenance nur fuer geaenderte Felder
  - delete_police AuditLog
  - create_versicherer AuditLog
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.models import AuditLog, FieldProvenance, InsurancePolicy, Object, User, Versicherer
from app.services.steckbrief_policen import (
    create_police,
    create_versicherer,
    delete_police,
    update_police,
    validate_police_dates,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def obj(db):
    o = Object(id=uuid.uuid4(), short_code="POL1", name="Test-Objekt Policen")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


@pytest.fixture
def user(db):
    u = User(
        id=uuid.uuid4(),
        google_sub="google-sub-pol-unit",
        email="pol-unit@dbshome.de",
        name="Pol Unit User",
        permissions_extra=["objects:view", "objects:edit", "registries:edit"],
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def versicherer(db):
    v = Versicherer(id=uuid.uuid4(), name="Test Versicherung AG", contact_info={})
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


# ---------------------------------------------------------------------------
# AC4 — Datumsvalidierung
# ---------------------------------------------------------------------------

def test_validate_police_dates_ok():
    err = validate_police_dates(
        start_date=date(2024, 1, 1),
        end_date=date(2025, 1, 1),
        next_main_due=date(2024, 12, 31),
    )
    assert err is None


def test_validate_police_dates_next_main_due_before_start():
    err = validate_police_dates(
        start_date=date(2025, 6, 1),
        end_date=None,
        next_main_due=date(2025, 1, 1),
    )
    assert err is not None
    assert "Ablauf-Datum" in err


def test_validate_police_dates_end_before_start():
    err = validate_police_dates(
        start_date=date(2025, 1, 1),
        end_date=date(2024, 12, 31),
        next_main_due=None,
    )
    assert err is not None
    assert "Ende-Datum" in err


def test_validate_police_dates_none_values():
    assert validate_police_dates(None, None, None) is None


# ---------------------------------------------------------------------------
# AC1 — create_police Provenance
# ---------------------------------------------------------------------------

def test_create_police_writes_provenance_for_all_fields(db, obj, user, versicherer):
    policy = create_police(
        db, obj, user, None,
        versicherer_id=versicherer.id,
        police_number="POL-001",
        produkt_typ="Haftpflicht",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        next_main_due=date(2025, 12, 31),
        notice_period_months=3,
        praemie=Decimal("1200.00"),
    )
    db.flush()

    provs = (
        db.query(FieldProvenance)
        .filter(
            FieldProvenance.entity_type == "police",
            FieldProvenance.entity_id == policy.id,
            FieldProvenance.source == "user_edit",
        )
        .all()
    )
    assert len(provs) == 8, f"Erwartet 8 Provenance-Rows, got {len(provs)}: {[p.field_name for p in provs]}"

    audit_entries = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "object_field_updated",
            AuditLog.entity_type == "police",
            AuditLog.entity_id == policy.id,
        )
        .all()
    )
    assert len(audit_entries) == 8, (
        f"AC1: Erwartet 8 AuditLog(action=object_field_updated, entity_type=police), "
        f"got {len(audit_entries)}"
    )


def test_create_police_skips_none_fields(db, obj, user, versicherer):
    policy = create_police(
        db, obj, user, None,
        versicherer_id=versicherer.id,
        police_number=None,
        produkt_typ=None,
        start_date=None,
        end_date=None,
        next_main_due=None,
        notice_period_months=None,
        praemie=None,
    )
    db.flush()

    provs = (
        db.query(FieldProvenance)
        .filter(
            FieldProvenance.entity_type == "police",
            FieldProvenance.entity_id == policy.id,
        )
        .all()
    )
    field_names = [p.field_name for p in provs]
    assert "police_number" not in field_names
    assert "produkt_typ" not in field_names
    # versicherer_id war gesetzt
    assert "versicherer_id" in field_names


def test_create_police_versicherer_id_has_provenance(db, obj, user, versicherer):
    policy = create_police(
        db, obj, user, None,
        versicherer_id=versicherer.id,
        police_number="POL-002",
        produkt_typ=None,
        start_date=None,
        end_date=None,
        next_main_due=None,
        notice_period_months=None,
        praemie=None,
    )
    db.flush()

    prov = (
        db.query(FieldProvenance)
        .filter(
            FieldProvenance.entity_type == "police",
            FieldProvenance.entity_id == policy.id,
            FieldProvenance.field_name == "versicherer_id",
        )
        .first()
    )
    assert prov is not None
    assert prov.value_snapshot["new"] == str(versicherer.id)


def test_update_police_writes_provenance_only_for_changed_fields(db, obj, user, versicherer):
    policy = create_police(
        db, obj, user, None,
        versicherer_id=None,
        police_number="ORIG-001",
        produkt_typ=None,
        start_date=None,
        end_date=None,
        next_main_due=None,
        notice_period_months=None,
        praemie=Decimal("1000.00"),
    )
    db.commit()
    db.refresh(policy)

    prov_count_before = (
        db.query(FieldProvenance)
        .filter(FieldProvenance.entity_id == policy.id)
        .count()
    )

    update_police(db, policy, user, None, praemie=Decimal("1200.00"))
    db.flush()

    prov_count_after = (
        db.query(FieldProvenance)
        .filter(FieldProvenance.entity_id == policy.id)
        .count()
    )
    assert prov_count_after == prov_count_before + 1

    newest = (
        db.query(FieldProvenance)
        .filter(
            FieldProvenance.entity_id == policy.id,
            FieldProvenance.field_name == "praemie",
        )
        .order_by(FieldProvenance.created_at.desc())
        .first()
    )
    assert newest is not None
    assert newest.value_snapshot["new"] == "1200.00"


# ---------------------------------------------------------------------------
# AC2 — delete_police AuditLog
# ---------------------------------------------------------------------------

def test_delete_police_writes_audit(db, obj, user):
    policy = create_police(
        db, obj, user, None,
        versicherer_id=None,
        police_number="DEL-001",
        produkt_typ=None,
        start_date=None,
        end_date=None,
        next_main_due=None,
        notice_period_months=None,
        praemie=None,
    )
    db.commit()
    db.refresh(policy)
    policy_id = policy.id

    delete_police(db, policy, user, None)
    db.flush()

    audit_entry = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "registry_entry_updated",
            AuditLog.entity_type == "police",
            AuditLog.entity_id == policy_id,
        )
        .first()
    )
    assert audit_entry is not None
    assert audit_entry.details_json["action"] == "delete"

    still_there = db.get(InsurancePolicy, policy_id)
    assert still_there is None


# ---------------------------------------------------------------------------
# AC3 — create_versicherer AuditLog
# ---------------------------------------------------------------------------

def test_create_versicherer_writes_audit(db, user):
    v = create_versicherer(
        db, user, None,
        name="Neue Versicherung GmbH",
        contact_info={"email": "info@nv.de"},
    )
    db.flush()

    audit_entry = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "registry_entry_created",
            AuditLog.entity_type == "versicherer",
            AuditLog.entity_id == v.id,
        )
        .first()
    )
    assert audit_entry is not None
    assert audit_entry.details_json["name"] == "Neue Versicherung GmbH"
