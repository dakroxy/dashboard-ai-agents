"""Unit-Tests fuer app/services/steckbrief_write_gate.py (Story 1.2, AC4–AC8, AC10)."""
from __future__ import annotations

import datetime as _dt
import decimal
import uuid

import pytest
from sqlalchemy.orm.attributes import flag_modified

from app.models import (
    AuditLog,
    Document,
    FieldProvenance,
    Object,
    ReviewQueueEntry,
    User,
    Workflow,
)
from app.services.steckbrief_write_gate import (
    WriteGateError,
    WriteResult,
    approve_review_entry,
    reject_review_entry,
    write_field_ai_proposal,
    write_field_human,
)


@pytest.fixture
def admin_user(db):
    user = User(
        id=uuid.uuid4(),
        google_sub="admin-sub",
        email="admin@dbshome.de",
        name="Admin",
        permissions_extra=["objects:view", "objects:edit", "objects:approve_ki"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# AC4 — write_field_human
# ---------------------------------------------------------------------------

def test_write_field_human_sets_value_and_provenance(db, test_object, admin_user):
    result = write_field_human(
        db,
        entity=test_object,
        field="year_roof",
        value=2021,
        source="user_edit",
        user=admin_user,
    )
    db.commit()

    assert result.written is True
    assert result.skipped is False

    db.expire_all()
    obj = db.get(Object, test_object.id)
    assert obj.year_roof == 2021

    provs = (
        db.query(FieldProvenance)
        .filter_by(entity_type="object", entity_id=obj.id, field_name="year_roof")
        .all()
    )
    assert len(provs) == 1
    assert provs[0].source == "user_edit"
    assert provs[0].user_id == admin_user.id
    assert provs[0].value_snapshot == {"old": None, "new": 2021}

    audits = (
        db.query(AuditLog)
        .filter_by(action="object_field_updated", entity_id=obj.id)
        .all()
    )
    assert len(audits) == 1
    assert audits[0].entity_type == "object"
    assert audits[0].user_id == admin_user.id


def test_write_field_human_creates_audit_in_same_transaction(
    db, test_object, admin_user
):
    # Vor commit() sind Audit + Provenance in der Session-new-Queue sichtbar
    # (autoflush=False in tests/conftest.py — deshalb nicht via db.query()).
    write_field_human(
        db,
        entity=test_object,
        field="year_roof",
        value=2021,
        source="user_edit",
        user=admin_user,
    )
    pending_audits = [o for o in db.new if isinstance(o, AuditLog)]
    pending_provs = [o for o in db.new if isinstance(o, FieldProvenance)]
    assert len(pending_audits) == 1
    assert len(pending_provs) == 1

    # Rollback nimmt Feld, Provenance und Audit gemeinsam mit.
    db.rollback()
    db.expire_all()
    assert db.get(Object, test_object.id).year_roof is None
    assert db.query(FieldProvenance).count() == 0
    assert db.query(AuditLog).filter_by(action="object_field_updated").count() == 0


def test_write_field_human_json_safe_snapshot(db, test_object, admin_user):
    """Der Snapshot enthaelt JSON-kompatible Werte — Decimal als String,
    Date als ISO-String, Primitives unveraendert. (Hintergrund: Postgres-
    JSONB akzeptiert nur JSON-Primitives; CD1-Felder halten aber Decimal,
    Date usw. als Python-Typen.)"""
    from app.services.steckbrief_write_gate import _json_safe

    # Direkt-Test des Helpers mit allen erwarteten Typen.
    assert _json_safe(None) is None
    assert _json_safe(True) is True
    assert _json_safe(42) == 42
    assert _json_safe(3.14) == 3.14
    assert _json_safe("hallo") == "hallo"
    assert _json_safe(uuid.UUID("11111111-1111-1111-1111-111111111111")) == \
        "11111111-1111-1111-1111-111111111111"
    assert _json_safe(_dt.date(2026, 4, 21)) == "2026-04-21"
    assert _json_safe(decimal.Decimal("0.3333")) == "0.3333"
    assert _json_safe(b"abc") == "YWJj"
    assert _json_safe([1, decimal.Decimal("2")]) == [1, "2"]
    assert _json_safe({"x": _dt.date(2026, 1, 1)}) == {"x": "2026-01-01"}

    # End-to-end: Decimal-Feld auf Object → Snapshot in Strings.
    test_object.last_known_balance = decimal.Decimal("100.00")
    db.commit()

    write_field_human(
        db, entity=test_object, field="last_known_balance",
        value=decimal.Decimal("250.50"),
        source="user_edit", user=admin_user,
    )
    db.commit()

    prov = (
        db.query(FieldProvenance)
        .filter_by(field_name="last_known_balance", entity_id=test_object.id)
        .first()
    )
    assert prov.value_snapshot == {"old": "100.00", "new": "250.50"}


# ---------------------------------------------------------------------------
# AC10 — JSONB-Mutation-Safety
# ---------------------------------------------------------------------------

def test_write_field_human_jsonb_reassignment_persisted(
    db, test_object, admin_user
):
    write_field_human(
        db, entity=test_object, field="voting_rights", value={"alt": 0.5},
        source="user_edit", user=admin_user,
    )
    db.commit()

    write_field_human(
        db, entity=test_object, field="voting_rights", value={"neu": 0.6},
        source="user_edit", user=admin_user,
    )
    db.commit()

    db.expire_all()
    obj = db.get(Object, test_object.id)
    assert obj.voting_rights == {"neu": 0.6}


def test_jsonb_sub_key_mutation_not_detected_warning(db, test_object):
    """Regressions-Anker fuer project-context §JSONB-Fallen.
    Direkte Sub-Key-Mutation ohne flag_modified wird NICHT persistiert —
    demonstriert, warum das Gate Deep-Copy + flag_modified macht."""
    test_object.voting_rights = {"alt": 0.5}
    db.commit()
    db.expire_all()

    obj = db.get(Object, test_object.id)
    obj.voting_rights["alt"] = 0.99
    db.commit()
    db.expire_all()

    obj = db.get(Object, test_object.id)
    # SQLAlchemy hat den Sub-Key-Write ignoriert — Wert bleibt 0.5.
    assert obj.voting_rights == {"alt": 0.5}


# ---------------------------------------------------------------------------
# AC5 — write_field_ai_proposal
# ---------------------------------------------------------------------------

def test_write_field_ai_proposal_does_not_touch_target(
    db, test_object, admin_user
):
    entry = write_field_ai_proposal(
        db,
        target_entity_type="object",
        target_entity_id=test_object.id,
        field="year_roof",
        proposed_value=2019,
        agent_ref="te_scan_agent",
        confidence=0.8,
        source_doc_id=None,
        agent_context={"prompt_version": "v1"},
        user=admin_user,
    )
    db.commit()

    db.expire_all()
    obj = db.get(Object, test_object.id)
    assert obj.year_roof is None

    reloaded = db.get(ReviewQueueEntry, entry.id)
    assert reloaded.status == "pending"
    assert reloaded.target_entity_type == "object"
    assert reloaded.field_name == "year_roof"
    assert reloaded.proposed_value == {"value": 2019}
    assert reloaded.agent_ref == "te_scan_agent"
    assert reloaded.confidence == 0.8
    assert reloaded.agent_context == {"prompt_version": "v1"}

    audit = db.query(AuditLog).filter_by(action="review_queue_created").first()
    assert audit is not None
    assert audit.entity_type == "object"


# ---------------------------------------------------------------------------
# AC6 — approve_review_entry
# ---------------------------------------------------------------------------

def test_approve_review_entry_writes_field_with_ai_suggestion_source(
    db, test_object, admin_user
):
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
    db.expire_all()

    obj = db.get(Object, test_object.id)
    assert obj.year_roof == 2019

    prov = (
        db.query(FieldProvenance)
        .filter_by(entity_id=obj.id, field_name="year_roof")
        .one()
    )
    assert prov.source == "ai_suggestion"
    assert prov.source_ref == "te_scan_agent"
    assert prov.confidence == 0.8
    assert prov.user_id == admin_user.id

    reloaded = db.get(ReviewQueueEntry, entry.id)
    assert reloaded.status == "approved"
    assert reloaded.decided_at is not None
    assert reloaded.decided_by_user_id == admin_user.id

    audit = db.query(AuditLog).filter_by(action="review_queue_approved").first()
    assert audit is not None


# ---------------------------------------------------------------------------
# AC7 — reject_review_entry
# ---------------------------------------------------------------------------

def test_reject_review_entry_marks_only(db, test_object, admin_user):
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

    prov_count_before = db.query(FieldProvenance).count()

    reject_review_entry(
        db, entry_id=entry.id, user=admin_user, reason="falsche OCR"
    )
    db.commit()
    db.expire_all()

    obj = db.get(Object, test_object.id)
    assert obj.year_roof is None

    reloaded = db.get(ReviewQueueEntry, entry.id)
    assert reloaded.status == "rejected"
    assert reloaded.decision_reason == "falsche OCR"
    assert reloaded.decided_at is not None
    assert reloaded.decided_by_user_id == admin_user.id

    assert db.query(FieldProvenance).count() == prov_count_before

    audit = db.query(AuditLog).filter_by(action="review_queue_rejected").first()
    assert audit is not None


def test_review_queue_source_doc_fk_on_delete_set_null():
    """Der FK `review_queue_entries.source_doc_id → documents.id` muss
    ON DELETE SET NULL haben — damit archivierte KI-Vorschlaege nicht
    verschwinden, wenn das Quell-PDF geloescht wird.

    Wird hier auf Metadata-Ebene geprueft: SQLite erzwingt ON DELETE-
    Policies nicht ohne `PRAGMA foreign_keys=ON`, fuer Postgres-Sematik
    im Unit-Test reicht die Schema-Definition."""
    from app.models import ReviewQueueEntry

    source_doc_col = ReviewQueueEntry.__table__.c.source_doc_id
    fks = list(source_doc_col.foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.column.table.name == "documents"
    assert fk.ondelete == "SET NULL"


# ---------------------------------------------------------------------------
# AC8 — Mirror-vs-User-Edit
# ---------------------------------------------------------------------------

def test_mirror_skips_if_user_edit_newer(db, test_object, admin_user):
    # Erst ein user_edit — invalidiert pflegegrad_cache.
    test_object.pflegegrad_score_cached = 50
    db.commit()
    write_field_human(
        db, entity=test_object, field="year_roof", value=2021,
        source="user_edit", user=admin_user,
    )
    db.commit()
    db.expire_all()

    obj = db.get(Object, test_object.id)
    assert obj.year_roof == 2021
    # user_edit resettet cache auf None.
    assert obj.pflegegrad_score_cached is None

    # Baseline-Counts nach dem user_edit — der folgende Mirror-Skip darf NICHT
    # noch eine Provenance-Row oder einen AuditLog-Eintrag erzeugen.
    prov_count_before = db.query(FieldProvenance).filter_by(
        entity_type="object", entity_id=test_object.id, field_name="year_roof"
    ).count()
    audit_count_before = db.query(AuditLog).filter_by(
        action="object_field_updated"
    ).count()

    # Nightly-Mirror kommt mit anderem Wert — darf user_edit nicht ueberschreiben.
    obj.pflegegrad_score_cached = 75  # Setup fuer "Mirror darf Cache NICHT reseten"
    db.commit()

    result = write_field_human(
        db, entity=obj, field="year_roof", value=2020,
        source="impower_mirror", user=None,
    )
    db.commit()
    db.expire_all()

    assert result.written is False
    assert result.skipped is True
    assert result.skip_reason == "user_edit_newer"

    obj = db.get(Object, test_object.id)
    assert obj.year_roof == 2021
    # pflegegrad_cache bleibt — Mirror hat NICHT invalidiert.
    assert obj.pflegegrad_score_cached == 75

    # Regressionsanker: Mirror-Skip darf weder Provenance noch Audit nachlegen.
    assert db.query(FieldProvenance).filter_by(
        entity_type="object", entity_id=test_object.id, field_name="year_roof"
    ).count() == prov_count_before
    assert db.query(AuditLog).filter_by(
        action="object_field_updated"
    ).count() == audit_count_before


def test_mirror_overwrites_if_last_was_mirror(db, test_object):
    write_field_human(
        db, entity=test_object, field="year_roof", value=2020,
        source="impower_mirror", user=None,
    )
    db.commit()

    result = write_field_human(
        db, entity=test_object, field="year_roof", value=2022,
        source="impower_mirror", user=None,
    )
    db.commit()

    assert result.written is True
    db.expire_all()
    obj = db.get(Object, test_object.id)
    assert obj.year_roof == 2022


def test_noop_unchanged_returns_skipped(db, test_object, admin_user):
    write_field_human(
        db, entity=test_object, field="year_roof", value=2021,
        source="user_edit", user=admin_user,
    )
    db.commit()

    prov_count_before = db.query(FieldProvenance).count()
    test_object.pflegegrad_score_cached = 50
    db.commit()

    result = write_field_human(
        db, entity=test_object, field="year_roof", value=2021,
        source="user_edit", user=admin_user,
    )
    db.commit()
    db.expire_all()

    assert result.written is False
    assert result.skipped is True
    assert result.skip_reason == "noop_unchanged"

    assert db.query(FieldProvenance).count() == prov_count_before
    # kein Invalidate
    obj = db.get(Object, test_object.id)
    assert obj.pflegegrad_score_cached == 50


def test_noop_first_write_none_value_no_provenance(db, test_object):
    """Mirror-Import mit `value=None` auf ein leeres Feld (kein Vorgaenger in
    Provenance) darf keine `{"old": None, "new": None}`-Provenance-Row
    erzeugen — das waere sinnloses Rauschen in der History."""
    assert test_object.year_roof is None
    prov_count_before = db.query(FieldProvenance).filter_by(
        entity_type="object", entity_id=test_object.id
    ).count()

    result = write_field_human(
        db, entity=test_object, field="year_roof", value=None,
        source="impower_mirror", user=None,
    )
    db.commit()

    assert result.written is False
    assert result.skipped is True
    assert result.skip_reason == "noop_unchanged"
    assert db.query(FieldProvenance).filter_by(
        entity_type="object", entity_id=test_object.id
    ).count() == prov_count_before


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

def test_write_gate_invalid_source_raises(db, test_object, admin_user):
    with pytest.raises(WriteGateError):
        write_field_human(
            db, entity=test_object, field="year_roof", value=2021,
            source="foo", user=admin_user,
        )


def test_write_gate_unknown_tablename_raises(db, admin_user):
    class Fake:
        __tablename__ = "foo_bar_nope"
        id = uuid.uuid4()
        year_roof = None

    with pytest.raises(WriteGateError):
        write_field_human(
            db, entity=Fake(), field="year_roof", value=2021,
            source="user_edit", user=admin_user,
        )


def test_write_ai_proposal_invalid_confidence(db, test_object):
    with pytest.raises(ValueError):
        write_field_ai_proposal(
            db,
            target_entity_type="object",
            target_entity_id=test_object.id,
            field="year_roof",
            proposed_value=2019,
            agent_ref="x",
            confidence=1.5,
            source_doc_id=None,
        )


def test_write_ai_proposal_unknown_target_type(db, test_object):
    with pytest.raises(WriteGateError):
        write_field_ai_proposal(
            db,
            target_entity_type="nonsense",
            target_entity_id=test_object.id,
            field="x",
            proposed_value=1,
            agent_ref="x",
            confidence=0.5,
            source_doc_id=None,
        )


# ---------------------------------------------------------------------------
# Pflegegrad-Cache-Invalidation
# ---------------------------------------------------------------------------

def test_invalidate_pflegegrad_on_object_write(db, test_object, admin_user):
    test_object.pflegegrad_score_cached = 75
    test_object.pflegegrad_score_updated_at = _dt.datetime.now(tz=_dt.timezone.utc)
    db.commit()

    write_field_human(
        db, entity=test_object, field="year_roof", value=2021,
        source="user_edit", user=admin_user,
    )
    db.commit()
    db.expire_all()

    obj = db.get(Object, test_object.id)
    assert obj.pflegegrad_score_cached is None
    assert obj.pflegegrad_score_updated_at is None


# ---------------------------------------------------------------------------
# Encrypted-Field-Snapshot-Marker (NFR-S2)
# ---------------------------------------------------------------------------

def test_encrypted_field_snapshot_marker(db, test_object, admin_user):
    test_object.entry_code_main_door = "1234"
    db.commit()

    write_field_human(
        db, entity=test_object, field="entry_code_main_door", value="5678",
        source="user_edit", user=admin_user,
    )
    db.commit()

    prov = (
        db.query(FieldProvenance)
        .filter_by(entity_id=test_object.id, field_name="entry_code_main_door")
        .one()
    )
    assert prov.value_snapshot == {
        "old": {"encrypted": True},
        "new": {"encrypted": True},
    }


def test_encrypted_field_audit_details_has_no_plaintext(
    db, test_object, admin_user
):
    test_object.entry_code_garage = "secret-old"
    db.commit()

    write_field_human(
        db, entity=test_object, field="entry_code_garage", value="secret-new",
        source="user_edit", user=admin_user,
    )
    db.commit()

    audit = (
        db.query(AuditLog)
        .filter_by(action="object_field_updated", entity_id=test_object.id)
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert audit is not None
    assert audit.details_json["old"] == {"encrypted": True}
    assert audit.details_json["new"] == {"encrypted": True}
    # Doppelt abgesichert: kein Klartext im gesamten details_json-Blob.
    import json
    blob = json.dumps(audit.details_json)
    assert "secret-old" not in blob
    assert "secret-new" not in blob


# ---------------------------------------------------------------------------
# Integrative Lifecycle-Kette (Story 1.2, AC4–AC7 zusammen)
# ---------------------------------------------------------------------------

def test_full_lifecycle_user_edit_then_ai_proposal_then_approve(
    db, test_object, admin_user
):
    """Chain: User schreibt Feld -> KI schlaegt Korrektur vor -> Admin
    approved. Am Ende zwei Provenance-Rows (user_edit + ai_suggestion),
    Entry auf approved, Audit-Chain komplett.

    Deckt die Komposition aus write_field_human + write_field_ai_proposal +
    approve_review_entry in einer Transaktion ab — die bestehenden Unit-
    Tests pruefen jede Funktion einzeln, nicht den Zusammenlauf.
    """
    write_field_human(
        db, entity=test_object, field="year_roof", value=1995,
        source="user_edit", user=admin_user,
    )
    db.commit()

    entry = write_field_ai_proposal(
        db,
        target_entity_type="object",
        target_entity_id=test_object.id,
        field="year_roof",
        proposed_value=2004,
        agent_ref="te_scan_agent",
        confidence=0.92,
        source_doc_id=None,
        user=admin_user,
    )
    db.commit()

    # Proposal darf das Zielfeld nicht anfassen (NFR-S6).
    db.expire_all()
    obj = db.get(Object, test_object.id)
    assert obj.year_roof == 1995

    approve_review_entry(db, entry_id=entry.id, user=admin_user)
    db.commit()

    db.expire_all()
    obj = db.get(Object, test_object.id)
    assert obj.year_roof == 2004

    provs = (
        db.query(FieldProvenance)
        .filter_by(entity_id=obj.id, field_name="year_roof")
        .all()
    )
    assert len(provs) == 2
    assert {p.source for p in provs} == {"user_edit", "ai_suggestion"}
    ai_prov = next(p for p in provs if p.source == "ai_suggestion")
    assert ai_prov.source_ref == "te_scan_agent"
    assert ai_prov.confidence == 0.92
    assert ai_prov.user_id == admin_user.id

    reloaded = db.get(ReviewQueueEntry, entry.id)
    assert reloaded.status == "approved"
    assert reloaded.decided_by_user_id == admin_user.id

    actions = [a.action for a in db.query(AuditLog).all()]
    assert actions.count("object_field_updated") == 2
    assert actions.count("review_queue_created") == 1
    assert actions.count("review_queue_approved") == 1


def test_approve_silently_overwrites_user_edit_made_after_proposal(
    db, test_object, admin_user
):
    """Characterization-Test fuer das Stale-Proposal-Szenario (siehe
    deferred-work.md > Story 1.2 > "Stale-Proposal-Check beim Approve"):
    wenn der User NACH Proposal-Erstellung dasselbe Feld manuell aendert,
    bypasst Approve diesen Edit heute stumm.

    UX-Entscheidung faellt in Story 3.5/3.6 (Warnung / stale-Status /
    Force-Flag) — dieser Test dokumentiert den aktuellen Stand als
    Regression-Anker und muss mit der UX-Umsetzung gespiegelt werden.
    """
    entry = write_field_ai_proposal(
        db,
        target_entity_type="object",
        target_entity_id=test_object.id,
        field="year_roof",
        proposed_value=2004,
        agent_ref="te_scan_agent",
        confidence=0.9,
        source_doc_id=None,
        user=admin_user,
    )
    db.commit()

    # User editiert dasselbe Feld danach von Hand.
    write_field_human(
        db, entity=test_object, field="year_roof", value=2018,
        source="user_edit", user=admin_user,
    )
    db.commit()

    approve_review_entry(db, entry_id=entry.id, user=admin_user)
    db.commit()

    db.expire_all()
    obj = db.get(Object, test_object.id)
    # Aktuell: KI-Wert ueberschreibt stumm den juengeren User-Edit.
    assert obj.year_roof == 2004
    reloaded = db.get(ReviewQueueEntry, entry.id)
    assert reloaded.status == "approved"
