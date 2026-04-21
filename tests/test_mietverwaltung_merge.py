"""Unit-Tests fuer den Case-State-Merge (M5 Paket 4 + Paket 5).

Deckt:
- `merge_case_state` mit Extractions nach Doc-Typ (property/owner/buildings/units/tc)
- Tenant-Fallback aus der Mieterliste, wenn kein eigener Mietvertrag
- Override-Merge: Dict-Sektionen feldweise, Listen komplett ersetzt
- `field_source` Provenance: user > auto(doc) > auto > missing

Keine externen Calls noetig — pure Funktionen.
"""
from __future__ import annotations

from app.services.mietverwaltung import field_source, merge_case_state


# ---------------------------------------------------------------------------
# Hilfsfunktionen: Extraction-Builder
# ---------------------------------------------------------------------------

def _vv(doc_id: str = "d-vv", **data) -> dict:
    return {"doc_id": doc_id, "doc_type": "verwaltervertrag", "data": data}


def _gb(doc_id: str = "d-gb", **data) -> dict:
    return {"doc_id": doc_id, "doc_type": "grundbuch", "data": data}


def _mv(doc_id: str = "d-mv", **data) -> dict:
    return {"doc_id": doc_id, "doc_type": "mietvertrag", "data": data}


def _ml(doc_id: str = "d-ml", **data) -> dict:
    return {"doc_id": doc_id, "doc_type": "mieterliste", "data": data}


# ---------------------------------------------------------------------------
# merge_case_state — Auto-Merge pro Sektion
# ---------------------------------------------------------------------------

class TestMergeEmpty:
    def test_no_extractions_produces_empty_state(self):
        state = merge_case_state([])
        assert state["property"] == {}
        assert state["management_contract"] == {}
        assert state["billing_address"] is None
        assert state["owner"] is None
        assert state["buildings"] == []
        assert state["units"] == []
        assert state["tenant_contracts"] == []


class TestMergeProperty:
    def test_property_fields_from_verwaltervertrag_primary(self):
        state = merge_case_state([
            _vv(property={
                "number": "HAM61",
                "name": "WEG Hamburger Str. 61",
                "street": "Hamburger Str. 61",
                "postal_code": "20099",
                "city": "Hamburg",
                "creditor_id": "DE71ZZZ00002822264",
            }),
        ])
        assert state["property"]["number"] == "HAM61"
        assert state["property"]["name"] == "WEG Hamburger Str. 61"
        assert state["property"]["creditor_id"] == "DE71ZZZ00002822264"

    def test_default_country_de_when_street_set(self):
        state = merge_case_state([
            _vv(property={"street": "Hamburger Str. 61", "postal_code": "20099", "city": "Hamburg"}),
        ])
        assert state["property"]["country"] == "DE"

    def test_no_default_country_when_no_street(self):
        state = merge_case_state([
            _vv(property={"number": "HAM61"}),
        ])
        assert "country" not in state["property"]

    def test_verwaltervertrag_wins_over_grundbuch_for_number(self):
        state = merge_case_state([
            _vv(property={"number": "FROM_VV"}),
            _gb(property={"number": "FROM_GB"}),
        ])
        assert state["property"]["number"] == "FROM_VV"

    def test_grundbuch_fills_land_registry_fields(self):
        state = merge_case_state([
            _gb(property={"land_registry_district": "Hamburg", "folio_number": "1234"}),
        ])
        assert state["property"]["land_registry_district"] == "Hamburg"
        assert state["property"]["folio_number"] == "1234"

    def test_street_falls_back_to_grundbuch_if_missing_in_vv(self):
        state = merge_case_state([
            _vv(property={"number": "HAM61"}),
            _gb(property={"street": "Hamburger Str. 61"}),
        ])
        assert state["property"]["street"] == "Hamburger Str. 61"


class TestMergeOwner:
    def test_owner_only_from_grundbuch(self):
        state = merge_case_state([
            _gb(owner={"last_name": "Mustermann", "first_name": "Max"}),
        ])
        assert state["owner"] == {"last_name": "Mustermann", "first_name": "Max"}

    def test_owner_ignored_from_verwaltervertrag(self):
        # Wichtig: Eigentuemer kommt NUR aus Grundbuch
        state = merge_case_state([
            _vv(owner={"last_name": "Ausverwaltervertrag"}),
        ])
        assert state["owner"] is None

    def test_owner_with_company_name_accepted(self):
        state = merge_case_state([
            _gb(owner={"company_name": "Schmidt Immobilien GmbH"}),
        ])
        assert state["owner"]["company_name"] == "Schmidt Immobilien GmbH"

    def test_owner_without_name_is_none(self):
        state = merge_case_state([
            _gb(owner={"street": "Ohne Namen"}),
        ])
        assert state["owner"] is None


class TestMergeBuildingsAndUnits:
    def test_buildings_from_mieterliste_unique(self):
        state = merge_case_state([
            _ml(buildings=[{"name": "Block A"}, {"name": "Block B"}, {"name": "Block A"}]),
        ])
        names = [b["name"] for b in state["buildings"]]
        assert names == ["Block A", "Block B"]

    def test_units_from_mieterliste(self):
        state = merge_case_state([
            _ml(units=[
                {"number": "1", "unit_type": "APARTMENT", "living_area": 85},
                {"number": "2", "unit_type": "APARTMENT", "living_area": 70},
            ]),
        ])
        assert len(state["units"]) == 2
        assert {u["number"] for u in state["units"]} == {"1", "2"}

    def test_units_merged_from_mietvertrag_when_same_number(self):
        state = merge_case_state([
            _ml(units=[{"number": "1", "unit_type": "APARTMENT"}]),
            _mv(unit={"number": "1", "living_area": 85, "floor": 2}),
        ])
        # Unit 1 soll um living_area + floor ergaenzt worden sein
        u1 = [u for u in state["units"] if u["number"] == "1"][0]
        assert u1["living_area"] == 85
        assert u1["floor"] == 2
        assert u1["unit_type"] == "APARTMENT"


class TestMergeTenantContracts:
    def test_one_tenant_contract_per_mietvertrag(self):
        state = merge_case_state([
            _mv(doc_id="d1", unit={"number": "1"}, tenant={"last_name": "Mueller"}, contract={"cold_rent": 800}),
            _mv(doc_id="d2", unit={"number": "2"}, tenant={"last_name": "Schmidt"}, contract={"cold_rent": 900}),
        ])
        assert len(state["tenant_contracts"]) == 2
        tenants = {tc["tenant"]["last_name"] for tc in state["tenant_contracts"]}
        assert tenants == {"Mueller", "Schmidt"}

    def test_tenant_fallback_from_mieterliste_when_no_mietvertrag(self):
        state = merge_case_state([
            _ml(units=[
                {"number": "1", "tenant_name": "Frau Meier", "cold_rent": 800},
            ]),
        ])
        assert len(state["tenant_contracts"]) == 1
        tc = state["tenant_contracts"][0]
        assert tc["tenant"]["company_name"] == "Frau Meier"
        assert tc.get("_partial") is True

    def test_mietvertrag_suppresses_mieterliste_fallback_for_same_unit(self):
        state = merge_case_state([
            _mv(doc_id="d1", unit={"number": "1"}, tenant={"last_name": "Mueller"}, contract={}),
            _ml(units=[{"number": "1", "tenant_name": "Veraltet"}]),
        ])
        # Nur EIN Tenant-Contract (der aus dem Mietvertrag)
        assert len(state["tenant_contracts"]) == 1
        assert state["tenant_contracts"][0]["tenant"]["last_name"] == "Mueller"


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------

class TestOverridesDictSections:
    def test_override_merges_field_into_property(self):
        state = merge_case_state(
            [_vv(property={"number": "HAM61", "name": "WEG Altstadt"})],
            overrides={"property": {"creditor_id": "DE71ZZZ00002822264"}},
        )
        assert state["property"]["number"] == "HAM61"  # Auto bleibt
        assert state["property"]["name"] == "WEG Altstadt"
        assert state["property"]["creditor_id"] == "DE71ZZZ00002822264"  # Override

    def test_override_replaces_auto_value(self):
        state = merge_case_state(
            [_vv(property={"number": "HAM61"})],
            overrides={"property": {"number": "HAM62"}},
        )
        assert state["property"]["number"] == "HAM62"

    def test_owner_override_with_empty_dict_clears(self):
        state = merge_case_state(
            [_gb(owner={"last_name": "Mustermann"})],
            overrides={"owner": {}},
        )
        assert state["owner"] is None

    def test_owner_override_with_fields_merges(self):
        state = merge_case_state(
            [_gb(owner={"last_name": "Mustermann"})],
            overrides={"owner": {"first_name": "Max"}},
        )
        assert state["owner"]["last_name"] == "Mustermann"
        assert state["owner"]["first_name"] == "Max"


class TestOverridesListSections:
    def test_buildings_override_replaces_completely(self):
        state = merge_case_state(
            [_ml(buildings=[{"name": "Block A"}, {"name": "Block B"}])],
            overrides={"buildings": [{"name": "Nur A"}]},
        )
        assert state["buildings"] == [{"name": "Nur A"}]

    def test_units_override_replaces_completely(self):
        state = merge_case_state(
            [_ml(units=[{"number": "1"}, {"number": "2"}])],
            overrides={"units": [{"number": "99", "unit_type": "COMMERCIAL"}]},
        )
        assert state["units"] == [{"number": "99", "unit_type": "COMMERCIAL"}]

    def test_tenant_contracts_override_replaces_completely(self):
        state = merge_case_state(
            [_mv(unit={"number": "1"}, tenant={"last_name": "Auto"}, contract={})],
            overrides={"tenant_contracts": []},
        )
        assert state["tenant_contracts"] == []


# ---------------------------------------------------------------------------
# _extractions + _overrides Persistence
# ---------------------------------------------------------------------------

class TestExtractionsProvenance:
    def test_extractions_block_indexed_by_doc_id(self):
        state = merge_case_state([
            _vv(doc_id="abc", property={"number": "HAM61"}),
            _gb(doc_id="xyz", owner={"last_name": "M"}),
        ])
        assert "abc" in state["_extractions"]
        assert state["_extractions"]["abc"]["doc_type"] == "verwaltervertrag"
        assert state["_extractions"]["xyz"]["doc_type"] == "grundbuch"

    def test_overrides_preserved_in_state(self):
        ov = {"property": {"creditor_id": "DE71ZZZ00002822264"}}
        state = merge_case_state([_vv(property={"number": "HAM61"})], overrides=ov)
        assert state["_overrides"] == ov


# ---------------------------------------------------------------------------
# field_source — Provenance per Feld
# ---------------------------------------------------------------------------

class TestFieldSource:
    def test_missing_when_state_is_none(self):
        assert field_source(None, "property", "number") == {"state": "missing"}

    def test_missing_when_field_empty(self):
        state = merge_case_state([])
        assert field_source(state, "property", "number") == {"state": "missing"}

    def test_auto_with_doc_type_when_from_extraction(self):
        state = merge_case_state([_vv(doc_id="abc", property={"number": "HAM61"})])
        src = field_source(state, "property", "number")
        assert src["state"] == "auto"
        assert src["doc_type"] == "verwaltervertrag"
        assert src["doc_id"] == "abc"

    def test_auto_without_doc_type_for_default_country(self):
        # country=DE wird vom Merge gesetzt, nicht aus einer Extraction
        state = merge_case_state([_vv(property={"street": "X", "postal_code": "1", "city": "Y"})])
        src = field_source(state, "property", "country")
        assert src["state"] == "auto"
        # Kein doc_type, da der Wert nicht aus einer Extraction kommt
        assert "doc_type" not in src

    def test_user_state_when_override_set(self):
        state = merge_case_state(
            [_vv(property={"number": "HAM61"})],
            overrides={"property": {"number": "USER_VALUE"}},
        )
        assert field_source(state, "property", "number") == {"state": "user"}

    def test_user_beats_auto_even_if_same_value(self):
        state = merge_case_state(
            [_vv(property={"number": "HAM61"})],
            overrides={"property": {"number": "HAM61"}},
        )
        assert field_source(state, "property", "number") == {"state": "user"}

    def test_empty_override_overwrites_auto_with_missing(self):
        # Leerer String als Override ueberschreibt den Auto-Wert: der gemergte
        # Wert ist leer, die Provenance ist "missing". So kann der User einen
        # automatisch uebernommenen Wert bewusst leeren.
        state = merge_case_state(
            [_vv(property={"number": "HAM61"})],
            overrides={"property": {"number": ""}},
        )
        assert state["property"].get("number") == ""
        assert field_source(state, "property", "number") == {"state": "missing"}
