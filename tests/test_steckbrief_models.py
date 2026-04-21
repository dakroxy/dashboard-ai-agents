"""Smoketests fuer die Steckbrief-Core-Modelle (Story 1.2, AC3).

Pruefen den rein strukturellen Teil: Tabellen liegen auf Base.metadata,
Klassen lassen sich importieren, Minimal-Roundtrip klappt, das bewusste
`photo_metadata`-Attribut existiert (Reserved-Name-Regression).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import Base


_EXPECTED_STECKBRIEF_TABLES: set[str] = {
    "objects",
    "units",
    "policen",
    "wartungspflichten",
    "schadensfaelle",
    "versicherer",
    "dienstleister",
    "banken",
    "ablesefirmen",
    "eigentuemer",
    "mieter",
    "mietvertraege",
    "zaehler",
    "facilioo_tickets",
    "steckbrief_photos",
    "field_provenance",
    "review_queue_entries",
}


def test_all_steckbrief_tables_registered():
    tables = set(Base.metadata.tables.keys())
    missing = _EXPECTED_STECKBRIEF_TABLES - tables
    assert not missing, f"Tabellen fehlen auf Base.metadata: {missing}"


def test_all_steckbrief_models_exported():
    from app.models import (
        Ablesefirma,
        Bank,
        Dienstleister,
        Eigentuemer,
        FaciliooTicket,
        FieldProvenance,
        InsurancePolicy,
        Mieter,
        Mietvertrag,
        Object,
        ReviewQueueEntry,
        Schadensfall,
        SteckbriefPhoto,
        Unit,
        Versicherer,
        Wartungspflicht,
        Zaehler,
    )
    import app.models as m

    expected = {
        "Object",
        "Unit",
        "SteckbriefPhoto",
        "InsurancePolicy",
        "Wartungspflicht",
        "Schadensfall",
        "Versicherer",
        "Dienstleister",
        "Bank",
        "Ablesefirma",
        "Eigentuemer",
        "Mieter",
        "Mietvertrag",
        "Zaehler",
        "FaciliooTicket",
        "FieldProvenance",
        "ReviewQueueEntry",
    }
    assert expected.issubset(set(m.__all__))

    # Sanity: alle Klassen sind auf der Base gemappt.
    for cls in (
        Object,
        Unit,
        SteckbriefPhoto,
        InsurancePolicy,
        Wartungspflicht,
        Schadensfall,
        Versicherer,
        Dienstleister,
        Bank,
        Ablesefirma,
        Eigentuemer,
        Mieter,
        Mietvertrag,
        Zaehler,
        FaciliooTicket,
        FieldProvenance,
        ReviewQueueEntry,
    ):
        assert hasattr(cls, "__tablename__")


def test_object_persists_roundtrip(db):
    from app.models import Object

    obj = Object(
        id=uuid.uuid4(),
        short_code="HAM77",
        name="HAM77 Testobjekt",
        full_address="Teststrasse 1, 20359 Hamburg",
        year_built=1995,
        year_roof=2018,
        voting_rights={"alt": 0.5},
    )
    db.add(obj)
    db.commit()

    db.expire_all()
    loaded = db.get(Object, obj.id)
    assert loaded is not None
    assert loaded.short_code == "HAM77"
    assert loaded.name == "HAM77 Testobjekt"
    assert loaded.year_built == 1995
    assert loaded.voting_rights == {"alt": 0.5}
    assert loaded.object_history_structured == []
    assert loaded.equipment_flags == {}


def test_steckbrief_photo_attr_not_metadata():
    """Regression: das JSONB-Feld heisst photo_metadata, nicht metadata."""
    from app.models import SteckbriefPhoto

    assert hasattr(SteckbriefPhoto, "photo_metadata")

    # SQLAlchemy laesst `SteckbriefPhoto.metadata` als MetaData-Referenz stehen
    # (das ist der Base.metadata-Proxy), das ist OK. Wichtig: es gibt KEIN
    # Mapped[dict]-Attribut mit Namen "metadata" auf dem Mapper.
    mapper = SteckbriefPhoto.__mapper__
    column_names = {c.key for c in mapper.columns}
    assert "photo_metadata" in column_names
    assert "metadata" not in column_names


def test_facilioo_ticket_unique_facilioo_id(db):
    from app.models import FaciliooTicket, Object

    obj = Object(id=uuid.uuid4(), short_code="FAC1", name="Facilioo-Test")
    db.add(obj)
    db.commit()

    t1 = FaciliooTicket(
        id=uuid.uuid4(), object_id=obj.id, facilioo_id="FAC-123"
    )
    db.add(t1)
    db.commit()

    t2 = FaciliooTicket(
        id=uuid.uuid4(), object_id=obj.id, facilioo_id="FAC-123"
    )
    db.add(t2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
