"""Smoke-Tests fuer Pflegegrad-Badge + Popover (Story 3.4).

AC1 — Badge auf Detail-Seite mit korrekter Farbkodierung
AC2 — Popover mit Cluster-Komposition
AC3 — Popover mit weakest_fields und Deep-Links
AC4 — Anker-IDs im HTML
AC5 — Pill-Badge auf Listen-Seite (indirekt via pflegegrad_color Unit-Test)
"""
import re
from types import SimpleNamespace
from unittest.mock import patch

from app.services.pflegegrad import PflegegradResult

RESULT_GREEN = PflegegradResult(
    score=85,
    per_cluster={"C1": 1.0, "C4": 1.0, "C6": 0.75, "C8": 1.0},
    weakest_fields=["reserve_current"],
)
RESULT_YELLOW = PflegegradResult(
    score=55,
    per_cluster={"C1": 1.0, "C4": 0.5, "C6": 0.5, "C8": 0.5},
    weakest_fields=["shutoff_water_location", "has_police"],
)
RESULT_RED = PflegegradResult(
    score=25,
    per_cluster={"C1": 0.3, "C4": 0.2, "C6": 0.3, "C8": 0.2},
    weakest_fields=["year_built", "has_police", "has_wartungspflicht"],
)


def _patch_pflegegrad(result):
    return patch(
        "app.routers.objects.get_or_update_pflegegrad_cache",
        return_value=(result, False),
    )


# ---------------------------------------------------------------------------
# AC1 — Farbkodierung
# ---------------------------------------------------------------------------

def test_detail_badge_green(steckbrief_admin_client, test_object):
    with _patch_pflegegrad(RESULT_GREEN):
        resp = steckbrief_admin_client.get(f"/objects/{test_object.id}")
    assert resp.status_code == 200
    assert re.search(r"Pflegegrad\s+85\b", resp.text)
    assert "bg-green-100" in resp.text


def test_detail_badge_yellow(steckbrief_admin_client, test_object):
    with _patch_pflegegrad(RESULT_YELLOW):
        resp = steckbrief_admin_client.get(f"/objects/{test_object.id}")
    assert resp.status_code == 200
    assert re.search(r"Pflegegrad\s+55\b", resp.text)
    assert "bg-yellow-100" in resp.text


def test_detail_badge_red(steckbrief_admin_client, test_object):
    with _patch_pflegegrad(RESULT_RED):
        resp = steckbrief_admin_client.get(f"/objects/{test_object.id}")
    assert resp.status_code == 200
    assert re.search(r"Pflegegrad\s+25\b", resp.text)
    assert "bg-red-100" in resp.text


def test_detail_no_crash_when_pflegegrad_result_none(steckbrief_admin_client, test_object):
    with patch(
        "app.routers.objects.get_or_update_pflegegrad_cache",
        return_value=(None, False),
    ):
        resp = steckbrief_admin_client.get(f"/objects/{test_object.id}")
    assert resp.status_code == 200
    assert not re.search(r"Pflegegrad\s+\d+", resp.text)


# ---------------------------------------------------------------------------
# AC2 — Cluster-Komposition
# ---------------------------------------------------------------------------

def test_detail_popover_cluster_names(steckbrief_admin_client, test_object):
    with _patch_pflegegrad(RESULT_YELLOW):
        resp = steckbrief_admin_client.get(f"/objects/{test_object.id}")
    # Popover-Header muss da sein.
    assert "Score-Komposition" in resp.text
    # Cluster-Namen explizit als Tabellenzelle pruefen — Section-Headers
    # auf der Seite (z.B. "Finanzen") wuerden ein loses "in resp.text"
    # auch dann erfuellen, wenn die Popover-Tabelle kaputt ist.
    for cluster_name in ["Stammdaten", "Technik", "Finanzen", "Versicherungen"]:
        assert f">{cluster_name}</td>" in resp.text, (
            f"{cluster_name} fehlt als <td> im Popover"
        )


# ---------------------------------------------------------------------------
# AC3 — weakest_fields Deep-Links
# ---------------------------------------------------------------------------

def test_detail_popover_weakest_field_links(steckbrief_admin_client, test_object):
    with _patch_pflegegrad(RESULT_YELLOW):
        resp = steckbrief_admin_client.get(f"/objects/{test_object.id}")
    assert 'href="#field-shutoff_water_location"' in resp.text
    assert 'href="#policen-section"' in resp.text


def test_detail_popover_empty_weakest_fields(steckbrief_admin_client, test_object):
    result_full = PflegegradResult(
        score=100,
        per_cluster={"C1": 1.0, "C4": 1.0, "C6": 1.0, "C8": 1.0},
        weakest_fields=[],
    )
    with _patch_pflegegrad(result_full):
        resp = steckbrief_admin_client.get(f"/objects/{test_object.id}")
    assert "Alle Pflichtfelder gepflegt" in resp.text


# ---------------------------------------------------------------------------
# AC4 — Anker-IDs
# ---------------------------------------------------------------------------

def test_detail_anchor_ids_present(steckbrief_admin_client, test_object):
    with _patch_pflegegrad(RESULT_GREEN):
        resp = steckbrief_admin_client.get(f"/objects/{test_object.id}")
    assert resp.status_code == 200
    for anchor_id in [
        'id="field-full_address"',
        'id="field-impower_property_id"',
        'id="eigentuemer-section"',
        'id="field-last_known_balance"',
        'id="field-reserve_current"',
        'id="field-sepa_mandate_refs"',
        'id="policen-section"',
        'id="wartungen-section"',
    ]:
        assert anchor_id in resp.text, f"Missing anchor: {anchor_id}"


# ---------------------------------------------------------------------------
# pflegegrad_color Unit-Test (AC1 + AC5 Grenzwerte)
# ---------------------------------------------------------------------------

def test_pflegegrad_color_unit():
    from app.templating import pflegegrad_color

    # Alle drei Klassen-Familien (bg / text / border-color) muessen pro
    # Range vorhanden sein — sonst verliert die Pill ihren Rand oder
    # die Farbe still-leise bei einer Refaktorierung.
    green = pflegegrad_color(85)
    assert "bg-green-100" in green
    assert "text-green-800" in green
    assert "border-green-200" in green
    assert "bg-green-100" in pflegegrad_color(70)  # Boundary

    yellow = pflegegrad_color(69)
    assert "bg-yellow-100" in yellow
    assert "text-yellow-800" in yellow
    assert "border-yellow-200" in yellow
    assert "bg-yellow-100" in pflegegrad_color(40)  # Boundary

    red = pflegegrad_color(39)
    assert "bg-red-100" in red
    assert "text-red-800" in red
    assert "border-red-200" in red
    assert "bg-red-100" in pflegegrad_color(0)

    none_classes = pflegegrad_color(None)
    assert "bg-slate-100" in none_classes
    assert "text-slate-500" in none_classes
    assert "border-slate-200" in none_classes


def test_table_body_pill_at_boundary_70():
    """Render-Test: Listen-Pill bei Boundary score=70 hat 'border'-Keyword
    UND Gruen-Klassen — schuetzt vor Regressionen, falls jemand
    pflegegrad_color() aus dem Listen-Template zurueckbaut.
    """
    from app.templating import templates

    template = templates.env.get_template("_obj_table_body.html")
    rows = [
        SimpleNamespace(
            id=1,
            short_code="TST1",
            name="Test",
            saldo=None,
            reserve_current=None,
            reserve_below_target=False,
            mandat_status="vorhanden",
            pflegegrad=70,  # Boundary: muss gruen sein
        ),
    ]
    html = template.render(rows=rows)
    assert "bg-green-100" in html
    assert "border-green-200" in html
    # Border-Keyword (ohne Suffix) muss in der Pill stehen — sonst
    # rendert Tailwind die Border-Color-Klasse nicht sichtbar.
    assert "rounded-full border" in html
