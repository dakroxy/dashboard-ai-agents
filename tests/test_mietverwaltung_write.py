"""Service-Tests fuer den Mietverwaltungs-Write-Pfad (M5 Paket 7).

Deckt:
- `preflight` auf Minimalanforderungen
- `_ensure_impower_result` Initialisierung
- `_tenant_key` deterministisch
- `_write_all_steps` volle Pipeline mit gemockter Impower-API
- Idempotenz: zweiter Durchlauf ueberspringt bereits erledigte Schritte
- Partial-Fail in einem Zwischenschritt wirft sauber `ImpowerError`

Alle Tests laufen gegen gemockte `_api_post` / `_api_put`, keine Netzwerk-Calls.
"""
from __future__ import annotations

import asyncio

import pytest

from app.services import mietverwaltung_write as mw
from app.services.impower import ImpowerError
from app.services.mietverwaltung_write import (
    _ensure_impower_result,
    _tenant_key,
    _write_all_steps,
    preflight,
)


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

class TestPreflight:
    def test_empty_state_fails_cleanly(self):
        res = preflight({})
        assert res.ok is False
        assert any("property.number" in m for m in res.missing)
        assert any("owner" in m for m in res.missing)
        assert any("units" in m for m in res.missing)

    def test_full_state_passes(self):
        state = {
            "property": {
                "number": "HAM61", "street": "Hauptstr. 1",
                "postal_code": "20099", "city": "Hamburg",
            },
            "owner": {"last_name": "Mustermann"},
            "units": [{"number": "1"}],
        }
        assert preflight(state).ok is True

    def test_owner_company_name_is_sufficient(self):
        state = {
            "property": {
                "number": "HAM61", "street": "X", "postal_code": "1", "city": "Y",
            },
            "owner": {"company_name": "Schmidt Immobilien GmbH"},
            "units": [{"number": "1"}],
        }
        assert preflight(state).ok is True

    def test_missing_units_reported(self):
        state = {
            "property": {
                "number": "HAM61", "street": "X", "postal_code": "1", "city": "Y",
            },
            "owner": {"last_name": "M"},
            "units": [],
        }
        res = preflight(state)
        assert res.ok is False
        assert any("units" in m for m in res.missing)


# ---------------------------------------------------------------------------
# _ensure_impower_result
# ---------------------------------------------------------------------------

class TestEnsureImpowerResult:
    def test_initializes_all_keys_on_empty_case(self):
        class _Case:
            impower_result = None

        ir = _ensure_impower_result(_Case())
        assert ir["contacts"] == {"tenants": {}}
        assert ir["building_ids"] == []
        assert ir["unit_ids"] == {}
        assert ir["tenant_contract_ids"] == {}
        assert ir["exchange_plan_ids"] == {}
        assert ir["deposit_ids"] == {}
        assert ir["steps_completed"] == []
        assert ir["errors"] == []

    def test_preserves_existing_values(self):
        class _Case:
            impower_result = {
                "property_id": 99,
                "contacts": {"owner_id": 42, "tenants": {"1": 101}},
                "steps_completed": ["owner_contact"],
            }

        ir = _ensure_impower_result(_Case())
        assert ir["property_id"] == 99
        assert ir["contacts"]["owner_id"] == 42
        assert ir["contacts"]["tenants"] == {"1": 101}
        assert "owner_contact" in ir["steps_completed"]


# ---------------------------------------------------------------------------
# _tenant_key
# ---------------------------------------------------------------------------

class TestTenantKey:
    def test_prefers_unit_number(self):
        assert _tenant_key({"unit_number": "3A", "source_doc_id": "xx"}) == "3A"

    def test_falls_back_to_source_doc_id(self):
        assert _tenant_key({"unit_number": None, "source_doc_id": "doc-99"}) == "doc-99"

    def test_stable_when_identifiers_identical(self):
        a = {"unit_number": "1"}
        b = {"unit_number": "1"}
        assert _tenant_key(a) == _tenant_key(b)


# ---------------------------------------------------------------------------
# _write_all_steps — Mocking-Infrastruktur
# ---------------------------------------------------------------------------

class _FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _WriteRecorder:
    """Sammelt POST/PUT-Calls an die Impower-Write-API und liefert programmierte
    Antworten pro (Methode, Pfad)-Key. Wenn der Handler ein Callable ist, wird
    er mit dem Payload aufgerufen."""

    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], object] = {}
        self.calls: list[dict] = []

    def on(self, method: str, path: str, response) -> None:
        self._handlers[(method, path)] = response

    def on_post(self, path: str, response) -> None:
        self.on("POST", path, response)

    def on_put(self, path: str, response) -> None:
        self.on("PUT", path, response)

    def _resolve(self, method: str, path: str, payload):
        handler = self._handlers.get((method, path))
        if handler is None:
            raise AssertionError(f"Unerwarteter {method} {path} (Payload={payload!r})")
        if callable(handler):
            return handler(payload)
        return handler

    async def fake_post(self, _client, path, payload):
        self.calls.append({"method": "POST", "path": path, "payload": payload})
        return self._resolve("POST", path, payload)

    async def fake_put(self, _client, path, payload):
        self.calls.append({"method": "PUT", "path": path, "payload": payload})
        return self._resolve("PUT", path, payload)


@pytest.fixture
def api(monkeypatch):
    rec = _WriteRecorder()
    monkeypatch.setattr(mw, "_make_client", lambda: _FakeClient())
    monkeypatch.setattr(mw, "_api_post", rec.fake_post)
    monkeypatch.setattr(mw, "_api_put", rec.fake_put)
    return rec


def _full_case_state() -> dict:
    """Minimal vollstaendiger Case-State fuer den Happy-Path."""
    return {
        "property": {
            "number": "HAM61",
            "name": "WEG Hamburger Str. 61",
            "street": "Hamburger Str. 61",
            "postal_code": "20099",
            "city": "Hamburg",
            "country": "DE",
            "creditor_id": "DE71ZZZ00002822264",
        },
        "management_contract": {
            "supervisor_name": "Daniel Kroll",
            "contract_start_date": "2024-01-01",
        },
        "billing_address": None,
        "owner": {"type": "PERSON", "last_name": "Mustermann", "first_name": "Max"},
        "buildings": [{"name": "Haupthaus"}],
        "units": [
            {"number": "1", "unit_type": "APARTMENT", "living_area": 85},
            {"number": "2", "unit_type": "APARTMENT", "living_area": 70},
        ],
        "tenant_contracts": [
            {
                "source_doc_id": "d-mv-1",
                "unit_number": "1",
                "tenant": {"type": "PERSON", "last_name": "Mueller", "first_name": "Anna"},
                "contract": {
                    "start_date": "2024-02-01",
                    "cold_rent": 800,
                    "operating_costs": 150,
                    "heating_costs": 80,
                    "deposit": 2400,
                },
            },
            {
                "source_doc_id": "d-mv-2",
                "unit_number": "2",
                "tenant": {"type": "PERSON", "last_name": "Schmidt"},
                "contract": {
                    "start_date": "2024-03-01",
                    "cold_rent": 700,
                },
            },
        ],
    }


def _wire_happy_path(api) -> None:
    """Alle Antworten fuer einen erfolgreichen Durchlauf programmieren."""
    # 1a. Owner-Contact + 1b. Tenants (alle gehen an /contacts)
    contact_ids = iter([5001, 6001, 6002])

    def post_contact(_payload):
        return {"id": next(contact_ids)}

    api.on_post("/services/pmp-accounting/api/v1/contacts", post_contact)

    # 2. Property
    api.on_post("/services/pmp-accounting/api/v1/properties", {"id": 900})

    # 3. PROPERTY_OWNER-Contract (Array-POST) und 6. TENANT-Vertraege
    contract_ids = iter([3001, 3002, 3003])

    def post_contracts(_payload):
        # Jedes Array-Element bekommt eine ID
        return [{"id": next(contract_ids)} for _ in _payload]

    api.on_post("/services/pmp-accounting/api/v1/contracts", post_contracts)

    # 4. PUT Property mit Buildings
    api.on_put(
        "/services/pmp-accounting/api/v1/properties",
        {
            "id": 900,
            "buildings": [{"id": 4001, "name": "Haupthaus"}],
        },
    )

    # 5. Units (Array-POST)
    unit_ids = iter([5101, 5102])

    def post_units(_payload):
        return [{"id": next(unit_ids)} for _ in _payload]

    api.on_post("/services/pmp-accounting/api/v1/units", post_units)

    # 7. Exchange-Plan (pro Mietvertrag ein POST)
    plan_ids = iter([7001, 7002])

    def post_plan(_payload):
        return {"id": next(plan_ids)}

    api.on_post("/services/pmp-accounting/api/v1/exchange-plan", post_plan)

    # 8. Deposits (Array-POST)
    deposit_ids = iter([8001])

    def post_deposits(_payload):
        return [{"id": next(deposit_ids)} for _ in _payload]

    api.on_post("/services/pmp-accounting/api/v1/plan/manual/deposit", post_deposits)


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

class TestWriteAllStepsHappyPath:
    def test_all_steps_run_and_persist_ids(self, api):
        _wire_happy_path(api)
        state = _full_case_state()
        ir = _ensure_impower_result(type("C", (), {"impower_result": None})())

        asyncio.run(_write_all_steps(state, ir))

        # IDs sind gesetzt
        assert ir["contacts"]["owner_id"] == 5001
        assert ir["contacts"]["tenants"] == {"1": 6001, "2": 6002}
        assert ir["property_id"] == 900
        assert ir["property_owner_contract_id"] == 3001
        assert ir["building_ids"] == [4001]
        assert ir["building_name_to_id"] == {"Haupthaus": 4001}
        assert ir["unit_ids"] == {"1": 5101, "2": 5102}
        assert ir["tenant_contract_ids"] == {"1": 3002, "2": 3003}
        assert set(ir["exchange_plan_ids"]) == {"1", "2"}
        assert ir["deposit_ids"] == {"1": 8001}  # nur Mieter 1 hat deposit

    def test_call_sequence_matches_specification(self, api):
        """Die Reihenfolge der API-Calls muss exakt der dokumentierten
        8-Step-Pipeline entsprechen."""
        _wire_happy_path(api)
        state = _full_case_state()
        ir = _ensure_impower_result(type("C", (), {"impower_result": None})())

        asyncio.run(_write_all_steps(state, ir))

        sequence = [(c["method"], c["path"]) for c in api.calls]
        expected_start = [
            # Schritt 1a + 1b: Contacts
            ("POST", "/services/pmp-accounting/api/v1/contacts"),
            ("POST", "/services/pmp-accounting/api/v1/contacts"),
            ("POST", "/services/pmp-accounting/api/v1/contacts"),
            # Schritt 2: Property
            ("POST", "/services/pmp-accounting/api/v1/properties"),
            # Schritt 3: PROPERTY_OWNER-Contract
            ("POST", "/services/pmp-accounting/api/v1/contracts"),
            # Schritt 4: PUT Property-Details
            ("PUT", "/services/pmp-accounting/api/v1/properties"),
            # Schritt 5: Units
            ("POST", "/services/pmp-accounting/api/v1/units"),
            # Schritt 6: TENANT-Vertraege
            ("POST", "/services/pmp-accounting/api/v1/contracts"),
        ]
        assert sequence[: len(expected_start)] == expected_start

    def test_unit_payload_has_expected_fields(self, api):
        _wire_happy_path(api)
        state = _full_case_state()
        ir = _ensure_impower_result(type("C", (), {"impower_result": None})())

        asyncio.run(_write_all_steps(state, ir))

        unit_call = [c for c in api.calls if c["path"].endswith("/units")][0]
        first = unit_call["payload"][0]
        assert first["propertyId"] == 900
        assert first["buildingId"] == 4001  # aus building_name_to_id-Fallback
        assert first["unitNrSharingDeclaration"] == "1"
        assert first["unitType"] == "APARTMENT"

    def test_property_owner_contract_is_sent_as_array(self, api):
        _wire_happy_path(api)
        state = _full_case_state()
        ir = _ensure_impower_result(type("C", (), {"impower_result": None})())

        asyncio.run(_write_all_steps(state, ir))

        contracts_calls = [c for c in api.calls if c["path"].endswith("/contracts")]
        # Erster /contracts-Call ist der PROPERTY_OWNER-Contract — Array
        first = contracts_calls[0]
        assert isinstance(first["payload"], list)
        assert first["payload"][0]["type"] == "PROPERTY_OWNER"
        assert first["payload"][0]["contacts"][0]["contactId"] == 5001

    def test_exchange_plan_positions_split_by_type(self, api):
        _wire_happy_path(api)
        state = _full_case_state()
        ir = _ensure_impower_result(type("C", (), {"impower_result": None})())

        asyncio.run(_write_all_steps(state, ir))

        plan_calls = [c for c in api.calls if c["path"].endswith("/exchange-plan")]
        # Mieter 1 hat cold_rent + operating_costs + heating_costs → 3 Positionen
        plan_for_unit_1 = plan_calls[0]["payload"]
        pos_types = {p["type"] for p in plan_for_unit_1["templateExchanges"]}
        assert pos_types == {"COLD_RENT", "OPERATING_COSTS", "HEATING_COSTS"}
        # Mieter 2 hat nur cold_rent
        plan_for_unit_2 = plan_calls[1]["payload"]
        pos_types_2 = {p["type"] for p in plan_for_unit_2["templateExchanges"]}
        assert pos_types_2 == {"COLD_RENT"}

    def test_deposit_only_created_when_amount_set(self, api):
        _wire_happy_path(api)
        state = _full_case_state()
        ir = _ensure_impower_result(type("C", (), {"impower_result": None})())

        asyncio.run(_write_all_steps(state, ir))

        deposit_calls = [c for c in api.calls if c["path"].endswith("/deposit")]
        assert len(deposit_calls) == 1
        # Nur EIN Deposit im Array (Mieter 1), Mieter 2 hat kein deposit-Feld
        assert len(deposit_calls[0]["payload"]) == 1
        assert deposit_calls[0]["payload"][0]["amount"] == 2400


# ---------------------------------------------------------------------------
# Idempotenz
# ---------------------------------------------------------------------------

class TestWriteAllStepsIdempotent:
    def test_replay_with_existing_ids_skips_contact_post(self, api):
        """Wenn owner_id bereits gesetzt ist, darf KEIN zweiter POST auf den
        Owner-Contact gehen."""
        _wire_happy_path(api)
        state = _full_case_state()

        # Vor-populiertes impower_result: Owner bereits angelegt
        class _Case:
            impower_result = {
                "contacts": {"owner_id": 5001, "tenants": {}},
                "steps_completed": ["owner_contact"],
            }

        ir = _ensure_impower_result(_Case())
        asyncio.run(_write_all_steps(state, ir))

        # Fuer den Owner-Contact darf kein POST gelaufen sein. Tenants (2) werden
        # aber noch angelegt. Total: 2 Tenant-Contacts statt 3 Contacts.
        contact_calls = [
            c for c in api.calls
            if c["path"] == "/services/pmp-accounting/api/v1/contacts"
        ]
        assert len(contact_calls) == 2  # nur Tenants, kein Owner
        assert ir["contacts"]["owner_id"] == 5001  # unveraendert

    def test_replay_with_all_ids_skips_everything(self, api):
        """Wenn alles schon angelegt ist, darf garnichts gepostet werden
        (ausser Put/Post ohne Idempotenz-Check). Hier: der Owner+Property+
        Contract+Units+Tenants sind schon da → nur Property-Detail-PUT,
        Exchange-Plans und Deposits werden nicht noetig wenn bereits IDs
        existieren."""
        state = _full_case_state()

        class _Case:
            impower_result = {
                "contacts": {"owner_id": 5001, "tenants": {"1": 6001, "2": 6002}},
                "property_id": 900,
                "property_owner_contract_id": 3001,
                "property_update_ok": True,
                "building_ids": [4001],
                "building_name_to_id": {"Haupthaus": 4001},
                "unit_ids": {"1": 5101, "2": 5102},
                "tenant_contract_ids": {"1": 3002, "2": 3003},
                "exchange_plan_ids": {"1": 7001, "2": 7002},
                "deposit_ids": {"1": 8001},
                "steps_completed": [],
            }

        ir = _ensure_impower_result(_Case())
        asyncio.run(_write_all_steps(state, ir))

        # Kein einziger Call darf rausgehen
        assert api.calls == []


# ---------------------------------------------------------------------------
# Fehlerpfad
# ---------------------------------------------------------------------------

class TestWriteAllStepsErrors:
    def test_property_post_error_raises_impower_error(self, api):
        """Wenn ein Schritt einen API-Error liefert, muss eine ImpowerError
        geworfen werden."""
        # Owner-Contact + Tenants OK
        contact_ids = iter([5001, 6001, 6002])
        api.on_post(
            "/services/pmp-accounting/api/v1/contacts",
            lambda _p: {"id": next(contact_ids)},
        )
        # Property-POST schlaegt fehl
        api.on_post(
            "/services/pmp-accounting/api/v1/properties",
            {"_error": 400, "_msg": "validation failed"},
        )

        state = _full_case_state()
        ir = _ensure_impower_result(type("C", (), {"impower_result": None})())

        with pytest.raises(ImpowerError) as exc_info:
            asyncio.run(_write_all_steps(state, ir))

        assert "Property anlegen" in str(exc_info.value)
        # Contacts wurden trotzdem angelegt (partial success)
        assert ir["contacts"]["owner_id"] == 5001
        assert len(ir["contacts"]["tenants"]) == 2

    def test_tenant_contract_skipped_when_unit_id_missing(self, api):
        """Wenn Unit-Anlage einen Unit-ID-Fehler hat, skippt der TENANT-Step
        die betroffene Zeile; kein Crash."""
        # Alle Contacts OK
        contact_ids = iter([5001, 6001, 6002])
        api.on_post(
            "/services/pmp-accounting/api/v1/contacts",
            lambda _p: {"id": next(contact_ids)},
        )
        api.on_post("/services/pmp-accounting/api/v1/properties", {"id": 900})
        # PROPERTY_OWNER-Contract kommt zurueck mit id=3001
        contract_ids = iter([3001, 3002])
        api.on_post(
            "/services/pmp-accounting/api/v1/contracts",
            lambda _p: [{"id": next(contract_ids)} for _ in _p],
        )
        api.on_put(
            "/services/pmp-accounting/api/v1/properties",
            {"id": 900, "buildings": [{"id": 4001, "name": "Haupthaus"}]},
        )
        # Units liefert NUR eine ID zurueck (die zweite fehlt)
        api.on_post(
            "/services/pmp-accounting/api/v1/units",
            [{"id": 5101}, {"not_id": True}],
        )
        # Exchange-Plan / Deposit nicht noetig — Tenant-Contract #2 faellt aus
        api.on_post(
            "/services/pmp-accounting/api/v1/exchange-plan",
            {"id": 7001},
        )
        api.on_post(
            "/services/pmp-accounting/api/v1/plan/manual/deposit",
            [{"id": 8001}],
        )

        state = _full_case_state()
        ir = _ensure_impower_result(type("C", (), {"impower_result": None})())

        asyncio.run(_write_all_steps(state, ir))

        # Unit 1 wurde angelegt, Unit 2 fehlt
        assert ir["unit_ids"] == {"1": 5101}
        # Tenant-Contract nur fuer Unit 1
        assert list(ir["tenant_contract_ids"].keys()) == ["1"]
