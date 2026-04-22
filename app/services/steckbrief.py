"""Read-only-Service fuer die Steckbrief-Liste und -Detailseite.

Pure Query-Helfer — keine Schreibpfade, keine HTTP-Typen. Liefert
Dataclasses fuer die Router-Schicht. Alle Provenance-Lookups laufen
hier zentral, damit die Pill-Logik in den Templates einfach bleibt.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

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
    db: Session, accessible_ids: set[uuid.UUID] | None
) -> list[ObjectRow]:
    """Liste aller sichtbaren Objekte + Anzahl Units in einer Query.

    `accessible_ids=None` bedeutet "keine Einschraenkung" (v1-Default, jeder
    mit `objects:view` sieht alles). Ein leeres Set heisst "keine IDs sichtbar"
    und wird ohne DB-Roundtrip mit `[]` beantwortet.
    """
    if accessible_ids is not None and len(accessible_ids) == 0:
        return []

    stmt = (
        select(
            Object.id,
            Object.short_code,
            Object.name,
            Object.full_address,
            func.count(Unit.id).label("unit_count"),
        )
        .outerjoin(Unit, Unit.object_id == Object.id)
        .group_by(Object.id)
        .order_by(Object.short_code.asc())
    )
    if accessible_ids is not None:
        stmt = stmt.where(Object.id.in_(accessible_ids))

    rows = db.execute(stmt).all()
    return [
        ObjectRow(
            id=row.id,
            short_code=row.short_code,
            name=row.name,
            full_address=row.full_address,
            unit_count=int(row.unit_count or 0),
        )
        for row in rows
    ]


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
