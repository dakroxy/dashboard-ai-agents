"""Unit tests for app/services/claude.py pure functions — no API calls, no DB."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.claude import (
    MandateExtraction,
    _compose_system_prompt,
    _evaluate_status,
    _split_text_and_json,
    _strip_codefence,
    prompt_version_for,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _workflow(system_prompt: str = "Test prompt.", learning_notes: str = "", key: str = "sepa_mandate") -> SimpleNamespace:
    return SimpleNamespace(
        key=key,
        system_prompt=system_prompt,
        learning_notes=learning_notes,
    )


# ---------------------------------------------------------------------------
# _evaluate_status
# ---------------------------------------------------------------------------

class TestEvaluateStatus:
    def test_ok_all_required_fields(self):
        data = {"owner_name": "Max Mustermann", "iban": "DE89370400440532013000", "weg_kuerzel": "HAM61", "confidence": "high"}
        assert _evaluate_status(data) == "ok"

    def test_ok_weg_name_without_kuerzel(self):
        data = {"owner_name": "Max Mustermann", "iban": "DE89370400440532013000", "weg_name": "Hamburger WEG", "confidence": "high"}
        assert _evaluate_status(data) == "ok"

    def test_ok_medium_confidence(self):
        data = {"owner_name": "Max Mustermann", "iban": "DE89370400440532013000", "weg_kuerzel": "HAM61", "confidence": "medium"}
        assert _evaluate_status(data) == "ok"

    def test_needs_review_missing_owner(self):
        data = {"iban": "DE89370400440532013000", "weg_kuerzel": "HAM61", "confidence": "high"}
        assert _evaluate_status(data) == "needs_review"

    def test_needs_review_owner_none(self):
        data = {"owner_name": None, "iban": "DE89370400440532013000", "weg_kuerzel": "HAM61", "confidence": "high"}
        assert _evaluate_status(data) == "needs_review"

    def test_needs_review_missing_iban(self):
        data = {"owner_name": "Max Mustermann", "weg_kuerzel": "HAM61", "confidence": "high"}
        assert _evaluate_status(data) == "needs_review"

    def test_needs_review_iban_none(self):
        data = {"owner_name": "Max Mustermann", "iban": None, "weg_kuerzel": "HAM61", "confidence": "high"}
        assert _evaluate_status(data) == "needs_review"

    def test_needs_review_missing_weg_entirely(self):
        data = {"owner_name": "Max Mustermann", "iban": "DE89370400440532013000", "confidence": "high"}
        assert _evaluate_status(data) == "needs_review"

    def test_needs_review_both_weg_fields_none(self):
        data = {"owner_name": "Max Mustermann", "iban": "DE89370400440532013000", "weg_kuerzel": None, "weg_name": None, "confidence": "high"}
        assert _evaluate_status(data) == "needs_review"

    def test_needs_review_low_confidence_overrides_complete_data(self):
        data = {"owner_name": "Max Mustermann", "iban": "DE89370400440532013000", "weg_kuerzel": "HAM61", "confidence": "low"}
        assert _evaluate_status(data) == "needs_review"

    def test_ok_uses_weg_kuerzel_when_both_weg_fields_set(self):
        data = {"owner_name": "Max Mustermann", "iban": "DE89370400440532013000", "weg_kuerzel": "HAM61", "weg_name": "Some WEG", "confidence": "high"}
        assert _evaluate_status(data) == "ok"


# ---------------------------------------------------------------------------
# _strip_codefence
# ---------------------------------------------------------------------------

class TestStripCodefence:
    def test_plain_text_unchanged(self):
        text = '{"weg_kuerzel": "HAM61"}'
        assert _strip_codefence(text) == text

    def test_removes_json_fence(self):
        text = '```json\n{"weg_kuerzel": "HAM61"}\n```'
        assert _strip_codefence(text) == '{"weg_kuerzel": "HAM61"}'

    def test_removes_plain_fence(self):
        text = '```\n{"key": "value"}\n```'
        assert _strip_codefence(text) == '{"key": "value"}'

    def test_strips_whitespace(self):
        text = '  {"key": "value"}  '
        assert _strip_codefence(text) == '{"key": "value"}'

    def test_multiline_json_preserved(self):
        inner = '{\n  "a": 1,\n  "b": 2\n}'
        text = f"```json\n{inner}\n```"
        assert _strip_codefence(text) == inner


# ---------------------------------------------------------------------------
# _split_text_and_json
# ---------------------------------------------------------------------------

FULL_EXTRACTION = {
    "weg_kuerzel": "HAM61",
    "weg_name": None,
    "weg_adresse": None,
    "unit_nr": None,
    "owner_name": "Max Mustermann",
    "iban": "DE89370400440532013000",
    "bic": None,
    "bank_name": None,
    "sepa_date": None,
    "creditor_id": None,
    "confidence": "high",
    "notes": "",
}

VALID_JSON_BLOCK = (
    '```json\n'
    '{"weg_kuerzel": "HAM61", "weg_name": null, "weg_adresse": null, "unit_nr": null,'
    ' "owner_name": "Max Mustermann", "iban": "DE89370400440532013000",'
    ' "bic": null, "bank_name": null, "sepa_date": null, "creditor_id": null,'
    ' "confidence": "high", "notes": ""}\n'
    '```'
)


class TestSplitTextAndJson:
    def test_no_json_block_returns_text_and_none(self):
        text = "Ich habe die Extraktion geprueft. Keine Aenderungen noetig."
        txt, data = _split_text_and_json(text)
        assert txt == text
        assert data is None

    def test_extracts_valid_json_from_codeblock(self):
        text = f"Ich passe die IBAN an.\n\n{VALID_JSON_BLOCK}"
        txt, data = _split_text_and_json(text)
        assert data is not None
        assert data["weg_kuerzel"] == "HAM61"
        assert data["owner_name"] == "Max Mustermann"
        assert "Ich passe die IBAN an." in txt
        assert "```" not in txt

    def test_invalid_json_returns_full_text_and_none(self):
        text = "Hier ist was kaputtes:\n```json\n{not: valid}\n```"
        txt, data = _split_text_and_json(text)
        assert data is None

    def test_json_failing_schema_validation_returns_none(self):
        text = 'Text\n```json\n{"confidence": "UNKNOWN_VALUE"}\n```'
        txt, data = _split_text_and_json(text)
        assert data is None

    def test_text_only_when_no_surrounding_text(self):
        txt, data = _split_text_and_json(VALID_JSON_BLOCK)
        assert data is not None
        assert txt  # fallback placeholder text is returned


# ---------------------------------------------------------------------------
# MandateExtraction schema
# ---------------------------------------------------------------------------

class TestMandateExtraction:
    def test_valid_full_extraction(self):
        ext = MandateExtraction(
            weg_kuerzel="HAM61",
            owner_name="Max Mustermann",
            iban="DE89370400440532013000",
            confidence="high",
        )
        assert ext.weg_kuerzel == "HAM61"
        assert ext.confidence == "high"

    def test_defaults_to_medium_confidence(self):
        ext = MandateExtraction()
        assert ext.confidence == "medium"

    def test_all_optional_fields_can_be_none(self):
        ext = MandateExtraction()
        assert ext.weg_kuerzel is None
        assert ext.owner_name is None
        assert ext.iban is None

    def test_invalid_confidence_raises(self):
        with pytest.raises(Exception):
            MandateExtraction(confidence="ultra")

    def test_notes_defaults_to_empty_string(self):
        ext = MandateExtraction()
        assert ext.notes == ""

    def test_model_dump_returns_dict(self):
        ext = MandateExtraction(weg_kuerzel="BRE11", confidence="low")
        d = ext.model_dump()
        assert isinstance(d, dict)
        assert d["weg_kuerzel"] == "BRE11"


# ---------------------------------------------------------------------------
# prompt_version_for and _compose_system_prompt
# ---------------------------------------------------------------------------

class TestPromptVersion:
    def test_deterministic(self):
        wf = _workflow("Prompt A")
        v1 = prompt_version_for(wf)
        v2 = prompt_version_for(wf)
        assert v1 == v2

    def test_changes_when_prompt_changes(self):
        v1 = prompt_version_for(_workflow("Prompt A"))
        v2 = prompt_version_for(_workflow("Prompt B"))
        assert v1 != v2

    def test_changes_when_notes_change(self):
        v1 = prompt_version_for(_workflow("Prompt A", learning_notes=""))
        v2 = prompt_version_for(_workflow("Prompt A", learning_notes="Neue Notiz"))
        assert v1 != v2

    def test_format_contains_key(self):
        version = prompt_version_for(_workflow(key="sepa_mandate"))
        assert version.startswith("sepa_mandate-")

    def test_hash_is_8_chars(self):
        version = prompt_version_for(_workflow())
        key_part, hash_part = version.rsplit("-", 1)
        assert len(hash_part) == 8


class TestComposeSystemPrompt:
    def test_includes_prompt(self):
        wf = _workflow("Base prompt text.")
        result = _compose_system_prompt(wf)
        assert "Base prompt text." in result

    def test_includes_learning_notes_when_set(self):
        wf = _workflow("Base prompt.", learning_notes="Lern-Notiz 1")
        result = _compose_system_prompt(wf)
        assert "Lern-Notiz 1" in result

    def test_no_notes_section_when_empty(self):
        wf = _workflow("Base prompt.", learning_notes="")
        result = _compose_system_prompt(wf)
        assert "LERN-NOTIZEN" not in result

    def test_chat_mode_adds_appendix(self):
        wf = _workflow("Base prompt.")
        result = _compose_system_prompt(wf, chat_mode=True)
        assert "RUECKFRAGEN-MODUS" in result

    def test_non_chat_mode_no_appendix(self):
        wf = _workflow("Base prompt.")
        result = _compose_system_prompt(wf, chat_mode=False)
        assert "RUECKFRAGEN-MODUS" not in result
