"""Story 2.7 — Unit-Tests fuer list_versicherer_aggregated."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.models import InsurancePolicy, Object, Schadensfall, Versicherer
from app.services.registries import list_versicherer_aggregated


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_object(db, short_code: str = "TST1") -> Object:
    obj = Object(id=uuid.uuid4(), short_code=short_code, name=f"Objekt {short_code}")
    db.add(obj)
    return obj


def _make_versicherer(db, name: str = "Testversicherer") -> Versicherer:
    v = Versicherer(id=uuid.uuid4(), name=name)
    db.add(v)
    return v


def _make_policy(db, obj: Object, versicherer: Versicherer, praemie=None) -> InsurancePolicy:
    p = InsurancePolicy(
        id=uuid.uuid4(),
        object_id=obj.id,
        versicherer_id=versicherer.id,
        praemie=Decimal(str(praemie)) if praemie is not None else None,
    )
    db.add(p)
    return p


def _make_schadensfall(db, policy: InsurancePolicy, amount) -> Schadensfall:
    s = Schadensfall(id=uuid.uuid4(), policy_id=policy.id, amount=Decimal(str(amount)))
    db.add(s)
    return s


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_empty_list_when_no_versicherer(db):
    rows = list_versicherer_aggregated(db)
    assert rows == []


def test_aggregation_counts_one_versicherer(db):
    obj = _make_object(db, "HAM1")
    v = _make_versicherer(db, "Allianz")
    p1 = _make_policy(db, obj, v, praemie=100)
    p2 = _make_policy(db, obj, v, praemie=200)
    _make_schadensfall(db, p1, 50)
    db.commit()

    rows = list_versicherer_aggregated(db)
    assert len(rows) == 1
    r = rows[0]
    assert r.policen_anzahl == 2
    assert r.gesamtpraemie == Decimal("300")
    assert r.gesamtschaden == Decimal("50")
    assert abs(r.schadensquote - 50 / 300) < 1e-9
    assert r.objekte_anzahl == 1


def test_no_double_count_praemie_with_multiple_schadensfaelle(db):
    obj = _make_object(db, "HAM2")
    v = _make_versicherer(db, "Zurich")
    p = _make_policy(db, obj, v, praemie=100)
    _make_schadensfall(db, p, 30)
    _make_schadensfall(db, p, 20)
    db.commit()

    rows = list_versicherer_aggregated(db)
    assert len(rows) == 1
    r = rows[0]
    assert r.policen_anzahl == 1
    assert r.gesamtpraemie == Decimal("100")  # NICHT 200
    assert r.gesamtschaden == Decimal("50")


def test_schadensquote_null_safe_when_no_praemie(db):
    obj = _make_object(db, "BRE1")
    v = _make_versicherer(db, "AXA")
    _make_policy(db, obj, v, praemie=None)
    db.commit()

    rows = list_versicherer_aggregated(db)
    assert len(rows) == 1
    assert rows[0].schadensquote == 0.0


def test_versicherer_without_policen_has_zero_counts(db):
    _make_versicherer(db, "Generali")
    db.commit()

    rows = list_versicherer_aggregated(db)
    assert len(rows) == 1
    r = rows[0]
    assert r.policen_anzahl == 0
    assert r.gesamtpraemie == Decimal("0")
    assert r.objekte_anzahl == 0
    assert r.schadensquote == 0.0


def test_sort_by_policen_anzahl_desc(db):
    obj = _make_object(db, "GVE1")
    va = _make_versicherer(db, "A-Versicherer")
    vb = _make_versicherer(db, "B-Versicherer")
    for _ in range(3):
        _make_policy(db, obj, va, praemie=100)
    _make_policy(db, obj, vb, praemie=100)
    db.commit()

    rows = list_versicherer_aggregated(db, sort="policen_anzahl", order="desc")
    assert len(rows) == 2
    assert rows[0].name == "A-Versicherer"
    assert rows[0].policen_anzahl == 3


def test_sort_by_name_asc_is_default(db):
    _make_versicherer(db, "Zurich")
    _make_versicherer(db, "Allianz")
    db.commit()

    rows = list_versicherer_aggregated(db)
    assert len(rows) == 2
    assert rows[0].name == "Allianz"
    assert rows[1].name == "Zurich"


def test_schadensquote_zero_when_schaden_without_praemie(db):
    obj = _make_object(db, "MUC1")
    v = _make_versicherer(db, "HUK")
    p = _make_policy(db, obj, v, praemie=Decimal("0"))
    _make_schadensfall(db, p, 100)
    db.commit()

    rows = list_versicherer_aggregated(db)
    assert len(rows) == 1
    assert rows[0].schadensquote == 0.0
