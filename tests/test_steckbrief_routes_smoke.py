"""Story 1.3 — Route-Smoke-Tests fuer Objekt-Liste und -Detailseite."""
from __future__ import annotations

import re
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.models import AuditLog, Eigentuemer, FieldProvenance, Object, Unit, User
from app.services.steckbrief_write_gate import write_field_human
from tests.conftest import _TEST_ENGINE, _TestSessionLocal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def steckbrief_admin_user(db):
    """Der zum steckbrief_admin_client gehoerende User (gleiche Perm-Liste)."""
    user = db.query(User).filter(
        User.email == "steckbrief-admin@dbshome.de"
    ).first()
    if user is not None:
        return user
    user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-admin-steckbrief-helper",
        email="steckbrief-admin@dbshome.de",
        name="Steckbrief Admin",
        permissions_extra=[
            "objects:view",
            "objects:edit",
            "objects:approve_ki",
            "objects:view_confidential",
            "registries:view",
            "registries:edit",
            "audit_log:view",
        ],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def make_object(db):
    def _make(short_code: str, name: str = "Testobjekt", units: int = 0) -> Object:
        obj = Object(id=uuid.uuid4(), short_code=short_code, name=name)
        db.add(obj)
        db.flush()
        for i in range(units):
            db.add(
                Unit(
                    id=uuid.uuid4(),
                    object_id=obj.id,
                    unit_number=f"{short_code}-U{i + 1}",
                )
            )
        db.commit()
        db.refresh(obj)
        return obj

    return _make


@pytest.fixture
def bulk_objects(db):
    objs: list[Object] = []
    for i in range(1, 51):
        short_code = f"OBJ{i:03d}"
        obj = Object(id=uuid.uuid4(), short_code=short_code, name=f"Obj {i}")
        db.add(obj)
        db.flush()
        # Variable unit counts 0-2 zur Abdeckung des LEFT-JOIN-Pfads.
        for u in range(i % 3):
            db.add(
                Unit(
                    id=uuid.uuid4(),
                    object_id=obj.id,
                    unit_number=f"{short_code}-U{u + 1}",
                )
            )
        objs.append(obj)
    db.commit()
    return objs


class _StmtCounter:
    """SQLAlchemy-Event-Listener, der SELECTs pro Request zaehlt."""

    def __init__(self):
        self.count = 0

    def __call__(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1


def _tbody_slice(body: str) -> str:
    """Extrahiert den <tbody>-Inhalt, damit Assertions nicht auf
    Sidebar/Header/Kommentare matchen koennen.
    Unterstuetzt <tbody> und <tbody id="..."> (Story 3.1: id="obj-rows")."""
    start = body.find("<tbody")
    end = body.find("</tbody>")
    assert start != -1 and end != -1, "kein <tbody> im Response"
    return body[start:end]


def _row_for(body: str, marker: str) -> str:
    """Liefert das <tr>...</tr>-Fragment, das `marker` enthaelt."""
    tbody = _tbody_slice(body)
    idx = tbody.find(marker)
    assert idx != -1, f"Marker {marker!r} nicht im tbody"
    tr_start = tbody.rfind("<tr", 0, idx)
    tr_end = tbody.find("</tr>", idx)
    assert tr_start != -1 and tr_end != -1, f"<tr>-Grenzen um {marker!r} nicht gefunden"
    return tbody[tr_start:tr_end + len("</tr>")]


# ---------------------------------------------------------------------------
# AC1 — Permission-Guards fuer die Liste
# ---------------------------------------------------------------------------

def test_list_requires_login(anon_client):
    response = anon_client.get("/objects")
    assert response.status_code == 302
    assert response.headers["location"].startswith("/auth/google/login")


def test_list_forbidden_without_objects_view(auth_client):
    # test_user hat keine objects:view-Permission
    response = auth_client.get("/objects")
    assert response.status_code == 403
    assert "objects:view" in response.json()["detail"]


# ---------------------------------------------------------------------------
# AC2 — Liste: Zeilen + Spalten + Sortierung + Links
# ---------------------------------------------------------------------------

def test_list_renders_rows_and_links(steckbrief_admin_client, make_object):
    o1 = make_object("BBB", "Zweites Objekt")
    o2 = make_object("AAA", "Erstes Objekt")
    o3 = make_object("CCC", "Drittes Objekt")

    response = steckbrief_admin_client.get("/objects")
    assert response.status_code == 200
    tbody = _tbody_slice(response.text)

    assert "AAA" in tbody and "BBB" in tbody and "CCC" in tbody
    assert f'href="/objects/{o1.id}"' in tbody
    assert f'href="/objects/{o2.id}"' in tbody
    assert f'href="/objects/{o3.id}"' in tbody

    # Deterministische Reihenfolge (AAA vor BBB vor CCC) — gescoped auf tbody,
    # damit Sidebar/Header den Test nicht stoeren (Review-Finding P5).
    pos_a = tbody.find("AAA")
    pos_b = tbody.find("BBB")
    pos_c = tbody.find("CCC")
    assert 0 <= pos_a < pos_b < pos_c


def test_list_empty_state(steckbrief_admin_client):
    response = steckbrief_admin_client.get("/objects")
    assert response.status_code == 200
    assert "Noch keine Objekte" in response.text


# ---------------------------------------------------------------------------
# AC3 — Performance / SQL-Statement-Count fuer die Liste
# ---------------------------------------------------------------------------

def test_list_performance_and_no_n_plus_1(steckbrief_admin_client, bulk_objects):
    # Wall-Clock ist zu flaky fuer CI (NFR-P2 wird auf echter Maschine gemessen).
    # Die SQL-Statement-Zaehlung ist der harte Guard: kein N+1 ueber 50 Objekte.
    counter = _StmtCounter()
    sa.event.listen(_TEST_ENGINE, "before_cursor_execute", counter)
    try:
        response = steckbrief_admin_client.get("/objects")
    finally:
        sa.event.remove(_TEST_ENGINE, "before_cursor_execute", counter)

    assert response.status_code == 200
    # Kein N+1: erwartet ist 1 Query fuer accessible_object_ids + 1 Query fuer
    # list_objects_with_unit_counts; Puffer von 1 fuer Framework-Setup.
    assert counter.count <= 3, (
        f"N+1 detected: {counter.count} SQL-Statements fuer 50 Objekte"
    )


# ---------------------------------------------------------------------------
# AC4 — Detail: Stammdaten + Eigentuemer
# ---------------------------------------------------------------------------

def test_detail_renders_stammdaten_and_eigentuemer(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("DET1", "Detail-Objekt")
    obj.full_address = "Musterstr. 1, 20095 Hamburg"
    obj.weg_nr = "WEG-42"
    obj.impower_property_id = "ImpowerProp-999"
    db.add(Eigentuemer(
        id=uuid.uuid4(), object_id=obj.id,
        name="Anna Muster", voting_stake_json={"percent": 50},
    ))
    db.add(Eigentuemer(
        id=uuid.uuid4(), object_id=obj.id,
        name="Bernd Muster", voting_stake_json={"percent": 25},
    ))
    db.commit()

    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    body = response.text

    assert "DET1" in body
    assert "Detail-Objekt" in body
    assert "Musterstr. 1, 20095 Hamburg" in body
    assert "WEG-42" in body
    assert "ImpowerProp-999" in body

    assert "Anna Muster" in body
    assert "Bernd Muster" in body
    assert "50" in body and "25" in body

    # Keine der noch nicht gebauten Sektionen (Finanzen ist seit Story 1.5,
    # Technik seit Story 1.6 da).
    assert "Review" not in body


# ---------------------------------------------------------------------------
# AC5 — Provenance-Pills pro Feld
# ---------------------------------------------------------------------------

def test_detail_provenance_pill_rendering(
    db, steckbrief_admin_client, make_object, steckbrief_admin_user
):
    obj = make_object("PIL1", "Pill-Objekt")

    write_field_human(
        db, entity=obj, field="name", value="Neuer Name",
        source="user_edit", user=steckbrief_admin_user,
    )
    write_field_human(
        db, entity=obj, field="full_address",
        value="Neue Str. 5, 20095 Hamburg",
        source="impower_mirror", user=None,
        source_ref="ImpowerProp-1234",
    )
    db.commit()

    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    body = response.text

    assert 'data-source="user_edit"' in body
    assert 'data-source="impower_mirror"' in body
    # Email im user_edit-Tooltip
    assert "steckbrief-admin@dbshome.de" in body
    # Mirror-Ref im Tooltip
    assert "ImpowerProp-1234" in body


def test_detail_missing_pill_for_unwritten_field(
    steckbrief_admin_client, make_object
):
    obj = make_object("PIL2", "Noch unerfasst")

    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    # Kein FieldProvenance vorhanden -> alle Felder muessen 'missing' sein
    assert 'data-source="missing"' in response.text


# ---------------------------------------------------------------------------
# AC6 — Stale-Banner
# ---------------------------------------------------------------------------

def test_detail_stale_banner_when_no_impower_provenance(
    steckbrief_admin_client, make_object
):
    obj = make_object("STA1", "Noch nie gespiegelt")

    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    assert "Noch nicht aus Impower synchronisiert" in response.text


def test_detail_stale_banner_absent_after_impower_mirror(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("STA2", "Wurde gespiegelt")
    write_field_human(
        db, entity=obj, field="full_address",
        value="Mirrored Str. 1", source="impower_mirror", user=None,
        source_ref="ImpowerProp-1",
    )
    db.commit()

    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    assert "Noch nicht aus Impower synchronisiert" not in response.text


def test_detail_stale_banner_persists_after_user_edit_only(
    db, steckbrief_admin_client, make_object, steckbrief_admin_user
):
    obj = make_object("STA3", "Nur User-Edit")
    write_field_human(
        db, entity=obj, field="name", value="Manuell",
        source="user_edit", user=steckbrief_admin_user,
    )
    db.commit()

    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert "Noch nicht aus Impower synchronisiert" in response.text


# ---------------------------------------------------------------------------
# AC7 — Detail: 404 / 422 / 302
# ---------------------------------------------------------------------------

def test_detail_404_unknown_id(steckbrief_admin_client):
    random_uuid = uuid.uuid4()
    response = steckbrief_admin_client.get(f"/objects/{random_uuid}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Objekt nicht gefunden"


def test_detail_422_invalid_uuid(steckbrief_admin_client):
    response = steckbrief_admin_client.get("/objects/not-a-uuid")
    assert response.status_code == 422


def test_detail_requires_login(anon_client):
    response = anon_client.get(f"/objects/{uuid.uuid4()}")
    assert response.status_code == 302


# ---------------------------------------------------------------------------
# AC8 — accessible_object_ids Hook
# ---------------------------------------------------------------------------

def test_detail_404_when_object_not_in_accessible_ids(
    steckbrief_admin_client, make_object, monkeypatch
):
    obj = make_object("HID1", "Versteckt")

    from app.routers import objects as router_mod
    monkeypatch.setattr(
        router_mod, "accessible_object_ids", lambda db, user: set()
    )
    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    # Ununterscheidbar von "existiert nicht" (NFR-S7)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC9 — Sidebar-Navigation
# ---------------------------------------------------------------------------

def test_sidebar_contains_objekte_link_for_permitted_user(
    steckbrief_admin_client,
):
    response = steckbrief_admin_client.get("/")
    assert response.status_code == 200
    body = response.text
    assert 'href="/objects"' in body
    assert "Objekte" in body


def test_sidebar_hides_objekte_link_for_unpermitted_user(auth_client):
    # test_user hat KEINE objects:view-Permission
    response = auth_client.get("/")
    assert response.status_code == 200
    # Weder der Link noch das Label — das Wort "Objekte" taucht sonst nirgendwo
    # auf dem Dashboard auf (Review-Finding P7, sonst wuerde ein Template-Bug
    # ohne <a>-Wrap den Test bestehen).
    assert 'href="/objects"' not in response.text
    assert "Objekte" not in response.text


# ---------------------------------------------------------------------------
# AC10 — Keine Write-Gate-Bypass-Wirkung
# ---------------------------------------------------------------------------

def test_detail_render_does_not_write_field_provenance_or_audit(
    db, steckbrief_admin_client, make_object
):
    obj = make_object("RO01", "Read-Only-Check")

    prov_before = db.query(FieldProvenance).count()
    audit_before = db.query(AuditLog).count()

    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200

    # Fremde Session ruft erneut die Counts ab (Transaktions-Isolation)
    session = _TestSessionLocal()
    try:
        assert session.query(FieldProvenance).count() == prov_before
        assert session.query(AuditLog).count() == audit_before
    finally:
        session.close()


def test_detail_sql_statement_count(
    db, steckbrief_admin_client, make_object, steckbrief_admin_user
):
    obj = make_object("SQL1", "Statement-Count")
    db.add(Eigentuemer(
        id=uuid.uuid4(), object_id=obj.id,
        name="A", voting_stake_json={"percent": 50},
    ))
    db.add(Eigentuemer(
        id=uuid.uuid4(), object_id=obj.id,
        name="B", voting_stake_json={"percent": 50},
    ))
    for field in ("name", "full_address", "weg_nr", "impower_property_id", "short_code"):
        write_field_human(
            db, entity=obj, field=field, value=f"v-{field}",
            source="user_edit", user=steckbrief_admin_user,
        )
    db.commit()

    counter = _StmtCounter()
    sa.event.listen(_TEST_ENGINE, "before_cursor_execute", counter)
    try:
        response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    finally:
        sa.event.remove(_TEST_ENGINE, "before_cursor_execute", counter)

    assert response.status_code == 200
    # Erwartet: accessible_ids, Object, Eigentuemer, Stammdaten-Provenance-Map,
    # Stale-Check, Finanzen-Provenance-Map, Sparkline-Rows, Technik-Provenance-Map,
    # Zugangscode-Provenance-Map (Story 1.7), SteckbriefPhoto-Liste (Story 1.8),
    # Policen-Liste mit Versicherer-Joinedload (Story 2.1), Versicherer-Dropdown (Story 2.1),
    # Schadensfaelle-Liste mit policy/versicherer/unit-joinedloads (Story 2.3),
    # Units-Dropdown (Story 2.3).
    # Puffer fuer Framework-Setup -> max 16.
    assert counter.count <= 16, (
        f"Zu viele SQL-Statements auf Detailseite: {counter.count}"
    )


# ---------------------------------------------------------------------------
# Story 3.1 — GET /objects/rows (HTMX-Fragment fuer Sort/Filter)
# ---------------------------------------------------------------------------

def test_rows_requires_login(anon_client):
    response = anon_client.get("/objects/rows")
    assert response.status_code == 302


def test_rows_forbidden_without_objects_view(auth_client):
    response = auth_client.get("/objects/rows")
    assert response.status_code == 403


def test_rows_direct_nav_without_htmx_redirects(steckbrief_admin_client):
    response = steckbrief_admin_client.get("/objects/rows")
    assert response.status_code == 303
    assert response.headers["location"] == "/objects"


def test_rows_htmx_request_returns_tbody_fragment(steckbrief_admin_client, db):
    db.add(Object(id=uuid.uuid4(), short_code="F001", name="Frag"))
    db.commit()
    response = steckbrief_admin_client.get(
        "/objects/rows",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert 'id="obj-rows"' in response.text
    assert "F001" in response.text


def test_rows_sort_by_saldo_desc_accepted(steckbrief_admin_client):
    response = steckbrief_admin_client.get(
        "/objects/rows?sort=saldo&order=desc",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200


def test_rows_invalid_sort_key_falls_back_to_short_code(steckbrief_admin_client, db):
    db.add(Object(id=uuid.uuid4(), short_code="INV", name="Invalid Sort"))
    db.commit()
    response = steckbrief_admin_client.get(
        "/objects/rows?sort=INVALID_KEY&order=asc",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200  # kein 500, Fallback auf short_code


def test_rows_filter_reserve_shows_only_below_threshold(steckbrief_admin_client, db):
    db.add(Object(id=uuid.uuid4(), short_code="LOW", name="Niedrig",
                  reserve_current=Decimal("1000"), reserve_target=Decimal("1000")))
    db.add(Object(id=uuid.uuid4(), short_code="OK", name="Gut",
                  reserve_current=Decimal("10000"), reserve_target=Decimal("1000")))
    db.commit()
    response = steckbrief_admin_client.get(
        "/objects/rows?filter_reserve=true",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "LOW" in response.text
    assert "OK" not in response.text


def test_rows_reserve_badge_rendered_for_object_below_threshold(steckbrief_admin_client, db):
    db.add(Object(id=uuid.uuid4(), short_code="BDG", name="Badge",
                  reserve_current=Decimal("500"), reserve_target=Decimal("1000")))
    db.commit()
    response = steckbrief_admin_client.get(
        "/objects/rows",
        headers={"HX-Request": "true"},
    )
    assert "unter Zielwert" in response.text


def test_rows_no_badge_when_reserve_above_threshold(steckbrief_admin_client, db):
    db.add(Object(id=uuid.uuid4(), short_code="NBD", name="NoBadge",
                  reserve_current=Decimal("9000"), reserve_target=Decimal("1000")))
    db.commit()
    response = steckbrief_admin_client.get(
        "/objects/rows",
        headers={"HX-Request": "true"},
    )
    assert "unter Zielwert" not in response.text
