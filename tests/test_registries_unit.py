"""Story 2.7+2.8 — Unit-Tests fuer list_versicherer_aggregated + get_versicherer_detail."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import InsurancePolicy, Object, Schadensfall, Versicherer
from app.services.registries import get_versicherer_detail, list_versicherer_aggregated


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


# ---------------------------------------------------------------------------
# Story 2.8 — get_versicherer_detail
# ---------------------------------------------------------------------------

def _make_policy_with_due(
    db, obj: Object, versicherer: Versicherer, *, praemie=None, next_main_due=None
) -> InsurancePolicy:
    p = InsurancePolicy(
        id=uuid.uuid4(),
        object_id=obj.id,
        versicherer_id=versicherer.id,
        praemie=Decimal(str(praemie)) if praemie is not None else None,
        next_main_due=next_main_due,
    )
    db.add(p)
    return p


def test_get_versicherer_detail_returns_none_for_unknown_id(db):
    assert get_versicherer_detail(db, uuid.uuid4()) is None


def test_get_versicherer_detail_header_aggregations(db):
    obj = _make_object(db, "AGG1")
    v = _make_versicherer(db, "Aggregations-Versicherer")
    p1 = _make_policy(db, obj, v, praemie=100)
    p2 = _make_policy(db, obj, v, praemie=200)
    _make_schadensfall(db, p1, 50)
    db.commit()

    detail = get_versicherer_detail(db, v.id)
    assert detail is not None
    assert detail.policen_anzahl == 2
    assert detail.gesamtpraemie == Decimal("300")
    assert detail.gesamtschaden == Decimal("50")
    assert detail.schadensquote == pytest.approx(50 / 300, abs=1e-3)


def test_get_versicherer_detail_heatmap_has_12_months(db):
    v = _make_versicherer(db, "Kein-Policen-Versicherer")
    db.commit()

    detail = get_versicherer_detail(db, v.id)
    assert detail is not None
    assert len(detail.heatmap) == 12
    assert all(b.severity == "empty" for b in detail.heatmap)


def test_heatmap_marks_expiring_policy_as_critical(db, monkeypatch):
    from app.services import registries as reg_mod

    # Stabilisiert auf Mitte des Monats, damit `today + 10 Tage` und `today - 5 Tage`
    # garantiert im selben Kalendermonat liegen (verhindert Test-Flake am Monatsanfang).
    today = date.today().replace(day=15)
    monkeypatch.setattr(reg_mod, "date", type("_FakeDate", (), {
        "today": staticmethod(lambda: today),
        "max": date.max,
        "min": date.min,
    }))

    obj = _make_object(db, "CRT1")
    v = _make_versicherer(db, "Critical-Versicherer")
    due_date = today + timedelta(days=10)
    _make_policy_with_due(db, obj, v, praemie=100, next_main_due=due_date)
    db.commit()

    detail = get_versicherer_detail(db, v.id)
    assert detail is not None
    target_bucket = next(
        b for b in detail.heatmap if b.year == due_date.year and b.month == due_date.month
    )
    assert target_bucket.severity == "critical"


def test_heatmap_marks_overdue_policy_as_critical(db, monkeypatch):
    from app.services import registries as reg_mod

    today = date.today().replace(day=15)
    monkeypatch.setattr(reg_mod, "date", type("_FakeDate", (), {
        "today": staticmethod(lambda: today),
        "max": date.max,
        "min": date.min,
    }))

    obj = _make_object(db, "OVD1")
    v = _make_versicherer(db, "Overdue-Versicherer")
    overdue = today - timedelta(days=5)  # 10. dieses Monats — sicher im aktuellen Monats-Bucket
    _make_policy_with_due(db, obj, v, praemie=100, next_main_due=overdue)
    db.commit()

    detail = get_versicherer_detail(db, v.id)
    assert detail is not None
    overdue_bucket = next(
        b for b in detail.heatmap if b.year == overdue.year and b.month == overdue.month
    )
    assert overdue_bucket.severity == "critical"


def test_overdue_count_counts_policies_before_current_month(db, monkeypatch):
    from app.services import registries as reg_mod

    today = date.today().replace(day=15)
    monkeypatch.setattr(reg_mod, "date", type("_FakeDate", (), {
        "today": staticmethod(lambda: today),
        "max": date.max,
        "min": date.min,
    }))

    obj = _make_object(db, "OVDLONG")
    v = _make_versicherer(db, "Long-Overdue-Versicherer")
    long_overdue = today.replace(day=1) - timedelta(days=15)  # garantiert im Vormonat
    in_current_month = today - timedelta(days=5)  # gleiche Monat — gehoert NICHT zum overdue_count
    _make_policy_with_due(db, obj, v, praemie=100, next_main_due=long_overdue)
    _make_policy_with_due(db, obj, v, praemie=100, next_main_due=in_current_month)
    db.commit()

    detail = get_versicherer_detail(db, v.id)
    assert detail is not None
    assert detail.overdue_count == 1  # nur die Police aus dem Vormonat


def test_heatmap_marks_expiring_policy_as_warning(db, monkeypatch):
    from app.services import registries as reg_mod

    today = date.today().replace(day=15)
    monkeypatch.setattr(reg_mod, "date", type("_FakeDate", (), {
        "today": staticmethod(lambda: today),
        "max": date.max,
        "min": date.min,
    }))

    obj = _make_object(db, "WRN1")
    v = _make_versicherer(db, "Warning-Versicherer")
    due_in_60 = today + timedelta(days=60)
    _make_policy_with_due(db, obj, v, praemie=100, next_main_due=due_in_60)
    db.commit()

    detail = get_versicherer_detail(db, v.id)
    assert detail is not None
    target_bucket = next(
        b for b in detail.heatmap if b.year == due_in_60.year and b.month == due_in_60.month
    )
    assert target_bucket.severity == "warning"


def test_schadensfaelle_sorted_newest_first(db):
    obj = _make_object(db, "SRT2")
    v = _make_versicherer(db, "Sort-Versicherer")
    p = _make_policy(db, obj, v, praemie=100)
    s_old = Schadensfall(id=uuid.uuid4(), policy_id=p.id, occurred_at=date(2024, 6, 1), amount=Decimal("10"))
    s_new = Schadensfall(id=uuid.uuid4(), policy_id=p.id, occurred_at=date(2025, 3, 1), amount=Decimal("20"))
    db.add(s_old)
    db.add(s_new)
    db.commit()

    detail = get_versicherer_detail(db, v.id)
    assert detail is not None
    assert len(detail.schadensfaelle) == 2
    assert detail.schadensfaelle[0].occurred_at == date(2025, 3, 1)


def test_verbundene_objekte_deduplicates(db):
    obj = _make_object(db, "DED1")
    v = _make_versicherer(db, "Dedup-Versicherer")
    _make_policy(db, obj, v, praemie=100)
    _make_policy(db, obj, v, praemie=200)
    db.commit()

    detail = get_versicherer_detail(db, v.id)
    assert detail is not None
    assert len(detail.verbundene_objekte) == 1


def test_detail_handles_empty_contact_info(db):
    v = Versicherer(id=uuid.uuid4(), name="Leerer-Kontakt-Versicherer", contact_info={})
    db.add(v)
    db.commit()

    detail = get_versicherer_detail(db, v.id)
    assert detail is not None
    assert detail.versicherer.contact_info == {}
