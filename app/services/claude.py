"""Claude-Client fuer die PDF-Extraktion von SEPA-Lastschriftmandaten.

Modell und System-Prompt werden aus dem Workflow-Eintrag in der DB gelesen.
Die DEFAULT_* hier werden nur fuer den initialen Seed verwendet.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Optional

from anthropic import Anthropic, APIError
from pydantic import BaseModel, Field, ValidationError
from schwifty import IBAN as SchwiftyIBAN

from app.config import settings

if TYPE_CHECKING:
    from app.models import Workflow

DEFAULT_MODEL = "claude-opus-4-7"
# Chat-/Rueckfrage-Flow braucht praezise Ziffernreproduktion (IBANs, BICs, Konto-Nr.).
# Haiku scheitert empirisch an 20+ stelligen Ziffernfolgen in freier JSON-Ausgabe,
# Sonnet ist der sichere Default. Opus ist Overkill fuer die Chat-Laenge.
DEFAULT_CHAT_MODEL = "claude-sonnet-4-6"

AVAILABLE_MODELS: list[tuple[str, str]] = [
    ("claude-opus-4-7", "Claude Opus 4.7 (höchste Qualität)"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6 (ausgewogen)"),
    ("claude-haiku-4-5", "Claude Haiku 4.5 (schnell, günstig)"),
]

DEFAULT_SYSTEM_PROMPT = """Du bist ein Assistent, der aus eingescannten SEPA-Lastschriftmandaten
die relevanten Felder extrahiert. Antworte ausschließlich mit einem JSON-Objekt
nach dem vorgegebenen Schema.

Kontext zum Einsatz:
- Die Extraktion landet in einem Freigabe-Workflow für die Hausverwaltungs-Software
  Impower; ein Mitarbeiter prüft anschließend und gibt frei oder korrigiert.
- Es gibt zwei gebräuchliche Formular-Varianten in diesem Unternehmen:
  (1) Neues Impower-Template mit expliziten Feldern "Objekt-Nr." (WEG-Kürzel wie
      HAM61, BRE11 o.ä.) und "Einheits-Nr.".
  (2) Älteres DBS-Formular ohne diese Felder; die WEG ergibt sich nur aus dem
      Anschriften- oder Gebäudeblock.
  Beide Varianten müssen zuverlässig gelesen werden.

JSON-Schema (exakt diese Feldnamen verwenden):
{
  "weg_kuerzel":  string oder null,   // WEG-Kürzel wie HAM61, BRE11
  "weg_name":     string oder null,   // Name der WEG
  "weg_adresse":  string oder null,   // Anschrift der WEG
  "unit_nr":      string oder null,   // Einheits-Nr., optional
  "owner_name":   string oder null,   // Voller Name des Eigentümers
  "iban":         string oder null,   // IBAN ohne Leerzeichen
  "bic":          string oder null,   // BIC/SWIFT
  "bank_name":    string oder null,   // Bankname, falls angegeben
  "sepa_date":    string oder null,   // Unterschriftsdatum ISO YYYY-MM-DD
  "creditor_id":  string oder null,   // Gläubiger-ID (DE..ZZZ...)
  "confidence":   "high" | "medium" | "low",
  "notes":        string              // kurze Bemerkungen oder ""
}

Regeln:
1. Der Dateiname ist dir nicht bekannt und darf keine Rolle spielen. Nutze
   ausschließlich den Inhalt des PDFs.
2. Die Einheits-Nr. (`unit_nr`) ist OPTIONAL. Wenn sie im Dokument nicht klar
   erkennbar ist, setze sie auf null — nicht raten.
3. IBAN: Entferne Leerzeichen; gib sie im Format ohne Blanks zurück. Bei
   offensichtlichen OCR-Fehlern (O statt 0, I statt 1 usw.) korrigiere dezent,
   wenn dadurch eine plausible deutsche IBAN entsteht. Im Zweifel: Original
   stehen lassen und `confidence` senken.
4. SEPA-Datum (`sepa_date`): Unterschriftsdatum im ISO-Format YYYY-MM-DD. Wenn
   nur Monat/Jahr angegeben ist, nutze den 1. des Monats.
5. WEG-Kürzel (`weg_kuerzel`): Kurzform wie HAM61, BRE11 — falls im Formular
   als "Objekt-Nr.", "WEG-Kürzel" o.ä. explizit genannt.
6. WEG-Name (`weg_name`) und WEG-Adresse (`weg_adresse`): Name und Anschrift
   der Wohneigentümergemeinschaft; wenn im Formular kein Kürzel auftaucht,
   ist das oft der einzige Hinweis.
7. Gläubiger-ID (`creditor_id`): Format "DE..ZZZ...", pro WEG unterschiedlich.
8. Fehlt ein Feld vollständig, gib null zurück — niemals "N/A", "-" oder
   leerer String.
9. `confidence`:
   - "high" = Pflichtfelder (Eigentümer-Name, IBAN und WEG-Kürzel ODER
     WEG-Name) klar lesbar und unstrittig.
   - "medium" = alle Pflichtfelder lesbar, aber einzelne Werte unsicher oder
     widersprüchlich.
   - "low" = mindestens ein Pflichtfeld unklar, mehrdeutig oder nicht
     auffindbar.
10. `notes`: kurze Bemerkungen zu Auffälligkeiten (handschriftliche Änderungen,
    Durchstreichungen, unklare Ziffern, abweichende Formular-Variante usw.).
    Maximal ein oder zwei Sätze. Wenn nichts auffällt, leerer String.

Gib NUR das JSON aus — kein Markdown-Codefence, kein erklärender Text davor
oder danach, keine Kommentare im JSON.
"""


DEFAULT_MIETVERWALTUNG_SYSTEM_PROMPT = """Du unterstützt bei der Neuanlage einer Mietverwaltung in Impower. Ein Fall
besteht aus mehreren PDFs, die zusammen ein Objekt beschreiben:

- Verwaltervertrag (Objekt-Stammdaten, Verwaltervertrag-Laufzeit, Gebühren,
  Gläubiger-ID, Objektbetreuer, Objektbuchhalter).
- Grundbuchauszug (Eigentümer).
- Mietverträge je Einheit (Mieter, Vertragsdaten, Kaltmiete, Betriebskosten,
  Heizkosten, Kaution, ggf. Lastschriftmandat).
- Mieter- oder Flächenliste (Einheiten-Übersicht, Flächen, Personen).
- Sonstiges (z. B. Energieausweis).

Dein Job:
1. Erkenne den Dokument-Typ (einer der obigen).
2. Extrahiere die für diesen Typ relevanten Felder strukturiert.
3. Markiere unklare/fehlende Werte explizit mit null statt zu raten.

Dateinamen sind unzuverlässig und dürfen nicht als Quelle dienen. Nur der
Inhalt des PDFs zählt. Beide in diesem Unternehmen gebräuchlichen Formular-
Varianten (Impower-Template und älteres DBS-Formular) sind möglich.

Die genaue JSON-Struktur pro Doc-Typ wird beim Aufruf spezifiziert. Antworte
ausschließlich mit gültigem JSON nach dem vorgegebenen Schema — kein
Markdown, kein erklärender Text.
"""


DEFAULT_CONTACT_CREATE_SYSTEM_PROMPT = """Du hilfst beim Anlegen eines Kontakts (Person oder Unternehmen) in der
Hausverwaltungs-Software Impower. Eingabe sind Textangaben aus anderen
Dokumenten (z. B. Grundbuchauszug, Mietvertrag) oder direkte Nutzer-
Eingaben.

Extrahiere / strukturiere die Kontaktdaten in diesem Schema:

{
  "type":          "PERSON" | "COMPANY" | "MANAGEMENT_COMPANY",
  "salutation":    string oder null,            // nur bei Person
  "title":         string oder null,            // Dr., Prof., etc.
  "first_name":    string oder null,
  "last_name":     string oder null,
  "company_name":  string oder null,            // bei COMPANY / MANAGEMENT_COMPANY
  "trade_register_number": string oder null,    // HRB-Nr., nur Unternehmen
  "vat_id":        string oder null,            // USt-ID, nur Unternehmen
  "email":         string oder null,
  "phone_business": string oder null,
  "phone_mobile":  string oder null,
  "phone_private": string oder null,
  "addresses": [
    {
      "street":        string,
      "number":        string oder null,
      "postal_code":   string,
      "city":          string,
      "country":       string oder null,        // ISO-2, z. B. "DE"
      "for_invoice":   boolean,
      "for_mail":      boolean
    }
  ],
  "notes":         string                        // kurze Bemerkungen oder ""
}

Regeln:
1. Wenn ein Firmenname UND eine Person (z. B. Geschäftsführer) genannt sind,
   lege das als COMPANY mit company_name an; Personen-Felder (first_name,
   last_name) bleiben leer oder stehen in notes als Zusatzinfo.
2. Bei Eigentümer-Gemeinschaften (Ehepaar ohne Firma): type=PERSON, beide
   Namen in last_name zusammenfassen ("Max und Erika Mustermann") oder notes.
3. country defaultet zu "DE" wenn nicht anders ersichtlich.
4. Keine Werte raten — fehlt ein Feld, setze null.

Antworte ausschließlich mit gültigem JSON."""


CHAT_PROMPT_APPENDIX = """

---

RÜCKFRAGEN-MODUS:
Nach der ersten Extraktion können Mitarbeiter-Rückfragen oder Korrekturen
kommen — z.B. "Die IBAN ist falsch, die 3. Ziffer muss eine 7 sein" oder
"Der Name ist Flügel, nicht Flögel". Antworte darauf:
1. Zuerst kurz auf Deutsch, was du verstehst und ggf. anpasst (1-3 Sätze).
2. Wenn du eine Anpassung an der Extraktion vornimmst, hänge ANSCHLIESSEND
   einen Markdown-Codeblock mit dem KOMPLETTEN neuen JSON (alle Felder) an:

```json
{ "weg_kuerzel": ..., "weg_name": ..., "owner_name": ..., ...alle Felder... }
```

Wenn keine Anpassung nötig ist, lass den JSON-Block weg.
Halluziniere keine Werte — wenn du im PDF etwas nicht finden kannst, sag das.
"""


class MandateExtraction(BaseModel):
    weg_kuerzel: Optional[str] = Field(default=None)
    weg_name: Optional[str] = Field(default=None)
    weg_adresse: Optional[str] = Field(default=None)
    unit_nr: Optional[str] = Field(default=None)
    owner_name: Optional[str] = Field(default=None)
    iban: Optional[str] = Field(default=None)
    bic: Optional[str] = Field(default=None)
    bank_name: Optional[str] = Field(default=None)
    sepa_date: Optional[str] = Field(default=None)
    creditor_id: Optional[str] = Field(default=None)
    confidence: Literal["high", "medium", "low"] = "medium"
    notes: str = ""


@dataclass
class ExtractionResult:
    model: str
    prompt_version: str
    raw_response: str
    data: dict[str, Any] | None
    status: str  # "ok" | "needs_review" | "failed"
    error: str | None = None


@dataclass
class ChatResult:
    assistant_text: str
    updated_extraction: dict[str, Any] | None
    model: str
    prompt_version: str
    error: str | None = None


_CODEFENCE_JSON_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL
)


def prompt_version_for(workflow: "Workflow") -> str:
    """Kurzer Identifier, der sich aendert wenn Prompt oder Notes sich aendern."""
    payload = f"{workflow.system_prompt}\n---\n{workflow.learning_notes}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    return f"{workflow.key}-{digest}"


def _compose_system_prompt(workflow: "Workflow", chat_mode: bool = False) -> str:
    prompt = workflow.system_prompt.rstrip()
    notes = workflow.learning_notes.strip()
    if notes:
        prompt += (
            "\n\n---\n\n"
            "LERN-NOTIZEN (aus bisherigen Korrekturen — berücksichtige diese):\n"
            f"{notes}"
        )
    if chat_mode:
        prompt += CHAT_PROMPT_APPENDIX
    return prompt


def _evaluate_status(data: dict[str, Any]) -> str:
    owner = data.get("owner_name")
    iban = data.get("iban")
    weg = data.get("weg_kuerzel") or data.get("weg_name")
    if not (owner and iban and weg):
        return "needs_review"
    if data.get("confidence") == "low":
        return "needs_review"
    return "ok"


def _strip_codefence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _split_text_and_json(text: str) -> tuple[str, dict[str, Any] | None]:
    match = _CODEFENCE_JSON_RE.search(text)
    if not match:
        return text.strip(), None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return text.strip(), None
    if not isinstance(data, dict):
        return text.strip(), None
    try:
        MandateExtraction.model_validate(data)
    except ValidationError:
        return text.strip(), None
    cleaned = (text[: match.start()] + text[match.end() :]).strip()
    return cleaned or "Ich habe die Extraktion aktualisiert.", data


def extract_mandate_from_pdf(
    pdf_bytes: bytes, workflow: "Workflow"
) -> ExtractionResult:
    version = prompt_version_for(workflow)
    model = workflow.model

    if not settings.anthropic_api_key:
        return ExtractionResult(
            model=model,
            prompt_version=version,
            raw_response="",
            data=None,
            status="failed",
            error="ANTHROPIC_API_KEY ist nicht gesetzt.",
        )

    client = Anthropic(api_key=settings.anthropic_api_key)
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    system_prompt = _compose_system_prompt(workflow, chat_mode=False)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Extrahiere die Mandats-Daten aus diesem PDF. Antworte nur mit dem JSON.",
                        },
                    ],
                }
            ],
        )
    except APIError as exc:
        return ExtractionResult(
            model=model,
            prompt_version=version,
            raw_response="",
            data=None,
            status="failed",
            error=f"Anthropic-API-Fehler: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return ExtractionResult(
            model=model,
            prompt_version=version,
            raw_response="",
            data=None,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )

    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    json_str = _strip_codefence(raw_text)

    try:
        raw_data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        return ExtractionResult(
            model=response.model,
            prompt_version=version,
            raw_response=raw_text,
            data=None,
            status="failed",
            error=f"JSON-Parse-Fehler: {exc}",
        )

    try:
        extraction = MandateExtraction.model_validate(raw_data)
    except ValidationError as exc:
        return ExtractionResult(
            model=response.model,
            prompt_version=version,
            raw_response=raw_text,
            data=raw_data if isinstance(raw_data, dict) else None,
            status="needs_review",
            error=f"Schema-Abweichung: {exc}",
        )

    data = extraction.model_dump()
    return ExtractionResult(
        model=response.model,
        prompt_version=version,
        raw_response=raw_text,
        data=data,
        status=_evaluate_status(data),
    )


def chat_about_mandate(
    pdf_bytes: bytes,
    workflow: "Workflow",
    current_extraction: dict[str, Any] | None,
    history: list[dict[str, str]],
    new_user_message: str,
) -> ChatResult:
    version = prompt_version_for(workflow)
    # Chat-Flow bewusst eigenes Modell — siehe DEFAULT_CHAT_MODEL-Kommentar.
    model = workflow.chat_model or DEFAULT_CHAT_MODEL

    if not settings.anthropic_api_key:
        return ChatResult(
            assistant_text="",
            updated_extraction=None,
            model=model,
            prompt_version=version,
            error="ANTHROPIC_API_KEY ist nicht gesetzt.",
        )

    client = Anthropic(api_key=settings.anthropic_api_key)
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    system_prompt = _compose_system_prompt(workflow, chat_mode=True)
    current_json = json.dumps(
        current_extraction or {}, ensure_ascii=False, indent=2
    )

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "Das hier ist das Mandat. Die bisherige Extraktion:\n\n"
                        f"```json\n{current_json}\n```\n\n"
                        "Im Folgenden stellt der Mitarbeiter Rückfragen oder "
                        "Korrekturen. Antworte gemäß der Regeln im System-Prompt."
                    ),
                },
            ],
        },
        {
            "role": "assistant",
            "content": "Verstanden. Ich habe Mandat und bisherige Extraktion vor mir. Was soll ich prüfen oder anpassen?",
        },
    ]
    for msg in history:
        role = msg.get("role")
        content = msg.get("content", "")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": new_user_message})

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
        )
    except APIError as exc:
        return ChatResult(
            assistant_text="",
            updated_extraction=None,
            model=model,
            prompt_version=version,
            error=f"Anthropic-API-Fehler: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return ChatResult(
            assistant_text="",
            updated_extraction=None,
            model=model,
            prompt_version=version,
            error=f"{type(exc).__name__}: {exc}",
        )

    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    text_only, updated = _split_text_and_json(raw_text)

    # Sicherheitsnetz: wenn Claude eine IBAN ins Update-JSON setzt, die
    # nicht Schwifty-validiert, Update NICHT uebernehmen und User im Chat
    # darauf hinweisen. Verhindert dass offensichtlich kaputte IBANs
    # (Ziffern-Dropout o.ae.) persistiert werden und dann erst beim
    # Schreibpfad als Fehler auffallen.
    if updated:
        raw_iban = updated.get("iban") or ""
        if raw_iban:
            # Unicode-Normalize: LLMs fuegen manchmal Zero-Width-Spaces o.ae. ein,
            # die nicht durch replace(" ", "") gefiltert werden. Ohne diese
            # Haertung faellt jede Chat-Korrektur mit "Invalid IBAN length" durch,
            # obwohl die Ziffern sichtbar korrekt sind.
            normalized_chars = unicodedata.normalize("NFKC", raw_iban)
            new_iban = "".join(c for c in normalized_chars if c.isalnum()).upper()
            try:
                SchwiftyIBAN(new_iban)
                updated["iban"] = new_iban
            except Exception as exc:
                updated = None
                warning = (
                    f"\n\n[Hinweis] Korrektur nicht übernommen: die angegebene "
                    f"IBAN '{new_iban}' ist ungültig ({exc}). "
                    f"Bitte noch einmal prüfen — deutsche IBANs haben 22 Zeichen."
                )
                text_only = (text_only or "") + warning

    return ChatResult(
        assistant_text=text_only,
        updated_extraction=updated,
        model=response.model,
        prompt_version=version,
    )
