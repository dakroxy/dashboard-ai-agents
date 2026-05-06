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


def _mobile_cards_slice(body: str) -> str:
    """Extrahiert den Mobile-Card-Section-Block aus objects_list.html
    (Story 3.2). Verhindert, dass Assertions zufaellig im Desktop-<tbody>
    matchen. Section-Marker: <div class="block sm:hidden ...> bis zum
    naechsten <div class="hidden sm:block ...>."""
    start = body.find('class="block sm:hidden')
    end = body.find('class="hidden sm:block')
    assert start != -1, "Mobile-Card-Section nicht gefunden (block sm:hidden)"
    assert end != -1, "Desktop-Wrapper nicht gefunden (hidden sm:block)"
    assert start < end, "Mobile-Section steht nach Desktop-Wrapper — Layout-Reihenfolge geprueft?"
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

    # Keine unerwarteten Review-Sektionen im Haupt-Content (Nav-Sidebar hat
    # jetzt "Review Queue" — nur Main-Content pruefen).
    m = re.search(r'<main[^>]*>(.*?)</main>', body, re.DOTALL)
    main_content = m.group(1) if m else body
    assert "Review" not in main_content


# ---------------------------------------------------------------------------
# Story 5-5 AC9 #152 — HTML-ID-Eindeutigkeit auf Objekt-Detailseite
# ---------------------------------------------------------------------------

def test_object_detail_html_ids_unique(
    db, steckbrief_admin_client, make_object
):
    """AC9 #152: Kein doppeltes id-Attribut auf der Objekt-Detailseite."""
    obj = make_object("IDU1", "ID-Eindeutigkeit-Test")
    resp = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert resp.status_code == 200
    body = resp.text
    ids = re.findall(r'\bid="([^"]+)"', body)
    dupes = [i for i in set(ids) if ids.count(i) > 1]
    assert not dupes, f"Doppelte HTML-IDs gefunden: {sorted(set(dupes))}"


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
        router_mod, "accessible_object_ids_for_request", lambda request, db, user: set()
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
    # Story 3.3 Pflegegrad-Score: +5 (1x Provenance-Batch + 3x Relational-Count + 1x Cache-Commit).
    # Story 4.4 Facilioo-Vorgaenge: +2 (get_open_tickets + get_last_facilioo_sync).
    # Story 5-3 AC5: +1 Versicherer-FK-Existenzcheck bei police_create/update.
    # Story 5-2 Review-Fix: +1 db.refresh() nach Pflegegrad-Cache-Lock — schliesst
    # den Lost-Write-Race, den der Lock allein offen liess.
    # Story 5-4 AC5: -3 (4 get_provenance_map → 1 get_provenance_map_bulk).
    # Story 5-4 AC6: -1 (Pflegegrad prov_map-Reuse, keine Extra-Query).
    # Puffer fuer Framework-Setup -> max 21.
    assert counter.count <= 21, (
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
    # Eindeutige short_codes (>=4 Zeichen, kein Substring anderer UI-Strings),
    # damit die Asserts nicht auf zufaellige Token im Response matchen
    # (Review-Patch P7: frueher LOW/OK ⇒ z. B. 'LOOKING' oder 'BOOKING'-False-Positive).
    db.add(Object(id=uuid.uuid4(), short_code="FRT001", name="Niedrig",
                  reserve_current=Decimal("1000"), reserve_target=Decimal("1000")))
    db.add(Object(id=uuid.uuid4(), short_code="FRT002", name="Gut",
                  reserve_current=Decimal("10000"), reserve_target=Decimal("1000")))
    db.commit()
    response = steckbrief_admin_client.get(
        "/objects/rows?filter_reserve=true",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    tbody = _tbody_slice(response.text)
    assert "FRT001" in tbody
    assert "FRT002" not in tbody


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


# ---------------------------------------------------------------------------
# Review-Patch P6 — AC4 Negativfaelle (Badge nicht rendern)
# ---------------------------------------------------------------------------

def test_rows_no_badge_when_reserve_target_is_none(steckbrief_admin_client, db):
    """AC4: kein Badge wenn reserve_target None (kein Threshold vergleichbar)."""
    db.add(Object(id=uuid.uuid4(), short_code="NTG", name="NullTarget",
                  reserve_current=Decimal("100"), reserve_target=None))
    db.commit()
    response = steckbrief_admin_client.get(
        "/objects/rows",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    row_html = _row_for(response.text, "NTG")
    assert "unter Zielwert" not in row_html


def test_rows_no_badge_when_reserve_current_is_none(steckbrief_admin_client, db):
    """AC4: kein Badge wenn reserve_current None (Spalte zeigt '—')."""
    db.add(Object(id=uuid.uuid4(), short_code="NCR", name="NullCurrent",
                  reserve_current=None, reserve_target=Decimal("1000")))
    db.commit()
    response = steckbrief_admin_client.get(
        "/objects/rows",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    row_html = _row_for(response.text, "NCR")
    assert "unter Zielwert" not in row_html


def test_rows_badge_rendered_for_decimal_zero_reserve_when_target_positive(
    steckbrief_admin_client, db,
):
    """AC4: reserve_current=Decimal('0') mit target>0 ⇒ Badge wird gerendert
    (Decimal-Truthiness-Falle: 0 ist NOT None, 0 < target*6 = True)."""
    db.add(Object(id=uuid.uuid4(), short_code="ZRO", name="ZeroReserve",
                  reserve_current=Decimal("0"), reserve_target=Decimal("500")))
    db.commit()
    response = steckbrief_admin_client.get(
        "/objects/rows",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    row_html = _row_for(response.text, "ZRO")
    assert "unter Zielwert" in row_html


# ---------------------------------------------------------------------------
# Review-Patch P6 — AC5 Negativfall (reserve_target=None vom Filter ausgeschlossen)
# ---------------------------------------------------------------------------

def test_rows_filter_excludes_objects_with_null_target(steckbrief_admin_client, db):
    db.add(Object(id=uuid.uuid4(), short_code="EXC001", name="NullTarget",
                  reserve_current=Decimal("100"), reserve_target=None))
    db.add(Object(id=uuid.uuid4(), short_code="EXC002", name="Below",
                  reserve_current=Decimal("100"), reserve_target=Decimal("1000")))
    db.commit()
    response = steckbrief_admin_client.get(
        "/objects/rows?filter_reserve=true",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    tbody = _tbody_slice(response.text)
    assert "EXC001" not in tbody
    assert "EXC002" in tbody


# ---------------------------------------------------------------------------
# Review-Patch P6 — AC6 Filter + Sort kombinierbar
# ---------------------------------------------------------------------------

def test_rows_filter_and_sort_combined_keeps_filter_and_sorts_result(
    steckbrief_admin_client, db,
):
    """AC6: Bei aktivem Filter und gewaehltem Sort werden BEIDE angewendet —
    nur unterhalb-Schwelle UND in der gewuenschten Reihenfolge."""
    # 3 Objekte unter Schwelle (reserve_current < target*6=6000), absteigend nach Saldo:
    db.add(Object(id=uuid.uuid4(), short_code="FS001", name="x",
                  reserve_current=Decimal("100"), reserve_target=Decimal("1000"),
                  last_known_balance=Decimal("10")))
    db.add(Object(id=uuid.uuid4(), short_code="FS002", name="y",
                  reserve_current=Decimal("100"), reserve_target=Decimal("1000"),
                  last_known_balance=Decimal("1000")))
    db.add(Object(id=uuid.uuid4(), short_code="FS003", name="z",
                  reserve_current=Decimal("100"), reserve_target=Decimal("1000"),
                  last_known_balance=Decimal("500")))
    # 1 Objekt UEBER Schwelle, hoher Saldo — darf trotz Sort nicht erscheinen:
    db.add(Object(id=uuid.uuid4(), short_code="FS999", name="hi",
                  reserve_current=Decimal("99999"), reserve_target=Decimal("1000"),
                  last_known_balance=Decimal("99999")))
    db.commit()
    response = steckbrief_admin_client.get(
        "/objects/rows?sort=saldo&order=desc&filter_reserve=true",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    tbody = _tbody_slice(response.text)
    # FS999 ist ueber Schwelle ⇒ raus (nur Filter-Effekt)
    assert "FS999" not in tbody
    # Reihenfolge der gefilterten Objekte: FS002 (1000) > FS003 (500) > FS001 (10)
    pos_2 = tbody.find("FS002")
    pos_3 = tbody.find("FS003")
    pos_1 = tbody.find("FS001")
    assert 0 <= pos_2 < pos_3 < pos_1


# ---------------------------------------------------------------------------
# Review-Patch D1 — Fragment liefert tbody primary + thead/filter-bar via OOB
# ---------------------------------------------------------------------------

def test_rows_fragment_includes_oob_thead_for_indicator_refresh(
    steckbrief_admin_client, db,
):
    """Damit ↑/↓-Indikator und hx-get-URLs nach jedem Sort aktualisiert werden,
    muss die Fragment-Response neben dem tbody auch <thead hx-swap-oob='true'>
    enthalten (Review-Patch D1)."""
    db.add(Object(id=uuid.uuid4(), short_code="OOB001", name="oob"))
    db.commit()
    response = steckbrief_admin_client.get(
        "/objects/rows?sort=saldo&order=desc",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    body = response.text
    # tbody ist primaeres Swap-Target
    assert 'id="obj-rows"' in body
    # thead und filter-bar via OOB
    assert 'id="obj-head"' in body
    assert 'hx-swap-oob="true"' in body
    assert 'id="obj-filter-bar"' in body
    # Sort-Indikator zeigt aktuellen Stand: saldo desc ⇒ ↓ (Unicode arrow,
    # nicht HTML-Entity — sonst escaped Jinja-Autoescape den Pfeil zu &amp;darr;).
    assert "↓" in body


def test_rows_fragment_filter_label_reflects_six_months(steckbrief_admin_client):
    """Review-Patch D2: Filter-Option-Label heisst 'Ruecklage < 6 Monatsbeitraege'
    (statt unklarem 'Ruecklage < Zielwert'), passt zur tatsaechlichen Bedingung."""
    response = steckbrief_admin_client.get(
        "/objects/rows",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "6 Monatsbeitr" in response.text  # 'Monatsbeitraege' mit umlaut-encoded


def test_list_full_page_filter_label_reflects_six_months(steckbrief_admin_client):
    """Same on the full-page render."""
    response = steckbrief_admin_client.get("/objects")
    assert response.status_code == 200
    assert "6 Monatsbeitr" in response.text


# ---------------------------------------------------------------------------
# Review-Patch P3+P4 — case-insensitive order/filter_reserve im Router
# ---------------------------------------------------------------------------

def test_rows_order_param_accepts_uppercase(steckbrief_admin_client, db):
    """?order=DESC soll als desc interpretiert werden (frueher: silently asc)."""
    db.add(Object(id=uuid.uuid4(), short_code="OA001", name="a", last_known_balance=Decimal("10")))
    db.add(Object(id=uuid.uuid4(), short_code="OA002", name="b", last_known_balance=Decimal("100")))
    db.commit()
    response = steckbrief_admin_client.get(
        "/objects/rows?sort=saldo&order=DESC",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    tbody = _tbody_slice(response.text)
    # Sort desc auf Saldo: 100 vor 10 ⇒ OA002 vor OA001
    assert tbody.find("OA002") < tbody.find("OA001")


def test_rows_filter_reserve_accepts_truthy_synonyms(steckbrief_admin_client, db):
    """?filter_reserve=1 / yes / on werden alle als True interpretiert."""
    db.add(Object(id=uuid.uuid4(), short_code="FT001", name="below",
                  reserve_current=Decimal("100"), reserve_target=Decimal("1000")))
    db.add(Object(id=uuid.uuid4(), short_code="FT002", name="above",
                  reserve_current=Decimal("99999"), reserve_target=Decimal("1000")))
    db.commit()
    for truthy in ("1", "yes", "TRUE", " on "):
        response = steckbrief_admin_client.get(
            f"/objects/rows?filter_reserve={truthy.strip().replace(' ', '%20')}",
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        tbody = _tbody_slice(response.text)
        assert "FT001" in tbody, f"filter_reserve={truthy!r} sollte Filter aktivieren"
        assert "FT002" not in tbody, f"filter_reserve={truthy!r} sollte Filter aktivieren"


# ---------------------------------------------------------------------------
# Story 3.2 — Mobile Card-Layout + Heizungs-Hotline Tap-to-Call
# ---------------------------------------------------------------------------

def test_list_mobile_card_section_present(steckbrief_admin_client, db):
    db.add(Object(id=uuid.uuid4(), short_code="MOB1", name="Mobil Eins"))
    db.commit()
    response = steckbrief_admin_client.get("/objects")
    assert response.status_code == 200
    assert "sm:hidden" in response.text, "Mobile Card-Section nicht gefunden (class sm:hidden fehlt)"
    assert "hidden sm:block" in response.text, "Desktop-Table-Toggle nicht gefunden"


def test_list_mobile_cards_contain_required_fields(steckbrief_admin_client, db):
    db.add(Object(id=uuid.uuid4(), short_code="MOB2", name="Mobil Zwei",
                  last_known_balance=Decimal("1234"), pflegegrad_score_cached=75))
    db.commit()
    response = steckbrief_admin_client.get("/objects")
    assert response.status_code == 200
    mobile = _mobile_cards_slice(response.text)
    assert "MOB2" in mobile, "short_code fehlt in Mobile-Card-Section"
    assert "Mobil Zwei" in mobile, "name fehlt in Mobile-Card-Section"
    assert "1234" in mobile, "Saldo fehlt in Mobile-Card-Section"
    assert "75%" in mobile, "Pflegegrad-Prozentwert fehlt in Mobile-Card-Section"


def test_list_mobile_cards_have_min_touch_target(steckbrief_admin_client, db):
    """AC1: Touch-Target jeder Card >= 44 px (via min-h-[44px]).
    Regression-Schutz, falls die Klasse beim Design-Refactor entfernt wird."""
    db.add(Object(id=uuid.uuid4(), short_code="TAP1", name="Touch Target"))
    db.commit()
    response = steckbrief_admin_client.get("/objects")
    assert response.status_code == 200
    mobile = _mobile_cards_slice(response.text)
    assert "min-h-[44px]" in mobile, (
        "Touch-Target-Klasse min-h-[44px] fehlt in Mobile-Card-Section (AC1)"
    )


def test_detail_heating_hotline_renders_tel_link(steckbrief_admin_client, db):
    obj = Object(id=uuid.uuid4(), short_code="HOT1", name="Hotline Test",
                 heating_hotline="040 123456")
    db.add(obj)
    db.commit()
    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    assert 'href="tel:040123456"' in response.text


def test_detail_heating_hotline_empty_shows_no_tel_link(steckbrief_admin_client, db):
    obj = Object(id=uuid.uuid4(), short_code="HOT2", name="Hotline Leer",
                 heating_hotline=None)
    db.add(obj)
    db.commit()
    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    assert 'href="tel:' not in response.text


def test_detail_photo_container_has_scroll_snap_classes(steckbrief_admin_client, db):
    obj = Object(id=uuid.uuid4(), short_code="PH01", name="Photo Test")
    db.add(obj)
    db.commit()
    response = steckbrief_admin_client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    assert "snap-x" in response.text
    assert "snap-mandatory" in response.text


def test_technik_field_save_heating_hotline_tel_kind_no_500(steckbrief_admin_client, db):
    obj = Object(id=uuid.uuid4(), short_code="TEL1", name="Tel Test")
    db.add(obj)
    db.commit()
    response = steckbrief_admin_client.post(
        f"/objects/{obj.id}/technik/field",
        data={"field_name": "heating_hotline", "value": "040 99887766"},
    )
    assert response.status_code == 200, (
        "500 deutet auf fehlenden 'tel'-Zweig in parse_technik_value() hin — Task 1.1 pruefen"
    )
    assert 'href="tel:04099887766"' in response.text


def test_list_desktop_table_still_rendered_after_mobile_addition(steckbrief_admin_client, db):
    db.add(Object(id=uuid.uuid4(), short_code="DSK1", name="Desktop Eins"))
    db.commit()
    response = steckbrief_admin_client.get("/objects")
    assert response.status_code == 200
    assert "hidden sm:block" in response.text
    assert "<table" in response.text
    assert 'id="obj-rows"' in response.text


def test_technik_field_edit_form_renders_type_tel_for_hotline(steckbrief_admin_client, db):
    obj = Object(id=uuid.uuid4(), short_code="EDT1", name="Edit Tel Test")
    db.add(obj)
    db.commit()
    response = steckbrief_admin_client.get(
        f"/objects/{obj.id}/technik/edit?field=heating_hotline"
    )
    assert response.status_code == 200
    assert 'type="tel"' in response.text
