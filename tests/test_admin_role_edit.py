"""Story 1.1 — Admin-Rollen-Edit zeigt neue Steckbrief-Permissions (AC1, AC5).

Ergaenzung zu test_steckbrief_bootstrap.py: dort wird die Registry / Groups
unit-level geprueft. Hier wird das tatsaechliche HTML-Rendering von
/admin/roles/{id} gegen den admin_client gefahren — deckt AC1 (Checkboxes
inklusive Gruppen-Header im UI) und AC5 (kein "unknown Permission"-Fehler
beim Render) zusammen ab.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user, get_optional_user
from app.db import get_db
from app.main import _seed_default_roles, app
from app.models import Role, User
from tests.conftest import _TestSessionLocal  # type: ignore


@pytest.fixture
def admin_client(db):
    user = User(
        id=uuid.uuid4(),
        google_sub=f"google-sub-{uuid.uuid4().hex[:12]}",
        email="role-admin@dbshome.de",
        name="Role Admin",
        permissions_extra=["users:manage"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    def override_db():
        session = _TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user

    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def seeded_user_role():
    _seed_default_roles()
    session = _TestSessionLocal()
    try:
        role = session.query(Role).filter(Role.key == "user").one()
        yield role.id
    finally:
        session.close()


class TestAdminRoleEditRendersSteckbriefPermissions:
    def test_page_renders_without_unknown_permission_error(
        self, admin_client, seeded_user_role
    ):
        # AC5 — Render darf nicht 500en, wenn alle Keys registriert sind.
        resp = admin_client.get(f"/admin/roles/{seeded_user_role}")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_page_contains_all_8_new_permission_checkboxes(
        self, admin_client, seeded_user_role
    ):
        # AC1 — alle 8 Steckbrief-Permissions muessen als Checkbox-Option
        # im Rollen-Edit-Formular auftauchen.
        resp = admin_client.get(f"/admin/roles/{seeded_user_role}")
        assert resp.status_code == 200
        html = resp.text
        for key in [
            "objects:view",
            "objects:edit",
            "objects:approve_ki",
            "objects:view_confidential",
            "registries:view",
            "registries:edit",
            "due_radar:view",
            "sync:admin",
        ]:
            assert f'value="{key}"' in html, f"Permission {key} fehlt im Rollen-Formular"

    def test_page_contains_new_permission_groups(
        self, admin_client, seeded_user_role
    ):
        # AC1 — Gruppen-Labels "Objekte", "Registries", "Due-Radar" erscheinen
        # als Abschnitts-Header im Rendering (ueber PERMISSIONS_BY_GROUP).
        resp = admin_client.get(f"/admin/roles/{seeded_user_role}")
        assert resp.status_code == 200
        html = resp.text
        for group_label in ["Objekte", "Registries", "Due-Radar"]:
            assert group_label in html, f"Gruppen-Header {group_label!r} fehlt"

    def test_default_user_subset_is_pre_checked(
        self, admin_client, seeded_user_role
    ):
        # AC2-Verifikation auf UI-Ebene: die 6 User-Default-Keys sind nach
        # Seed vor-selektiert, objects:view_confidential + sync:admin NICHT.
        resp = admin_client.get(f"/admin/roles/{seeded_user_role}")
        html = resp.text

        def _checkbox_checked(key: str) -> bool:
            needle = f'value="{key}"'
            idx = html.find(needle)
            assert idx != -1, f"Checkbox fuer {key} fehlt"
            # Das "checked"-Attribut steht im selben <input>-Tag — konservativ
            # die naechsten 200 Zeichen nach value= untersuchen.
            return "checked" in html[idx : idx + 200]

        for key in [
            "objects:view",
            "objects:edit",
            "objects:approve_ki",
            "registries:view",
            "registries:edit",
            "due_radar:view",
        ]:
            assert _checkbox_checked(key), f"{key} sollte vor-selektiert sein"

        for key in ["objects:view_confidential", "sync:admin"]:
            assert not _checkbox_checked(key), (
                f"{key} darf nicht im User-Default-Subset vor-selektiert sein"
            )
