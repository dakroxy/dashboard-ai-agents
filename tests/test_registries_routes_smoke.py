"""Story 2.7 — Route-Smoke-Tests fuer Versicherer-Listenansicht."""
from __future__ import annotations

import uuid
from decimal import Decimal

from app.models import InsurancePolicy, Object, Versicherer


# ---------------------------------------------------------------------------
# Auth / Permission
# ---------------------------------------------------------------------------

def test_unauthenticated_redirects(anon_client):
    resp = anon_client.get("/registries/versicherer")
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/auth/google/login")


def test_no_permission_returns_403(auth_client):
    resp = auth_client.get("/registries/versicherer")
    assert resp.status_code == 403
    assert "registries:view" in resp.text


def test_permitted_user_returns_200(steckbrief_admin_client):
    resp = steckbrief_admin_client.get("/registries/versicherer")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# Fragment endpoint
# ---------------------------------------------------------------------------

def test_rows_fragment_unauthenticated_redirects(anon_client):
    resp = anon_client.get("/registries/versicherer/rows")
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/auth/google/login")


def test_rows_fragment_no_permission_returns_403(auth_client):
    resp = auth_client.get("/registries/versicherer/rows")
    assert resp.status_code == 403


def test_rows_fragment_sort_roundtrip(steckbrief_admin_client, db):
    obj = Object(id=uuid.uuid4(), short_code="SRT1", name="Sort-Objekt")
    db.add(obj)
    v_viel = Versicherer(id=uuid.uuid4(), name="Viel-Versicherer")
    v_wenig = Versicherer(id=uuid.uuid4(), name="Wenig-Versicherer")
    db.add(v_viel)
    db.add(v_wenig)
    for _ in range(3):
        db.add(InsurancePolicy(
            id=uuid.uuid4(), object_id=obj.id,
            versicherer_id=v_viel.id, praemie=Decimal("100"),
        ))
    db.add(InsurancePolicy(
        id=uuid.uuid4(), object_id=obj.id,
        versicherer_id=v_wenig.id, praemie=Decimal("100"),
    ))
    db.commit()

    resp = steckbrief_admin_client.get(
        "/registries/versicherer/rows?sort=policen_anzahl&order=desc"
    )
    assert resp.status_code == 200
    body = resp.text
    pos_viel = body.index("Viel-Versicherer")
    pos_wenig = body.index("Wenig-Versicherer")
    assert pos_viel < pos_wenig, "Versicherer mit mehr Policen muss zuerst erscheinen"


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def test_sidebar_link_visible_for_permitted_user(steckbrief_admin_client):
    resp = steckbrief_admin_client.get("/")
    assert resp.status_code == 200
    assert 'href="/registries/versicherer"' in resp.text


def test_sidebar_link_hidden_for_unpermitted_user(auth_client):
    resp = auth_client.get("/")
    assert resp.status_code == 200
    assert 'href="/registries/versicherer"' not in resp.text


# ---------------------------------------------------------------------------
# Story 2.8 — Versicherer-Detailseite
# ---------------------------------------------------------------------------

def test_detail_unauthenticated_redirects(anon_client):
    resp = anon_client.get(f"/registries/versicherer/{uuid.uuid4()}")
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/auth/google/login")


def test_detail_no_permission_returns_403(auth_client):
    resp = auth_client.get(f"/registries/versicherer/{uuid.uuid4()}")
    assert resp.status_code == 403


def test_detail_unknown_versicherer_returns_404(steckbrief_admin_client):
    resp = steckbrief_admin_client.get(f"/registries/versicherer/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_detail_permitted_user_returns_200(steckbrief_admin_client, db):
    v = Versicherer(id=uuid.uuid4(), name="Detail-Smoke-Versicherer")
    db.add(v)
    db.commit()

    resp = steckbrief_admin_client.get(f"/registries/versicherer/{v.id}")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Detail-Smoke-Versicherer" in resp.text
