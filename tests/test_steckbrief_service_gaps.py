"""Service-Level-Luecken fuer app/services/steckbrief.py (Story 1.3).

Die Route-Smoke-Tests in test_steckbrief_routes_smoke.py fassen die Service-
Funktionen nur durch die HTTP-Linse an. Hier sind die Pfade, die nicht durch
einen Router laufen:

- `list_objects_with_unit_counts(accessible_ids=set())` → leeres Set schliesst
   den DB-Roundtrip ab und liefert `[]`.
- `get_provenance_map(..., fields=[])` → frueher Return ohne Query.
- `get_provenance_map` Latest-Ordering bei mehreren Provenance-Rows pro Feld:
   `created_at DESC, id DESC` — Tiebreaker greift, wenn zwei Rows im selben
   Test-Tick entstehen.
- `accessible_object_ids(disabled_user)` → leeres Set ohne Object-Query.
- `accessible_object_ids(user_ohne_view_perm)` → leeres Set.
"""
from __future__ import annotations

import datetime as _dt
import uuid

import pytest

from app.models import FieldProvenance, Object, User
from app.permissions import accessible_object_ids
from app.services.steckbrief import (
    get_provenance_map,
    list_objects_with_unit_counts,
)


# ---------------------------------------------------------------------------
# list_objects_with_unit_counts
# ---------------------------------------------------------------------------

def test_list_objects_empty_accessible_ids_returns_empty_without_query(db):
    """accessible_ids=set() darf keine SQL-Query ausloesen — frueher Short-
    Circuit, sonst laden wir fuer einen User ohne jede Objekt-Sichtbarkeit
    die komplette Tabelle nur um sie anschliessend durch einen leeren
    IN ()-Filter zu werfen."""
    # Seed ein Objekt, um sicherzustellen, dass der Short-Circuit es nicht sieht.
    db.add(Object(id=uuid.uuid4(), short_code="SEED", name="seed"))
    db.commit()

    result = list_objects_with_unit_counts(db, accessible_ids=set())
    assert result == []


def test_list_objects_none_accessible_ids_returns_all(db):
    """accessible_ids=None bedeutet 'keine Einschraenkung' (v1-Default)."""
    db.add(Object(id=uuid.uuid4(), short_code="AAA", name="a"))
    db.add(Object(id=uuid.uuid4(), short_code="BBB", name="b"))
    db.commit()

    result = list_objects_with_unit_counts(db, accessible_ids=None)
    assert {r.short_code for r in result} == {"AAA", "BBB"}


# ---------------------------------------------------------------------------
# get_provenance_map
# ---------------------------------------------------------------------------

def test_get_provenance_map_empty_fields_returns_empty(db):
    """Leere fields-Liste → leeres Dict, ohne Query."""
    result = get_provenance_map(
        db, entity_type="object", entity_id=uuid.uuid4(), fields=[]
    )
    assert result == {}


def test_get_provenance_map_unknown_field_returns_none(db):
    """Ein Feld ohne jede Provenance-Row ist im Ergebnis-Dict mit None
    vertreten — die Route mapped das auf die 'missing'-Pill."""
    obj_id = uuid.uuid4()
    result = get_provenance_map(
        db, entity_type="object", entity_id=obj_id, fields=["year_roof", "name"]
    )
    assert result == {"year_roof": None, "name": None}


def test_get_provenance_map_picks_latest_per_field_by_created_at(db):
    """Bei mehreren Provenance-Rows pro (entity, field) gewinnt die juengste
    nach (created_at DESC, id DESC). Gleicher Sort-Key wie das Write-Gate —
    sonst divergieren Pills und Write-Gate-Guard."""
    obj = Object(id=uuid.uuid4(), short_code="PMX", name="Prov-Map")
    db.add(obj)
    db.flush()

    # Alt (vor 2 Stunden), Neu (jetzt), auf demselben Feld.
    old = FieldProvenance(
        id=uuid.uuid4(),
        entity_type="object",
        entity_id=obj.id,
        field_name="name",
        source="impower_mirror",
        source_ref="PROP-OLD",
        user_id=None,
        confidence=None,
        value_snapshot={"old": None, "new": "alt"},
        created_at=_dt.datetime.now(tz=_dt.timezone.utc) - _dt.timedelta(hours=2),
    )
    new = FieldProvenance(
        id=uuid.uuid4(),
        entity_type="object",
        entity_id=obj.id,
        field_name="name",
        source="impower_mirror",
        source_ref="PROP-NEW",
        user_id=None,
        confidence=None,
        value_snapshot={"old": "alt", "new": "neu"},
        created_at=_dt.datetime.now(tz=_dt.timezone.utc),
    )
    db.add_all([old, new])
    db.commit()

    result = get_provenance_map(
        db, entity_type="object", entity_id=obj.id, fields=["name"]
    )
    entry = result["name"]
    assert entry is not None
    assert entry.prov.source_ref == "PROP-NEW"


# ---------------------------------------------------------------------------
# accessible_object_ids (permissions.py, aber Story-1.3-Contract)
# ---------------------------------------------------------------------------

def test_accessible_object_ids_disabled_user_empty(db):
    """NFR-Regel: disabled User sehen nichts — auch nicht die Objekt-Liste."""
    user = User(
        id=uuid.uuid4(),
        google_sub="disabled-sub",
        email="disabled@dbshome.de",
        name="Disabled",
        permissions_extra=["objects:view"],
        disabled_at=_dt.datetime.now(tz=_dt.timezone.utc),
    )
    db.add(user)
    db.add(Object(id=uuid.uuid4(), short_code="DIS", name="d"))
    db.commit()

    assert accessible_object_ids(db, user) == set()


def test_accessible_object_ids_without_view_permission_empty(db):
    """Ohne objects:view bleibt das Set leer, egal wieviele Objekte existieren."""
    user = User(
        id=uuid.uuid4(),
        google_sub="noperm-sub",
        email="noperm@dbshome.de",
        name="NoPerm",
        permissions_extra=[],
    )
    db.add(user)
    db.add(Object(id=uuid.uuid4(), short_code="SEC", name="s"))
    db.commit()

    assert accessible_object_ids(db, user) == set()


def test_accessible_object_ids_with_view_returns_all_ids_v1(db):
    """v1-Semantik laut permissions.py: `objects:view` → ALLE Objekt-IDs."""
    user = User(
        id=uuid.uuid4(),
        google_sub="view-sub",
        email="view@dbshome.de",
        name="Viewer",
        permissions_extra=["objects:view"],
    )
    db.add(user)
    o1 = Object(id=uuid.uuid4(), short_code="O1", name="1")
    o2 = Object(id=uuid.uuid4(), short_code="O2", name="2")
    db.add_all([o1, o2])
    db.commit()

    assert accessible_object_ids(db, user) == {o1.id, o2.id}
