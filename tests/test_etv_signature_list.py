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
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user, get_optional_user
from app.db import get_db
from app.main import app
from app.models import ResourceAccess, User, Workflow
from app.permissions import RESOURCE_TYPE_WORKFLOW
from tests.conftest import _make_session_cookie, _TEST_CSRF_TOKEN
from app.routers import etv_signature_list as etv_router
from app.services import facilioo
from app.templating import templates as jinja_templates


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
                "mea_decimal": Decimal("128"),
            },
            {
                "voting_group": {
                    "parties": [{"id": 22, "fullName": "Bert Test"}],
                    "units": [{"number": "WE-2", "position": "EG re."}],
                },
                "mea_decimal": Decimal("94"),
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
    assert rows[0]["shares"] == "128"


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
                "mea_decimal": Decimal("200"),
            }
        ],
        "mandates": [],
    }
    rows = etv_router._build_rows(payload)
    assert rows[0]["owner_names"] == "Anna Beispiel, Bert Beispiel"


def test_build_rows_empty_voting_groups_returns_empty_list():
    rows = etv_router._build_rows({"voting_groups": [], "mandates": []})
    assert rows == []


def test_build_rows_renders_dash_when_mea_missing():
    payload = {
        "voting_groups": [
            {
                "voting_group": {
                    "parties": [{"id": 1, "fullName": "Anna"}],
                    "units": [{"number": "WE-1", "position": "EG"}],
                },
                "mea_decimal": None,
            }
        ],
        "mandates": [],
    }
    rows = etv_router._build_rows(payload)
    assert rows[0]["shares"] == "—"


@pytest.mark.parametrize(
    "raw,expected",
    [
        (Decimal("128"), "128"),
        (Decimal("128.00"), "128"),
        (Decimal("98.57"), "98.57"),
        (Decimal("98.50"), "98.5"),
        (Decimal("0"), "0"),
        (Decimal("0.1") + Decimal("0.2"), "0.3"),  # Float-Drift waere 0.30000000000000004
    ],
)
def test_format_decimal_strips_trailing_zeros(raw, expected):
    assert etv_router._format_decimal(raw) == expected


def test_format_mea_returns_dash_for_none():
    assert etv_router._format_mea(None) == "—"


def test_format_mea_formats_decimal_via_format_decimal():
    assert etv_router._format_mea(Decimal("128.00")) == "128"


def test_compute_total_mea_sums_voting_groups():
    payload = {
        "voting_groups": [
            {"mea_decimal": Decimal("128")},
            {"mea_decimal": Decimal("94")},
            {"mea_decimal": Decimal("193")},
        ]
    }
    assert etv_router._compute_total_mea(payload) == "415"


def test_compute_total_mea_skips_none_entries():
    payload = {
        "voting_groups": [
            {"mea_decimal": Decimal("100")},
            {"mea_decimal": None},
            {"mea_decimal": Decimal("50.5")},
        ]
    }
    assert etv_router._compute_total_mea(payload) == "150.5"


def test_compute_total_mea_returns_dash_when_all_unset():
    payload = {
        "voting_groups": [
            {"mea_decimal": None},
            {"mea_decimal": None},
        ]
    }
    assert etv_router._compute_total_mea(payload) == "—"


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


def test_format_conference_label_includes_weg_number_when_present():
    label = etv_router._format_conference_label(
        {
            "title": "ETV2025",
            "date": "2025-08-18T14:00:00Z",
            "_property_number": "PLS22",
        }
    )
    assert "PLS22" in label and "ETV2025" in label
    assert label.index("PLS22") < label.index("ETV2025")


# ---------------------------------------------------------------------------
# Pagination — Facilioo ist 1-indexed (`pageNumber=0` -> HTTP 400)
# ---------------------------------------------------------------------------


def _patched_facilioo(handler):
    transport = httpx.MockTransport(handler)

    class _Patched(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = transport
            super().__init__(**kwargs)

    return _Patched


@pytest.mark.asyncio
async def test_missing_token_raises_immediately_no_retry_wait(monkeypatch):
    """Ohne Token soll der Client SOFORT failen — sonst zieht der httpx-
    LocalProtocolError-Retry 22 s pro Aufruf (Bug, der in Prod gesehen wurde)."""
    import time
    from app.services import facilioo as fc
    monkeypatch.setattr(fc.settings, "facilioo_bearer_token", "")
    t0 = time.time()
    with pytest.raises(fc.FaciliooError) as exc_info:
        await fc.list_conferences()
    assert (time.time() - t0) < 0.5, "Muss unter 500 ms scheitern, kein Retry"
    assert "nicht gesetzt" in str(exc_info.value).lower()


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
        "app.services.facilioo.httpx.AsyncClient",
        _patched_facilioo(handler),
    )

    items = await facilioo.list_conferences()
    assert seen_pages == ["1"], f"Erwartet pageNumber=1, gesehen: {seen_pages}"
    assert len(items) == 2


@pytest.mark.asyncio
async def test_list_conferences_with_properties_enriches_each_conference(monkeypatch):
    """Pro Conference wird /conferences/{id}/property nachgeladen und
    `_property_number` + `_property_name` ans Item gehaengt."""

    def handler(request):
        path = request.url.path
        if path == "/api/conferences":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": 1, "title": "ETV PLS22"},
                        {"id": 2, "title": "ETV GVE1"},
                    ],
                    "totalPages": 1,
                },
            )
        if path == "/api/conferences/1/property":
            return httpx.Response(200, json={"number": "PLS22", "name": "WEG PLS22"})
        if path == "/api/conferences/2/property":
            return httpx.Response(200, json={"number": "GVE1", "name": "WEG GVE1"})
        return httpx.Response(404, text="unexpected")

    monkeypatch.setattr(
        "app.services.facilioo.httpx.AsyncClient",
        _patched_facilioo(handler),
    )

    items = await facilioo.list_conferences_with_properties()
    assert len(items) == 2
    assert items[0]["_property_number"] == "PLS22"
    assert items[0]["_property_name"] == "WEG PLS22"
    assert items[1]["_property_number"] == "GVE1"


@pytest.mark.asyncio
async def test_list_conferences_with_properties_tolerates_property_failure(monkeypatch):
    """Ein einzelner Property-Fetch-Fehler darf den Listing-Aufruf nicht
    sprengen — die Conference erscheint dann ohne WEG-Kuerzel."""

    def handler(request):
        path = request.url.path
        if path == "/api/conferences":
            return httpx.Response(
                200,
                json={"items": [{"id": 1, "title": "ETV"}], "totalPages": 1},
            )
        if path == "/api/conferences/1/property":
            # 404 statt 5xx — verhindert den 22s-Retry-Pfad im Test.
            return httpx.Response(404, text="property not found")
        return httpx.Response(404)

    monkeypatch.setattr(
        "app.services.facilioo.httpx.AsyncClient",
        _patched_facilioo(handler),
    )

    items = await facilioo.list_conferences_with_properties()
    assert len(items) == 1
    assert items[0]["_property_number"] is None


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
        "app.services.facilioo.httpx.AsyncClient",
        _patched_facilioo(handler),
    )

    items = await facilioo.list_conferences()
    assert len(items) == 102
    assert items[0]["id"] == 1 and items[-1]["id"] == 102


# ---------------------------------------------------------------------------
# Aggregator: fetch_conference_signature_payload
# ---------------------------------------------------------------------------


def _aggregator_handler_factory(
    *,
    total_vgs: int,
    page_size: int = 10,
    mea_value_for_unit=None,
    attribute_5xx_for_unit_id: int | None = None,
):
    """Baut einen httpx.MockTransport-Handler fuer den Aggregator.

    Erzeugt `total_vgs` Voting-Groups ueber so viele Pages wie noetig (Page-Size 10).
    Pro VG eine Unit mit ID `2_000_000 + vg_idx`. `mea_value_for_unit(uid)` liefert
    den MEA-String oder None (kein Attribut gepflegt).
    """

    if mea_value_for_unit is None:
        def mea_value_for_unit(uid):  # noqa: E306
            return "100"

    def handler(request):
        path = request.url.path
        params = dict(request.url.params)

        if path.endswith("/property") or path == f"/api/conferences/123":
            if path == "/api/conferences/123":
                return httpx.Response(
                    200,
                    json={"id": 123, "title": "ETV Test", "date": "2026-05-12T18:30:00Z"},
                )
            return httpx.Response(
                200, json={"name": "WEG TEST", "id": 999, "number": "TEST"}
            )
        if path == "/api/conferences/123/voting-groups/shares":
            page = int(params.get("pageNumber", "1"))
            requested_size = int(params.get("pageSize", str(page_size)))
            actual_size = min(requested_size, page_size)
            total_pages = (total_vgs + actual_size - 1) // actual_size
            start = (page - 1) * actual_size
            end = min(start + actual_size, total_vgs)
            items = [
                {"votingGroupId": 1_000_000 + i, "shares": "0"}
                for i in range(start, end)
            ]
            return httpx.Response(
                200,
                json={
                    "items": items,
                    "pageNumber": page,
                    "pageSize": actual_size,
                    "totalPages": total_pages,
                    "totalCount": total_vgs,
                },
            )
        if path == "/api/conferences/123/mandates":
            return httpx.Response(
                200,
                json={
                    "items": [{"propertyOwnerId": 11, "representativeId": 99}],
                    "totalPages": 1,
                },
            )
        if path.startswith("/api/voting-groups/"):
            vg_id = int(path.rsplit("/", 1)[-1])
            vg_idx = vg_id - 1_000_000
            unit_id = 2_000_000 + vg_idx
            return httpx.Response(
                200,
                json={
                    "id": vg_id,
                    "parties": [{"id": 11 + vg_idx, "fullName": f"Owner {vg_idx}"}],
                    "units": [{"id": unit_id, "number": str(vg_idx), "position": ""}],
                },
            )
        if path.startswith("/api/units/") and path.endswith("/attribute-values"):
            uid = int(path.split("/")[3])
            if attribute_5xx_for_unit_id is not None and uid == attribute_5xx_for_unit_id:
                return httpx.Response(503, text="upstream down")
            value = mea_value_for_unit(uid)
            items = (
                [{"attributeId": facilioo.MEA_ATTRIBUTE_ID, "value": value}]
                if value is not None
                else []
            )
            return httpx.Response(
                200,
                json={"items": items, "pageNumber": 1, "totalPages": 1},
            )
        return httpx.Response(404, json={"err": f"unexpected {path}"})

    return handler


@pytest.mark.asyncio
async def test_aggregator_paginates_voting_group_shares_beyond_page_one(monkeypatch):
    """Regression: fetch_conference_signature_payload muss alle 16 VGs liefern,
    nicht nur die ersten 10."""
    monkeypatch.setattr(
        "app.services.facilioo.httpx.AsyncClient",
        _patched_facilioo(_aggregator_handler_factory(total_vgs=16)),
    )
    payload = await facilioo.fetch_conference_signature_payload(123)
    assert len(payload["voting_groups"]) == 16


@pytest.mark.asyncio
async def test_aggregator_pulls_mea_from_unit_attribute_values(monkeypatch):
    """Pro Unit lookup attribute-values, mea_decimal = Sum der Werte."""
    # Pro Unit liefert Facilioo unterschiedliche MEA-Werte, je nach uid.
    def mea_for_unit(uid):
        # Erste VG: MEA 128, zweite: 94, dritte: 98.57.
        idx = uid - 2_000_000
        return {0: "128", 1: "94", 2: "98.57"}[idx]

    handler = _aggregator_handler_factory(
        total_vgs=3, mea_value_for_unit=mea_for_unit
    )
    monkeypatch.setattr(
        "app.services.facilioo.httpx.AsyncClient",
        _patched_facilioo(handler),
    )
    payload = await facilioo.fetch_conference_signature_payload(123)
    decs = [vg["mea_decimal"] for vg in payload["voting_groups"]]
    assert decs == [Decimal("128"), Decimal("94"), Decimal("98.57")]


@pytest.mark.asyncio
async def test_aggregator_sums_mea_when_voting_group_has_multiple_units(monkeypatch):
    """Voting-Group mit n Units → mea_decimal ist die Summe."""
    base_handler = _aggregator_handler_factory(
        total_vgs=1, mea_value_for_unit=lambda uid: "50.25"
    )

    def handler(request):
        path = request.url.path
        # Einen Voting-Group-Detail-Call manipulieren: zwei Units statt einer.
        if path.startswith("/api/voting-groups/"):
            return httpx.Response(
                200,
                json={
                    "id": 1_000_000,
                    "parties": [{"id": 11, "fullName": "A"}],
                    "units": [
                        {"id": 2_000_000, "number": "1", "position": ""},
                        {"id": 2_000_001, "number": "2", "position": ""},
                    ],
                },
            )
        return base_handler(request)

    monkeypatch.setattr(
        "app.services.facilioo.httpx.AsyncClient",
        _patched_facilioo(handler),
    )
    payload = await facilioo.fetch_conference_signature_payload(123)
    assert payload["voting_groups"][0]["mea_decimal"] == Decimal("100.50")


@pytest.mark.asyncio
async def test_aggregator_marks_mea_none_when_no_attribute_present(monkeypatch):
    """Unit ohne attributeId=1438 → mea_decimal=None (Fallback rendert '—')."""
    handler = _aggregator_handler_factory(
        total_vgs=2, mea_value_for_unit=lambda uid: None
    )
    monkeypatch.setattr(
        "app.services.facilioo.httpx.AsyncClient",
        _patched_facilioo(handler),
    )
    payload = await facilioo.fetch_conference_signature_payload(123)
    assert all(vg["mea_decimal"] is None for vg in payload["voting_groups"])


@pytest.mark.asyncio
async def test_aggregator_propagates_facilioo_error_on_attribute_5xx(monkeypatch):
    """Persistente 5xx auf attribute-values: Aggregator degradiert gracefully
    (Story 5-3 AC1: return_exceptions=True). Unit bekommt leere Attributliste,
    Payload wird trotzdem zurueckgegeben."""
    handler = _aggregator_handler_factory(
        total_vgs=1, attribute_5xx_for_unit_id=2_000_000
    )
    monkeypatch.setattr(
        "app.services.facilioo.httpx.AsyncClient",
        _patched_facilioo(handler),
    )
    payload = await facilioo.fetch_conference_signature_payload(123)
    # Partial-degrade: kein Raise, aber die fehlschlagende Unit bekommt mea_decimal=None.
    assert "voting_groups" in payload
    assert len(payload["voting_groups"]) == 1
    assert payload["voting_groups"][0]["mea_decimal"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("poison_value", ["NaN", "Infinity", "-Infinity", "sNaN"])
async def test_aggregator_skips_nan_and_infinity_values(monkeypatch, poison_value):
    """Defensiv: Decimal('NaN'/'Infinity'/'-Infinity'/'sNaN') sind valide
    Konstruktoren; ohne `is_finite()`-Guard wuerde der Wert die Summe und
    den PDF-Output vergiften."""
    handler = _aggregator_handler_factory(
        total_vgs=1, mea_value_for_unit=lambda uid: poison_value
    )
    monkeypatch.setattr(
        "app.services.facilioo.httpx.AsyncClient",
        _patched_facilioo(handler),
    )
    payload = await facilioo.fetch_conference_signature_payload(123)
    # Kein finiter Wert -> mea_decimal=None (rendert spaeter als "—").
    assert payload["voting_groups"][0]["mea_decimal"] is None


@pytest.mark.asyncio
async def test_aggregator_uses_first_attribute_value_when_multiple_present(monkeypatch):
    """Defensiv: falls Facilioo je zwei attributeId=1438-Rows pro Unit liefert
    (Schema-Drift / History), nimmt der Aggregator nur die erste — sonst wuerde
    die MEA der Unit doppelt aufsummiert."""
    base_handler = _aggregator_handler_factory(total_vgs=1)

    def handler(request):
        path = request.url.path
        if path.startswith("/api/units/") and path.endswith("/attribute-values"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"attributeId": facilioo.MEA_ATTRIBUTE_ID, "value": "128"},
                        {"attributeId": facilioo.MEA_ATTRIBUTE_ID, "value": "999"},
                        {"attributeId": 9999, "value": "ignore"},
                    ],
                    "totalPages": 1,
                },
            )
        return base_handler(request)

    monkeypatch.setattr(
        "app.services.facilioo.httpx.AsyncClient",
        _patched_facilioo(handler),
    )
    payload = await facilioo.fetch_conference_signature_payload(123)
    # Erste valide Row (128), nicht 128+999=1127.
    assert payload["voting_groups"][0]["mea_decimal"] == Decimal("128")


# ---------------------------------------------------------------------------
# PDF-Template-Render-Tests (Jinja, ohne WeasyPrint)
# ---------------------------------------------------------------------------


def _render_pdf_template(rows, mea_total):
    return jinja_templates.get_template("etv_signature_list_pdf.html").render(
        {
            "header": {
                "weg_name": "WEG Test",
                "date_label": "01.01.2026",
                "time_label": "18:00",
                "location": "",
                "room": "",
                "title": "",
            },
            "rows": rows,
            "mea_total": mea_total,
        }
    )


def test_pdf_template_renders_summen_zeile_when_rows_present():
    html = _render_pdf_template(
        rows=[{"owner_names": "A", "units": "1", "shares": "128", "has_mandate": False}],
        mea_total="128",
    )
    assert "<tfoot>" in html
    assert "Summe" in html
    # MEA-Wert in der Summen-Zelle.
    assert ">128<" in html


def test_pdf_template_omits_summen_zeile_when_no_rows():
    html = _render_pdf_template(rows=[], mea_total="—")
    assert "<tfoot>" not in html
    assert "Keine Stimmgruppen hinterlegt" in html


def test_pdf_template_has_no_erzeugt_am_footer():
    html = _render_pdf_template(
        rows=[{"owner_names": "A", "units": "1", "shares": "100", "has_mandate": False}],
        mea_total="100",
    )
    assert "Erzeugt am" not in html
    assert "<footer>" not in html.lower()


def test_pdf_template_uses_real_umlaut_in_header():
    html = _render_pdf_template(
        rows=[{"owner_names": "A", "units": "1", "shares": "100", "has_mandate": False}],
        mea_total="100",
    )
    assert "Eigentümer" in html
    assert "Eigentuemer" not in html


def test_select_template_uses_real_umlauts():
    html = jinja_templates.get_template("etv_signature_list_select.html").render(
        {"options": [], "error": None, "user": None, "title": "ETV"}
    )
    assert "Eigentümerversammlung" in html
    assert "Eigentuemerversammlung" not in html


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

    monkeypatch.setattr(etv_router, "list_conferences_with_properties", fake_list)

    resp = auth_client.get("/workflows/etv-signature-list/")
    assert resp.status_code == 200
    body = resp.text
    # Sidebar-Sektion da + Link auf ETV-URL.
    # Section-Header steht zwischen Versicherer-Eintrag und Workflow-Einstellungen-Link.
    assert "Workflow-Einstellungen" in body  # neuer Konfig-Label
    assert 'href="/workflows/etv-signature-list/"' in body


def test_select_screen_lists_conferences(monkeypatch, auth_client, db, test_user):
    _seed_etv_workflow_with_access(db, test_user.id)

    async def fake_list():
        return [
            {
                "id": 1,
                "title": "ETV A",
                "date": "2026-05-12T18:30:00Z",
                "state": "PLANNED",
                "_property_number": "PLS22",
            },
            {
                "id": 2,
                "title": "ETV B",
                "date": "2026-04-01T18:30:00Z",
                "state": "DONE",
                "_property_number": "GVE1",
            },
        ]

    monkeypatch.setattr(etv_router, "list_conferences_with_properties", fake_list)

    resp = auth_client.get("/workflows/etv-signature-list/")
    assert resp.status_code == 200
    body = resp.text
    assert "ETV A" in body and "ETV B" in body
    # WEG-Kuerzel im Dropdown-Label sichtbar.
    assert "PLS22" in body and "GVE1" in body
    # Sortiert desc -> ETV A (Mai) muss vor ETV B (April) im HTML stehen.
    assert body.index("ETV A") < body.index("ETV B")


def test_select_screen_shows_banner_when_facilioo_down(
    monkeypatch, auth_client, db, test_user
):
    _seed_etv_workflow_with_access(db, test_user.id)

    async def fake_list():
        raise etv_router.FaciliooError("network down", -1)

    monkeypatch.setattr(etv_router, "list_conferences_with_properties", fake_list)

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
    monkeypatch.setattr(etv_router, "list_conferences_with_properties", fake_list)

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
            client.cookies.set("session", _make_session_cookie({"csrf_token": _TEST_CSRF_TOKEN}))
            client.headers["X-CSRF-Token"] = _TEST_CSRF_TOKEN
            resp = client.post(
                "/workflows/etv-signature-list/generate",
                data={"conference_id": "6944"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()
