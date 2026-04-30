import uuid
from datetime import datetime, timezone

import pytest

from app.models import AuditLog, Object
from app.models.governance import ReviewQueueEntry
from sqlalchemy import select


def _make_object(db, short_code="TST1"):
    obj = Object(id=uuid.uuid4(), short_code=short_code, name="Test-Objekt")
    db.add(obj)
    db.flush()
    return obj


def _make_pending_entry(db, obj: Object, field_name="heating_type", proposed="Fernwärme"):
    entry = ReviewQueueEntry(
        target_entity_type="object",
        target_entity_id=obj.id,
        field_name=field_name,
        proposed_value={"value": proposed},
        agent_ref="test-agent-v1",
        confidence=0.9,
        status="pending",
        agent_context={},
        created_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
    )
    db.add(entry)
    db.commit()
    return entry


def test_approve_sets_status(steckbrief_admin_client, db):
    obj = _make_object(db)
    entry = _make_pending_entry(db, obj)
    resp = steckbrief_admin_client.post(f"/admin/review-queue/{entry.id}/approve")
    assert resp.status_code in (204, 303)
    db.expire_all()
    updated = db.get(ReviewQueueEntry, entry.id)
    assert updated.status == "approved"
    assert updated.decided_by_user_id is not None
    assert updated.decided_at is not None


def test_approve_writes_field(steckbrief_admin_client, db):
    obj = _make_object(db, short_code="TST2")
    entry = _make_pending_entry(db, obj, field_name="heating_type", proposed="Fernwärme")
    steckbrief_admin_client.post(f"/admin/review-queue/{entry.id}/approve")
    db.expire_all()
    assert db.get(Object, obj.id).heating_type == "Fernwärme"


def test_approve_creates_audit_log(steckbrief_admin_client, db):
    obj = _make_object(db, short_code="TST3")
    entry = _make_pending_entry(db, obj)
    steckbrief_admin_client.post(f"/admin/review-queue/{entry.id}/approve")
    logs = db.execute(
        select(AuditLog).where(AuditLog.action == "review_queue_approved")
    ).scalars().all()
    assert len(logs) >= 1


def test_approve_supersedes_other_pending(steckbrief_admin_client, db):
    obj = _make_object(db, short_code="TST4")
    entry_a = _make_pending_entry(db, obj, field_name="heating_type", proposed="Gas")
    entry_b = _make_pending_entry(db, obj, field_name="heating_type", proposed="Fernwärme")
    steckbrief_admin_client.post(f"/admin/review-queue/{entry_b.id}/approve")
    db.expire_all()
    superseded = db.get(ReviewQueueEntry, entry_a.id)
    approved = db.get(ReviewQueueEntry, entry_b.id)
    assert superseded.status == "superseded"
    assert approved.status == "approved"
    # Auto-Supersede: decided_at als Zeitstempel gesetzt, decided_by_user_id
    # bewusst null (niemand hat den Entry explizit entschieden).
    assert superseded.decided_at is not None
    assert superseded.decided_by_user_id is None
    # Approve-Entry hat dagegen beide Felder.
    assert approved.decided_at is not None
    assert approved.decided_by_user_id is not None


def test_reject_sets_status(steckbrief_admin_client, db):
    obj = _make_object(db, short_code="TST5")
    entry = _make_pending_entry(db, obj)
    resp = steckbrief_admin_client.post(
        f"/admin/review-queue/{entry.id}/reject",
        data={"reason": "Falsches Feld"},
    )
    assert resp.status_code in (204, 303)
    db.expire_all()
    updated = db.get(ReviewQueueEntry, entry.id)
    assert updated.status == "rejected"
    assert updated.decision_reason == "Falsches Feld"


def test_reject_no_field_write(steckbrief_admin_client, db):
    obj = _make_object(db, short_code="TST6")
    original_heating = obj.heating_type
    entry = _make_pending_entry(db, obj, field_name="heating_type", proposed="Solar")
    steckbrief_admin_client.post(
        f"/admin/review-queue/{entry.id}/reject",
        data={"reason": "Korrekturfehler"},
    )
    db.expire_all()
    assert db.get(Object, obj.id).heating_type == original_heating


def test_reject_missing_reason_returns_400(steckbrief_admin_client, db):
    obj = _make_object(db, short_code="TST7")
    entry = _make_pending_entry(db, obj)
    resp = steckbrief_admin_client.post(
        f"/admin/review-queue/{entry.id}/reject",
        data={"reason": ""},
    )
    assert resp.status_code == 400


def test_approve_already_approved_returns_400(steckbrief_admin_client, db):
    obj = _make_object(db, short_code="TST8")
    entry = _make_pending_entry(db, obj)
    steckbrief_admin_client.post(f"/admin/review-queue/{entry.id}/approve")
    resp = steckbrief_admin_client.post(f"/admin/review-queue/{entry.id}/approve")
    assert resp.status_code == 400


def test_approve_no_permission_returns_403(auth_client, db):
    obj = _make_object(db, short_code="TST9")
    entry = _make_pending_entry(db, obj)
    resp = auth_client.post(f"/admin/review-queue/{entry.id}/approve")
    assert resp.status_code == 403


def test_reject_no_permission_returns_403(auth_client, db):
    obj = _make_object(db, short_code="TS10")
    entry = _make_pending_entry(db, obj)
    resp = auth_client.post(
        f"/admin/review-queue/{entry.id}/reject",
        data={"reason": "egal"},
    )
    assert resp.status_code == 403


def test_approve_unknown_entry_returns_404(steckbrief_admin_client, db):
    resp = steckbrief_admin_client.post(
        f"/admin/review-queue/{uuid.uuid4()}/approve"
    )
    assert resp.status_code == 404


def test_reject_unknown_entry_returns_404(steckbrief_admin_client, db):
    resp = steckbrief_admin_client.post(
        f"/admin/review-queue/{uuid.uuid4()}/reject",
        data={"reason": "Begründung"},
    )
    assert resp.status_code == 404


def test_reject_creates_audit_log(steckbrief_admin_client, db):
    obj = _make_object(db, short_code="TS11")
    entry = _make_pending_entry(db, obj)
    steckbrief_admin_client.post(
        f"/admin/review-queue/{entry.id}/reject",
        data={"reason": "Falscher Wert"},
    )
    logs = db.execute(
        select(AuditLog).where(AuditLog.action == "review_queue_rejected")
    ).scalars().all()
    assert len(logs) >= 1


def test_reject_too_long_reason_returns_400(steckbrief_admin_client, db):
    obj = _make_object(db, short_code="TS12")
    entry = _make_pending_entry(db, obj)
    resp = steckbrief_admin_client.post(
        f"/admin/review-queue/{entry.id}/reject",
        data={"reason": "x" * 2001},
    )
    assert resp.status_code == 400
    db.expire_all()
    assert db.get(ReviewQueueEntry, entry.id).status == "pending"


def test_reject_unicode_whitespace_only_returns_400(steckbrief_admin_client, db):
    """Zero-Width-Space + NBSP umgehen str.strip() — NFKC-Normalize muss greifen."""
    obj = _make_object(db, short_code="TS13")
    entry = _make_pending_entry(db, obj)
    # U+200B (Zero-Width-Space) + U+00A0 (NBSP) + U+FEFF (BOM/ZWNBSP)
    resp = steckbrief_admin_client.post(
        f"/admin/review-queue/{entry.id}/reject",
        data={"reason": "​ ﻿  "},
    )
    assert resp.status_code == 400
    db.expire_all()
    assert db.get(ReviewQueueEntry, entry.id).status == "pending"


def test_reject_form_fragment_returns_410_for_decided_entry(
    steckbrief_admin_client, db
):
    obj = _make_object(db, short_code="TS14")
    entry = _make_pending_entry(db, obj)
    # Entry wird approved → Reject-Form-Fragment fuer denselben Entry darf
    # nicht mehr ausgeliefert werden.
    steckbrief_admin_client.post(f"/admin/review-queue/{entry.id}/approve")
    resp = steckbrief_admin_client.get(
        f"/admin/review-queue/{entry.id}/reject-form"
    )
    assert resp.status_code == 410


def test_reject_form_fragment_returns_404_for_unknown_entry(
    steckbrief_admin_client,
):
    resp = steckbrief_admin_client.get(
        f"/admin/review-queue/{uuid.uuid4()}/reject-form"
    )
    assert resp.status_code == 404


def test_redirect_preserves_filter_via_hx_current_url(steckbrief_admin_client, db):
    """P7: HX-Redirect bewahrt Filter-Query der aufrufenden Liste."""
    obj = _make_object(db, short_code="TS15")
    entry = _make_pending_entry(db, obj)
    resp = steckbrief_admin_client.post(
        f"/admin/review-queue/{entry.id}/approve",
        headers={
            "HX-Request": "true",
            "HX-Current-URL": (
                "http://testserver/admin/review-queue?min_age_days=7"
            ),
        },
    )
    assert resp.status_code == 204
    assert resp.headers["HX-Redirect"].endswith("min_age_days=7")
