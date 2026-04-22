"""Orchestrator-Tests fuer `run_mietverwaltung_write` (M5 Paket 7).

test_mietverwaltung_write.py deckt `_write_all_steps` ab — also den inneren
Pipeline-Flow gegen die gemockte Impower-API. Der aeussere BackgroundTask-
Orchestrator hatte bisher null Coverage, obwohl genau er:

  - den Preflight-Check vor dem Write macht,
  - `case.status` zwischen writing / written / partial / error setzt,
  - Audit-Eintraege pro Ausgang schreibt,
  - die Fehler-Taxonomie (ImpowerError vs. generic Exception) unterscheidet,
  - eine eigene DB-Session via `SessionLocal()` oeffnet.

Die Tests hier patchen `_write_all_steps` als ganzen Schritt und fahren den
Orchestrator direkt — Impower-API-Mocks bleiben dem Pipeline-Test-File
ueberlassen.
"""
from __future__ import annotations

import uuid

import pytest

from app.models import AuditLog, Case, User, Workflow
from app.services import mietverwaltung_write as mw


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_session_local(monkeypatch):
    """run_mietverwaltung_write oeffnet eine neue Session via `SessionLocal()`,
    die per `from app.db import SessionLocal` am Modul-Top gebunden wurde.
    conftest patcht `app.db.SessionLocal` NACH diesem Import — fuer
    mietverwaltung_write muessen wir den Modul-lokalen Namen umbiegen."""
    from tests.conftest import _TestSessionLocal

    monkeypatch.setattr(mw, "SessionLocal", _TestSessionLocal)


@pytest.fixture
def mw_workflow(db):
    wf = Workflow(
        id=uuid.uuid4(),
        key=f"mv-test-{uuid.uuid4().hex[:6]}",
        name="Mietverwaltung Test",
        description="",
        model="claude-opus-4-7",
        chat_model="claude-sonnet-4-6",
        system_prompt="",
        learning_notes="",
        active=True,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@pytest.fixture
def mw_user(db):
    user = User(
        id=uuid.uuid4(),
        google_sub=f"mv-user-{uuid.uuid4().hex[:6]}",
        email=f"mv-{uuid.uuid4().hex[:6]}@dbshome.de",
        name="MV Test User",
        permissions_extra=[],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _full_state() -> dict:
    """Preflight-erfuellender Minimal-State."""
    return {
        "property": {
            "number": "HAM61", "street": "Hauptstr. 1",
            "postal_code": "20099", "city": "Hamburg",
        },
        "owner": {"last_name": "Mustermann"},
        "units": [{"number": "1"}],
    }


def _mk_case(db, workflow, user, *, state=None, status="draft", impower_result=None) -> Case:
    case = Case(
        id=uuid.uuid4(),
        workflow_id=workflow.id,
        created_by_id=user.id,
        name="Testfall",
        status=status,
        state=state or {},
        impower_result=impower_result,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


# ---------------------------------------------------------------------------
# Happy Path
# ---------------------------------------------------------------------------

def test_run_write_happy_path_sets_written_and_audits(
    db, mw_workflow, mw_user, monkeypatch
):
    """Wenn `_write_all_steps` ohne Fehler durchlaeuft, muss status='written'
    gesetzt sein und ein `mietverwaltung_write_complete`-Audit existieren."""
    case = _mk_case(db, mw_workflow, mw_user, state=_full_state())

    async def fake_steps(state, ir):
        # Simuliert einen erfolgreichen Run: Property + Units + Tenant-Contracts
        # sind angelegt.
        ir["property_id"] = 900
        ir["unit_ids"] = {"1": 5101}
        ir["tenant_contract_ids"] = {"1": 3001}
        ir["steps_completed"].extend(
            [
                "owner_contact", "tenant_contacts",
                "property_create", "property_owner_contract",
                "property_details", "units", "tenant_contracts_create",
                "exchange_plans", "deposits",
            ]
        )

    monkeypatch.setattr(mw, "_write_all_steps", fake_steps)

    mw.run_mietverwaltung_write(case.id)

    db.expire_all()
    reloaded = db.get(Case, case.id)
    assert reloaded.status == "written"
    assert reloaded.impower_result["property_id"] == 900
    assert reloaded.impower_result["unit_ids"] == {"1": 5101}

    audits = db.query(AuditLog).filter_by(
        action="mietverwaltung_write_complete", entity_id=case.id
    ).all()
    assert len(audits) == 1
    assert audits[0].details_json["property_id"] == 900
    assert audits[0].details_json["units"] == 1
    assert audits[0].details_json["tenant_contracts"] == 1


# ---------------------------------------------------------------------------
# Preflight-Fail
# ---------------------------------------------------------------------------

def test_run_write_preflight_fail_sets_error_status_and_audits(
    db, mw_workflow, mw_user, monkeypatch
):
    """Unvollstaendiger State → Preflight schlaegt fehl, Orchestrator setzt
    status='error' und loggt `mietverwaltung_write_preflight_failed` mit
    der Liste der fehlenden Felder. `_write_all_steps` darf gar nicht aufgerufen
    werden."""
    # Nur Owner + Units fehlen bewusst → preflight meldet Missing-Felder.
    incomplete_state = {"property": {"number": "X"}}
    case = _mk_case(db, mw_workflow, mw_user, state=incomplete_state)

    called = {"count": 0}

    async def forbidden_steps(*_args, **_kwargs):
        called["count"] += 1

    monkeypatch.setattr(mw, "_write_all_steps", forbidden_steps)

    mw.run_mietverwaltung_write(case.id)

    assert called["count"] == 0, "_write_all_steps darf bei Preflight-Fail nicht laufen"

    db.expire_all()
    reloaded = db.get(Case, case.id)
    assert reloaded.status == "error"
    assert reloaded.impower_result is not None
    errors = reloaded.impower_result["errors"]
    assert len(errors) == 1
    assert errors[0]["step"] == "preflight"
    assert "Pflichtfelder fehlen" in errors[0]["message"]

    audits = db.query(AuditLog).filter_by(
        action="mietverwaltung_write_preflight_failed", entity_id=case.id
    ).all()
    assert len(audits) == 1
    assert "missing" in audits[0].details_json
    assert isinstance(audits[0].details_json["missing"], list)
    assert len(audits[0].details_json["missing"]) >= 3  # Owner + Units + property-Pflichten


# ---------------------------------------------------------------------------
# Impower-Error → Partial
# ---------------------------------------------------------------------------

def test_run_write_impower_error_sets_partial_when_steps_done(
    db, mw_workflow, mw_user, monkeypatch
):
    """Wenn `_write_all_steps` eine ImpowerError wirft, aber vorher schon
    mindestens ein Schritt durchlief, ist der Case `partial` — nicht `error`.
    Damit kann der User per Retry fortsetzen (Idempotenz)."""
    from app.services.impower import ImpowerError

    case = _mk_case(db, mw_workflow, mw_user, state=_full_state())

    async def fail_mid(state, ir):
        ir["contacts"]["owner_id"] = 5001
        ir["steps_completed"].append("owner_contact")
        raise ImpowerError("Property anlegen fehlgeschlagen: validation failed", 400)

    monkeypatch.setattr(mw, "_write_all_steps", fail_mid)

    mw.run_mietverwaltung_write(case.id)

    db.expire_all()
    reloaded = db.get(Case, case.id)
    assert reloaded.status == "partial"
    assert reloaded.impower_result["contacts"]["owner_id"] == 5001
    assert "owner_contact" in reloaded.impower_result["steps_completed"]

    errors = reloaded.impower_result["errors"]
    assert len(errors) == 1
    assert "Property anlegen" in errors[0]["message"]
    # Der step-Label ist der letzte completed step (Fortschritts-Anker fuer UI).
    assert errors[0]["step"] == "owner_contact"

    audits = db.query(AuditLog).filter_by(
        action="mietverwaltung_write_error", entity_id=case.id
    ).all()
    assert len(audits) == 1
    assert "Property anlegen" in audits[0].details_json["error"]


def test_run_write_impower_error_before_any_step_sets_error(
    db, mw_workflow, mw_user, monkeypatch
):
    """Wenn ImpowerError fliegt, bevor ein einziger Schritt durchlief, ist
    `partial` nicht ehrlich — dann ist es `error`."""
    from app.services.impower import ImpowerError

    case = _mk_case(db, mw_workflow, mw_user, state=_full_state())

    async def fail_immediately(state, ir):
        raise ImpowerError("Token ungueltig", 401)

    monkeypatch.setattr(mw, "_write_all_steps", fail_immediately)

    mw.run_mietverwaltung_write(case.id)

    db.expire_all()
    reloaded = db.get(Case, case.id)
    assert reloaded.status == "error"
    assert reloaded.impower_result["steps_completed"] == []
    # Step-Label ist "unknown", weil kein completed-Step vorlag.
    assert reloaded.impower_result["errors"][0]["step"] == "unknown"


# ---------------------------------------------------------------------------
# Unerwartete Exception
# ---------------------------------------------------------------------------

def test_run_write_unexpected_exception_sets_error_and_audits_crashed(
    db, mw_workflow, mw_user, monkeypatch
):
    """Wenn etwas anderes als ImpowerError fliegt (z.B. httpx-Timeout oder
    ein Bug im Pipeline-Code), muss der Orchestrator das als crashed
    taggen — nicht als partial, sonst maskieren wir Bugs."""
    case = _mk_case(db, mw_workflow, mw_user, state=_full_state())

    async def boom(state, ir):
        ir["steps_completed"].append("owner_contact")
        raise RuntimeError("unexpected bug")

    monkeypatch.setattr(mw, "_write_all_steps", boom)

    mw.run_mietverwaltung_write(case.id)

    db.expire_all()
    reloaded = db.get(Case, case.id)
    assert reloaded.status == "error"
    errors = reloaded.impower_result["errors"]
    assert len(errors) == 1
    assert errors[0]["step"] == "orchestrator"
    assert "RuntimeError" in errors[0]["message"]

    audits = db.query(AuditLog).filter_by(
        action="mietverwaltung_write_crashed", entity_id=case.id
    ).all()
    assert len(audits) == 1
    assert "RuntimeError" in audits[0].details_json["error"]


# ---------------------------------------------------------------------------
# Case nicht gefunden
# ---------------------------------------------------------------------------

def test_run_write_unknown_case_id_noops(db, monkeypatch):
    """Wenn die Case-ID nicht existiert (geloescht zwischen Trigger und Task-
    Start), darf der Orchestrator keine Exception werfen — sonst killt das
    den BackgroundTask-Handler."""
    called = {"count": 0}

    async def should_not_run(*_args, **_kwargs):
        called["count"] += 1

    monkeypatch.setattr(mw, "_write_all_steps", should_not_run)

    mw.run_mietverwaltung_write(uuid.uuid4())

    assert called["count"] == 0
    # Keine Audit-Eintraege ausgeloest.
    assert db.query(AuditLog).count() == 0


# ---------------------------------------------------------------------------
# Status-Transition: writing-Flag waehrend des Runs
# ---------------------------------------------------------------------------

def test_run_write_sets_writing_status_before_pipeline(
    db, mw_workflow, mw_user, monkeypatch
):
    """Bevor `_write_all_steps` aufgerufen wird, muss der Case auf
    status='writing' stehen — damit ein parallel laufender Meta-Refresh
    im UI den Spinner zeigt, nicht noch den alten `draft`-Stand."""
    case = _mk_case(db, mw_workflow, mw_user, state=_full_state())
    observed: list[str] = []

    async def observe_status(state, ir):
        # Re-Fetch in separater Session, um den committed Zustand zu sehen.
        from tests.conftest import _TestSessionLocal

        s = _TestSessionLocal()
        try:
            observed.append(s.get(Case, case.id).status)
        finally:
            s.close()

    monkeypatch.setattr(mw, "_write_all_steps", observe_status)

    mw.run_mietverwaltung_write(case.id)

    assert observed == ["writing"], (
        f"Status muss vor Pipeline-Start auf 'writing' sein, war aber {observed!r}"
    )

    # Nach dem Run ist er dann 'written'.
    db.expire_all()
    assert db.get(Case, case.id).status == "written"
