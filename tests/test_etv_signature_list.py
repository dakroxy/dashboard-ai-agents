"""Tests fuer das ETV-Unterschriftenlisten-Modul.

- Helper-Tests (Unit): Datentransformation, Vollmacht-Detection, Filename-Slug.
- Pagination-Tests (httpx.MockTransport): Facilioo ist 1-indexed.
- Route-Tests (TestClient): GET-Auswahl, POST-Generate, FaciliooError-Pfad,
  403 ohne Workflow-Access. WeasyPrint wird durchgehend gemockt — die echte
  Render-Pfad-Verifikation laeuft via Live-Smoke (siehe Spec Verification).
"""
from __future__ import annotations

import sys
import types
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user, get_optional_user
from app.db import get_db
from app.main import app
from app.models import ResourceAccess, User, Workflow
from app.permissions import RESOURCE_TYPE_WORKFLOW
from app.routers import etv_signature_list as etv_router
from app.services import facilioo_client


# ---------------------------------------------------------------------------
# Helper / Pure-Function Tests
# ---------------------------------------------------------------------------


def test_build_rows_marks_mandate_when_owner_id_matches():
    payload = {
        "voting_groups": [
            {
                "voting_group": {
                    "parties": [{"id": 11, "fullName": "Anna Beispiel"}],
                    "units": [{"number": "WE-1", "position": "EG li."}],
                },
                "shares": "100/1000",
            },
            {
                "voting_group": {
                    "parties": [{"id": 22, "fullName": "Bert Test"}],
                    "units": [{"number": "WE-2", "position": "EG re."}],
                },
                "shares": "120/1000",
            },
        ],
        # Nur Owner 11 hat eine Vollmacht -> ☑
        "mandates": [{"propertyOwnerId": 11, "representativeId": 99}],
    }
    rows = etv_router._build_rows(payload)
    assert rows[0]["has_mandate"] is True
    assert rows[1]["has_mandate"] is False
    assert rows[0]["owner_names"] == "Anna Beispiel"
    assert rows[0]["units"] == "WE-1 (EG li.)"
    assert rows[0]["shares"] == "100/1000"


def test_build_rows_joins_multiple_parties_with_comma():
    payload = {
        "voting_groups": [
            {
                "voting_group": {
                    "parties": [
                        {"id": 1, "fullName": "Anna Beispiel"},
                        {"id": 2, "fullName": "Bert Beispiel"},
                    ],
                    "units": [{"number": "WE-1", "position": "OG"}],
                },
                "shares": "200/1000",
            }
        ],
        "mandates": [],
    }
    rows = etv_router._build_rows(payload)
    assert rows[0]["owner_names"] == "Anna Beispiel, Bert Beispiel"


def test_build_rows_empty_voting_groups_returns_empty_list():
    rows = etv_router._build_rows({"voting_groups": [], "mandates": []})
    assert rows == []


def test_build_header_extracts_weg_name_and_formats_date():
    payload = {
        "conference": {
            "title": "Ordentliche ETV 2026",
            "date": "2026-05-12T18:30:00+02:00",
            "location": "Vereinsheim",
            "room": "Saal 1",
        },
        "property": {"name": "WEG PLS22 Ploetzenstr. 22, 31139 Hildesheim"},
    }
    header = etv_router._build_header(payload)
    assert header["weg_name"] == "WEG PLS22 Ploetzenstr. 22, 31139 Hildesheim"
    assert header["date_label"] == "12.05.2026"
    assert header["time_label"] == "18:30"
    assert header["location"] == "Vereinsheim"
    assert header["room"] == "Saal 1"


def test_build_filename_uses_date_and_property_slug():
    fn = etv_router._build_filename(
        {"date": "2026-05-12T18:30:00Z"},
        {"name": "WEG PLS22 Ploetzenstr. 22, 31139 Hildesheim"},
    )
    assert fn.startswith("etv-2026-05-12-")
    assert fn.endswith(".pdf")
    # ASCII-only, kein Whitespace, kein Slash
    assert " " not in fn and "/" not in fn


def test_format_conference_label_handles_missing_date():
    assert "ohne Datum" in etv_router._format_conference_label({"title": "X"})


# ---------------------------------------------------------------------------
# Pagination — Facilioo ist 1-indexed (`pageNumber=0` -> HTTP 400)
# ---------------------------------------------------------------------------


def _patched_facilioo_client(handler):
    transport = httpx.MockTransport(handler)

    class _Patched(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = transport
            super().__init__(**kwargs)

    return _Patched


@pytest.mark.asyncio
async def test_list_conferences_starts_at_page_one(monkeypatch):
    """Regression: Facilioo verlangt pageNumber>=1, sonst 400.
    Der Client darf nie pageNumber=0 anfragen."""
    seen_pages: list[str] = []

    def handler(request):
        page = request.url.params.get("pageNumber")
        seen_pages.append(page)
        if page == "0":
            return httpx.Response(
                400,
                json={"errors": [{"field": "PageNumber", "message": "must be >=1"}]},
            )
        # Eine Seite, totalPages=1 -> Loop endet.
        return httpx.Response(
            200,
            json={
                "items": [{"id": 1, "title": "ETV A"}, {"id": 2, "title": "ETV B"}],
                "pageNumber": 1,
                "pageSize": 100,
                "totalPages": 1,
                "totalCount": 2,
            },
        )

    monkeypatch.setattr(
        "app.services.facilioo_client.httpx.AsyncClient",
        _patched_facilioo_client(handler),
    )

    items = await facilioo_client.list_conferences()
    assert seen_pages == ["1"], f"Erwartet pageNumber=1, gesehen: {seen_pages}"
    assert len(items) == 2


@pytest.mark.asyncio
async def test_list_conferences_walks_multiple_pages(monkeypatch):
    """Multi-Page: Loop iteriert solange page < totalPages."""

    def handler(request):
        page = int(request.url.params.get("pageNumber"))
        if page == 1:
            return httpx.Response(
                200,
                json={
                    "items": [{"id": i} for i in range(1, 101)],  # 100 Items
                    "pageNumber": 1,
                    "totalPages": 2,
                },
            )
        if page == 2:
            return httpx.Response(
                200,
                json={
                    "items": [{"id": 101}, {"id": 102}],
                    "pageNumber": 2,
                    "totalPages": 2,
                },
            )
        return httpx.Response(400, json={"err": "unexpected page"})

    monkeypatch.setattr(
        "app.services.facilioo_client.httpx.AsyncClient",
        _patched_facilioo_client(handler),
    )

    items = await facilioo_client.list_conferences()
    assert len(items) == 102
    assert items[0]["id"] == 1 and items[-1]["id"] == 102


# ---------------------------------------------------------------------------
# Route-Smoke-Tests
# ---------------------------------------------------------------------------


def _seed_etv_workflow_with_access(db, user_id: uuid.UUID) -> Workflow:
    """Stellt sicher, dass der ETV-Workflow existiert und der User Zugriff hat.
    Lifespan-Seed kann je nach Test-Konstellation noch nicht gelaufen sein."""
    wf = (
        db.query(Workflow)
        .filter(Workflow.key == etv_router.ETV_WORKFLOW_KEY)
        .first()
    )
    if wf is None:
        wf = Workflow(
            id=uuid.uuid4(),
            key=etv_router.ETV_WORKFLOW_KEY,
            name="ETV-Unterschriftenliste",
            description="",
            model="",
            chat_model="claude-sonnet-4-6",
            system_prompt="",
            learning_notes="",
            active=True,
        )
        db.add(wf)
        db.commit()
        db.refresh(wf)

    exists = (
        db.query(ResourceAccess)
        .filter(
            ResourceAccess.user_id == user_id,
            ResourceAccess.resource_type == RESOURCE_TYPE_WORKFLOW,
            ResourceAccess.resource_id == wf.id,
        )
        .first()
    )
    if exists is None:
        db.add(
            ResourceAccess(
                id=uuid.uuid4(),
                user_id=user_id,
                resource_type=RESOURCE_TYPE_WORKFLOW,
                resource_id=wf.id,
                mode="allow",
            )
        )
        db.commit()
    return wf


def test_sidebar_lists_etv_workflow_for_user_with_access(
    monkeypatch, auth_client, db, test_user
):
    """Sidebar muss einen Link auf den ETV-Workflow enthalten, sobald der
    User Resource-Access auf den Workflow hat."""
    _seed_etv_workflow_with_access(db, test_user.id)

    async def fake_list():
        return []

    monkeypatch.setattr(etv_router, "list_conferences", fake_list)

    resp = auth_client.get("/workflows/etv-signature-list/")
    assert resp.status_code == 200
    body = resp.text
    # Sidebar-Sektion da + Link auf ETV-URL.
    assert "KI-Workflows" in body
    assert 'href="/workflows/etv-signature-list/"' in body


def test_select_screen_lists_conferences(monkeypatch, auth_client, db, test_user):
    _seed_etv_workflow_with_access(db, test_user.id)

    async def fake_list():
        return [
            {"id": 1, "title": "ETV A", "date": "2026-05-12T18:30:00Z", "state": "PLANNED"},
            {"id": 2, "title": "ETV B", "date": "2026-04-01T18:30:00Z", "state": "DONE"},
        ]

    monkeypatch.setattr(etv_router, "list_conferences", fake_list)

    resp = auth_client.get("/workflows/etv-signature-list/")
    assert resp.status_code == 200
    body = resp.text
    assert "ETV A" in body and "ETV B" in body
    # Sortiert desc -> ETV A (Mai) muss vor ETV B (April) im HTML stehen.
    assert body.index("ETV A") < body.index("ETV B")


def test_select_screen_shows_banner_when_facilioo_down(
    monkeypatch, auth_client, db, test_user
):
    _seed_etv_workflow_with_access(db, test_user.id)

    async def fake_list():
        raise etv_router.FaciliooError("network down", -1)

    monkeypatch.setattr(etv_router, "list_conferences", fake_list)

    resp = auth_client.get("/workflows/etv-signature-list/")
    assert resp.status_code == 200
    assert "nicht erreichbar" in resp.text


def test_generate_returns_pdf_on_happy_path(
    monkeypatch, auth_client, db, test_user
):
    _seed_etv_workflow_with_access(db, test_user.id)

    async def fake_payload(conf_id):
        return {
            "conference": {
                "id": conf_id,
                "title": "ETV PLS22",
                "date": "2026-05-12T18:30:00Z",
                "location": "Vereinsheim",
                "room": "Saal 1",
            },
            "property": {"name": "WEG PLS22 Ploetzenstr."},
            "voting_groups": [
                {
                    "voting_group": {
                        "parties": [{"id": 11, "fullName": "Anna Beispiel"}],
                        "units": [{"number": "WE-1", "position": "EG"}],
                    },
                    "shares": "100/1000",
                }
            ],
            "mandates": [{"propertyOwnerId": 11, "representativeId": 99}],
        }

    monkeypatch.setattr(
        etv_router, "fetch_conference_signature_payload", fake_payload
    )

    # WeasyPrint mocken (System-Libs fehlen evtl. lokal).
    fake_weasy = types.ModuleType("weasyprint")

    class _FakeHTML:
        def __init__(self, string=None):
            assert string is not None and "<html" in string
            self.string = string

        def write_pdf(self):
            return b"%PDF-1.4\nfake-pdf-bytes"

    fake_weasy.HTML = _FakeHTML  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "weasyprint", fake_weasy)

    resp = auth_client.post(
        "/workflows/etv-signature-list/generate",
        data={"conference_id": "6944"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF-")
    cd = resp.headers.get("content-disposition", "")
    assert cd.startswith("attachment;") and ".pdf" in cd


def test_generate_falls_back_to_banner_on_facilioo_error(
    monkeypatch, auth_client, db, test_user
):
    _seed_etv_workflow_with_access(db, test_user.id)

    async def fake_payload(conf_id):
        raise etv_router.FaciliooError("upstream 503", 503)

    async def fake_list():
        return []

    monkeypatch.setattr(
        etv_router, "fetch_conference_signature_payload", fake_payload
    )
    monkeypatch.setattr(etv_router, "list_conferences", fake_list)

    # WeasyPrint stub egal — wir kommen nicht bis zum Render.
    fake_weasy = types.ModuleType("weasyprint")
    fake_weasy.HTML = lambda string=None: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "weasyprint", fake_weasy)

    resp = auth_client.post(
        "/workflows/etv-signature-list/generate",
        data={"conference_id": "6944"},
    )
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "konnte die Conference" in resp.text or "nicht laden" in resp.text


def test_generate_returns_403_without_workflow_access(monkeypatch, db):
    """User OHNE ResourceAccess auf den ETV-Workflow bekommt 403."""
    # Eigener Test-Setup ohne den auth_client-fixture, da der User dort
    # automatisch Zugriff auf alle geseedeten Workflows kriegt.
    user = User(
        id=uuid.uuid4(),
        google_sub="g-sub-no-access",
        email="noaccess@dbshome.de",
        name="No Access",
        permissions_extra=[],
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Workflow-Eintrag muss existieren, sonst gibt's 500 statt 403.
    wf = (
        db.query(Workflow)
        .filter(Workflow.key == etv_router.ETV_WORKFLOW_KEY)
        .first()
    )
    if wf is None:
        wf = Workflow(
            id=uuid.uuid4(),
            key=etv_router.ETV_WORKFLOW_KEY,
            name="ETV-Unterschriftenliste",
            description="",
            model="",
            chat_model="claude-sonnet-4-6",
            system_prompt="",
            learning_notes="",
            active=True,
        )
        db.add(wf)
        db.commit()

    def override_db():
        yield db

    def override_user():
        return user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_user] = override_user

    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/workflows/etv-signature-list/generate",
                data={"conference_id": "6944"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()
