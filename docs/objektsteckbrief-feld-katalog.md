# Objektsteckbrief — Feld-Katalog

**Status:** Entwurf 2026-04-21 aus Brainstorming-Session (`docs/brainstorming/objektsteckbrief-2026-04-21.md`)
**Zweck:** Vollstaendige Attribut-Landkarte als Grundlage fuer Migration, Routen, Formular-Rendering und Registry-Implementierung.
**Offen:** Finale Typ-Entscheidungen (ENUM-Werte, Praezision bei DECIMAL), v1.1-Scope fuer Registry-Detailseiten.

---

## Legende

| Spalte | Werte |
|---|---|
| **Typ** | `str` · `text` · `int` · `decimal` · `bool` · `date` · `datetime` · `enum(...)` · `file` (SharePoint-Link) · `FK→Entitaet` · `JSONB` · `array<...>` · `derived` (berechnet) |
| **Pflicht v1** | `✓` Pflicht · `○` optional · `v2` erst in v2 |
| **SoR** | `Imp` Impower · `Fac` Facilioo · `SP` SharePoint · **`St`** Steckbrief (intern) · `derived` berechnet |
| **Sync** | `M` Mirror (periodisch kopieren) · `L` Live-Pull bei Anzeige · `RO` Read-only-Display (kein Kopieren, nur Link) · `—` rein intern |
| **v1** | `M` Must · `S` Should · `C` Could · `—` Won't (v2+) |

**Default-Regel:** alle Felder mit SoR = `St` sind schreibbar im Steckbrief. Felder mit SoR = `Imp`/`Fac` sind in v1 **read-only** im Steckbrief, Write-Back schrittweise ab v1.1 je Feld.

---

## Cluster 1 — Stammdaten & Einheiten-Struktur

**SoR-Default:** Impower (Mirror). Steckbrief fuehrt nur Sekundaer-IDs + Kurzform.

| # | Feld (tech.) | Typ | Pflicht v1 | SoR | Sync | Registry-FK | v1 |
|---|---|---|---|---|---|---|---|
| 1.1 | `short_code` (interne Kurzform, z. B. HAM61) | str | ✓ | St | — | — | M |
| 1.2 | `name` | str | ✓ | Imp | M | — | M |
| 1.3 | `address_street`, `_zip`, `_city`, `_country` | str | ✓ | Imp | M | — | M |
| 1.4 | `impower_property_id` | str | ✓ | Imp | M | — | M |
| 1.5 | `facilioo_id` | str | ○ | Fac | M | — | M |
| 1.6 | `weg_number_intern` | str | ○ | St | — | — | M |
| 1.7 | `owners` | array<FK→Eigentuemer> | ✓ | Imp | M | Eigentuemer | M |
| 1.8 | `voting_rights` (pro Eigentuemer: MEA oder Stimmen) | JSONB | ✓ | Imp | M | — | M |
| 1.9 | `unit_count` | derived | ✓ | derived | — | — | M |
| 1.10 | `total_mea` | derived | ✓ | derived | — | — | M |

---

## Cluster 2 — Einheits-Steckbrief (pro WE)

**SoR-Default:** Impower fuer Kern, Facilioo fuer Zaehler, Steckbrief fuer alles Darueberhinaus.

| # | Feld (pro Unit) | Typ | Pflicht v1 | SoR | Sync | Registry-FK | v1 |
|---|---|---|---|---|---|---|---|
| 2.1 | `unit_number` | str | ✓ | Imp | M | — | M |
| 2.2 | `impower_unit_id` | str | ✓ | Imp | M | — | M |
| 2.3 | `facilioo_unit_id` | str | ○ | Fac | M | — | M |
| 2.4 | `usage_type` | enum(Wohnen, Gewerbe, TG, Keller, Stellplatz, Garage) | ✓ | Imp | M | — | M |
| 2.5 | `floor_area_sqm` | decimal | ✓ | Imp | M | — | M |
| 2.6 | `area_method` | enum(WoFlV, DIN 277, uebernommen, sonstige) | ○ | St | — | — | M |
| 2.7 | `room_count` | decimal | ○ | St | — | — | M |
| 2.8 | `floor_level` | int | ○ | St | — | — | M |
| 2.9 | `has_balcony`, `balcony_sqm` | bool, decimal | ○ | St | — | — | M |
| 2.10 | `basement_room_assigned` | str | ○ | St | — | — | M |
| 2.11 | `parking_spot_assigned` | str | ○ | St | — | — | M |
| 2.12 | `floorplan_file` | file | ○ | SP | RO | — | M |
| 2.13 | `equipment_features` | array<enum> (Fussbodenheizung, Kamin, Einbaukueche, Aufzug, Balkon, Terrasse, Garten, …) | ○ | St | — | — | M |
| 2.14 | `current_owner` | FK→Eigentuemer | ✓ | Imp | M | Eigentuemer | M |
| 2.15 | `current_tenant` | FK→Mieter | ○ | Imp | M | Mieter | M |
| 2.16 | `meters` | array<FK→Zaehler> | ○ | Fac | M | Zaehler | S |
| 2.17 | `image_gallery` | array<file> | ○ | SP | RO | — | S |

---

## Cluster 3 — Personen & laufende Vorgaenge

**Hinweis:** Die Personen selbst sind **normalisierte Entitaeten** (siehe unten). Hier sind nur die *Beziehungen* und Aggregations-Views auf das Objekt.

| # | Feld am Objekt | Typ | Pflicht v1 | SoR | Sync | Registry-FK | v1 |
|---|---|---|---|---|---|---|---|
| 3.1 | `tenants_current` (Sicht) | derived | ✓ | derived | — | Mieter | M |
| 3.2 | `tenant_history` (Vormieter pro WE + Leerstand) | array<JSONB> | ○ | St | — | — | S |
| 3.3 | `open_tickets` (pro Mieter + pro Eigentuemer) | array<FK→FacilioTicket> | ✓ | Fac | L | — | M |
| 3.4 | `notes_on_owners` (intern, Menschen-Notizen) | JSONB (pro Eigentuemer: freier Text + Schlagworte) | ○ | St | — | — | M |
| 3.5 | `notes_on_tenants` (intern) | JSONB | ○ | St | — | — | S |

---

## Cluster 4 — Technik & Gebaeudesubstanz

**SoR-Default:** Steckbrief komplett. Bild-zentriert: jedes Feld kann mit Foto-Link angereichert werden.

| # | Feld | Typ | Pflicht v1 | SoR | Sync | Registry-FK | v1 |
|---|---|---|---|---|---|---|---|
| 4.1 | `water_shutoff_location`, `_photo` | str, file | ✓ | St | — | — | M |
| 4.2 | `gas_shutoff_location`, `_photo` | str, file | ○ | St | — | — | M |
| 4.3 | `electric_main_location`, `_photo` | str, file | ✓ | St | — | — | M |
| 4.4 | `entry_code_main_door` | str (encrypted) | ○ | St | — | — | M |
| 4.5 | `entry_code_garage` | str (encrypted) | ○ | St | — | — | M |
| 4.6 | `elevator_emergency_contract` | JSONB (Firma, Kundennr, Hotline) | ○ | St | — | — | M |
| 4.7 | `heating_type` | enum(Gas-Brennwert, Oel, Fernwaerme, Waermepumpe, Biomasse, Blockheizkraftwerk, sonstige) | ✓ | St | — | — | M |
| 4.8 | `heating_manufacturer`, `_model`, `_year` | str, str, int | ○ | St | — | — | M |
| 4.9 | `heating_location` | str | ○ | St | — | — | M |
| 4.10 | `heating_service_provider` | FK→Dienstleister | ○ | St | — | Dienstleister | M |
| 4.11 | `heating_fault_hotline` | str | ○ | St | — | — | M |
| 4.12 | `fuse_box_photo_per_unit` | array<file> | ○ | St | — | — | C |
| 4.13 | `year_built` | int | ✓ | St | — | — | M |
| 4.14 | `year_full_renovation` | int | ○ | St | — | — | M |
| 4.15 | `year_roof`, `_pipes_water`, `_pipes_elec`, `_pipes_gas`, `_windows`, `_facade`, `_insulation` | int (je) | ○ | St | — | — | M |
| 4.16 | `roof_type`, `facade_material`, `insulation_type` | str (je, optional) | ○ | St | — | — | S |
| 4.17 | `known_contractors` (kennt dieses Objekt) | array<FK→Dienstleister> mit Gewerke-Historie | ○ | St | — | Dienstleister | M |

---

## Cluster 5 — Medien / DMS

**SoR-Default:** SharePoint fuer Dateien, Steckbrief fuer Metadaten.

| # | Feld | Typ | Pflicht v1 | SoR | Sync | Registry-FK | v1 |
|---|---|---|---|---|---|---|---|
| 5.1 | `property_images` (Galerie Objekt) | array<Image> | ○ | SP | RO | — | S |
| 5.2 | Per Image: `file`, `label`, `captured_at`, `component_ref`, `uploaded_by`, `uploaded_at` | — | — | SP + St (Metadata) | — | — | S |
| 5.3 | `unit_images` | array<Image> pro Unit | ○ | SP | RO | — | S |
| 5.4 | `technical_component_images` (Heizung, Absperrhahn, Sicherungskasten) | array<Image> | ○ | SP | RO | — | M (fuer 4.x-Komponenten) |
| 5.5 | `location_description` | text | ○ | St | — | — | S |
| 5.6 | `poi_structured` (Schule, OePNV, Einkauf, Arzt: je Name, Entfernung) | array<JSONB> | ○ | St | — | — | C (v1.1 AI-gezogen) |

**Implementierungs-Hinweis:** Upload laeuft via Graph-API mit Service-Account. Bilder landen in `SharePoint/DBS/Objekte/{short_code}/{kategorie}/`. Der Steckbrief speichert nur `drive_item_id` + Metadaten. Kein lokaler Blob-Store.

---

## Cluster 6 — Finanzen

**SoR-Default:** Impower (Mirror fuer die meisten, Live-Pull fuer Saldo).

| # | Feld | Typ | Pflicht v1 | SoR | Sync | Registry-FK | v1 |
|---|---|---|---|---|---|---|---|
| 6.1 | `bank_accounts` | array<FK→Bankkonto> | ✓ | Imp | M | Bank | M |
| 6.2 | Per Konto: `current_balance` | decimal | ✓ | Imp | **L** (live-pull) | — | M |
| 6.3 | `reserve_current` | decimal | ✓ | Imp | M | — | M |
| 6.4 | `reserve_history` | array<{date, value}> | ○ | St | — | — | M |
| 6.5 | `reserve_target_monthly` | decimal | ○ | Imp | M | — | M |
| 6.6 | `economic_plan_status` | JSONB (Status enum, Beschlussdatum, PDF-Link) | ○ | Imp | M | — | M |
| 6.7 | `annual_statement_status` | JSONB (analog) | ○ | Imp | M | — | M |
| 6.8 | `sepa_mandates` | array<FK→SepaMandat> | ✓ | Imp | M | — | M |
| 6.9 | `special_contributions` (historisch + geplant) | array<JSONB> | ○ | Imp | M | — | S |
| 6.10 | `payment_quota_pct` | derived | — | derived | — | — | M |
| 6.11 | `maintenance_backlog_estimate_eur` | decimal | ○ | St | — | — | S |
| 6.12 | `insurance_losses_5y_sum` | derived | — | derived | — | — | S |

---

## Cluster 7 — Verwaltervertrag & Dienstleister

**SoR-Default:** Steckbrief fuer unseren Vertrag; Facilioo fuer Dienstleister-CRM-Grunddaten + Steckbrief fuer objekt-bezogene Meta-Felder.

| # | Feld | Typ | Pflicht v1 | SoR | Sync | Registry-FK | v1 |
|---|---|---|---|---|---|---|---|
| 7.1 | `management_contract` | JSONB | ✓ | St | — | — | M |
| 7.1.a | → `package_type` | enum(Full-Service, Miet, WEG, Mix, sonstige) | ✓ | St | — | — | M |
| 7.1.b | → `price_per_unit`, `price_fixed`, `extra_hourly_rate` | decimal | ✓ | St | — | — | M |
| 7.1.c | → `special_services` | text | ○ | St | — | — | M |
| 7.1.d | → `contract_start`, `contract_end`, `notice_period_months`, `next_price_review` | date/int | ✓ | St | — | — | M |
| 7.1.e | → `contract_pdf` | file | ✓ | SP | RO | — | M |
| 7.2 | `assigned_service_providers` | array<FK→Dienstleister> mit Gewerk, Vertragsstatus, verbrannt-Flag | ○ | St | — | Dienstleister | M |
| 7.3 | `known_contractors` | siehe 4.17 | — | — | — | — | — |
| 7.4 | `meter_reading_companies` | array<FK→Ablesefirma> | ○ | Fac | M | Ablesefirma | S |

---

## Cluster 8 — Versicherungen & Wartungspflichten

**SoR-Default:** Steckbrief. Policen und Wartungspflichten sind **eigene Entitaeten** mit Objekt-FK.

| # | Feld am Objekt | Typ | Pflicht v1 | SoR | Sync | Registry-FK | v1 |
|---|---|---|---|---|---|---|---|
| 8.1 | `policies` | array<FK→Police> | ✓ | St | — | Versicherer (ueber Police) | M |
| 8.2 | `damage_history` | array<FK→Schadensfall> | ○ | St | — | — | M |
| 8.3 | `maintenance_obligations` | array<FK→Wartungspflicht> | ✓ | St | — | — | M |
| 8.4 | `risk_attributes` | JSONB | ○ | St | — | — | M |
| 8.4.a | → `building_class`, `roof_material`, `zuers_zone`, `heritage_protection`, `current_vacancy`, `pv_present`, `charging_points_count`, `commercial_tenants` | mixed | ○ | St | — | — | M |

**Siehe Entitaets-Definitionen unten:** `Police`, `Schadensfall`, `Wartungspflicht`.

---

## Cluster 9 — Recht & Governance

**SoR-Default:** Facilioo fuer Beschluesse/Pendenzen (Mirror), Steckbrief fuer strukturierte TE-Felder + Rechtsstreitigkeiten.

| # | Feld | Typ | Pflicht v1 | SoR | Sync | Registry-FK | v1 |
|---|---|---|---|---|---|---|---|
| 9.1 | `decision_history` | array<FK→FaciliooDecision> | ✓ | Fac | M | — | S |
| 9.2 | `open_pendencies` | array<FK→FaciliooPendency> | ○ | Fac | M | — | S |
| 9.3 | `upcoming_decisions` | array<FK→FaciliooDecision> | ○ | Fac | M | — | S |
| 9.4 | `owner_requests_next_eth` | array<FK→FaciliooRequest> | ○ | Fac | M | — | S |
| 9.5 | `teilungserklaerung_pdf` | file | ○ | SP | RO | — | M |
| 9.6 | `te_structured` | JSONB | ○ | St | — | — | S (KI-gestuetzt v2) |
| 9.6.a | → `voting_rule` | enum(Kopf, MEA, Objekt, gemischt) | ○ | St | — | — | S |
| 9.6.b | → `special_usage_rights` | array<JSONB> (Einheit, Objekt, Bezeichnung) | ○ | St | — | — | S |
| 9.6.c | → `quorum_rules` | text | ○ | St | — | — | C |
| 9.7 | `gemeinschaftsordnung_pdf`, `go_highlights` | file + text | ○ | SP + St | RO | — | S |
| 9.8 | `legal_disputes` | array<JSONB> | ○ | St | — | — | M |
| 9.8.a | → `case_number`, `opponent`, `dispute_value`, `lawyer`, `next_hearing`, `status` | mixed | — | St | — | — | M |
| 9.9 | `meeting_minutes_recent` | array<file-SharePoint-Link> | ○ | SP | RO | — | M |

---

## Cluster 10 — Baurecht / DD / ESG

Gesplittet in `v1-MUST` (Baurecht-Kern), `v1-COULD` (DD-Erweitert), `v2` (ESG-Vollumfang).

### Baurecht-Kern (v1-MUST)

| # | Feld | Typ | SoR | v1 |
|---|---|---|---|---|
| 10.1 | `grundbuch` (JSONB: Blatt-Nr, Amtsgericht, Flur, Flurstueck, Groesse_qm, Lasten_abt_ii, Lasten_abt_iii, letzter_Auszug_date, PDF) | JSONB + file | St | M |
| 10.2 | `baugenehmigung_pdf`, `_date` | file, date | St | M |
| 10.3 | `abnahme_pdf`, `_date` | file, date | St | M |
| 10.4 | `nutzungsaenderungen` | array<{date, scope, pdf}> | St | M |
| 10.5 | `heritage_protection_status` | enum(keine, Einzeldenkmal, Ensemble, Umgebung) | St | M |
| 10.6 | `erhaltungssatzung`, `milieuschutz` | bool | St | M |
| 10.7 | `baulasten` | array<JSONB> | St | S |
| 10.8 | `energy_certificate` | JSONB (Typ, Endenergie, Klasse, Ausstellung, Gueltig_bis, PDF) | St + SP | M |
| 10.9 | `environmental_risks` (Altlast, Kampfmittel, Radon, Starkregen-Klasse, Hochwasser-Zone) | JSONB | St | S |
| 10.10 | `defect_backlog` | array<JSONB> (Beschreibung, Summe, Prio, Foto, Quelle, Status) | St | M |

### DD-Erweitert (v1-COULD)

| # | Feld | Typ | SoR | v1 |
|---|---|---|---|---|
| 10.11 | `external_reports` | array<JSONB> (Wert/Dach/Statik/Schadstoff/Thermografie: Datum, Ersteller, Summe, PDF, Ablauf) | St | C |
| 10.12 | `property_tax` (Hebesatz, letzter Bescheid) | JSONB | St | C |
| 10.13 | `funding_status` (KfW-Nr, BAFA-Nr, §7h/7i, Denkmal-AfA) | JSONB | St | C |

### ESG (v2)

| # | Feld | Typ | SoR | v1 |
|---|---|---|---|---|
| 10.14 | `heating_replacement_plan` | JSONB | St | — |
| 10.15 | `co2_tier_model` | JSONB (aktueller Wert, Vermieter-Anteil, Gebaeude-Effizienz) | St | — |
| 10.16 | `isfp_pdf`, `isfp_summary` | file + JSONB | St + SP | — |
| 10.17 | `hydraulic_balancing` (Datum, PDF, naechste Faelligkeit) | JSONB | St | — |
| 10.18 | `charging_infrastructure` | array<JSONB> (Punkte, kW, Betreiber, Abrechnung, geplanter Ausbau) | St | — |
| 10.19 | `pv_systems` | array<JSONB> (Typ WEG/Balkon, MaStR-Nr, EEG-Ende, Mieterstrom) | St | — |
| 10.20 | `water_cycle` (Regenwassernutzung, Versiegelung-qm, Haerte, Legionellen-Plan) | JSONB | St | — |
| 10.21 | `accessibility` (barrierefreie WEs, Aufzug-Reichweite, DIN 18040) | JSONB | St | — |

---

## Cluster 11 — Vertrauliches (WON'T v1)

Blockiert durch fehlendes Feld-Level-ACL.

| # | Feld | Typ | SoR | v1 |
|---|---|---|---|---|
| 11.1 | `silent_risks` (Text + Sichtbarkeits-Flag) | array<JSONB> | St | — |
| 11.2 | `blacklisted_providers` — als Flag an `Dienstleister`-Entitaet plus Grund + Datum, nicht separate Liste | — | St | — (Flag bereits in Dienstleister ab v1, aber die *Sicht darauf* ist permissioned) |

---

## Cluster 12 — Meta / System-Features

### v1-MUST

| # | Feld | Typ | SoR | v1 |
|---|---|---|---|---|
| 12.1 | `maintenance_score` (Pflegegrad 0–100) | derived | derived | M |
| 12.2 | `field_provenance` (pro Feld: Quelle, Zeitstempel, Confidence, User-ID bei manuell) | Tabelle | St | M |
| 12.3 | `review_queue` (KI-Vorschlaege mit Ziel-Feld, Wert, Confidence, Status) | Tabelle | St | M |
| 12.4 | Normalisierte Entitaeten (siehe unten) | — | — | M |
| 12.5 | Registries: Versicherer-Detailseite, Dienstleister-Detailseite, Due-Radar global | — | — | M |

### v1-COULD / v2

| # | Feld | Typ | SoR | v1 |
|---|---|---|---|---|
| 12.6 | `events` (Event-Stream: Ablaufmeldungen, neue Entitaeten, Ruecklagen-Unterschreitung) | Tabelle | St | C |
| 12.7 | Context-Pack-Endpoint `/objects/{id}/context` | — | — | C |
| 12.8 | Custom-Module-Baukasten (JSONB-Extension pro Objekt + UI-Generator) | JSONB | St | — |
| 12.9 | Stichtags-Snapshot | Tabelle | St | — |
| 12.10 | Semantische Suche ueber Freitexte (Embeddings) | — | — | — |

---

## Normalisierte Seiten-Entitaeten (Registry-faehig)

Jede dieser Entitaeten ist eine eigene Tabelle mit eigener Detailseite + Listen-Ansicht.

### Versicherer

| Feld | Typ |
|---|---|
| `id`, `name`, `short_code` | str |
| `contact_broker` (Maklerkontakt) | JSONB |
| `claims_hotline` | str |
| `website`, `portal_login_ref` | str |

**Aggregationen auf Detailseite:** alle verbundenen Policen, Gesamtpraemie p.a., Schadensquote, Laufzeit-Heatmap (Ablaeufe <90 Tage), verbundene Objekte.

### Police

| Feld | Typ |
|---|---|
| `id`, `versicherer_id` (FK), `object_id` (FK) | — |
| `policy_number`, `type` (enum: Gebaeude/Haftpflicht/Glas/Elementar/Leitungswasser/Grobe-Fahrlaessigkeit/Gewerbe) | str/enum |
| `sum_insured`, `deductible`, `annual_premium` | decimal |
| `coverage_summary`, `exclusions` (KI-extrahiert) | text |
| `contract_start`, `contract_end`, `notice_period_months`, `next_main_due` | date/int |
| `policy_holder` (enum: WEG / Einzeleigentuemer-FK) | mixed |
| `pdf_link` | file |

### Wartungspflicht

| Feld | Typ |
|---|---|
| `id`, `object_id`, `policy_id` (FK) | — |
| `obligation_type` (enum: Heizungswartung, E-Check, Blitzschutz, Rueckstausicherung, Schornsteinfeger, Trinkwasserpruefung, Aufzug-TUeV, Spielplatzpruefung, sonstige) | enum |
| `last_inspection_date`, `last_inspection_pdf` | date + file |
| `next_due_date` | date |
| `responsible_provider_id` | FK→Dienstleister |
| `notes` | text |

### Schadensfall

| Feld | Typ |
|---|---|
| `id`, `object_id`, `unit_id` (optional), `policy_id` (FK) | — |
| `damage_date`, `reported_date`, `damage_type` | date/str |
| `claimed_amount`, `settled_amount`, `status` (enum: offen/reguliert/abgelehnt) | decimal/enum |
| `insurer_reference` | str |

### Dienstleister / Handwerker

| Feld | Typ |
|---|---|
| `id`, `name`, `facilioo_provider_id` | str |
| `trade` (enum: Heizung, Sanitaer, Elektro, Dach, Garten, Winterdienst, Hausmeister, Schornsteinfeger, Schluesseldienst, Ablesefirma, Sonstiges) | enum |
| `contact_phone`, `contact_email`, `emergency_hotline` | str |
| `hourly_rate` | decimal |
| `is_blacklisted`, `blacklist_reason`, `blacklist_date` | bool, text, date |

**Aggregationen auf Detailseite:** verbundene Objekte, Gewerke-Historie, Auftragsvolumen 12 Monate, verbrannt-Flag global sichtbar.

### Bank

| Feld | Typ |
|---|---|
| `id`, `name`, `bic` | str |

**Aggregationen:** alle Konten + Mandate pro Bank (fuer IBAN-Wechsel-Kampagnen).

### Bankkonto

| Feld | Typ |
|---|---|
| `id`, `bank_id` (FK), `object_id` (FK) | — |
| `iban`, `account_purpose` (enum: WEG, Ruecklage, Instandhaltung, Mietkonto) | str/enum |
| `signing_rules` | JSONB |

### Eigentuemer

| Feld | Typ |
|---|---|
| `id`, `impower_contact_id`, `facilioo_id` | str |
| Kontaktdaten, Geburtsdatum, bevorzugte Sprache, Anrede | mixed |
| `notes_intern` (Menschen-Notizen, Schlagworte) | JSONB |

**Aggregationen:** alle Objekte des Multi-WEG-Eigentuemers, Gesamthausgeld, offene Forderungen.

### Mieter

| Feld | Typ |
|---|---|
| `id`, `impower_contact_id` | str |
| Kontaktdaten, bevorzugte Sprache, Wohnparteien (Erwachsene/Kinder/Untermieter/Haustier) | mixed |

### Mietvertrag

| Feld | Typ |
|---|---|
| `id`, `tenant_id` (FK), `unit_id` (FK) | — |
| `cold_rent`, `operating_cost_prepayment`, `heating_cost_prepayment`, `deposit_amount`, `deposit_status` | decimal/enum |
| `start_date`, `end_date` (optional), `last_rent_increase_date` | date |
| `index_agreement` (Referenzindex) | enum |
| `staircase_rent_steps` | JSONB |
| `pet_clause`, `special_equipment` | text |
| `pdf_link` | file |

### Ablesefirma

| Feld | Typ |
|---|---|
| `id`, `name`, `provider_code` (ista/techem/minol/…) | str |
| Vertragsende mit welchen Objekten | Aggregation |

### Zaehler (pro Einheit)

| Feld | Typ |
|---|---|
| `id`, `unit_id` (FK), `reading_company_id` (FK) | — |
| `meter_type` (Strom/Gas/Kaltwasser/Warmwasser/Heizung) | enum |
| `meter_number`, `location`, `last_reading_date`, `last_reading_value` | mixed |

### Facilioo-Mirror-Entitaeten (read-only)

- `FaciliooDecision` (Beschluss)
- `FaciliooPendency` (offene Pendenz)
- `FaciliooRequest` (Eigentuemer-Wunsch)
- `FaciliooTicket` (offener Vorgang)

Jede hat `facilioo_id`, `object_id` (FK), Inhalt, Datum, Status. Sync via periodischem Mirror-Job.

---

## System-Tabellen (Meta)

### `field_provenance`

| Spalte | Typ |
|---|---|
| `id`, `entity_type`, `entity_id`, `field_name` | str |
| `value_snapshot` | text/JSONB |
| `source` | enum(manual, impower_mirror, facilioo_mirror, pdf_extraction, ai_suggestion) |
| `source_ref` (Doc-ID, Sync-Run-ID, User-ID) | str |
| `confidence` (nur bei AI) | decimal |
| `created_at`, `approved_at`, `approved_by` | datetime, datetime, FK→User |

**Zweck:** Jeder Schreibvorgang (auch Mirror) erzeugt einen Eintrag. Damit ist *jedes* Feld im Steckbrief genealogisch nachvollziehbar.

### `review_queue`

| Spalte | Typ |
|---|---|
| `id`, `entity_type`, `entity_id`, `field_name`, `proposed_value` | mixed |
| `source` (PDF-Doc-ID, Chat-Session-ID) | str |
| `confidence` | decimal |
| `status` | enum(pending, approved, rejected, superseded) |
| `created_at`, `reviewed_at`, `reviewed_by` | datetime, datetime, FK→User |

**UI-Hinweis:** Jede Objekt-Detailseite zeigt ein Badge "N Vorschlaege offen" das die Queue oeffnet, gefiltert auf dieses Objekt.

### `events` (v1-COULD, v2-Pflicht)

| Spalte | Typ |
|---|---|
| `id`, `entity_type`, `entity_id`, `event_type` | str |
| `payload` | JSONB |
| `severity` (info/warn/critical) | enum |
| `created_at`, `consumed_by` | datetime, array<str> |

**Use-Cases:** Due-Radar-Trigger, Notification-Hub (Backlog-Punkt 4), Audit-Signal.

---

## Offene Punkte / Folge-Entscheidungen

1. **ENUM-Werte finalisieren** — insb. `usage_type`, `heating_type`, `obligation_type`, `policy.type`, `trade`. Vor Migration zu klaeren.
2. **Encryption fuer Zugangscodes** (Feld 4.4, 4.5) — KMS-Integration oder `cryptography.fernet`? Entscheidung beim Fundament-Story.
3. **Permission-Granularitaet fuer `notes_on_owners` / `silent_risks`** — ab v1 Objekt-ACL reicht, in v2 Feld-ACL fuer Cluster 11.
4. **Mirror-Frequenz Impower/Facilioo** — Nightly fuer Stammdaten/Finanzen (Cluster 1, 6), 15-Minuten fuer Tickets (3.3)? Entscheidung im Mirror-Spec-Dokument.
5. **Registry-Detailseiten Prio v1.1** — Bank vs. Eigentuemer vs. Mieter vs. Ablesefirma.
6. **TE-Scan-Agent** — als eigener BMAD-Meilenstein (nach M5), analog SEPA-Workflow. Prompt-Draft + Pydantic-Schema stehen aus.

---

## Naechster Schritt

Das Architektur-Dokument (`docs/architecture-objektsteckbrief.md`) — Datenmodell-Skizze (ERD-artig), Sync-Strategie-Muster pro Cluster, SharePoint-Graph-API-Setup, Migrations-Reihenfolge — faellt als naechstes Artefakt an. Oder alternativ direkt der Story-Schnitt (Epic + 8 Stories) via `bmad-create-epics-and-stories`.
