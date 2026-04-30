"""Read-only-Service fuer die Steckbrief-Liste und -Detailseite.

Pure Query-Helfer — keine Schreibpfade, keine HTTP-Typen. Liefert
Dataclasses fuer die Router-Schicht. Alle Provenance-Lookups laufen
hier zentral, damit die Pill-Logik in den Templates einfach bleibt.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Eigentuemer, FieldProvenance, Object, Unit, User


@dataclass(frozen=True)
class ObjectRow:
    id: uuid.UUID
    short_code: str
    name: str
    full_address: str | None
    unit_count: int


@dataclass(frozen=True)
class ObjectListRow:
    id: uuid.UUID
    short_code: str
    name: str
    full_address: str | None
    unit_count: int
    saldo: Decimal | None
    reserve_current: Decimal | None
    reserve_target: Decimal | None
    mandat_status: str                  # "vorhanden" | "fehlt"
    pflegegrad: int | None              # pflegegrad_score_cached
    reserve_below_target: bool          # vorberechnete Badge-/Filter-Bedingung


_SORT_ALLOWED = frozenset({
    "short_code", "name", "saldo", "reserve_current", "mandat_status", "pflegegrad"
})

# Schwellwert: "Ruecklage unter Zielwert" = unter 6 Monatsbeitraegen
# (`reserve_target` ist der monatliche Soll-Wert, siehe docs/data-models.md:349).
RESERVE_TARGET_MONTHS: int = 6


def is_reserve_below_target(
    reserve_current: Decimal | None, reserve_target: Decimal | None
) -> bool:
    """Single source of truth fuer die Badge-/Filter-Bedingung.

    Wird vom Service (Filter, vorberechnetes ObjectListRow-Feld) und von Tests
    konsumiert. Frueher dupliziert in Service + Template — nach Review-Patch P5
    nur noch hier. None-handling explizit (Decimal('0')-Truthiness-Falle).
    """
    if reserve_current is None or reserve_target is None:
        return False
    return reserve_current < reserve_target * RESERVE_TARGET_MONTHS


def normalize_sort_order(sort: str, order: str) -> tuple[str, str]:
    """Normalisiert Query-Parameter fuer Sort/Order.

    - `sort` faellt auf 'short_code' zurueck, wenn er nicht in `_SORT_ALLOWED` ist.
    - `order` ist case-insensitive und whitespace-toleranzbehaftet (DESC/desc/' desc'
      werden alle als 'desc' interpretiert).
    """
    safe_sort = sort if sort in _SORT_ALLOWED else "short_code"
    safe_order = "desc" if order.strip().lower() == "desc" else "asc"
    return safe_sort, safe_order


@dataclass(frozen=True)
class ObjectDetail:
    obj: Object
    eigentuemer: list[Eigentuemer]


@dataclass(frozen=True)
class ProvenanceWithUser:
    """FieldProvenance-Row + aufgeloeste User-Email fuer den Tooltip.

    Bewusst als Wrapper statt Mutation an der ORM-Instanz — sonst koennte
    ein Session-Refresh/Autoflush das transiente Attribut clearen oder eine
    identity-mapped Row in einer anderen Request-Session zeigt die falsche
    Email (Review-Finding P2).
    """
    prov: FieldProvenance
    user_email: str | None


def list_objects_with_unit_counts(
    db: Session,
    accessible_ids: set[uuid.UUID] | None,
    *,
    sort: str = "short_code",
    order: str = "asc",
    filter_reserve_below_target: bool = False,
) -> list[ObjectListRow]:
    """Liste aller sichtbaren Objekte mit erweiterten Feldern fuer Sort/Filter.

    `accessible_ids=None` bedeutet "keine Einschraenkung" (v1-Default, jeder
    mit `objects:view` sieht alles). Ein leeres Set heisst "keine IDs sichtbar"
    und wird ohne DB-Roundtrip mit `[]` beantwortet.

    Sortierung laeuft in Python (SQLite-Kompatibilitaet, kein nullslast()).
    NULLs landen immer am Ende — unabhaengig von `order` — via Zwei-Listen-Methode.
    """
    if accessible_ids is not None and len(accessible_ids) == 0:
        return []

    stmt = (
        select(
            Object.id,
            Object.short_code,
            Object.name,
            Object.full_address,
            Object.last_known_balance,
            Object.reserve_current,
            Object.reserve_target,
            Object.sepa_mandate_refs,
            Object.pflegegrad_score_cached,
            func.count(Unit.id).label("unit_count"),
        )
        .outerjoin(Unit, Unit.object_id == Object.id)
        .group_by(Object.id)
    )
    if accessible_ids is not None:
        stmt = stmt.where(Object.id.in_(accessible_ids))

    rows: list[ObjectListRow] = [
        ObjectListRow(
            id=r.id,
            short_code=r.short_code,
            name=r.name,
            full_address=r.full_address,
            unit_count=int(r.unit_count or 0),
            saldo=r.last_known_balance,
            reserve_current=r.reserve_current,
            reserve_target=r.reserve_target,
            mandat_status="vorhanden" if r.sepa_mandate_refs else "fehlt",
            pflegegrad=r.pflegegrad_score_cached,
            reserve_below_target=is_reserve_below_target(
                r.reserve_current, r.reserve_target
            ),
        )
        for r in db.execute(stmt).all()
    ]

    if filter_reserve_below_target:
        rows = [r for r in rows if r.reserve_below_target]

    safe_sort, safe_order = normalize_sort_order(sort, order)
    is_desc = safe_order == "desc"

    # Zwei-Phasen Stable-Sort: Tiebreaker-Pass zuerst (immer ASC nach short_code),
    # dann Primary-Pass mit reverse=is_desc. Pythons Sort ist stable, also bleibt
    # bei gleichem Primary-Key die Tiebreaker-Reihenfolge erhalten — auch bei
    # reverse=True. Ohne diesen Trick wuerde reverse=True den Tiebreaker mit
    # umkehren (Review-Patch P2).

    if safe_sort in ("short_code", "name"):
        rows.sort(key=lambda r: r.short_code.casefold())
        rows.sort(key=lambda r: getattr(r, safe_sort).casefold(), reverse=is_desc)
        return rows

    if safe_sort == "mandat_status":
        rows.sort(key=lambda r: r.short_code.casefold())
        rows.sort(
            key=lambda r: 1 if r.mandat_status == "vorhanden" else 0,
            reverse=is_desc,
        )
        return rows

    # Numerische Felder (saldo, reserve_current, pflegegrad): NULLs immer
    # ans Ende. Sentinel-Tuple kippt bei reverse=True — Zwei-Listen-Methode
    # haelt NULLs in beiden Richtungen sicher am Ende. NULL-Liste explizit
    # nach short_code sortieren, sonst Reihenfolge non-deterministisch
    # (Review-Patch P1).
    non_null = [r for r in rows if getattr(r, safe_sort) is not None]
    null_rows = [r for r in rows if getattr(r, safe_sort) is None]
    non_null.sort(key=lambda r: r.short_code.casefold())
    non_null.sort(
        key=lambda r: float(getattr(r, safe_sort)),
        reverse=is_desc,
    )
    null_rows.sort(key=lambda r: r.short_code.casefold())
    return non_null + null_rows


def get_object_detail(
    db: Session,
    object_id: uuid.UUID,
    accessible_ids: set[uuid.UUID] | None,
) -> ObjectDetail | None:
    """Liefert Object + Eigentuemer-Liste fuer die Detailseite.

    Nicht-existentes Objekt oder ausserhalb von ``accessible_ids`` → ``None``.
    Der Router mappt beides auf 404 (NFR-S7: Nicht-Existenz und Nicht-Zugriff
    sollen aus Sicht des Users ununterscheidbar sein).
    """
    if accessible_ids is not None and object_id not in accessible_ids:
        return None

    obj = db.execute(
        select(Object).where(Object.id == object_id)
    ).scalar_one_or_none()
    if obj is None:
        return None

    eig_rows = db.execute(
        select(Eigentuemer)
        .where(Eigentuemer.object_id == object_id)
        .order_by(Eigentuemer.name.asc())
    ).scalars().all()

    return ObjectDetail(obj=obj, eigentuemer=list(eig_rows))


def get_provenance_map(
    db: Session,
    entity_type: str,
    entity_id: uuid.UUID,
    fields: Iterable[str],
) -> dict[str, ProvenanceWithUser | None]:
    """Holt pro Feld die neueste FieldProvenance-Row inkl. aufgeloester User-Email.

    Eine Query ueber alle Felder + LEFT JOIN auf Users, Python-seitiges
    Group-by — portabel fuer Postgres und SQLite (SQLite kennt kein
    `DISTINCT ON`). Sort-Key identisch zu `_latest_provenance` im Write-Gate
    (`created_at DESC, id DESC`).

    Rueckgabe ist ein Wrapper (`ProvenanceWithUser`) statt der nackten
    ORM-Row, um die Email sauber an das Render-Dict zu binden, ohne die
    identity-mapped SQLAlchemy-Instanz zu mutieren.
    """
    field_list = list(fields)
    result: dict[str, ProvenanceWithUser | None] = {f: None for f in field_list}
    if not field_list:
        return result

    stmt = (
        select(FieldProvenance, User.email)
        .outerjoin(User, User.id == FieldProvenance.user_id)
        .where(
            FieldProvenance.entity_type == entity_type,
            FieldProvenance.entity_id == entity_id,
            FieldProvenance.field_name.in_(field_list),
        )
        .order_by(
            FieldProvenance.created_at.desc(), FieldProvenance.id.desc()
        )
    )
    for prov, email in db.execute(stmt).all():
        if result.get(prov.field_name) is None:
            result[prov.field_name] = ProvenanceWithUser(prov=prov, user_email=email)
    return result


def has_any_impower_provenance(
    db: Session, entity_type: str, entity_id: uuid.UUID
) -> bool:
    """True, wenn fuer die Entitaet schon mindestens einmal ein Impower-Mirror
    geschrieben wurde. Stabile Heuristik fuer das Stale-Banner (AC6):
    User-Edits verlaengern den Banner-Zustand nicht.
    """
    stmt = (
        select(FieldProvenance.id)
        .where(
            FieldProvenance.entity_type == entity_type,
            FieldProvenance.entity_id == entity_id,
            FieldProvenance.source == "impower_mirror",
        )
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Sparkline (Story 1.5 — Ruecklage-Historie in der Finanzen-Sektion)
# ---------------------------------------------------------------------------

def reserve_history_for_sparkline(
    db: Session, object_id: uuid.UUID, months: int = 6
) -> list[tuple[datetime, float]]:
    """Liefert chronologisch sortierte (timestamp, value)-Tupel der
    `reserve_current`-Mirror-Writes der letzten `months` Monate.

    Wird in der Finanzen-Sektion fuer die Inline-SVG-Sparkline gebraucht.
    JSONB-Lese-Falle: `value_snapshot["new"]` kann nach JSONB-Roundtrip
    `str` (`"45000.00"`, da Write-Gate Decimal als String serialisiert),
    `int` oder `float` sein — alle drei werden ueber `float(str(raw))`
    einheitlich gemacht. Rows ohne `new` (oder leerem Wert) werden
    uebersprungen, sonst verschleppen wir 0.0-Artefakte in die Kurve.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 31)
    stmt = (
        select(FieldProvenance)
        .where(
            FieldProvenance.entity_type == "object",
            FieldProvenance.entity_id == object_id,
            FieldProvenance.field_name == "reserve_current",
            FieldProvenance.source == "impower_mirror",
            FieldProvenance.created_at >= cutoff,
        )
        .order_by(FieldProvenance.created_at.asc())
    )
    rows = db.execute(stmt).scalars().all()

    points: list[tuple[datetime, float]] = []
    for row in rows:
        snapshot = row.value_snapshot or {}
        raw = snapshot.get("new")
        if raw is None or raw == "":
            continue
        try:
            val = float(str(raw))
        except (TypeError, ValueError):
            continue
        points.append((row.created_at, val))
    return points


def build_sparkline_svg(points: list[tuple[datetime, float]]) -> str | None:
    """Liefert einen fertigen SVG-String fuer eine Sparkline oder ``None`` bei
    weniger als 2 Datenpunkten (Template rendert dann den Placeholder).

    Render-Logik komplett im Service, damit das Template nur ``{{ svg | safe }}``
    macht und keine eigene Berechnung enthaelt. ViewBox 120x40 px,
    Stroke-Farbe sky-500 (passt zu den Mirror-Pills).
    """
    if len(points) < 2:
        return None

    vals = [v for _, v in points]
    min_v, max_v = min(vals), max(vals)
    w, h = 120, 40
    pad = 2

    def to_xy(i: int, v: float) -> tuple[float, float]:
        x = pad + i / (len(vals) - 1) * (w - 2 * pad)
        if max_v == min_v:
            y = h / 2
        else:
            y = h - pad - (v - min_v) / (max_v - min_v) * (h - 2 * pad)
        return round(x, 1), round(y, 1)

    coords = [to_xy(i, v) for i, v in enumerate(vals)]
    path_d = " ".join(
        f"{'M' if i == 0 else 'L'}{x},{y}"
        for i, (x, y) in enumerate(coords)
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<path d="{path_d}" stroke="#0ea5e9" stroke-width="1.5" fill="none"/>'
        f'</svg>'
    )


# ---------------------------------------------------------------------------
# Technik-Sektion (Story 1.6) — Feld-Registry + Validator
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TechnikField:
    """Deskriptor eines einzelnen Technik-Felds.

    Wird vom Router (Feld-Whitelist + Label + Kind-Dispatch) und vom Template
    (UI-Label + Render-Dispatch) gleichermassen konsumiert — Single Source of
    Truth.
    """
    key: str          # Spalten-Name auf Object
    label: str        # UI-Label (Deutsch)
    kind: str         # "int_year" | "text"
    max_len: int = 500


TECHNIK_ABSPERRPUNKTE: tuple[TechnikField, ...] = (
    TechnikField("shutoff_water_location", "Wasser-Absperrung", "text"),
    TechnikField("shutoff_electricity_location", "Strom-Absperrung", "text"),
    TechnikField("shutoff_gas_location", "Gas-Absperrung", "text"),
)
TECHNIK_HEIZUNG: tuple[TechnikField, ...] = (
    TechnikField("heating_type", "Heizungs-Typ", "text"),
    TechnikField("year_heating", "Baujahr Heizung", "int_year"),
    TechnikField("heating_company", "Wartungsfirma", "text"),
    TechnikField("heating_hotline", "Störungs-Hotline", "tel"),
)
TECHNIK_HISTORIE: tuple[TechnikField, ...] = (
    TechnikField("year_built", "Baujahr Gebäude", "int_year"),
    TechnikField("year_roof", "Jahr letzte Dach-Sanierung", "int_year"),
    TechnikField("year_electrics", "Jahr Elektrik-Check", "int_year"),
)
TECHNIK_FIELDS: tuple[TechnikField, ...] = (
    *TECHNIK_ABSPERRPUNKTE,
    *TECHNIK_HEIZUNG,
    *TECHNIK_HISTORIE,
)
TECHNIK_FIELD_KEYS: frozenset[str] = frozenset(f.key for f in TECHNIK_FIELDS)

_TECHNIK_LOOKUP: dict[str, TechnikField] = {f.key: f for f in TECHNIK_FIELDS}


def parse_technik_value(field_key: str, raw: str) -> tuple[Any | None, str | None]:
    """Validiert und parst User-Input fuer Technik-Felder.

    - Leerer Input → (None, None): bewusste Loeschung (Story 1.6 AC6).
    - `int_year`: Integer zwischen 1800 und (aktuelles Jahr + 1). Alles
      andere liefert einen deutschen Fehlertext.
    - `text`: Laenge <= field.max_len. Nur leading/trailing Whitespace
      wird gestript.

    Unbekannter field_key → ValueError (Programmier-Guard, nie user-sichtbar;
    der Router filtert ueber TECHNIK_FIELD_KEYS vorab).
    """
    field = _TECHNIK_LOOKUP.get(field_key)
    if field is None:
        raise ValueError(f"Unbekanntes Technik-Feld: {field_key!r}")
    stripped = (raw or "").strip()
    if stripped == "":
        return None, None
    if field.kind == "int_year":
        try:
            year_f = float(stripped)
        except ValueError:
            return None, "Bitte eine ganze Zahl (Jahr) eingeben."
        if year_f != int(year_f):
            return None, "Bitte eine ganze Zahl (Jahr) eingeben."
        year = int(year_f)
        current_year = datetime.now().year
        if not (1800 <= year <= current_year + 1):
            return None, f"Jahr muss zwischen 1800 und {current_year + 1} liegen."
        return year, None
    if field.kind in ("text", "tel"):
        if len(stripped) > field.max_len:
            return None, f"Maximal {field.max_len} Zeichen erlaubt."
        return stripped, None
    raise ValueError(f"Unbekannter Feld-Typ: {field.kind!r}")


# ---------------------------------------------------------------------------
# Zugangscode-Registry (Story 1.7 — separate von TECHNIK_FIELDS, da
# Encrypt/Decrypt-Logik eigene Endpoints erfordert)
# ---------------------------------------------------------------------------

ZUGANGSCODE_FIELDS: tuple[TechnikField, ...] = (
    TechnikField("entry_code_main_door", "Haustür-Code", "code"),
    TechnikField("entry_code_garage", "Garage-Code", "code"),
    TechnikField("entry_code_technical_room", "Technikraum-Code", "code"),
)
ZUGANGSCODE_FIELD_KEYS: frozenset[str] = frozenset(
    f.key for f in ZUGANGSCODE_FIELDS
)

_ZUGANGSCODE_MAX_LEN: int = 200


# ---------------------------------------------------------------------------
# Foto-Komponenten-Registry (Story 1.8)
# ---------------------------------------------------------------------------
PHOTO_COMPONENT_REFS: dict[str, str] = {
    "absperrpunkt_wasser":  "Absperrpunkt Wasser",
    "absperrpunkt_strom":   "Absperrpunkt Strom",
    "absperrpunkt_gas":     "Absperrpunkt Gas",
    "heizung_typenschild":  "Heizung / Typenschild",
}


def parse_zugangscode_value(
    field_key: str, raw: str
) -> tuple[str | None, str | None]:
    """Validiert User-Input fuer Zugangscode-Felder.

    - Leerer Input → (None, None): bewusste Loeschung (AC4).
    - Nicht-leer: Whitespace strippen, Laenge pruefen.
    - Unbekannter field_key → ValueError (Programmier-Guard).

    Rueckgabe: (wert, fehlermeldung) — exakt eines davon ist None.
    """
    if field_key not in ZUGANGSCODE_FIELD_KEYS:
        raise ValueError(f"Unbekanntes Zugangscode-Feld: {field_key!r}")
    stripped = (raw or "").strip()
    if not stripped:
        return None, None
    if len(stripped) > _ZUGANGSCODE_MAX_LEN:
        return None, f"Maximal {_ZUGANGSCODE_MAX_LEN} Zeichen erlaubt."
    return stripped, None
