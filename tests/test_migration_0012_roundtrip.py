"""Minimal-Check: das Datenmodell laedt sauber mit den neuen 0012-Feldern
(ORM-Metadata + create_all mussten bereits in conftest durchlaufen sein).

Ein echter alembic-upgrade-Roundtrip ist im Projekt nicht verkabelt
(kein alembic-Test-Harness). Die Migration-Datei selbst wird manuell
in docker compose geprueft; hier stellen wir nur sicher, dass die
neuen Spalten im ORM existieren und beschreibbar sind.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from app.models import Eigentuemer, Object


def test_object_has_new_finance_mirror_fields(db):
    obj = Object(
        id=uuid.uuid4(),
        short_code="MGT1",
        name="Mig-Test",
        reserve_current=Decimal("42.00"),
        reserve_target=Decimal("7.50"),
        wirtschaftsplan_status="beschlossen",
        sepa_mandate_refs=[{"mandate_id": 1}],
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    assert obj.reserve_current == Decimal("42.00")
    assert obj.reserve_target == Decimal("7.50")
    assert obj.wirtschaftsplan_status == "beschlossen"
    assert obj.sepa_mandate_refs == [{"mandate_id": 1}]


def test_eigentuemer_has_impower_contact_id(db):
    obj = Object(id=uuid.uuid4(), short_code="MGT2", name="Mig-Test-2")
    db.add(obj)
    db.flush()
    eig = Eigentuemer(
        id=uuid.uuid4(),
        object_id=obj.id,
        name="A",
        impower_contact_id="42",
    )
    db.add(eig)
    db.commit()
    db.refresh(eig)
    assert eig.impower_contact_id == "42"
