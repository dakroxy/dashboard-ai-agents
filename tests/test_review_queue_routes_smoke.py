import uuid
from datetime import datetime, timezone

from app.models.governance import ReviewQueueEntry


def _make_entry(db, field_name="heating_type"):
    entry = ReviewQueueEntry(
        target_entity_type="object",
        target_entity_id=uuid.uuid4(),
        field_name=field_name,
        proposed_value={"value": "Fernwärme"},
        agent_ref="test-agent-v1",
        confidence=0.9,
        status="pending",
        agent_context={},
        created_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
    )
    db.add(entry)
    db.commit()
    return entry


def test_review_queue_unauthenticated(anon_client):
    resp = anon_client.get("/admin/review-queue", follow_redirects=False)
    assert resp.status_code == 302


def test_review_queue_no_permission(auth_client):
    resp = auth_client.get("/admin/review-queue")
    assert resp.status_code == 403


def test_review_queue_empty_state(steckbrief_admin_client):
    resp = steckbrief_admin_client.get("/admin/review-queue")
    assert resp.status_code == 200
    assert "Keine Vorschläge offen" in resp.text


def test_review_queue_entry_visible(steckbrief_admin_client, db):
    _make_entry(db, field_name="heating_type")
    resp = steckbrief_admin_client.get("/admin/review-queue")
    assert resp.status_code == 200
    assert "heating_type" in resp.text


def test_review_queue_rows_fragment_200(steckbrief_admin_client):
    resp = steckbrief_admin_client.get("/admin/review-queue/rows")
    assert resp.status_code == 200
    assert "Keine Vorschläge offen" in resp.text


def test_review_queue_filter_field_name(steckbrief_admin_client, db):
    _make_entry(db, field_name="heating_type")
    _make_entry(db, field_name="year_built")
    resp = steckbrief_admin_client.get("/admin/review-queue/rows?field_name=heating_type")
    assert resp.status_code == 200
    assert "heating_type" in resp.text
    assert "year_built" not in resp.text


def test_review_queue_filter_min_age_excludes_fresh(steckbrief_admin_client, db):
    entry = ReviewQueueEntry(
        target_entity_type="object",
        target_entity_id=uuid.uuid4(),
        field_name="heating_type",
        proposed_value={"value": "Gas"},
        agent_ref="agent",
        confidence=0.8,
        status="pending",
        agent_context={},
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    db.commit()
    resp = steckbrief_admin_client.get("/admin/review-queue/rows?min_age_days=1")
    assert resp.status_code == 200
    assert "Keine Vorschläge offen" in resp.text


def test_review_queue_filter_invalid_uuid_no_422(steckbrief_admin_client, db):
    _make_entry(db, field_name="heating_type")
    resp = steckbrief_admin_client.get(
        "/admin/review-queue/rows?assigned_to_user_id=not-a-uuid"
    )
    assert resp.status_code == 200
    assert "heating_type" in resp.text
