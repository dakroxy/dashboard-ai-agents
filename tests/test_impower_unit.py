"""Unit tests for Impower matching logic — no network calls, no DB."""
from __future__ import annotations

import pytest

from app.services.impower import (
    _contact_display_name,
    _similarity,
    match_contact_in_property,
    match_property,
)


# ---------------------------------------------------------------------------
# _similarity
# ---------------------------------------------------------------------------

class TestSimilarity:
    def test_identical_strings(self):
        assert _similarity("Hamburg", "Hamburg") == 1.0

    def test_case_insensitive(self):
        assert _similarity("HAMBURG", "hamburg") == 1.0

    def test_partial_overlap(self):
        score = _similarity("Hamburg Altstadt", "Hamburg")
        assert 0.5 < score < 1.0

    def test_completely_different(self):
        score = _similarity("ABCDEF", "ZYXWVU")
        assert score < 0.3

    def test_leading_trailing_whitespace_ignored(self):
        assert _similarity("  Hamburg  ", "Hamburg") == 1.0

    def test_empty_strings(self):
        assert _similarity("", "") == 1.0

    def test_empty_vs_nonempty(self):
        assert _similarity("", "Hamburg") == 0.0


# ---------------------------------------------------------------------------
# _contact_display_name
# ---------------------------------------------------------------------------

class TestContactDisplayName:
    def test_company_with_person(self):
        contact = {"companyName": "Muster GmbH", "firstName": "Max", "lastName": "Mustermann"}
        result = _contact_display_name(contact)
        assert "Muster GmbH" in result
        assert "Max Mustermann" in result

    def test_company_without_person(self):
        contact = {"companyName": "Solo GmbH", "firstName": "", "lastName": ""}
        result = _contact_display_name(contact)
        assert result == "Solo GmbH"

    def test_person_only(self):
        contact = {"companyName": "", "firstName": "Anna", "lastName": "Schmidt"}
        result = _contact_display_name(contact)
        assert result == "Anna Schmidt"

    def test_last_name_only(self):
        contact = {"companyName": "", "firstName": "", "lastName": "Kroll"}
        result = _contact_display_name(contact)
        assert result == "Kroll"

    def test_fallback_to_recipient_name(self):
        contact = {"companyName": "", "firstName": "", "lastName": "", "recipientName": "Empfaenger AG"}
        result = _contact_display_name(contact)
        assert result == "Empfaenger AG"

    def test_fallback_to_id(self):
        contact = {"id": 42}
        result = _contact_display_name(contact)
        assert "42" in result

    def test_missing_all_keys(self):
        result = _contact_display_name({})
        assert result  # must return something non-empty


# ---------------------------------------------------------------------------
# match_property
# ---------------------------------------------------------------------------

PROPS = [
    {"id": 1, "propertyHrId": "HAM61", "name": "WEG Hamburger Strasse 61", "address": "Hamburger Strasse 61, 20099 Hamburg"},
    {"id": 2, "propertyHrId": "BRE11", "name": "WEG Bremer Allee 11",      "address": "Bremer Allee 11, 28195 Bremen"},
    {"id": 3, "propertyHrId": "GVE1",  "name": "WEG Gevelsberg 1",         "address": "Kirchstrasse 5, 58285 Gevelsberg"},
]


class TestMatchProperty:
    def test_exact_kuerzel_match(self):
        match, ambiguous = match_property(PROPS, "HAM61", None, None)
        assert match is not None
        assert match.property_id == 1
        assert match.score == 1.0
        assert not ambiguous

    def test_exact_kuerzel_case_insensitive(self):
        match, _ = match_property(PROPS, "ham61", None, None)
        assert match is not None
        assert match.property_id == 1

    def test_exact_kuerzel_with_whitespace(self):
        match, _ = match_property(PROPS, " HAM61 ", None, None)
        assert match is not None
        assert match.property_id == 1

    def test_fuzzy_name_match(self):
        match, ambiguous = match_property(PROPS, None, "WEG Bremer Allee 11", None)
        assert match is not None
        assert match.property_id == 2
        assert not ambiguous

    def test_fuzzy_address_match(self):
        match, _ = match_property(PROPS, None, None, "Kirchstrasse 5, 58285 Gevelsberg")
        assert match is not None
        assert match.property_id == 3

    def test_no_match_below_threshold(self):
        match, ambiguous = match_property(PROPS, None, "Voellig unbekannte WEG XYZ", None)
        assert match is None
        assert not ambiguous

    def test_no_properties_returns_none(self):
        match, _ = match_property([], "HAM61", None, None)
        assert match is None

    def test_ambiguous_when_scores_close(self):
        # Two properties with very similar names
        similar_props = [
            {"id": 10, "propertyHrId": "A1", "name": "WEG Musterstrasse 1",  "address": ""},
            {"id": 11, "propertyHrId": "A2", "name": "WEG Musterstrasse 10", "address": ""},
        ]
        # "WEG Musterstrasse 1" should match both, possibly ambiguously
        match, ambiguous = match_property(similar_props, None, "WEG Musterstrasse 1", None)
        # Either returns a match or None; the key assertion is that ambiguous is True if both score high
        if match is not None:
            # We can only assert ambiguous if both score above threshold
            scores = [_similarity(p["name"], "WEG Musterstrasse 1") for p in similar_props]
            if all(s >= 0.72 for s in scores) and abs(scores[0] - scores[1]) < 0.05:
                assert ambiguous

    def test_kuerzel_takes_precedence_over_fuzzy(self):
        # Even if name also matches, kürzel should win with score=1.0
        match, _ = match_property(PROPS, "BRE11", "WEG Hamburger Strasse 61", None)
        assert match is not None
        assert match.property_id == 2  # kürzel match
        assert match.score == 1.0

    def test_returns_property_metadata(self):
        match, _ = match_property(PROPS, "GVE1", None, None)
        assert match is not None
        assert match.property_hr_id == "GVE1"
        assert "Gevelsberg" in match.property_name


# ---------------------------------------------------------------------------
# match_contact_in_property
# ---------------------------------------------------------------------------

def _make_contracts(property_id=1):
    return [
        {
            "id": 101,
            "propertyId": property_id,
            "contacts": [{"id": 201}],
        },
        {
            "id": 102,
            "propertyId": property_id,
            "contacts": [{"id": 202}],
        },
    ]


def _make_contacts_by_id():
    return {
        201: {"id": 201, "companyName": "", "firstName": "Max",  "lastName": "Mustermann", "bankAccounts": []},
        202: {"id": 202, "companyName": "", "firstName": "Anna", "lastName": "Schmidt",    "bankAccounts": [{"iban": "DE123"}]},
    }


class TestMatchContactInProperty:
    def test_finds_matching_contact(self):
        match, ambiguous = match_contact_in_property(
            _make_contracts(), _make_contacts_by_id(), 1, "Max Mustermann", set()
        )
        assert match is not None
        assert match.contact_id == 201
        assert not ambiguous

    def test_includes_open_contracts(self):
        match, _ = match_contact_in_property(
            _make_contracts(), _make_contacts_by_id(), 1, "Max Mustermann", set()
        )
        assert 101 in match.open_contract_ids

    def test_excludes_booked_contracts(self):
        match, _ = match_contact_in_property(
            _make_contracts(), _make_contacts_by_id(), 1, "Max Mustermann", {101}
        )
        assert match is not None
        assert 101 not in match.open_contract_ids

    def test_no_match_when_name_differs(self):
        match, _ = match_contact_in_property(
            _make_contracts(), _make_contacts_by_id(), 1, "Voellig Unbekannt", set()
        )
        assert match is None

    def test_filters_by_property(self):
        # Contracts for property 2 only; searching in property 1 should yield no match
        contracts_p2 = [
            {"id": 201, "propertyId": 2, "contacts": [{"id": 201}]},
        ]
        match, _ = match_contact_in_property(
            contracts_p2, _make_contacts_by_id(), 1, "Max Mustermann", set()
        )
        assert match is None

    def test_detects_existing_bank_account(self):
        match, _ = match_contact_in_property(
            _make_contracts(), _make_contacts_by_id(), 1, "Anna Schmidt", set()
        )
        assert match is not None
        assert match.has_bank_account is True

    def test_no_bank_account_flag(self):
        match, _ = match_contact_in_property(
            _make_contracts(), _make_contacts_by_id(), 1, "Max Mustermann", set()
        )
        assert match is not None
        assert match.has_bank_account is False

    def test_empty_contracts_returns_none(self):
        match, _ = match_contact_in_property([], _make_contacts_by_id(), 1, "Max Mustermann", set())
        assert match is None

    def test_contact_not_in_contacts_by_id_skipped(self):
        contracts = [{"id": 101, "propertyId": 1, "contacts": [{"id": 999}]}]
        match, _ = match_contact_in_property(contracts, _make_contacts_by_id(), 1, "Max Mustermann", set())
        assert match is None
