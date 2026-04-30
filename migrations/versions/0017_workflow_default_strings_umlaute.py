"""workflows: description + system_prompt der 4 Default-Keys auf echte Umlaute

Hintergrund: Der „Umlaut-Sweep ausserhalb ETV" hat die Strings im Code
auf echte Umlaute (ä/ö/ü/ß) umgestellt. ``_seed_default_workflow``
ueberschreibt bestehende DB-Rows aber nicht (idempotent only on
missing keys), d. h. Production-DBs zeigen weiter die alten ASCII-Werte
(``Eigentuemer``, ``Mietvertraege``, ``fuer``) im Workflow-Listing.

Strategie:
- ``description``: per Key ohne Schutz-WHERE updaten — die Spalte ist
  nicht UI-editierbar, eine vorhandene Abweichung wuerde nur per
  manuellem SQL passieren.
- ``system_prompt``: nur ueberschreiben, wenn ein eindeutiger ASCII-
  Marker aus dem alten Default noch drin ist. Marker absichtlich
  spezifisch (`WEG-Kuerzel wie HAM61`, ``Du unterstuetzt bei der
  Neuanlage``, ``Geschaeftsfuehrer``), damit minimal angepasste
  User-Versionen geschuetzt sind.
- ETV-Workflow: ``system_prompt`` war leer und bleibt leer — nur
  Description-Update.

Down-Migration ist no-op. Den Sweep zurueckdrehen waere Unsinn; die
neuen Werte sind die kanonischen Defaults.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_DESCRIPTIONS: dict[str, str] = {
    "sepa_mandate": (
        "Extraktion von Eigentümer, WEG, IBAN und SEPA-Datum aus "
        "eingescannten SEPA-Lastschriftmandaten. Ziel: automatische "
        "Pflege in Impower nach Human-in-the-Loop-Freigabe."
    ),
    "mietverwaltung_setup": (
        "Neuanlage einer kompletten Mietverwaltung in Impower aus 1-n PDFs "
        "(Verwaltervertrag, Grundbuch, Mieterliste, Mietverträge). "
        "Fall-basiert: mehrere Dokumente bilden zusammen einen Fall."
    ),
    "contact_create": (
        "Sub-Workflow zum Anlegen eines Impower-Kontakts (Person oder "
        "Unternehmen). Wiederverwendbar aus anderen Workflows (z. B. "
        "aus Mietverwaltung heraus für Eigentümer/Mieter)."
    ),
    "etv_signature_list": (
        "Druckfertige Unterschriftenliste für eine Eigentümer-"
        "versammlung (ETV). Liest Conferences + Voting-Groups + "
        "Mandate aus Facilioo und rendert ein A4-Querformat-PDF. "
        "Kein Claude — reiner Read-/Render-Pfad."
    ),
}


_NEW_SEPA_PROMPT = """Du bist ein Assistent, der aus eingescannten SEPA-Lastschriftmandaten
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


_NEW_MIETVERWALTUNG_PROMPT = """Du unterstützt bei der Neuanlage einer Mietverwaltung in Impower. Ein Fall
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


_NEW_CONTACT_CREATE_PROMPT = """Du hilfst beim Anlegen eines Kontakts (Person oder Unternehmen) in der
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


# ASCII-Marker aus dem alten Default-Prompt; wenn nicht mehr enthalten,
# hat der User den Prompt editiert und wir ueberschreiben nicht.
_PROMPT_MARKERS: dict[str, tuple[str, str]] = {
    "sepa_mandate": ("WEG-Kuerzel wie HAM61", _NEW_SEPA_PROMPT),
    "mietverwaltung_setup": (
        "Du unterstuetzt bei der Neuanlage einer Mietverwaltung",
        _NEW_MIETVERWALTUNG_PROMPT,
    ),
    "contact_create": ("Geschaeftsfuehrer", _NEW_CONTACT_CREATE_PROMPT),
}


def upgrade() -> None:
    bind = op.get_bind()

    for key, new_description in _NEW_DESCRIPTIONS.items():
        bind.execute(
            sa.text(
                "UPDATE workflows SET description = :desc WHERE key = :key"
            ),
            {"desc": new_description, "key": key},
        )

    for key, (marker, new_prompt) in _PROMPT_MARKERS.items():
        bind.execute(
            sa.text(
                "UPDATE workflows SET system_prompt = :prompt "
                "WHERE key = :key AND system_prompt LIKE :marker"
            ),
            {
                "prompt": new_prompt,
                "key": key,
                "marker": f"%{marker}%",
            },
        )


def downgrade() -> None:
    # No-op: den Sweep zurueckdrehen waere Unsinn — die neuen Werte sind die
    # kanonischen Defaults aus dem Code.
    pass
