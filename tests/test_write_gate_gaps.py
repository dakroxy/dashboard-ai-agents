"""Luecken-Tests fuer app/services/steckbrief_write_gate.py (Stories 1.1/1.2).

Die vorhandenen write_gate_unit-Tests decken den Happy-Path, die Mirror-vs-
User-Edit-Regel, JSON-Snapshot-Safety und den Pflegegrad-Cache-Invalidate.
Hier sind die Fehler- und Nebenpfade:

- `source="ai_suggestion"` ohne User muss eine WriteGateError werfen —
  der kanonische Pfad geht ueber approve_review_entry, das immer einen User
  traegt; direkte AI-Writes ohne Reviewer waeren ein Audit-Gap.
- `write_field_ai_proposal` fuer ein Ciphertext-Feld muss abweisen — sonst
  landet der LLM-Klartext-Vorschlag in `review_queue_entries.proposed_value`
  und verletzt NFR-S2 noch vor Story 1.7 (Encryption).
- `approve_review_entry` mit bereits decided Entry → ValueError
  (doppeltes Approve darf keine zweite Provenance-Row erzeugen).
- `approve_review_entry` mit geloeschter Ziel-Entity → WriteGateError.
- `reject_review_entry` auf bereits decided Entry → ValueError.
- Registry-Entities (Versicherer, Dienstleister, ...) schreiben die Audit-
  Action `registry_entry_updated`, nicht `object_field_updated`. Das Filter-
  Dropdown in /admin/logs trennt beide bewusst.
- `write_field_human` ohne geflushte id auf der Entity → WriteGateError.
"""
from __future__ import annotations

import uuid

import pytest

from app.models import AuditLog, Dienstleister, ReviewQueueEntry, User, Versicherer
from app.services.steckbrief_write_gate import (
    WriteGateError,
    approve_review_entry,
    reject_review_entry,
    write_field_ai_proposal,
    write_field_human,
)


@pytest.fixture
def admin_user(db):
    user = User(
        id=uuid.uuid4(),
        google_sub="gaps-admin-sub",
        email="gaps-admin@dbshome.de",
        name="Gaps Admin",
        permissions_extra=["objects:edit", "objects:approve_ki"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# AI-Source-Sanity
# ---------------------------------------------------------------------------

def test_write_field_human_ai_suggestion_without_user_raises(db, test_object):
    with pytest.raises(WriteGateError, match="ai_suggestion"):
        write_field_human(
            db,
            entity=test_object,
            field="year_roof",
            value=2020,
            source="ai_suggestion",
            user=None,
        )


def test_write_field_ai_proposal_for_encrypted_field_raises(db, test_object):
    """KI-Proposals fuer Ciphertext-Felder wuerden den Klartext-Vorschlag in
    review_queue_entries persistieren — NFR-S2 muss das blockieren, auch
    wenn Story 1.7 (Encryption) noch nicht scharf ist."""
    with pytest.raises(WriteGateError, match="Ciphertext"):
        write_field_ai_proposal(
            db,
            target_entity_type="object",
            target_entity_id=test_object.id,
            field="entry_code_main_door",
            proposed_value="0000",
            agent_ref="leak-agent",
            confidence=0.5,
            source_doc_id=None,
        )


# ---------------------------------------------------------------------------
# Review-Queue-Lifecycle-Edges
# ---------------------------------------------------------------------------

def test_approve_review_entry_already_decided_raises(db, test_object, admin_user):
    entry = write_field_ai_proposal(
        db,
        target_entity_type="object",
        target_entity_id=test_object.id,
        field="year_roof",
        proposed_value=2019,
        agent_ref="te_scan_agent",
        confidence=0.8,
        source_doc_id=None,
    )
    db.commit()

    approve_review_entry(db, entry_id=entry.id, user=admin_user)
    db.commit()

    # Zweiter Approve auf denselben Entry ist kein gueltiger Zustandsuebergang.
    with pytest.raises(ValueError, match="bereits entschieden"):
        approve_review_entry(db, entry_id=entry.id, user=admin_user)


def test_approve_review_entry_missing_target_raises(db, test_object, admin_user):
    """Wenn die Ziel-Entity zwischen Proposal und Approve geloescht wurde,
    darf das Approve nicht stumm scheitern — sonst bleibt ein approved-Entry
    ohne Provenance-Row zurueck."""
    entry = write_field_ai_proposal(
        db,
        target_entity_type="object",
        target_entity_id=test_object.id,
        field="year_roof",
        proposed_value=2019,
        agent_ref="te_scan_agent",
        confidence=0.8,
        source_doc_id=None,
    )
    db.commit()

    # Ziel-Entity loeschen.
    db.delete(test_object)
    db.commit()

    with pytest.raises(WriteGateError, match="Ziel-Entity"):
        approve_review_entry(db, entry_id=entry.id, user=admin_user)


def test_approve_review_entry_unknown_id_raises(db, admin_user):
    with pytest.raises(WriteGateError, match="nicht gefunden"):
        approve_review_entry(db, entry_id=uuid.uuid4(), user=admin_user)


def test_reject_review_entry_already_decided_raises(db, test_object, admin_user):
    entry = write_field_ai_proposal(
        db,
        target_entity_type="object",
        target_entity_id=test_object.id,
        field="year_roof",
        proposed_value=2019,
        agent_ref="te_scan_agent",
        confidence=0.8,
        source_doc_id=None,
    )
    db.commit()

    reject_review_entry(db, entry_id=entry.id, user=admin_user, reason="test")
    db.commit()

    with pytest.raises(ValueError, match="bereits entschieden"):
        reject_review_entry(
            db, entry_id=entry.id, user=admin_user, reason="zweites Mal"
        )


def test_reject_review_entry_unknown_id_raises(db, admin_user):
    with pytest.raises(WriteGateError, match="nicht gefunden"):
        reject_review_entry(
            db, entry_id=uuid.uuid4(), user=admin_user, reason="ghost"
        )


# ---------------------------------------------------------------------------
# Audit-Action-Mapping pro Entity-Type
# ---------------------------------------------------------------------------

def test_write_field_human_on_registry_entity_uses_registry_action(db, admin_user):
    """Registry-Edits (Versicherer/Dienstleister/Bank/...) loggen als
    `registry_entry_updated`, NICHT als `object_field_updated`. Das Filter-
    Dropdown in /admin/logs trennt beide — wenn das Mapping verrutscht,
    landet ein Registry-Edit unter 'Objekt-Feld geaendert'."""
    v = Versicherer(id=uuid.uuid4(), name="Allianz SE")
    db.add(v)
    db.commit()

    write_field_human(
        db, entity=v, field="name", value="Allianz AG",
        source="user_edit", user=admin_user,
    )
    db.commit()

    actions = [a.action for a in db.query(AuditLog).all()]
    assert "registry_entry_updated" in actions
    assert "object_field_updated" not in actions


def test_write_field_human_on_dienstleister_also_registry_action(db, admin_user):
    """Quergegenprobe: zweite Registry-Entity (Dienstleister) geht auch auf
    die Registry-Action. Schuetzt gegen versehentliches Hardcoden auf
    'versicherer' im Mapping."""
    dl = Dienstleister(id=uuid.uuid4(), name="Meier GmbH")
    db.add(dl)
    db.commit()

    write_field_human(
        db, entity=dl, field="name", value="Meier & Sohn GmbH",
        source="user_edit", user=admin_user,
    )
    db.commit()

    actions = [a.action for a in db.query(AuditLog).all()]
    assert "registry_entry_updated" in actions
    assert "object_field_updated" not in actions


# ---------------------------------------------------------------------------
# Contract-Check: fehlende Entity-ID
# ---------------------------------------------------------------------------

def test_write_field_human_entity_without_id_raises(db, admin_user):
    """Entity ohne id (nicht geflushed) → WriteGateError. Sonst wuerde
    die FieldProvenance-Row mit entity_id=None landen und NFR-S3 (Auditierbarkeit)
    brechen."""
    from app.models import Object

    obj = Object(short_code="NOID", name="no-id")
    # NICHT db.add, NICHT flush → id bleibt None.
    with pytest.raises(WriteGateError, match="id"):
        write_field_human(
            db, entity=obj, field="name", value="X",
            source="user_edit", user=admin_user,
        )
