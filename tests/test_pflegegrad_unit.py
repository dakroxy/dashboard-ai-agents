"""Unit-Tests fuer app/services/pflegegrad.py (Story 3.3, AC1–AC3, AC5)."""
from __future__ import annotations

import datetime as _dt
import uuid

import pytest

from app.models import Eigentuemer, FieldProvenance, InsurancePolicy, Object, User, Wartungspflicht
from app.services.pflegegrad import (
    CACHE_TTL,
    PflegegradResult,
    get_or_update_pflegegrad_cache,
    pflegegrad_score,
)

# Stabiles Basis-Datum (Monatsmitte, kein Flackern bei Monatsrand)
_BASE = _dt.datetime.now(_dt.timezone.utc).replace(
    day=15, hour=12, minute=0, second=0, microsecond=0
)


@pytest.fixture
def admin_user(db):
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-pflegegrad-admin",
        email="pflegegrad-admin@dbshome.de",
        name="Pflegegrad Admin",
        permissions_extra=["objects:view", "objects:edit"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _add_scalar_provs(db, obj_id: uuid.UUID, fields: list[str], created_at: _dt.datetime):
    for field in fields:
        db.add(
            FieldProvenance(
                id=uuid.uuid4(),
                entity_type="object",
                entity_id=obj_id,
                field_name=field,
                source="user_edit",
                value_snapshot={"old": None, "new": "x"},
                created_at=created_at,
            )
        )
    db.commit()


# ---------------------------------------------------------------------------
# AC1 — Score 100 bei vollstaendigem Objekt
# ---------------------------------------------------------------------------

def test_all_full_fresh_provenance_score_100(db, test_object):
    # Alle C1/C4-Scalar-Felder befuellen
    test_object.full_address = "Musterstr. 1, 20099 Hamburg"
    test_object.impower_property_id = "PROP-001"
    test_object.shutoff_water_location = "Keller"
    test_object.shutoff_electricity_location = "Keller"
    test_object.heating_type = "Gas"
    test_object.year_built = 1990
    # C6
    from decimal import Decimal
    test_object.last_known_balance = Decimal("12345.00")
    test_object.reserve_current = Decimal("5000.00")
    test_object.sepa_mandate_refs = [{"id": "M1"}]
    db.commit()

    # Frische Provenance fuer alle 8 Scalar-Felder
    _add_scalar_provs(
        db,
        test_object.id,
        [
            "full_address", "impower_property_id",
            "shutoff_water_location", "shutoff_electricity_location",
            "heating_type", "year_built",
            "last_known_balance", "reserve_current",
        ],
        created_at=_BASE - _dt.timedelta(days=30),
    )

    # Relationale Objekte anlegen
    db.add(Eigentuemer(id=uuid.uuid4(), object_id=test_object.id, name="Max Muster"))
    db.add(InsurancePolicy(id=uuid.uuid4(), object_id=test_object.id))
    db.add(
        Wartungspflicht(
            id=uuid.uuid4(),
            object_id=test_object.id,
            bezeichnung="Kaminkehrer",
        )
    )
    db.commit()

    result = pflegegrad_score(test_object, db)

    assert isinstance(result, PflegegradResult)
    assert result.score == 100
    assert result.per_cluster == {"C1": 1.0, "C4": 1.0, "C6": 1.0, "C8": 1.0}
    assert result.weakest_fields == []


# ---------------------------------------------------------------------------
# AC2 — Score ~20 bei nur C1 befuellt
# ---------------------------------------------------------------------------

def test_only_c1_filled_score_20(db, test_object):
    test_object.full_address = "Musterstr. 1, 20099 Hamburg"
    test_object.impower_property_id = "PROP-001"
    # C4, C6, C8 bleiben leer / Default
    db.commit()

    _add_scalar_provs(
        db,
        test_object.id,
        ["full_address", "impower_property_id"],
        created_at=_BASE - _dt.timedelta(days=30),
    )

    db.add(Eigentuemer(id=uuid.uuid4(), object_id=test_object.id, name="Max Muster"))
    db.commit()

    result = pflegegrad_score(test_object, db)

    assert result.score == 20
    assert result.per_cluster["C1"] == 1.0
    assert result.per_cluster["C4"] == 0.0
    assert result.per_cluster["C6"] == 0.0
    assert result.per_cluster["C8"] == 0.0

    # Alle C4-Felder muessen in weakest_fields sein
    for field in ("shutoff_water_location", "shutoff_electricity_location", "heating_type", "year_built"):
        assert field in result.weakest_fields, f"{field} fehlt in weakest_fields"
    # C6-Scalar-Felder
    for field in ("last_known_balance", "reserve_current"):
        assert field in result.weakest_fields, f"{field} fehlt in weakest_fields"
    # C6 sepa_mandate_refs
    assert "sepa_mandate_refs" in result.weakest_fields
    # C8 relational
    assert "has_police" in result.weakest_fields
    assert "has_wartungspflicht" in result.weakest_fields


# ---------------------------------------------------------------------------
# AC3 — Aktualitaets-Decay fuer Provenance > 1095 Tage
# ---------------------------------------------------------------------------

def test_c4_decay_1095_days(db, test_object):
    # Alle C1/C6/C8 vollstaendig und aktuell
    from decimal import Decimal
    test_object.full_address = "Musterstr. 1, 20099 Hamburg"
    test_object.impower_property_id = "PROP-001"
    test_object.last_known_balance = Decimal("1.00")
    test_object.reserve_current = Decimal("1.00")
    test_object.sepa_mandate_refs = [{"id": "M1"}]
    # C4 befuellt
    test_object.shutoff_water_location = "Keller"
    test_object.shutoff_electricity_location = "Keller"
    test_object.heating_type = "Gas"
    test_object.year_built = 1990
    db.commit()

    # Frische Provenance fuer C1 und C6
    _add_scalar_provs(
        db,
        test_object.id,
        ["full_address", "impower_property_id", "last_known_balance", "reserve_current"],
        created_at=_BASE - _dt.timedelta(days=30),
    )

    # Alte Provenance fuer alle C4-Felder (> 1095 Tage → Decay 0.1)
    _add_scalar_provs(
        db,
        test_object.id,
        ["shutoff_water_location", "shutoff_electricity_location", "heating_type", "year_built"],
        created_at=_BASE - _dt.timedelta(days=1100),
    )

    db.add(Eigentuemer(id=uuid.uuid4(), object_id=test_object.id, name="Max Muster"))
    db.add(InsurancePolicy(id=uuid.uuid4(), object_id=test_object.id))
    db.add(Wartungspflicht(id=uuid.uuid4(), object_id=test_object.id, bezeichnung="Kaminkehrer"))
    db.commit()

    result = pflegegrad_score(test_object, db)

    assert result.per_cluster["C4"] == pytest.approx(0.1)
    # Alle C4-Felder haben Decay < 1.0 → in weakest_fields
    for field in ("shutoff_water_location", "shutoff_electricity_location", "heating_type", "year_built"):
        assert field in result.weakest_fields, f"{field} fehlt in weakest_fields"


# ---------------------------------------------------------------------------
# AC5a — Cache-Population bei leerem Cache
# ---------------------------------------------------------------------------

def test_get_or_update_cache_population(db, test_object):
    assert test_object.pflegegrad_score_cached is None
    assert test_object.pflegegrad_score_updated_at is None

    result, updated = get_or_update_pflegegrad_cache(test_object, db)

    assert updated is True
    assert test_object.pflegegrad_score_cached == result.score
    assert test_object.pflegegrad_score_updated_at is not None
    assert isinstance(result, PflegegradResult)


# ---------------------------------------------------------------------------
# AC5b — Kein Cache-Write wenn frisch (< TTL)
# ---------------------------------------------------------------------------

def test_get_or_update_cache_no_write_when_fresh(db, test_object):
    now = _dt.datetime.now(_dt.timezone.utc)
    initial_score = 42
    initial_ts = now - _dt.timedelta(seconds=30)  # 30 s alt → frisch (TTL=5 min)

    test_object.pflegegrad_score_cached = initial_score
    test_object.pflegegrad_score_updated_at = initial_ts
    db.commit()
    db.refresh(test_object)

    result, updated = get_or_update_pflegegrad_cache(test_object, db)

    assert updated is False
    assert test_object.pflegegrad_score_cached == initial_score
    # SQLite gibt naive Datetimes zurueck; Vergleich auf naiver Ebene ausreichend
    stored = test_object.pflegegrad_score_updated_at
    if stored is not None and stored.tzinfo is None:
        stored = stored.replace(tzinfo=_dt.timezone.utc)
    assert stored == initial_ts
