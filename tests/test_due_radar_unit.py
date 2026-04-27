"""Story 2.5 — Unit-Tests fuer list_due_within (DueRadarEntry-Service)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.models import InsurancePolicy, Object, Versicherer, Wartungspflicht
from app.services.due_radar import list_due_within


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_object(db, short_code: str = "TST1") -> Object:
    obj = Object(id=uuid.uuid4(), short_code=short_code, name=f"Obj {short_code}")
    db.add(obj)
    db.flush()
    return obj


def _make_versicherer(db, name: str = "Allianz") -> Versicherer:
    v = Versicherer(id=uuid.uuid4(), name=name)
    db.add(v)
    db.flush()
    return v


def _make_police(db, obj: Object, next_main_due: date, versicherer: Versicherer | None = None) -> InsurancePolicy:
    p = InsurancePolicy(
        id=uuid.uuid4(),
        object_id=obj.id,
        versicherer_id=versicherer.id if versicherer else None,
        next_main_due=next_main_due,
    )
    db.add(p)
    db.flush()
    return p


def _make_wartung(db, policy: InsurancePolicy, bezeichnung: str, next_due_date: date) -> Wartungspflicht:
    w = Wartungspflicht(
        id=uuid.uuid4(),
        policy_id=policy.id,
        object_id=policy.object_id,
        bezeichnung=bezeichnung,
        next_due_date=next_due_date,
    )
    db.add(w)
    db.flush()
    return w


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_empty_when_no_accessible_ids(db):
    """Early-Return bei leerem Set — kein DB-Roundtrip, leere Liste."""
    result = list_due_within(db, accessible_object_ids=set())
    assert result == []


def test_police_entry_included_within_90_days(db):
    """Police mit next_main_due = today+30 erscheint im Ergebnis."""
    obj = _make_object(db, "HAM1")
    versicherer = _make_versicherer(db, "Allianz")
    due = date.today() + timedelta(days=30)
    _make_police(db, obj, due, versicherer)
    db.commit()

    result = list_due_within(db, accessible_object_ids={obj.id})

    assert len(result) == 1
    entry = result[0]
    assert entry.kind == "police"
    assert entry.due_date == due
    assert entry.title == "Allianz"
    assert entry.object_short_code == "HAM1"


def test_wartung_entry_via_police_join(db):
    """Wartung ohne direktes object_id — erfordert JOIN via policen."""
    obj = _make_object(db, "HAM2")
    due = date.today() + timedelta(days=45)
    policy = _make_police(db, obj, date.today() + timedelta(days=60))
    _make_wartung(db, policy, "Kaminkehrerinspektion", due)
    db.commit()

    result = list_due_within(db, accessible_object_ids={obj.id})

    wartung_entries = [e for e in result if e.kind == "wartung"]
    assert len(wartung_entries) == 1
    entry = wartung_entries[0]
    assert entry.kind == "wartung"
    assert entry.title == "Kaminkehrerinspektion"
    assert entry.object_short_code == "HAM2"


def test_severity_under_30_days_red(db):
    """days_remaining=15 → severity='< 30 Tage'."""
    obj = _make_object(db)
    _make_police(db, obj, date.today() + timedelta(days=15))
    db.commit()

    result = list_due_within(db, accessible_object_ids={obj.id})
    assert result[0].severity == "< 30 Tage"
    assert result[0].days_remaining == 15


def test_severity_30_to_90_days_orange(db):
    """days_remaining=45 → severity='< 90 Tage'."""
    obj = _make_object(db)
    _make_police(db, obj, date.today() + timedelta(days=45))
    db.commit()

    result = list_due_within(db, accessible_object_ids={obj.id})
    assert result[0].severity == "< 90 Tage"
    assert result[0].days_remaining == 45


def test_overdue_entry_included_and_severity_stays_red(db):
    """Ueberfaellige Police (next_main_due = today-5) erscheint im Ergebnis
    und hat severity='< 30 Tage' (keine separate 'ueberfaellig'-Severity)."""
    obj = _make_object(db)
    _make_police(db, obj, date.today() - timedelta(days=5))
    db.commit()

    result = list_due_within(db, accessible_object_ids={obj.id})
    assert len(result) == 1
    entry = result[0]
    assert entry.days_remaining == -5
    assert entry.severity == "< 30 Tage"
