"""Pflegegrad-Score-Service (Story 3.3).

Berechnet einen deterministischen Pflegegrad-Score (0–100) pro Objekt aus
Completeness und Aktualitaet (Provenance-Decay). Wird von der Detail-Route
gecacht und von der List-View sortiert.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Eigentuemer, FieldProvenance, InsurancePolicy, Object, Wartungspflicht

if TYPE_CHECKING:
    from app.services.steckbrief import ProvenanceWithUser


# ---------------------------------------------------------------------------
# Pflichtfeld-Katalog (Quelle der Wahrheit fuer Score-Berechnung)
# ---------------------------------------------------------------------------

# Cluster-Gewichte (Summe = 1.0)
CLUSTER_WEIGHTS: dict[str, float] = {
    "C1": 0.20,
    "C4": 0.30,
    "C6": 0.20,
    "C8": 0.30,
}

# Scalar-Felder mit Provenance-Decay (ORM-Feldnamen auf Object)
_C1_SCALAR: tuple[str, ...] = ("full_address", "impower_property_id")
_C4_SCALAR: tuple[str, ...] = (
    "shutoff_water_location",
    "shutoff_electricity_location",
    "heating_type",
    "year_built",
)
_C6_SCALAR: tuple[str, ...] = ("last_known_balance", "reserve_current")

# Union aller Scalar-Felder fuer eine einzige Provenance-Query
_ALL_SCALAR: tuple[str, ...] = _C1_SCALAR + _C4_SCALAR + _C6_SCALAR

CACHE_TTL = timedelta(minutes=5)

# (deutsches Label, Anker-ID) pro weakest-field-Key.
# Anker-IDs korrespondieren mit id="..." in den Templates (AC4).
WEAKEST_FIELD_LABELS: dict[str, tuple[str, str]] = {
    # C1 — Stammdaten (ids via Task 3 in Story 3.4 hinzugefuegt)
    "full_address": ("Adresse", "#field-full_address"),
    "impower_property_id": ("Impower-Eigenschaft", "#field-impower_property_id"),
    "has_eigentuemer": ("Eigentümer", "#eigentuemer-section"),
    # C4 — Technik (ids bereits vorhanden via _obj_technik_field_view.html)
    "shutoff_water_location": ("Absperrung Wasser", "#field-shutoff_water_location"),
    "shutoff_electricity_location": ("Absperrung Strom", "#field-shutoff_electricity_location"),
    "heating_type": ("Heizungstyp", "#field-heating_type"),
    "year_built": ("Baujahr", "#field-year_built"),
    # C6 — Finanzen (ids via Task 4 in Story 3.4 hinzugefuegt)
    "last_known_balance": ("Kontosaldo", "#field-last_known_balance"),
    "reserve_current": ("Ruecklage aktuell", "#field-reserve_current"),
    "sepa_mandate_refs": ("SEPA-Mandate", "#field-sepa_mandate_refs"),
    # C8 — Versicherungen (ids via Task 5 in Story 3.4 hinzugefuegt)
    "has_police": ("Versicherungspolice", "#policen-section"),
    "has_wartungspflicht": ("Wartungspflicht", "#wartungen-section"),
}


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PflegegradResult:
    score: int
    per_cluster: dict[str, float]
    weakest_fields: list[str]


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _ensure_utc(dt: datetime.datetime) -> datetime.datetime:
    """Macht naive Datetimes zu UTC-aware (SQLite gibt naive zurueck)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _decay(age_days: int | None) -> float:
    if age_days is None or age_days <= 365:
        return 1.0
    if age_days <= 1095:
        return 0.5
    return 0.1


# ---------------------------------------------------------------------------
# Score-Berechnung
# ---------------------------------------------------------------------------

def pflegegrad_score(
    obj: Object,
    db: Session,
    prov_map: "dict[str, ProvenanceWithUser | None] | None" = None,
) -> PflegegradResult:
    """Berechnet den Pflegegrad-Score.

    Optionaler `prov_map`-Parameter: wenn vorhanden (z. B. vom Bulk-Aufruf in
    `object_detail`), werden die Provenance-Daten daraus gelesen ohne DB-Hit.
    Ohne `prov_map` laufen die Queries wie bisher (fuer List-View, Background-Jobs).
    """
    now = datetime.datetime.now(tz=timezone.utc)

    latest_prov: dict[str, FieldProvenance] = {}
    if prov_map is not None:
        # Reuse aus Bulk-Map: ProvenanceWithUser → FieldProvenance extrahieren.
        # Achtung: Ein Schluessel im prov_map mit Wert None wird als "kein
        # Provenance-Eintrag in DB" verstanden — eine zusaetzliche DB-Query
        # waere redundant. Fields, die im prov_map gar nicht vorkommen
        # (partial map vom Caller), werden weiter unten per Bulk-Query nachgeladen,
        # damit ein partieller prov_map nicht silent den Decay deaktiviert.
        for field_name, wrap in prov_map.items():
            if wrap is not None:
                latest_prov[field_name] = wrap.prov
        missing = [f for f in _ALL_SCALAR if f not in prov_map]
        if missing:
            # Ein einziger Bulk-Lookup fuer alle nicht im prov_map enthaltenen
            # Felder — vermeidet N Einzel-Queries und stellt Korrektheit her,
            # falls der Caller nur eine Sub-Map (z. B. Sektions-Slice) uebergibt.
            provs = (
                db.execute(
                    select(FieldProvenance)
                    .where(
                        FieldProvenance.entity_type == "object",
                        FieldProvenance.entity_id == obj.id,
                        FieldProvenance.field_name.in_(missing),
                    )
                    .order_by(FieldProvenance.created_at.desc())
                )
                .scalars()
                .all()
            )
            for prov in provs:
                if prov.field_name not in latest_prov:
                    latest_prov[prov.field_name] = prov
    else:
        # -- Provenance: eine Query fuer alle Scalar-Felder --
        provs = (
            db.execute(
                select(FieldProvenance)
                .where(
                    FieldProvenance.entity_type == "object",
                    FieldProvenance.entity_id == obj.id,
                    FieldProvenance.field_name.in_(_ALL_SCALAR),
                )
                .order_by(FieldProvenance.created_at.desc())
            )
            .scalars()
            .all()
        )
        for prov in provs:
            if prov.field_name not in latest_prov:
                latest_prov[prov.field_name] = prov

    # -- Relationale Counts --
    eigentuemer_count = db.execute(
        select(func.count()).where(Eigentuemer.object_id == obj.id)
    ).scalar_one()

    police_count = db.execute(
        select(func.count()).where(InsurancePolicy.object_id == obj.id)
    ).scalar_one()

    wartung_count = db.execute(
        select(func.count()).where(Wartungspflicht.object_id == obj.id)
    ).scalar_one()

    # -- Effektive Werte berechnen --
    weakest: list[str] = []

    def _scalar_effective(field: str) -> float:
        val = getattr(obj, field)
        if val is None:
            weakest.append(field)
            return 0.0
        prov = latest_prov.get(field)
        age = (now - _ensure_utc(prov.created_at)).days if prov is not None else None
        eff = _decay(age)
        if eff < 1.0:
            weakest.append(field)
        return eff

    def _relational_effective(sentinel: str, count: int) -> float:
        if count == 0:
            weakest.append(sentinel)
            return 0.0
        return 1.0

    def _jsonb_bool_effective(field: str, val: list) -> float:
        if not val:
            weakest.append(field)
            return 0.0
        return 1.0

    # C1: full_address, impower_property_id, has_eigentuemer
    c1_vals = [
        _scalar_effective("full_address"),
        _scalar_effective("impower_property_id"),
        _relational_effective("has_eigentuemer", eigentuemer_count),
    ]

    # C4: 4 Technik-Felder
    c4_vals = [
        _scalar_effective("shutoff_water_location"),
        _scalar_effective("shutoff_electricity_location"),
        _scalar_effective("heating_type"),
        _scalar_effective("year_built"),
    ]

    # C6: last_known_balance, reserve_current, sepa_mandate_refs
    c6_vals = [
        _scalar_effective("last_known_balance"),
        _scalar_effective("reserve_current"),
        _jsonb_bool_effective("sepa_mandate_refs", obj.sepa_mandate_refs or []),
    ]

    # C8: has_police, has_wartungspflicht
    c8_vals = [
        _relational_effective("has_police", police_count),
        _relational_effective("has_wartungspflicht", wartung_count),
    ]

    per_cluster = {
        "C1": sum(c1_vals) / len(c1_vals),
        "C4": sum(c4_vals) / len(c4_vals),
        "C6": sum(c6_vals) / len(c6_vals),
        "C8": sum(c8_vals) / len(c8_vals),
    }

    raw_score = sum(per_cluster[k] * CLUSTER_WEIGHTS[k] for k in per_cluster)
    score = round(raw_score * 100)

    return PflegegradResult(
        score=score,
        per_cluster=per_cluster,
        weakest_fields=weakest,
    )


# ---------------------------------------------------------------------------
# Cache-Helper
# ---------------------------------------------------------------------------

def get_or_update_pflegegrad_cache(
    obj: Object,
    db: Session,
    prov_map: "dict[str, ProvenanceWithUser | None] | None" = None,
) -> tuple[PflegegradResult, bool]:
    """Berechnet Score + aktualisiert Cache wenn stale.
    Returns: (result, cache_was_updated)

    Optionaler `prov_map`-Parameter wird an `pflegegrad_score` durchgereicht
    (AC6): wenn vorhanden, entfallen alle Provenance-DB-Queries.
    Muss innerhalb einer Transaktion gerufen werden — Row-Lock haelt bis zum
    naechsten commit/rollback. Caller (object_detail in objects.py:285) committet
    im Anschluss.
    """
    # Row-Lock VOR is_stale-Pruefung: serialisiert parallele Cache-Writes
    # (Last-Writer-Wins-Race, Defer #34).
    db.execute(select(Object).where(Object.id == obj.id).with_for_update())
    # Nach Lock-Erwerb Cache-Felder neu laden — sonst entscheidet `is_stale`
    # auf dem Pre-Lock-Snapshot und ein gleichzeitiger Worker-Schreiber wuerde
    # ueberschrieben.
    db.refresh(obj, attribute_names=["pflegegrad_score_cached", "pflegegrad_score_updated_at"])
    result = pflegegrad_score(obj, db, prov_map=prov_map)

    now = datetime.datetime.now(tz=timezone.utc)
    is_stale = (
        obj.pflegegrad_score_cached is None
        or obj.pflegegrad_score_updated_at is None
        or (now - _ensure_utc(obj.pflegegrad_score_updated_at)) >= CACHE_TTL
    )
    if is_stale:
        # direkter Cache-Write — explizite Ausnahme vom Write-Gate-Boundary (Story 3.3)
        obj.pflegegrad_score_cached = result.score
        obj.pflegegrad_score_updated_at = now
        # kein db.commit() — Caller committed

    return result, is_stale
