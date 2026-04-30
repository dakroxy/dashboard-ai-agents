"""Claude-Client fuer die Mietverwaltungs-Anlage (M5 — Paket 4).

Pro Doc-Typ (verwaltervertrag, grundbuch, mietvertrag, mieterliste, sonstiges)
eigener Prompt + Pydantic-Schema. classify_document erkennt den Typ automatisch,
extract_for_doc_type extrahiert die typ-spezifischen Felder. merge_case_state
baut aus n Extractions den konsolidierten Case-State fuer den Write-Pfad.

Designentscheidungen:
- Das System-Prompt vom Workflow (mietverwaltung_setup) ist der Koordinator-/
  Meta-Prompt; die typ-spezifischen Prompts sind Code-Konstanten. Wenn der
  Nutzer pro Typ im UI tunen moechte, wird spaeter die Workflow-Konfig um
  ``extraction_prompts: JSONB`` erweitert (Paket 5+).
- Extraction-Schemas sind schlank — nur Felder, die am Ende via Impower-Write
  (`write_mietverwaltung`, Paket 7) gebraucht werden plus das, was das UI
  (Paket 5) anzeigen soll.
- Merge ist rein funktional: aus ``case.state['_extractions']`` wird der
  gemergte Stand neu berechnet. Nutzer-Overrides (Paket 5) kommen spaeter
  ueber ``case.state['_overrides']`` obendrauf.
"""
from __future__ import annotations

import base64
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Optional

from anthropic import Anthropic, APIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from schwifty import IBAN as SchwiftyIBAN

from app.config import settings
from app.services.claude import DEFAULT_CHAT_MODEL, DEFAULT_MODEL, prompt_version_for

if TYPE_CHECKING:
    from app.models import Workflow


# ---------------------------------------------------------------------------
# Case-Chat (Paket 8)
# ---------------------------------------------------------------------------

CASE_CHAT_PROMPT = """Du bist der Mietverwaltungs-Agent. Der Nutzer hat einen
„Fall" mit n PDFs (Verwaltervertrag, Grundbuch, Mieterliste, Mietverträge
u. a.) hochgeladen. Die KI hat pro PDF typ-spezifische Felder extrahiert.
Der konsolidierte Case-State (gemergte Daten plus manuelle User-Overrides)
wird dir in jeder Runde mitgegeben.

Deine Aufgaben:

1. Antworte auf Rückfragen zum aktuellen Stand (Deutsch, kurz, präzise).
2. Wenn der Nutzer eine Korrektur oder Ergänzung vornehmen will, schlage
   einen konkreten Override-Patch vor — als JSON-Codeblock am Ende deiner
   Antwort. Struktur:

```json
{
  "overrides": {
    "property":            {"creditor_id": "DE71ZZZ00002822264"},
    "management_contract": {"supervisor_name": "Daniel Kroll"},
    "owner":               {"company_name": "Schmidt Immobilien GmbH"},
    "billing_address":     {"is_same_as_owner": true},
    "buildings":           [{"name": "Block F"}, {"name": "Block B"}],
    "units":               [{"number": "1", "unit_type": "COMMERCIAL", ...}],
    "tenant_contracts":    [...]
  }
}
```

Regeln für den Patch:
- Sende NUR Sektionen mit Änderungen. Felder, die gleich bleiben sollen,
  nicht erwähnen.
- Für Dict-Sektionen (property, management_contract, billing_address,
  owner): nur die zu ändernden Felder. Der Server merged sie über den
  bestehenden Stand.
- Für Listen (buildings, units, tenant_contracts): gib die KOMPLETTE neue
  Liste, wenn du sie veränderst — der Server ersetzt die Liste komplett.
- IBAN ohne Leerzeichen, Geldbeträge als Zahl (Punkt als Dezimal),
  Datumsfelder im ISO-Format YYYY-MM-DD.
- ISO-Länder 2-buchstabig (DE/AT/CH).

Wenn keine Änderung gewünscht ist (pure Info-Frage), lass den
JSON-Codeblock weg. Halluziniere keine Werte — wenn du etwas nicht sicher
weisst, sag das.
"""


class CasePatch(BaseModel):
    """Erwartetes Struktur des ``overrides``-Patches aus Claude."""

    model_config = ConfigDict(extra="ignore")

    property: Optional[dict[str, Any]] = None
    management_contract: Optional[dict[str, Any]] = None
    billing_address: Optional[dict[str, Any]] = None
    owner: Optional[dict[str, Any]] = None
    buildings: Optional[list[dict[str, Any]]] = None
    units: Optional[list[dict[str, Any]]] = None
    tenant_contracts: Optional[list[dict[str, Any]]] = None


@dataclass
class CaseChatResult:
    assistant_text: str
    patch: dict[str, Any] | None  # nur die override-Sektionen
    model: str
    prompt_version: str
    error: str | None = None


def _extract_case_patch(text: str) -> tuple[str, dict[str, Any] | None, str | None]:
    """Trennt Antwort-Text und JSON-Patch. Gibt (text, patch_dict, warning) zurueck."""
    match = _CODEFENCE_RE.search(text)
    if not match:
        return text.strip(), None, None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return text.strip(), None, "Patch-JSON nicht parsebar."
    if not isinstance(data, dict):
        return text.strip(), None, "Patch-JSON ist kein Objekt."
    overrides = data.get("overrides")
    if not isinstance(overrides, dict):
        return text.strip(), None, "Patch-JSON hat keinen 'overrides'-Key."
    try:
        validated = CasePatch.model_validate(overrides)
    except ValidationError as exc:
        return text.strip(), None, f"Patch-Schema-Fehler: {exc}"
    cleaned_text = (text[: match.start()] + text[match.end() :]).strip()
    patch = {k: v for k, v in validated.model_dump(exclude_none=True).items()}

    # IBAN-Guard: mietvertrag-Patches duerfen nur gueltige IBANs enthalten.
    iban_warnings: list[str] = []
    if patch.get("tenant_contracts"):
        for tc in patch["tenant_contracts"]:
            contract = (tc or {}).get("contract") or {}
            raw_iban = contract.get("iban")
            if not raw_iban:
                continue
            normalized = _normalize_iban(str(raw_iban))
            try:
                SchwiftyIBAN(normalized)
                contract["iban"] = normalized
            except Exception as exc:
                iban_warnings.append(f"IBAN '{normalized}' ungültig ({exc}) — verworfen.")
                contract["iban"] = None

    warning = "; ".join(iban_warnings) if iban_warnings else None
    return (
        cleaned_text or "Patch angewendet.",
        patch or None,
        warning,
    )


def chat_about_case(
    workflow: "Workflow",
    case_state: dict[str, Any],
    documents_summary: list[dict[str, Any]],
    history: list[dict[str, str]],
    new_user_message: str,
) -> CaseChatResult:
    """Chat-Service fuer den Mietverwaltungs-Case.

    ``documents_summary`` listet pro Doc: {"filename", "doc_type", "status"}.
    PDFs werden aus Kosten/Performance-Gruenden NICHT mitgesendet — der
    Case-State enthaelt die extrahierten Felder. Bei gezielten PDF-Rueckfragen
    muss der User das Doc selbst oeffnen.
    """
    version = prompt_version_for(workflow)
    model = workflow.chat_model or DEFAULT_CHAT_MODEL

    if not settings.anthropic_api_key:
        return CaseChatResult(
            assistant_text="",
            patch=None,
            model=model,
            prompt_version=version,
            error="ANTHROPIC_API_KEY ist nicht gesetzt.",
        )

    # State verschlanken: _extractions raus (gross), _overrides bleibt.
    state_for_prompt = {
        k: v for k, v in (case_state or {}).items() if k != "_extractions"
    }
    state_json = json.dumps(state_for_prompt, ensure_ascii=False, indent=2)
    docs_lines = [
        f"- {d.get('filename')} (Typ: {d.get('doc_type') or '—'}, Status: {d.get('status')})"
        for d in documents_summary
    ]
    docs_block = "\n".join(docs_lines) if docs_lines else "(keine Dokumente)"

    system_prompt = (
        workflow.system_prompt.rstrip() + "\n\n---\n\n" + CASE_CHAT_PROMPT
    )
    if workflow.learning_notes.strip():
        system_prompt += (
            "\n\n---\n\nLERN-NOTIZEN (aus bisherigen Korrekturen):\n"
            f"{workflow.learning_notes.strip()}"
        )

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                "Hochgeladene Dokumente:\n"
                f"{docs_block}\n\n"
                "Aktueller Case-State (JSON):\n\n"
                f"```json\n{state_json}\n```"
            ),
        },
        {
            "role": "assistant",
            "content": "Verstanden. Der aktuelle Stand ist mir bekannt. Was möchtest du prüfen oder ändern?",
        },
    ]
    for msg in history:
        role = msg.get("role")
        content = msg.get("content", "")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": new_user_message})

    client = Anthropic(api_key=settings.anthropic_api_key)
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
        return CaseChatResult(
            assistant_text="", patch=None, model=model, prompt_version=version,
            error=f"Anthropic-API-Fehler: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return CaseChatResult(
            assistant_text="", patch=None, model=model, prompt_version=version,
            error=f"{type(exc).__name__}: {exc}",
        )

    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    text_only, patch, warning = _extract_case_patch(raw_text)
    if warning:
        text_only = f"{text_only}\n\n[Hinweis] {warning}"
    return CaseChatResult(
        assistant_text=text_only,
        patch=patch,
        model=response.model,
        prompt_version=version,
    )

VALID_DOC_TYPES: tuple[str, ...] = (
    "verwaltervertrag",
    "grundbuch",
    "mietvertrag",
    "mieterliste",
    "sonstiges",
)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

CLASSIFY_PROMPT = """Du bekommst ein einzelnes PDF aus einer Mietverwaltungs-Neuanlage.
Bestimme den Dokument-Typ. Mögliche Werte:

- "verwaltervertrag"  — Verwaltervertrag zwischen Eigentümer und Hausverwaltung,
  enthält typisch Objekt-Nr., Adresse, Vertragsbeginn/-ende, Gebühren,
  Objektbetreuer, Gläubiger-ID.
- "grundbuch"         — Grundbuchauszug, Abteilung I zeigt den/die Eigentümer.
- "mietvertrag"       — Mietvertrag zwischen Eigentümer und einem Mieter;
  bezieht sich auf eine konkrete Einheit, enthält Kaltmiete/Betriebskosten/
  Heizkosten, Kaution.
- "mieterliste"       — Mieter- oder Flächenliste: tabellarische Übersicht
  über alle Einheiten eines Objekts, oft mit Flächen, Blocknummern, Mieter-
  Namen, Personen. Kann auch eine Einheiten-/Flächenliste ohne Mieter sein.
- "sonstiges"         — Passt zu keinem der vier obigen (z. B. Energieausweis,
  Nebenkostenabrechnung, Schriftwechsel).

Antworte AUSSCHLIESSLICH mit gültigem JSON:

{"doc_type": "<einer der obigen Werte>", "confidence": "high"|"medium"|"low", "reason": "<1 Satz Begründung>"}

Dateinamen sind unzuverlässig und dürfen nicht in die Entscheidung
einfliessen — nur der Inhalt zählt.
"""


_PROMPT_BASE = """Du extrahierst strukturierte Felder aus einem PDF für die
Mietverwaltungs-Anlage in Impower. Regeln, die immer gelten:

1. Der Dateiname ist unzuverlässig; nutze nur den PDF-Inhalt.
2. Fehlende oder unklare Werte: ``null`` setzen. Nicht raten.
3. Datumsfelder im ISO-Format YYYY-MM-DD.
4. Geldbeträge als Zahl (Punkt als Dezimal, kein Euro-Zeichen, keine
   1.000er-Trennung) — z. B. 13925.15.
5. IBAN ohne Leerzeichen. BIC in Großbuchstaben.
6. Länderkennzeichen als ISO-2 (``DE``, ``AT``, ``CH``).
7. Antworte ausschließlich mit gültigem JSON nach dem Schema — kein Markdown,
   kein erklärender Text davor/danach.
"""


PROMPT_VERWALTERVERTRAG = _PROMPT_BASE + """

Dokument-Typ: VERWALTERVERTRAG. Extrahiere die Objekt-Stammdaten und die
Verwaltungsvertrags-Eckdaten.

JSON-Schema:

{
  "property": {
    "number":      string oder null,   // Objekt-Nr. / WEG-Kürzel wie SBA9
    "name":        string oder null,   // Objektbezeichnung, falls separat genannt
    "street":      string oder null,   // Straße + Hausnummer
    "postal_code": string oder null,
    "city":        string oder null,
    "country":     string oder null,   // ISO-2, default "DE"
    "creditor_id": string oder null    // Gläubiger-ID (DE..ZZZ...)
  },
  "management_contract": {
    "management_company_name": string oder null,  // Name der Verwaltung
    "supervisor_name":         string oder null,  // Objektbetreuer
    "accountant_name":         string oder null,  // Objektbuchhalter
    "contract_start_date":     string oder null,  // Vertragsbeginn YYYY-MM-DD
    "contract_end_date":       string oder null,  // Vertragsende, null = unbefristet
    "dunning_fee_net":         number oder null   // Mahnung netto in EUR
  },
  "billing_address": {
    "is_same_as_owner": boolean,                  // true falls im Vertrag vermerkt
    "street":           string oder null,
    "postal_code":      string oder null,
    "city":             string oder null
  },
  "confidence": "high" | "medium" | "low",
  "notes":      string                             // kurze Bemerkungen oder ""
}
"""


PROMPT_GRUNDBUCH = _PROMPT_BASE + """

Dokument-Typ: GRUNDBUCHAUSZUG. Extrahiere den/die Eigentümer (Abteilung I)
und die Objektadresse (Bestandsverzeichnis).

JSON-Schema:

{
  "property": {
    "street":                 string oder null,
    "postal_code":            string oder null,
    "city":                   string oder null,
    "land_registry_district": string oder null,   // Grundbuchbezirk/Amtsgericht
    "folio_number":           string oder null    // Grundbuchblatt-Nr.
  },
  "owner": {
    "type":                   "PERSON" | "COMPANY",
    "salutation":             string oder null,   // nur Person
    "title":                  string oder null,   // Dr., Prof. etc.
    "first_name":             string oder null,
    "last_name":              string oder null,
    "company_name":           string oder null,
    "trade_register_number":  string oder null,   // HRB-Nr.
    "street":                 string oder null,   // Eigentümer-Anschrift
    "postal_code":            string oder null,
    "city":                   string oder null,
    "country":                string oder null
  },
  "confidence": "high" | "medium" | "low",
  "notes":      string
}

Hinweise:
- Bei Ehepaar (Eigentum zu je 1/2): type=PERSON, beide Namen im ``last_name``
  zusammenfügen (``Max und Erika Mustermann``) und in ``notes`` erwähnen.
- Bei COMPANY: HRB-Nr. ins ``trade_register_number``-Feld. Ist das Unternehmen
  zusätzlich als Erbengemeinschaft / BGB-Gesellschaft notiert, bleibt
  type=COMPANY und Details in ``notes``.
"""


PROMPT_MIETVERTRAG = _PROMPT_BASE + """

Dokument-Typ: MIETVERTRAG. Extrahiere den Mieter, die betroffene Einheit und
die vertraglichen Eckdaten (Miete, Kaution, ggf. Lastschriftmandat).

JSON-Schema:

{
  "property": {
    "street":      string oder null,
    "postal_code": string oder null,
    "city":        string oder null
  },
  "unit": {
    "number":      string oder null,   // Einheits-Nr., falls im Vertrag genannt
    "unit_type":   "APARTMENT" | "COMMERCIAL" | "PARKING" | "OTHER" | null,
    "floor":       string oder null,   // z. B. "EG", "1", "DG"
    "position":    string oder null,   // z. B. "links", "1OGR"
    "living_area": number oder null    // m2
  },
  "tenant": {
    "type":          "PERSON" | "COMPANY",
    "salutation":    string oder null,
    "first_name":    string oder null,
    "last_name":     string oder null,
    "company_name":  string oder null,
    "email":         string oder null,
    "phone":         string oder null,
    "street":        string oder null,   // Mieter-Privatanschrift, falls abweichend
    "postal_code":   string oder null,
    "city":          string oder null
  },
  "contract": {
    "signed_date":      string oder null,   // Unterschriftsdatum YYYY-MM-DD
    "start_date":       string oder null,   // Mietbeginn
    "end_date":         string oder null,   // null = unbefristet
    "vat_relevant":     boolean oder null,
    "cold_rent":        number oder null,   // Kaltmiete monatlich
    "operating_costs":  number oder null,   // Betriebskosten/Nebenkosten-Vorauszahlung
    "heating_costs":    number oder null,   // Heizkosten-Vorauszahlung
    "total_rent":       number oder null,   // Warmmiete/Summe, falls explizit
    "deposit":          number oder null,   // Kautionsbetrag
    "deposit_type":     "CASH" | "GUARANTEE" | "DEPOSIT_ACCOUNT" | null,
    "deposit_due_date": string oder null,
    "payment_method":   "SELF_PAYER" | "DIRECT_DEBIT" | null,
    "iban":             string oder null,   // nur wenn Lastschriftmandat im Vertrag
    "bic":              string oder null
  },
  "confidence": "high" | "medium" | "low",
  "notes":      string
}

Hinweise:
- Gewerbe vs. Wohnung: wenn das Dokument Gewerberaum/Gewerbemiete/MwSt. erwähnt,
  ``unit_type=COMMERCIAL`` und ``vat_relevant=true``.
- Wenn nur eine Gesamtmiete genannt ist und Betriebs-/Heizkosten nicht
  getrennt ausgewiesen sind, setze die Einzelposten auf null und nutze
  ``total_rent``.
"""


PROMPT_MIETERLISTE = _PROMPT_BASE + """

Dokument-Typ: MIETERLISTE oder FLÄCHENLISTE. Extrahiere die Einheiten-
Tabelle. Manche Listen haben Block-Bezeichnungen (Block F, Block B etc.);
falls vorhanden, erfasse sie im ``buildings``-Array.

JSON-Schema:

{
  "property": {
    "street":      string oder null,
    "postal_code": string oder null,
    "city":        string oder null
  },
  "buildings": [
    {
      "name": string   // z. B. "Block F", "Block B", "Haus 1"
    }
  ],
  "units": [
    {
      "number":          string,                    // Einheits-Nr., Pflicht
      "unit_type":       "APARTMENT" | "COMMERCIAL" | "PARKING" | "OTHER" | null,
      "building_name":   string oder null,          // referenziert ``buildings[].name``
      "floor":           string oder null,
      "position":        string oder null,
      "living_area":     number oder null,          // m2
      "heating_area":    number oder null,          // m2
      "persons":         integer oder null,
      "tenant_name":     string oder null,
      "cold_rent":       number oder null,
      "operating_costs": number oder null,
      "heating_costs":   number oder null
    }
  ],
  "confidence": "high" | "medium" | "low",
  "notes":      string
}

Hinweise:
- Gib jede Einheit genau einmal zurück, auch wenn sie in der Quell-Tabelle
  mehrfach auftaucht (z. B. Flächenliste + Mieterliste nebeneinander).
- ``persons`` nur setzen wenn die Liste eine Personenzahl pro Einheit
  ausweist; sonst null.
- ``buildings`` darf leer sein, wenn die Liste keine Block-Bezeichnung hat.
"""


PROMPT_SONSTIGES = _PROMPT_BASE + """

Dokument-Typ: SONSTIGES (z. B. Energieausweis, Nebenkostenabrechnung,
Schriftwechsel). Liefere eine Kurz-Zusammenfassung und nützliche
Einzelangaben als freie KV.

JSON-Schema:

{
  "summary":        string,                         // 1-3 Sätze: was ist das?
  "useful_fields":  object,                          // freie KV, z. B. {"energy_rating": "C", "heating_type": "Gas"}
  "confidence": "high" | "medium" | "low",
  "notes":      string
}
"""


_PROMPTS: dict[str, str] = {
    "verwaltervertrag": PROMPT_VERWALTERVERTRAG,
    "grundbuch": PROMPT_GRUNDBUCH,
    "mietvertrag": PROMPT_MIETVERTRAG,
    "mieterliste": PROMPT_MIETERLISTE,
    "sonstiges": PROMPT_SONSTIGES,
}


# ---------------------------------------------------------------------------
# Pydantic-Schemas pro Doc-Typ
# ---------------------------------------------------------------------------

UnitType = Literal["APARTMENT", "COMMERCIAL", "PARKING", "OTHER"]
ContactType = Literal["PERSON", "COMPANY", "MANAGEMENT_COMPANY"]
DepositType = Literal["CASH", "GUARANTEE", "DEPOSIT_ACCOUNT"]
PaymentMethod = Literal["SELF_PAYER", "DIRECT_DEBIT"]
Confidence = Literal["high", "medium", "low"]


class _BaseExtraction(BaseModel):
    """Gemeinsame Config fuer alle Doc-Extractions."""

    model_config = ConfigDict(extra="ignore")

    confidence: Confidence = "medium"
    notes: str = ""


class _PropertyBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    number: Optional[str] = None
    name: Optional[str] = None
    street: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    creditor_id: Optional[str] = None
    land_registry_district: Optional[str] = None
    folio_number: Optional[str] = None


class _ManagementContractBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    management_company_name: Optional[str] = None
    supervisor_name: Optional[str] = None
    accountant_name: Optional[str] = None
    contract_start_date: Optional[str] = None
    contract_end_date: Optional[str] = None
    dunning_fee_net: Optional[float] = None


class _BillingAddressBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    is_same_as_owner: bool = True
    street: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None


class _OwnerBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: ContactType = "PERSON"
    salutation: Optional[str] = None
    title: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    trade_register_number: Optional[str] = None
    street: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


class _UnitBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    number: Optional[str] = None
    unit_type: Optional[UnitType] = None
    building_name: Optional[str] = None
    floor: Optional[str] = None
    position: Optional[str] = None
    living_area: Optional[float] = None
    heating_area: Optional[float] = None
    persons: Optional[int] = None
    tenant_name: Optional[str] = None
    cold_rent: Optional[float] = None
    operating_costs: Optional[float] = None
    heating_costs: Optional[float] = None


class _BuildingBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str


class _TenantBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: ContactType = "PERSON"
    salutation: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    street: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None


class _ContractBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    signed_date: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    vat_relevant: Optional[bool] = None
    cold_rent: Optional[float] = None
    operating_costs: Optional[float] = None
    heating_costs: Optional[float] = None
    total_rent: Optional[float] = None
    deposit: Optional[float] = None
    deposit_type: Optional[DepositType] = None
    deposit_due_date: Optional[str] = None
    payment_method: Optional[PaymentMethod] = None
    iban: Optional[str] = None
    bic: Optional[str] = None


class VerwaltervertragExtraction(_BaseExtraction):
    property: _PropertyBlock = Field(default_factory=_PropertyBlock)
    management_contract: _ManagementContractBlock = Field(
        default_factory=_ManagementContractBlock
    )
    billing_address: _BillingAddressBlock = Field(
        default_factory=_BillingAddressBlock
    )


class GrundbuchExtraction(_BaseExtraction):
    property: _PropertyBlock = Field(default_factory=_PropertyBlock)
    owner: _OwnerBlock = Field(default_factory=_OwnerBlock)


class MietvertragExtraction(_BaseExtraction):
    property: _PropertyBlock = Field(default_factory=_PropertyBlock)
    unit: _UnitBlock = Field(default_factory=_UnitBlock)
    tenant: _TenantBlock = Field(default_factory=_TenantBlock)
    contract: _ContractBlock = Field(default_factory=_ContractBlock)


class MieterlisteExtraction(_BaseExtraction):
    property: _PropertyBlock = Field(default_factory=_PropertyBlock)
    buildings: list[_BuildingBlock] = Field(default_factory=list)
    units: list[_UnitBlock] = Field(default_factory=list)


class SonstigesExtraction(_BaseExtraction):
    summary: str = ""
    useful_fields: dict[str, Any] = Field(default_factory=dict)


_SCHEMAS: dict[str, type[_BaseExtraction]] = {
    "verwaltervertrag": VerwaltervertragExtraction,
    "grundbuch": GrundbuchExtraction,
    "mietvertrag": MietvertragExtraction,
    "mieterliste": MieterlisteExtraction,
    "sonstiges": SonstigesExtraction,
}


# ---------------------------------------------------------------------------
# Ergebnis-Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ClassifyResult:
    doc_type: str | None
    confidence: str
    reason: str
    model: str
    raw_response: str
    error: str | None = None


@dataclass
class ExtractResult:
    doc_type: str
    model: str
    prompt_version: str
    raw_response: str
    data: dict[str, Any] | None
    status: str  # "ok" | "needs_review" | "failed"
    error: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CODEFENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


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


def _parse_json_payload(raw_text: str) -> tuple[dict[str, Any] | None, str]:
    """Versucht das JSON aus der Claude-Antwort zu ziehen. Toleriert Codefence
    und eingestreuten Text (nimmt dann das erste Objekt in einem Codefence)."""
    text = _strip_codefence(raw_text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data, ""
    except json.JSONDecodeError as exc:
        pass
    match = _CODEFENCE_RE.search(raw_text)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                return data, ""
        except json.JSONDecodeError:
            pass
    return None, "Konnte kein JSON-Objekt aus der Claude-Antwort parsen."


def _normalize_iban(raw: str) -> str:
    """Unicode-NFKC + reine Alphanumerik — wie in services/impower.py und
    services/claude.py, um Zero-Width-Spaces u.a. Schmutz aus LLM-Outputs
    zu entfernen bevor wir gegen schwifty validieren."""
    normalized = unicodedata.normalize("NFKC", raw)
    return "".join(c for c in normalized if c.isalnum()).upper()


def _validate_iban_or_drop(data: dict[str, Any], path: list[str]) -> str | None:
    """Nimmt den IBAN-Wert an dem Pfad in data, normalisiert ihn und validiert
    ihn per schwifty. Schreibt den normalisierten Wert zurueck wenn ok, sonst
    setzt er ihn auf None und gibt die Fehlermeldung zurueck."""
    node: Any = data
    for key in path[:-1]:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
        if node is None:
            return None
    if not isinstance(node, dict):
        return None
    raw = node.get(path[-1])
    if not raw:
        return None
    normalized = _normalize_iban(str(raw))
    try:
        SchwiftyIBAN(normalized)
    except Exception as exc:  # noqa: BLE001
        node[path[-1]] = None
        return f"IBAN '{normalized}' ungültig ({exc}) — verworfen."
    node[path[-1]] = normalized
    return None


# ---------------------------------------------------------------------------
# Classify
# ---------------------------------------------------------------------------

def classify_document(
    pdf_bytes: bytes, workflow: "Workflow"
) -> ClassifyResult:
    """Bestimmt den Doc-Typ eines PDFs per Claude. Nutzt das Chat-Modell,
    weil der Output knapp ist und Haiku/Sonnet dafuer reichen."""
    model = workflow.chat_model or DEFAULT_CHAT_MODEL

    if not settings.anthropic_api_key:
        return ClassifyResult(
            doc_type=None,
            confidence="low",
            reason="",
            model=model,
            raw_response="",
            error="ANTHROPIC_API_KEY ist nicht gesetzt.",
        )

    client = Anthropic(api_key=settings.anthropic_api_key)
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    try:
        response = client.messages.create(
            model=model,
            max_tokens=256,
            system=CLASSIFY_PROMPT,
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
                            "text": "Klassifiziere dieses Dokument.",
                        },
                    ],
                }
            ],
        )
    except APIError as exc:
        return ClassifyResult(
            doc_type=None,
            confidence="low",
            reason="",
            model=model,
            raw_response="",
            error=f"Anthropic-API-Fehler: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return ClassifyResult(
            doc_type=None,
            confidence="low",
            reason="",
            model=model,
            raw_response="",
            error=f"{type(exc).__name__}: {exc}",
        )

    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    data, parse_err = _parse_json_payload(raw_text)
    if data is None:
        return ClassifyResult(
            doc_type=None,
            confidence="low",
            reason="",
            model=response.model,
            raw_response=raw_text,
            error=parse_err,
        )

    doc_type = data.get("doc_type")
    if doc_type not in VALID_DOC_TYPES:
        doc_type = None
    return ClassifyResult(
        doc_type=doc_type,
        confidence=data.get("confidence", "medium"),
        reason=data.get("reason", ""),
        model=response.model,
        raw_response=raw_text,
        error=None if doc_type else "Unbekannter doc_type in Antwort.",
    )


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

def _compose_extract_system_prompt(
    workflow: "Workflow", doc_type: str
) -> str:
    """System-Prompt = Workflow-Meta-Prompt + typ-spezifische Anweisung +
    Lern-Notizen (wenn vorhanden). Das Workflow-System-Prompt ist bewusst
    der Meta-Teil; die konkreten Schemas kommen aus Code."""
    base = workflow.system_prompt.rstrip()
    type_prompt = _PROMPTS[doc_type]
    notes = workflow.learning_notes.strip()
    prompt = f"{base}\n\n---\n\n{type_prompt}"
    if notes:
        prompt += (
            "\n\n---\n\nLERN-NOTIZEN (aus bisherigen Korrekturen — "
            f"berücksichtige diese):\n{notes}"
        )
    return prompt


def _evaluate_extract_status(doc_type: str, data: dict[str, Any]) -> str:
    """Minimal-Check: Pflichtfelder pro Doc-Typ vorhanden? Sonst needs_review."""
    confidence = data.get("confidence", "medium")
    if doc_type == "verwaltervertrag":
        prop = data.get("property") or {}
        mc = data.get("management_contract") or {}
        ok = (
            (prop.get("number") or prop.get("name"))
            and prop.get("street")
            and prop.get("city")
            and mc.get("contract_start_date")
        )
    elif doc_type == "grundbuch":
        owner = data.get("owner") or {}
        ok = bool(
            owner.get("last_name")
            or owner.get("company_name")
        )
    elif doc_type == "mietvertrag":
        tenant = data.get("tenant") or {}
        contract = data.get("contract") or {}
        ok = bool(
            (tenant.get("last_name") or tenant.get("company_name"))
            and contract.get("start_date")
        )
    elif doc_type == "mieterliste":
        units = data.get("units") or []
        ok = len(units) > 0
    elif doc_type == "sonstiges":
        ok = bool(data.get("summary"))
    else:
        ok = False
    if not ok:
        return "needs_review"
    if confidence == "low":
        return "needs_review"
    return "ok"


def extract_for_doc_type(
    pdf_bytes: bytes, workflow: "Workflow", doc_type: str
) -> ExtractResult:
    """Extrahiert typ-spezifische Felder aus einem PDF per Claude."""
    version = f"{prompt_version_for(workflow)}-{doc_type}"
    model = workflow.model or DEFAULT_MODEL

    if doc_type not in _SCHEMAS:
        return ExtractResult(
            doc_type=doc_type,
            model=model,
            prompt_version=version,
            raw_response="",
            data=None,
            status="failed",
            error=f"Unbekannter doc_type: {doc_type}",
        )

    if not settings.anthropic_api_key:
        return ExtractResult(
            doc_type=doc_type,
            model=model,
            prompt_version=version,
            raw_response="",
            data=None,
            status="failed",
            error="ANTHROPIC_API_KEY ist nicht gesetzt.",
        )

    client = Anthropic(api_key=settings.anthropic_api_key)
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    system_prompt = _compose_extract_system_prompt(workflow, doc_type)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
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
                            "text": f"Extrahiere die Felder als JSON. Doc-Typ: {doc_type}.",
                        },
                    ],
                }
            ],
        )
    except APIError as exc:
        return ExtractResult(
            doc_type=doc_type,
            model=model,
            prompt_version=version,
            raw_response="",
            data=None,
            status="failed",
            error=f"Anthropic-API-Fehler: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return ExtractResult(
            doc_type=doc_type,
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
    raw_data, parse_err = _parse_json_payload(raw_text)
    if raw_data is None:
        return ExtractResult(
            doc_type=doc_type,
            model=response.model,
            prompt_version=version,
            raw_response=raw_text,
            data=None,
            status="failed",
            error=parse_err,
        )

    # IBAN-Guard: Mietvertrag kann eine IBAN enthalten (Lastschriftmandat).
    # Andere Typen aktuell nicht.
    iban_warnings: list[str] = []
    if doc_type == "mietvertrag":
        warn = _validate_iban_or_drop(raw_data, ["contract", "iban"])
        if warn:
            iban_warnings.append(warn)

    schema = _SCHEMAS[doc_type]
    try:
        validated = schema.model_validate(raw_data)
    except ValidationError as exc:
        return ExtractResult(
            doc_type=doc_type,
            model=response.model,
            prompt_version=version,
            raw_response=raw_text,
            data=raw_data,
            status="needs_review",
            error=f"Schema-Abweichung: {exc}",
        )

    data = validated.model_dump()
    if iban_warnings:
        prev_notes = data.get("notes", "") or ""
        data["notes"] = (
            prev_notes + (" " if prev_notes else "") + " ".join(iban_warnings)
        ).strip()

    return ExtractResult(
        doc_type=doc_type,
        model=response.model,
        prompt_version=version,
        raw_response=raw_text,
        data=data,
        status=_evaluate_extract_status(doc_type, data),
    )


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

# Pro Feld im konsolidierten Case-State: welche Doc-Typen duerfen es setzen,
# und in welcher Reihenfolge (frueher = hoehere Prio)?
_FIELD_PRIORITY: dict[str, tuple[str, ...]] = {
    # Property-Stammdaten
    "property.number":       ("verwaltervertrag",),
    "property.name":         ("verwaltervertrag",),
    "property.street":       ("verwaltervertrag", "grundbuch", "mieterliste", "mietvertrag"),
    "property.postal_code":  ("verwaltervertrag", "grundbuch", "mieterliste", "mietvertrag"),
    "property.city":         ("verwaltervertrag", "grundbuch", "mieterliste", "mietvertrag"),
    "property.country":      ("verwaltervertrag", "grundbuch"),
    "property.creditor_id":  ("verwaltervertrag",),
    "property.land_registry_district": ("grundbuch",),
    "property.folio_number":           ("grundbuch",),
    # Verwaltungsvertrag
    "management_contract":   ("verwaltervertrag",),
    # Rechnungsadresse
    "billing_address":       ("verwaltervertrag",),
    # Eigentuemer
    "owner":                 ("grundbuch",),
}


def _pick(values: list[tuple[str, Any]], priority: tuple[str, ...]) -> Any:
    """Aus einer Liste (doc_type, value) den ersten Wert nach Prioritaet."""
    by_type: dict[str, Any] = {}
    for doc_type, value in values:
        if value is None or value == "":
            continue
        by_type.setdefault(doc_type, value)
    for doc_type in priority:
        if doc_type in by_type:
            return by_type[doc_type]
    return None


def merge_case_state(
    extractions: list[dict[str, Any]],
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Baut aus n Extractions + User-Overrides den konsolidierten Case-State.

    Input:
      - ``extractions``: Liste von Dicts mit {"doc_id", "doc_type", "data"} —
        "data" ist das validierte Extraction-Output-Dict.
      - ``overrides``: strukturierte User-Eingaben, die pro Feld/Sektion Vorrang
        vor der Auto-Merge haben. Schema:
          {
            "property":            {feld: wert},          # feldweise ueber Auto
            "management_contract": {feld: wert},
            "billing_address":     {feld: wert},
            "owner":               {feld: wert},
            "buildings":           [{...}],               # komplette Liste ersetzt Auto
            "units":               [{...}],
            "tenant_contracts":    [{...}],
          }
        Felder, die nicht im Override stehen, kommen aus der Auto-Merge.

    Output: Case-State-Dict mit den gemergten Feldern + ``_extractions`` +
    ``_overrides`` als Provenance/Persistenz-Rohdaten.
    """
    overrides = overrides or {}
    # Rohdaten pro Doc festhalten fuer Provenance
    raw_by_doc: dict[str, dict[str, Any]] = {}
    for entry in extractions:
        doc_id = str(entry.get("doc_id", ""))
        if not doc_id:
            continue
        raw_by_doc[doc_id] = {
            "doc_type": entry.get("doc_type"),
            "data": entry.get("data") or {},
            "status": entry.get("status"),
        }

    # Property-Block: Feld-weise mergen
    property_state: dict[str, Any] = {}
    property_fields = (
        "number", "name", "street", "postal_code", "city", "country",
        "creditor_id", "land_registry_district", "folio_number",
    )
    for field in property_fields:
        vals: list[tuple[str, Any]] = []
        for entry in extractions:
            data = entry.get("data") or {}
            prop = data.get("property") or {}
            vals.append((entry.get("doc_type", ""), prop.get(field)))
        prio = _FIELD_PRIORITY.get(f"property.{field}", VALID_DOC_TYPES)
        v = _pick(vals, prio)
        if v is not None:
            property_state[field] = v

    # Default country DE, falls irgendwo Adresse erkannt
    if property_state.get("street") and not property_state.get("country"):
        property_state["country"] = "DE"

    # Management-Contract: nur aus Verwaltervertrag
    mc_state: dict[str, Any] = {}
    for entry in extractions:
        if entry.get("doc_type") != "verwaltervertrag":
            continue
        block = (entry.get("data") or {}).get("management_contract") or {}
        for k, v in block.items():
            if v is not None and v != "":
                mc_state.setdefault(k, v)

    # Billing-Address: nur aus Verwaltervertrag
    billing_state: dict[str, Any] | None = None
    for entry in extractions:
        if entry.get("doc_type") != "verwaltervertrag":
            continue
        block = (entry.get("data") or {}).get("billing_address") or {}
        if block:
            billing_state = {k: v for k, v in block.items() if v is not None and v != ""}
            break

    # Owner: nur aus Grundbuch
    owner_state: dict[str, Any] | None = None
    for entry in extractions:
        if entry.get("doc_type") != "grundbuch":
            continue
        block = (entry.get("data") or {}).get("owner") or {}
        if block.get("last_name") or block.get("company_name"):
            owner_state = {k: v for k, v in block.items() if v is not None and v != ""}
            break

    # Buildings: aus Mieterliste (primaer) — eindeutige Namen
    buildings_state: list[dict[str, Any]] = []
    seen_buildings: set[str] = set()
    for entry in extractions:
        if entry.get("doc_type") != "mieterliste":
            continue
        for b in (entry.get("data") or {}).get("buildings") or []:
            name = (b or {}).get("name")
            if not name or name in seen_buildings:
                continue
            seen_buildings.add(name)
            buildings_state.append({"name": name})

    # Units: aus Mieterliste (primaer), Mietvertraege ergaenzen per unit.number
    units_by_number: dict[str, dict[str, Any]] = {}
    # Erst Mieterliste
    for entry in extractions:
        if entry.get("doc_type") != "mieterliste":
            continue
        for u in (entry.get("data") or {}).get("units") or []:
            num = (u or {}).get("number")
            if not num:
                continue
            units_by_number[str(num)] = {k: v for k, v in u.items() if v is not None}
    # Dann Mietvertraege: merge in unit.number wenn vorhanden, sonst anhaengen
    for entry in extractions:
        if entry.get("doc_type") != "mietvertrag":
            continue
        u = (entry.get("data") or {}).get("unit") or {}
        num = u.get("number")
        if not num:
            continue
        existing = units_by_number.get(str(num)) or {}
        for k, v in u.items():
            if v is not None and k not in existing:
                existing[k] = v
        units_by_number[str(num)] = existing
    units_state = list(units_by_number.values())

    # Tenant-Contracts: 1 pro Mietvertrag-PDF
    tenant_contracts: list[dict[str, Any]] = []
    for entry in extractions:
        if entry.get("doc_type") != "mietvertrag":
            continue
        data = entry.get("data") or {}
        tenant_contracts.append(
            {
                "source_doc_id": str(entry.get("doc_id", "")),
                "unit_number": (data.get("unit") or {}).get("number"),
                "tenant": data.get("tenant") or {},
                "contract": data.get("contract") or {},
            }
        )

    # Mieter-Namen fallback aus Mieterliste einziehen, falls kein eigener Mietvertrag
    tenant_unit_numbers = {
        str(tc.get("unit_number")) for tc in tenant_contracts if tc.get("unit_number")
    }
    for entry in extractions:
        if entry.get("doc_type") != "mieterliste":
            continue
        for u in (entry.get("data") or {}).get("units") or []:
            num = (u or {}).get("number")
            name = (u or {}).get("tenant_name")
            if not num or not name or str(num) in tenant_unit_numbers:
                continue
            tenant_contracts.append(
                {
                    "source_doc_id": str(entry.get("doc_id", "")),
                    "unit_number": str(num),
                    "tenant": {"type": "PERSON", "company_name": name},
                    "contract": {
                        "cold_rent": u.get("cold_rent"),
                        "operating_costs": u.get("operating_costs"),
                        "heating_costs": u.get("heating_costs"),
                    },
                    "_partial": True,
                }
            )

    state: dict[str, Any] = {
        "property": property_state,
        "management_contract": mc_state,
        "billing_address": billing_state,
        "owner": owner_state,
        "buildings": buildings_state,
        "units": units_state,
        "tenant_contracts": tenant_contracts,
        "_extractions": raw_by_doc,
        "_overrides": overrides,
    }

    # Overrides obendrauf — einfache Dict-Sektionen feldweise mergen,
    # Listen-Sektionen komplett ersetzen (das User-Editier-Modell aendert
    # Listen als Ganzes: add/remove/reorder).
    for section in ("property", "management_contract", "billing_address"):
        o = overrides.get(section) or {}
        if o:
            base = dict(state.get(section) or {})
            base.update({k: v for k, v in o.items() if v is not None})
            state[section] = base

    # Owner darf in Override komplett leer/weggenommen werden (z. B. falls
    # der User einen anderen Eigentuemer-Kontakt ausgewaehlt hat).
    if "owner" in overrides:
        o = overrides["owner"]
        if o is None or o == {}:
            state["owner"] = None
        else:
            base = dict(state.get("owner") or {})
            base.update({k: v for k, v in o.items() if v is not None})
            state["owner"] = base

    for section in ("buildings", "units", "tenant_contracts"):
        if section in overrides and overrides[section] is not None:
            state[section] = overrides[section]

    return state


# ---------------------------------------------------------------------------
# Feld-Provenance (Paket 5: fuer Status-Indikatoren pro Feld im Formular)
# ---------------------------------------------------------------------------

def field_source(
    case_state: dict[str, Any] | None, section: str, field: str
) -> dict[str, Any]:
    """Bestimmt Herkunft eines Feldwerts im Case-State.

    Returns:
        {"state": "user"}                       — vom User manuell gesetzt
        {"state": "auto", "doc_type": "..."}    — aus einer Doc-Extraktion
        {"state": "auto"}                       — aus Auto-Merge, kein klarer
                                                   Source-Doc (z. B. Default DE)
        {"state": "missing"}                    — Wert ist leer/null
    """
    if not case_state:
        return {"state": "missing"}
    overrides = case_state.get("_overrides") or {}
    sec_override = overrides.get(section)
    if isinstance(sec_override, dict) and field in sec_override:
        val = sec_override[field]
        if val is not None and val != "":
            return {"state": "user"}

    value = (case_state.get(section) or {}).get(field) if isinstance(case_state.get(section), dict) else None
    if value is None or value == "":
        return {"state": "missing"}

    extractions = case_state.get("_extractions") or {}
    for doc_id, entry in extractions.items():
        data = (entry or {}).get("data") or {}
        block = data.get(section) if isinstance(data.get(section), dict) else None
        if block and block.get(field) not in (None, ""):
            return {"state": "auto", "doc_type": entry.get("doc_type"), "doc_id": doc_id}
    return {"state": "auto"}
