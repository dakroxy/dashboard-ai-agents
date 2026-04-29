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
from decimal import Decimal

import pytest

from app.models import FieldProvenance, Object, Unit, User
from app.permissions import accessible_object_ids
from app.services.steckbrief import (
    ObjectListRow,
    get_provenance_map,
    is_reserve_below_target,
    list_objects_with_unit_counts,
    normalize_sort_order,
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


# ---------------------------------------------------------------------------
# ObjectListRow + list_objects_with_unit_counts (Story 3.1)
# ---------------------------------------------------------------------------

def test_list_objects_returns_objectlistrow_with_extended_fields(db):
    db.add(Object(id=uuid.uuid4(), short_code="EXT", name="Extended",
                  reserve_current=Decimal("5000"), reserve_target=Decimal("1000"),
                  pflegegrad_score_cached=85))
    db.commit()
    result = list_objects_with_unit_counts(db, accessible_ids=None)
    assert len(result) == 1
    row = result[0]
    assert isinstance(row, ObjectListRow)
    assert row.pflegegrad == 85
    assert row.reserve_current == Decimal("5000")
    assert row.reserve_target == Decimal("1000")
    assert row.mandat_status == "fehlt"  # sepa_mandate_refs default=[]


def test_mandat_status_vorhanden_when_sepa_refs_nonempty(db):
    db.add(Object(id=uuid.uuid4(), short_code="MND", name="Mandat",
                  sepa_mandate_refs=[{"id": "m-1"}]))
    db.commit()
    rows = list_objects_with_unit_counts(db, accessible_ids=None)
    assert rows[0].mandat_status == "vorhanden"


def test_mandat_status_fehlt_when_sepa_refs_empty(db):
    db.add(Object(id=uuid.uuid4(), short_code="NOM", name="NoMandat",
                  sepa_mandate_refs=[]))
    db.commit()
    rows = list_objects_with_unit_counts(db, accessible_ids=None)
    assert rows[0].mandat_status == "fehlt"


def test_filter_reserve_below_target_excludes_above_threshold(db):
    db.add(Object(id=uuid.uuid4(), short_code="ABOVE", name="Ueber Schwelle",
                  reserve_current=Decimal("7000"), reserve_target=Decimal("1000")))
    db.add(Object(id=uuid.uuid4(), short_code="BELOW", name="Unter Schwelle",
                  reserve_current=Decimal("3000"), reserve_target=Decimal("1000")))
    db.commit()
    rows = list_objects_with_unit_counts(db, accessible_ids=None, filter_reserve_below_target=True)
    codes = {r.short_code for r in rows}
    assert "BELOW" in codes
    assert "ABOVE" not in codes


def test_filter_reserve_excludes_null_values(db):
    db.add(Object(id=uuid.uuid4(), short_code="NULLR", name="Null Reserve",
                  reserve_current=None, reserve_target=Decimal("1000")))
    db.commit()
    rows = list_objects_with_unit_counts(db, accessible_ids=None, filter_reserve_below_target=True)
    assert all(r.short_code != "NULLR" for r in rows)


def test_filter_reserve_decimal_zero_is_below_target(db):
    db.add(Object(id=uuid.uuid4(), short_code="ZERO", name="Zero Reserve",
                  reserve_current=Decimal("0"), reserve_target=Decimal("500")))
    db.commit()
    rows = list_objects_with_unit_counts(db, accessible_ids=None, filter_reserve_below_target=True)
    assert any(r.short_code == "ZERO" for r in rows), "Decimal('0') muss als 0 < 500*6=3000 erkannt werden"


def test_sort_saldo_nulls_always_last_ascending(db):
    db.add(Object(id=uuid.uuid4(), short_code="AAA", name="a", last_known_balance=Decimal("100")))
    db.add(Object(id=uuid.uuid4(), short_code="BBB", name="b", last_known_balance=None))
    db.add(Object(id=uuid.uuid4(), short_code="CCC", name="c", last_known_balance=Decimal("50")))
    db.commit()
    rows = list_objects_with_unit_counts(db, accessible_ids=None, sort="saldo", order="asc")
    codes = [r.short_code for r in rows]
    assert codes[-1] == "BBB", "NULL-Saldo muss zuletzt sein (asc)"


def test_sort_saldo_nulls_always_last_descending(db):
    db.add(Object(id=uuid.uuid4(), short_code="AAA", name="a", last_known_balance=Decimal("100")))
    db.add(Object(id=uuid.uuid4(), short_code="BBB", name="b", last_known_balance=None))
    db.add(Object(id=uuid.uuid4(), short_code="CCC", name="c", last_known_balance=Decimal("50")))
    db.commit()
    rows = list_objects_with_unit_counts(db, accessible_ids=None, sort="saldo", order="desc")
    codes = [r.short_code for r in rows]
    assert codes[-1] == "BBB", "NULL-Saldo muss zuletzt sein (desc)"


def test_sort_tiebreaker_short_code_casefold(db):
    db.add(Object(id=uuid.uuid4(), short_code="bbb", name="b", last_known_balance=Decimal("100")))
    db.add(Object(id=uuid.uuid4(), short_code="AAA", name="a", last_known_balance=Decimal("100")))
    db.commit()
    rows = list_objects_with_unit_counts(db, accessible_ids=None, sort="saldo", order="asc")
    assert rows[0].short_code == "AAA"  # casefold: "aaa" < "bbb"


def test_list_objects_unit_count_in_objectlistrow(db):
    """ObjectListRow traegt unit_count weiter, auch wenn die Listen-UI sie
    aktuell nicht als Spalte zeigt (Story 3.2 wird sie im Card-Layout nutzen)."""
    obj = Object(id=uuid.uuid4(), short_code="UC5", name="Unit-Count")
    db.add(obj)
    db.flush()
    for i in range(5):
        db.add(Unit(id=uuid.uuid4(), object_id=obj.id, unit_number=f"UC5-{i}"))
    db.commit()
    rows = list_objects_with_unit_counts(db, accessible_ids=None)
    target = next(r for r in rows if r.short_code == "UC5")
    assert target.unit_count == 5


# ---------------------------------------------------------------------------
# Review-Patch P5 — `reserve_below_target` als single source of truth
# ---------------------------------------------------------------------------

def test_is_reserve_below_target_decimal_zero_is_below_when_target_positive():
    """Decimal('0') ist NOT None und 0 < target*6 ⇒ True (Truthiness-Falle)."""
    assert is_reserve_below_target(Decimal("0"), Decimal("500")) is True


def test_is_reserve_below_target_none_inputs_return_false():
    assert is_reserve_below_target(None, Decimal("500")) is False
    assert is_reserve_below_target(Decimal("100"), None) is False
    assert is_reserve_below_target(None, None) is False


def test_is_reserve_below_target_threshold_inclusive_boundary():
    # Genau am Schwellwert (current == target * 6) ⇒ NICHT below (strict <)
    assert is_reserve_below_target(Decimal("6000"), Decimal("1000")) is False
    # Knapp drueber ⇒ NICHT below
    assert is_reserve_below_target(Decimal("6001"), Decimal("1000")) is False
    # Knapp drunter ⇒ below
    assert is_reserve_below_target(Decimal("5999"), Decimal("1000")) is True


def test_object_list_row_carries_reserve_below_target_field(db):
    """ObjectListRow.reserve_below_target wird vorberechnet, damit das Template
    nicht eigenstaendig die Schwelle berechnet (Review-Patch P5)."""
    db.add(Object(id=uuid.uuid4(), short_code="RBT1", name="below",
                  reserve_current=Decimal("500"), reserve_target=Decimal("1000")))
    db.add(Object(id=uuid.uuid4(), short_code="RBT2", name="above",
                  reserve_current=Decimal("9000"), reserve_target=Decimal("1000")))
    db.add(Object(id=uuid.uuid4(), short_code="RBT3", name="null-current",
                  reserve_current=None, reserve_target=Decimal("1000")))
    db.add(Object(id=uuid.uuid4(), short_code="RBT4", name="null-target",
                  reserve_current=Decimal("100"), reserve_target=None))
    db.commit()
    rows = {r.short_code: r for r in list_objects_with_unit_counts(db, accessible_ids=None)}
    assert rows["RBT1"].reserve_below_target is True
    assert rows["RBT2"].reserve_below_target is False
    assert rows["RBT3"].reserve_below_target is False
    assert rows["RBT4"].reserve_below_target is False


# ---------------------------------------------------------------------------
# Review-Patch P3+P4 — normalize_sort_order Helper
# ---------------------------------------------------------------------------

def test_normalize_sort_order_unknown_sort_falls_back_to_short_code():
    safe_sort, _ = normalize_sort_order("INVALID_KEY", "asc")
    assert safe_sort == "short_code"


def test_normalize_sort_order_order_case_insensitive():
    assert normalize_sort_order("saldo", "DESC")[1] == "desc"
    assert normalize_sort_order("saldo", "Desc")[1] == "desc"
    assert normalize_sort_order("saldo", "  desc ")[1] == "desc"
    assert normalize_sort_order("saldo", "ASC")[1] == "asc"


def test_normalize_sort_order_unknown_order_falls_back_to_asc():
    assert normalize_sort_order("saldo", "BLA")[1] == "asc"
    assert normalize_sort_order("saldo", "")[1] == "asc"


# ---------------------------------------------------------------------------
# Review-Patch P5 — Filter-Excludes auch reserve_target=None
# ---------------------------------------------------------------------------

def test_filter_reserve_excludes_null_target(db):
    """AC5 Negativfall: reserve_target=None schliesst Objekt vom Filter aus
    (kein Threshold vergleichbar)."""
    db.add(Object(id=uuid.uuid4(), short_code="NTGT", name="Null Target",
                  reserve_current=Decimal("100"), reserve_target=None))
    db.commit()
    rows = list_objects_with_unit_counts(
        db, accessible_ids=None, filter_reserve_below_target=True
    )
    assert all(r.short_code != "NTGT" for r in rows)


# ---------------------------------------------------------------------------
# Review-Patch P2 — Tiebreaker bleibt ASC auch bei order=desc
# ---------------------------------------------------------------------------

def test_sort_tiebreaker_stable_on_descending_numeric(db):
    """Bei gleichem Saldo soll short_code IMMER ASC bleiben, auch bei order=desc.
    Frueher kehrte reverse=True den ganzen Tuple-Key um (Tiebreaker auch desc)."""
    db.add(Object(id=uuid.uuid4(), short_code="ZZZ", name="z", last_known_balance=Decimal("100")))
    db.add(Object(id=uuid.uuid4(), short_code="AAA", name="a", last_known_balance=Decimal("100")))
    db.commit()
    rows = list_objects_with_unit_counts(
        db, accessible_ids=None, sort="saldo", order="desc"
    )
    # Beide Saldi sind identisch; Tiebreaker auf short_code ASC erwartet.
    assert rows[0].short_code == "AAA"
    assert rows[1].short_code == "ZZZ"


def test_sort_tiebreaker_stable_on_descending_string(db):
    """name-Sort desc: bei gleichem name bleibt short_code asc."""
    db.add(Object(id=uuid.uuid4(), short_code="ZZZ", name="Same", last_known_balance=Decimal("0")))
    db.add(Object(id=uuid.uuid4(), short_code="AAA", name="Same", last_known_balance=Decimal("0")))
    db.commit()
    rows = list_objects_with_unit_counts(
        db, accessible_ids=None, sort="name", order="desc"
    )
    same_rows = [r for r in rows if r.name == "Same"]
    assert [r.short_code for r in same_rows] == ["AAA", "ZZZ"]


# ---------------------------------------------------------------------------
# Review-Patch P1 — null_rows werden auch nach short_code sortiert
# ---------------------------------------------------------------------------

def test_sort_numeric_null_rows_are_sorted_by_short_code(db):
    """Mehrere NULL-Saldo-Objekte: Reihenfolge muss deterministisch sein
    (short_code asc), nicht zufaellig nach DB-Order."""
    db.add(Object(id=uuid.uuid4(), short_code="ZZZ", name="z", last_known_balance=None))
    db.add(Object(id=uuid.uuid4(), short_code="AAA", name="a", last_known_balance=None))
    db.add(Object(id=uuid.uuid4(), short_code="MMM", name="m", last_known_balance=None))
    db.commit()
    rows = list_objects_with_unit_counts(
        db, accessible_ids=None, sort="saldo", order="asc"
    )
    null_codes = [r.short_code for r in rows if r.saldo is None]
    assert null_codes == ["AAA", "MMM", "ZZZ"]


# ---------------------------------------------------------------------------
# Review-Patch P6 — sort=name primaere casefold-Sortierung
# ---------------------------------------------------------------------------

def test_sort_by_name_uses_casefold_primary(db):
    """name=asc mit gemischter Gross-/Kleinschreibung: ascii-Ordering wuerde
    'BBB' vor 'aaa' setzen (Grossbuchstaben-Codepoints kleiner). casefold
    gleicht das aus → erwartet ist alphabetisch unabhaengig vom Case."""
    db.add(Object(id=uuid.uuid4(), short_code="X1", name="aaa"))
    db.add(Object(id=uuid.uuid4(), short_code="X2", name="BBB"))
    db.add(Object(id=uuid.uuid4(), short_code="X3", name="ccc"))
    db.commit()
    rows = list_objects_with_unit_counts(
        db, accessible_ids=None, sort="name", order="asc"
    )
    assert [r.short_code for r in rows] == ["X1", "X2", "X3"]


# ---------------------------------------------------------------------------
# Review-Patch P6 — sort=mandat_status Reihenfolge
# ---------------------------------------------------------------------------

def test_sort_by_mandat_status_asc_puts_fehlt_first(db):
    """mandat_status asc: 'fehlt' (0) < 'vorhanden' (1)."""
    db.add(Object(id=uuid.uuid4(), short_code="MV", name="vorh",
                  sepa_mandate_refs=[{"id": "x"}]))
    db.add(Object(id=uuid.uuid4(), short_code="MF", name="fehlt",
                  sepa_mandate_refs=[]))
    db.commit()
    rows = list_objects_with_unit_counts(
        db, accessible_ids=None, sort="mandat_status", order="asc"
    )
    assert rows[0].mandat_status == "fehlt"
    assert rows[1].mandat_status == "vorhanden"


def test_sort_by_mandat_status_desc_puts_vorhanden_first(db):
    db.add(Object(id=uuid.uuid4(), short_code="MV", name="vorh",
                  sepa_mandate_refs=[{"id": "x"}]))
    db.add(Object(id=uuid.uuid4(), short_code="MF", name="fehlt",
                  sepa_mandate_refs=[]))
    db.commit()
    rows = list_objects_with_unit_counts(
        db, accessible_ids=None, sort="mandat_status", order="desc"
    )
    assert rows[0].mandat_status == "vorhanden"
    assert rows[1].mandat_status == "fehlt"


def test_sort_by_mandat_status_tiebreaker_short_code_asc_in_desc(db):
    """Bei gleichem mandat_status (alle 'fehlt') bleibt short_code ASC,
    auch wenn Primary-Sort desc ist."""
    db.add(Object(id=uuid.uuid4(), short_code="ZZZ", name="z", sepa_mandate_refs=[]))
    db.add(Object(id=uuid.uuid4(), short_code="AAA", name="a", sepa_mandate_refs=[]))
    db.commit()
    rows = list_objects_with_unit_counts(
        db, accessible_ids=None, sort="mandat_status", order="desc"
    )
    assert [r.short_code for r in rows] == ["AAA", "ZZZ"]


# ---------------------------------------------------------------------------
# Review-Patch P6 — Saldo-Reihenfolge der non-null-Werte tatsaechlich pruefen
# ---------------------------------------------------------------------------

def test_sort_saldo_desc_puts_largest_first(db):
    db.add(Object(id=uuid.uuid4(), short_code="S1", name="s1", last_known_balance=Decimal("10")))
    db.add(Object(id=uuid.uuid4(), short_code="S2", name="s2", last_known_balance=Decimal("100")))
    db.add(Object(id=uuid.uuid4(), short_code="S3", name="s3", last_known_balance=Decimal("50")))
    db.commit()
    rows = list_objects_with_unit_counts(
        db, accessible_ids=None, sort="saldo", order="desc"
    )
    assert [r.short_code for r in rows] == ["S2", "S3", "S1"]


def test_sort_saldo_asc_puts_smallest_first(db):
    db.add(Object(id=uuid.uuid4(), short_code="S1", name="s1", last_known_balance=Decimal("10")))
    db.add(Object(id=uuid.uuid4(), short_code="S2", name="s2", last_known_balance=Decimal("100")))
    db.add(Object(id=uuid.uuid4(), short_code="S3", name="s3", last_known_balance=Decimal("50")))
    db.commit()
    rows = list_objects_with_unit_counts(
        db, accessible_ids=None, sort="saldo", order="asc"
    )
    assert [r.short_code for r in rows] == ["S1", "S3", "S2"]
