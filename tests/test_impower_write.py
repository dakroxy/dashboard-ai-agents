"""Unit- und Service-Tests fuer den Impower-Write-Pfad (M3 SEPA).

Alle externen HTTP-Calls sind gemockt. Tests decken:
- `_normalize_iban` (Unicode-Haertung gegen Zero-Width-Spaces)
- `_strip_server_fields` (Field-Whitelist beim PUT)
- `_derive_bic_from_iban` (schwifty-BLZ-Register)
- `_build_contact_payload` (Pflichtfeld + Stripping)
- `write_sepa_mandate` Idempotenz-Zweig (already_present)
- `write_sepa_mandate` Neuanlage-Zweig (PUT Contact + POST Mandat + POST UCM-Array)
- `write_sepa_mandate` BIC-Ableitung bei leerem BIC
- `write_sepa_mandate` Fehler bei ungueltiger IBAN
"""
from __future__ import annotations

import pytest

from app.services import impower as imp
from app.services.impower import (
    WriteResult,
    _build_contact_payload,
    _derive_bic_from_iban,
    _normalize_iban,
    _strip_server_fields,
    write_sepa_mandate,
)


# ---------------------------------------------------------------------------
# _normalize_iban
# ---------------------------------------------------------------------------

class TestNormalizeIban:
    def test_plain_iban_uppercased(self):
        assert _normalize_iban("de89370400440532013000") == "DE89370400440532013000"

    def test_whitespace_removed(self):
        assert _normalize_iban("DE89 3704 0044 0532 0130 00") == "DE89370400440532013000"

    def test_zero_width_space_removed(self):
        # U+200B ZWSP darf nicht durchrutschen (Memory: feedback_llm_iban_unicode_normalize)
        iban_with_zwsp = "DE89​370400440532013000"
        assert _normalize_iban(iban_with_zwsp) == "DE89370400440532013000"

    def test_tab_and_nbsp_removed(self):
        iban = "DE89\t3704 0044 0532 0130 00"
        assert _normalize_iban(iban) == "DE89370400440532013000"

    def test_empty_returns_empty(self):
        assert _normalize_iban("") == ""

    def test_none_returns_empty(self):
        assert _normalize_iban(None) == ""

    def test_keeps_digits_and_letters_only(self):
        assert _normalize_iban("DE-89/3704.0044*0532 0130 00") == "DE89370400440532013000"


# ---------------------------------------------------------------------------
# _strip_server_fields
# ---------------------------------------------------------------------------

class TestStripServerFields:
    def test_removes_all_managed_fields(self):
        item = {
            "id": 1,
            "iban": "DE89370400440532013000",
            "created": "2024-01-01",
            "createdBy": "user42",
            "updated": "2024-02-01",
            "updatedBy": "user43",
            "domainId": 100,
            "casaviSyncData": {"foo": "bar"},
        }
        out = _strip_server_fields(item)
        assert out == {"id": 1, "iban": "DE89370400440532013000"}

    def test_noop_when_no_managed_fields(self):
        item = {"iban": "DE89370400440532013000", "bic": "COBADEFFXXX"}
        assert _strip_server_fields(item) == item

    def test_keeps_other_fields(self):
        item = {"id": 1, "created": "x", "something": "else"}
        assert _strip_server_fields(item) == {"id": 1, "something": "else"}


# ---------------------------------------------------------------------------
# _derive_bic_from_iban
# ---------------------------------------------------------------------------

class TestDeriveBic:
    def test_known_blz_returns_bic(self):
        # Commerzbank BLZ 37040044, valide Pruefziffer
        bic = _derive_bic_from_iban("DE89370400440532013000")
        assert bic is not None
        assert isinstance(bic, str)
        assert len(bic) in (8, 11)

    def test_invalid_iban_returns_none(self):
        # Syntaktisch kaputte IBAN darf keinen BIC liefern
        assert _derive_bic_from_iban("NOT_AN_IBAN") is None


# ---------------------------------------------------------------------------
# _build_contact_payload
# ---------------------------------------------------------------------------

class TestBuildContactPayload:
    def test_type_defaults_to_person_if_missing(self):
        assert _build_contact_payload("")["type"] == "PERSON"

    def test_unknown_type_falls_back_to_person(self):
        assert _build_contact_payload("ALIEN")["type"] == "PERSON"

    def test_company_type_preserved(self):
        assert _build_contact_payload("COMPANY")["type"] == "COMPANY"

    def test_management_company_type_preserved(self):
        assert _build_contact_payload("MANAGEMENT_COMPANY")["type"] == "MANAGEMENT_COMPANY"

    def test_type_uppercased_and_trimmed(self):
        assert _build_contact_payload("  person  ")["type"] == "PERSON"

    def test_empty_strings_dropped(self):
        payload = _build_contact_payload("PERSON", first_name="", last_name="  ", email=None)
        assert "firstName" not in payload
        assert "lastName" not in payload
        assert "email" not in payload

    def test_strips_whitespace_on_values(self):
        payload = _build_contact_payload("PERSON", last_name="  Kroll  ")
        assert payload["lastName"] == "Kroll"

    def test_addresses_without_content_dropped(self):
        payload = _build_contact_payload(
            "PERSON", last_name="X", addresses=[{"street": "", "postalCode": "", "city": ""}],
        )
        assert "addresses" not in payload

    def test_addresses_with_content_kept(self):
        payload = _build_contact_payload(
            "PERSON", last_name="X",
            addresses=[{"street": "Hauptstr. 1", "postalCode": "20099", "city": "Hamburg"}],
        )
        assert payload["addresses"] == [
            {"street": "Hauptstr. 1", "postalCode": "20099", "city": "Hamburg"}
        ]


# ---------------------------------------------------------------------------
# write_sepa_mandate — Mocking-Infrastruktur
# ---------------------------------------------------------------------------

class _FakeClient:
    """Async-Context-Manager-Placeholder — echte Request-Arbeit laeuft in den
    gemockten _api_*-Funktionen, der Client wird nur als Token weitergereicht."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _ApiRecorder:
    """Sammelt API-Calls + liefert programmierte Antworten.

    Nutzung:
        rec = _ApiRecorder()
        rec.on_get("/services/pmp-accounting/api/v1/contacts/42", {"id": 42, ...})
        rec.on_put("/services/pmp-accounting/api/v1/contacts/42", lambda p: {...})
        rec.on_post("/services/pmp-accounting/api/v1/direct-debit-mandate", {"id": 999})
    """

    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], object] = {}
        self.calls: list[dict] = []

    def on(self, method: str, path: str, response) -> None:
        self._handlers[(method, path)] = response

    def on_get(self, path: str, response) -> None:
        self.on("GET", path, response)

    def on_post(self, path: str, response) -> None:
        self.on("POST", path, response)

    def on_put(self, path: str, response) -> None:
        self.on("PUT", path, response)

    def _resolve(self, method: str, path: str, payload=None):
        key = (method, path)
        handler = self._handlers.get(key)
        if handler is None:
            raise AssertionError(f"Unerwarteter {method} {path} (Payload={payload!r})")
        if callable(handler):
            return handler(payload)
        return handler

    async def fake_get(self, _client, path, params=None):
        self.calls.append({"method": "GET", "path": path, "params": params})
        return self._resolve("GET", path)

    async def fake_post(self, _client, path, payload):
        self.calls.append({"method": "POST", "path": path, "payload": payload})
        return self._resolve("POST", path, payload)

    async def fake_put(self, _client, path, payload):
        self.calls.append({"method": "PUT", "path": path, "payload": payload})
        return self._resolve("PUT", path, payload)


@pytest.fixture
def api(monkeypatch):
    rec = _ApiRecorder()
    monkeypatch.setattr(imp, "_make_client", lambda: _FakeClient())
    monkeypatch.setattr(imp, "_api_get", rec.fake_get)
    monkeypatch.setattr(imp, "_api_post", rec.fake_post)
    monkeypatch.setattr(imp, "_api_put", rec.fake_put)
    return rec


# ---------------------------------------------------------------------------
# write_sepa_mandate
# ---------------------------------------------------------------------------

_IBAN = "DE89370400440532013000"
_BIC = "COBADEFFXXX"


class TestWriteSepaMandateIdempotent:
    async def test_already_present_short_circuits(self, api):
        api.on_get(
            "/services/pmp-accounting/api/v1/contacts/42",
            {"id": 42, "bankAccounts": [{"id": 700, "iban": _IBAN, "bic": _BIC}]},
        )
        api.on_get(
            "/services/pmp-accounting/api/v1/direct-debit-mandate",
            [{"id": 555, "bankAccountId": 700, "state": "BOOKED"}],
        )

        result = await write_sepa_mandate(
            contact_id=42,
            property_id=1,
            open_contract_ids=[101, 102],
            iban=_IBAN,
            bic=_BIC,
            holder_name="Max Mustermann",
            signed_date="2024-01-01",
        )

        assert isinstance(result, WriteResult)
        assert result.already_present is True
        assert result.direct_debit_mandate_id == 555
        assert result.bank_account_id == 700
        assert result.bank_account_created is False
        # KEIN POST im Idempotenz-Zweig
        post_calls = [c for c in api.calls if c["method"] == "POST"]
        assert post_calls == []
        # KEIN PUT im Idempotenz-Zweig (Bank-Account existierte schon)
        put_calls = [c for c in api.calls if c["method"] == "PUT"]
        assert put_calls == []

    async def test_same_bank_account_but_no_booked_mandate_creates_mandate(self, api):
        # Bank-Account existiert, aber kein BOOKED-Mandat → Neuanlage
        api.on_get(
            "/services/pmp-accounting/api/v1/contacts/42",
            {"id": 42, "bankAccounts": [{"id": 700, "iban": _IBAN, "bic": _BIC}]},
        )
        api.on_get(
            "/services/pmp-accounting/api/v1/direct-debit-mandate",
            [{"id": 111, "bankAccountId": 700, "state": "DEACTIVATED"}],
        )
        api.on_post(
            "/services/pmp-accounting/api/v1/direct-debit-mandate",
            {"id": 800},
        )
        api.on_post(
            "/services/pmp-accounting/api/v1/unit-contract-mandate",
            [{"id": 9001}, {"id": 9002}],
        )

        result = await write_sepa_mandate(
            contact_id=42, property_id=1, open_contract_ids=[101, 102],
            iban=_IBAN, bic=_BIC, holder_name="Max", signed_date="2024-01-01",
        )

        assert result.already_present is False
        assert result.bank_account_id == 700
        assert result.bank_account_created is False
        assert result.direct_debit_mandate_id == 800
        assert result.unit_contract_mandate_ids == [9001, 9002]


class TestWriteSepaMandateNewCreate:
    async def test_full_new_flow_sends_put_post_post(self, api):
        """Neuanlage-Zweig: Contact ohne Bank-Account → PUT Contact mit neuem
        Account, POST Mandat, POST UCM-Array."""
        # 1. GET Contact (keine bankAccounts)
        api.on_get(
            "/services/pmp-accounting/api/v1/contacts/42",
            {"id": 42, "firstName": "Max", "lastName": "Mustermann", "bankAccounts": []},
        )

        # 2. PUT Contact → Response mit neuer bankAccountId
        def put_response(payload):
            assert payload["id"] == 42
            assert len(payload["bankAccounts"]) == 1
            new_ba = payload["bankAccounts"][0]
            assert new_ba["iban"] == _IBAN
            assert new_ba["bic"] == _BIC
            assert new_ba["accountHolderName"] == "Max Mustermann"
            # Server-managed Fields duerfen nicht im Payload stehen
            assert "created" not in payload
            assert "updated" not in payload
            return {
                "id": 42,
                "bankAccounts": [{"id": 900, "iban": _IBAN, "bic": _BIC}],
            }

        api.on_put("/services/pmp-accounting/api/v1/contacts/42", put_response)

        # 3. GET existing mandates (leer)
        api.on_get("/services/pmp-accounting/api/v1/direct-debit-mandate", [])

        # 4. POST Mandat
        def post_mandate(payload):
            assert payload["propertyId"] == 1
            assert payload["bankAccountId"] == 900
            assert payload["directDebitSignedOnDate"] == "2024-03-15"
            assert "state" not in payload
            return {"id": 2001}

        api.on_post(
            "/services/pmp-accounting/api/v1/direct-debit-mandate", post_mandate,
        )

        # 5. POST UCM-Array (EIN Call, nicht Loop)
        def post_ucm(payload):
            assert isinstance(payload, list)
            assert len(payload) == 2
            assert payload[0]["directDebitMandateId"] == 2001
            assert payload[0]["state"] == "BOOKED"
            return [{"id": 7001}, {"id": 7002}]

        api.on_post(
            "/services/pmp-accounting/api/v1/unit-contract-mandate", post_ucm,
        )

        result = await write_sepa_mandate(
            contact_id=42, property_id=1, open_contract_ids=[101, 102],
            iban=_IBAN, bic=_BIC, holder_name="Max Mustermann",
            signed_date="2024-03-15",
        )

        assert result.error is None
        assert result.bank_account_created is True
        assert result.bank_account_id == 900
        assert result.direct_debit_mandate_id == 2001
        assert result.unit_contract_mandate_ids == [7001, 7002]

        methods = [(c["method"], c["path"]) for c in api.calls]
        # Reihenfolge entscheidend: GET Contact → PUT Contact → GET Mandate → POST Mandat → POST UCM
        assert methods == [
            ("GET", "/services/pmp-accounting/api/v1/contacts/42"),
            ("PUT", "/services/pmp-accounting/api/v1/contacts/42"),
            ("GET", "/services/pmp-accounting/api/v1/direct-debit-mandate"),
            ("POST", "/services/pmp-accounting/api/v1/direct-debit-mandate"),
            ("POST", "/services/pmp-accounting/api/v1/unit-contract-mandate"),
        ]

    async def test_put_strips_server_fields_from_existing_accounts(self, api):
        # Memory: project_impower_bank_account_flow — Server-Felder muessen
        # aus bestehenden bankAccounts[]-Items raus, sonst 400
        api.on_get(
            "/services/pmp-accounting/api/v1/contacts/42",
            {
                "id": 42,
                "bankAccounts": [
                    {
                        "id": 700, "iban": "DE02100500000024290661",
                        "bic": "BELADEBEXXX",
                        "created": "2023-01-01T00:00:00Z",
                        "createdBy": "x", "updated": "2024-01-01",
                        "updatedBy": "y", "domainId": 1,
                        "casaviSyncData": {"foo": "bar"},
                    },
                ],
            },
        )

        captured = {}

        def put_handler(payload):
            captured["accounts"] = payload["bankAccounts"]
            return {
                "id": 42,
                "bankAccounts": payload["bankAccounts"][:1] + [
                    {"id": 900, "iban": _IBAN, "bic": _BIC},
                ],
            }

        api.on_put("/services/pmp-accounting/api/v1/contacts/42", put_handler)
        api.on_get("/services/pmp-accounting/api/v1/direct-debit-mandate", [])
        api.on_post(
            "/services/pmp-accounting/api/v1/direct-debit-mandate", {"id": 2001},
        )
        api.on_post(
            "/services/pmp-accounting/api/v1/unit-contract-mandate",
            [{"id": 7001}],
        )

        await write_sepa_mandate(
            contact_id=42, property_id=1, open_contract_ids=[101],
            iban=_IBAN, bic=_BIC, holder_name="Max", signed_date="2024-01-01",
        )

        existing = captured["accounts"][0]
        for managed in ("created", "createdBy", "updated", "updatedBy", "domainId", "casaviSyncData"):
            assert managed not in existing, f"{managed} haette gestrippt werden muessen"
        # ID + Kern-Felder bleiben
        assert existing["id"] == 700
        assert existing["iban"] == "DE02100500000024290661"


class TestWriteSepaMandateBicDerivation:
    async def test_missing_bic_derived_from_iban(self, api):
        """Wenn BIC leer ist, wird er via schwifty aus der IBAN abgeleitet."""
        api.on_get(
            "/services/pmp-accounting/api/v1/contacts/42",
            {"id": 42, "bankAccounts": []},
        )

        captured_bic: dict = {}

        def put_handler(payload):
            captured_bic["bic"] = payload["bankAccounts"][0]["bic"]
            return {
                "id": 42,
                "bankAccounts": [
                    {"id": 900, "iban": _IBAN, "bic": payload["bankAccounts"][0]["bic"]},
                ],
            }

        api.on_put("/services/pmp-accounting/api/v1/contacts/42", put_handler)
        api.on_get("/services/pmp-accounting/api/v1/direct-debit-mandate", [])
        api.on_post(
            "/services/pmp-accounting/api/v1/direct-debit-mandate", {"id": 2001},
        )
        api.on_post(
            "/services/pmp-accounting/api/v1/unit-contract-mandate", [{"id": 7001}],
        )

        result = await write_sepa_mandate(
            contact_id=42, property_id=1, open_contract_ids=[101],
            iban=_IBAN, bic="",  # <— leer, muss abgeleitet werden
            holder_name="Max", signed_date="2024-01-01",
        )

        assert result.error is None
        assert captured_bic["bic"], "BIC wurde nicht abgeleitet"
        assert len(captured_bic["bic"]) in (8, 11)


class TestWriteSepaMandateErrors:
    async def test_invalid_iban_captured_in_error(self, api):
        # Bei ungueltiger IBAN wird in _ensure_bank_account bereits validiert,
        # bevor GET auf den Contact ueberhaupt laeuft — d.h. die API muss
        # garnichts antworten koennen. Der Fehler landet als String in result.error.
        result = await write_sepa_mandate(
            contact_id=42, property_id=1, open_contract_ids=[101],
            iban="DE00INVALIDIBAN", bic=_BIC,
            holder_name="Max", signed_date="2024-01-01",
        )
        assert result.error is not None
        assert "ungueltig" in result.error.lower() or "invalid" in result.error.lower()
        # Kein einziger API-Call darf rausgehen
        assert api.calls == []

    async def test_unknown_blz_and_no_bic_fails_clean(self, api):
        # IBAN in einem Land wo schwifty keine BLZ-Registry hat → BIC nicht
        # ableitbar und kein User-BIC mitgegeben → klarer Fehler, kein PUT.
        # Malta-IBAN hat ein valides Prueffeld, aber kein Bundesbank-BLZ.
        api.on_get(
            "/services/pmp-accounting/api/v1/contacts/42",
            {"id": 42, "bankAccounts": []},
        )
        result = await write_sepa_mandate(
            contact_id=42, property_id=1, open_contract_ids=[101],
            iban="MT84MALT011000012345MTLCAST001S", bic="",
            holder_name="Max", signed_date="2024-01-01",
        )
        assert result.error is not None
        assert "BIC" in result.error
        # Nur GET Contact lief, kein PUT / POST
        methods = [c["method"] for c in api.calls]
        assert "PUT" not in methods
        assert "POST" not in methods
