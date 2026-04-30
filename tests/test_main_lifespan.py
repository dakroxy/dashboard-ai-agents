"""Lifespan-Wiring Tests fuer Story 4.3 (AC1, AC8).

Verifiziert:
- bei settings.facilioo_mirror_enabled=True ruft der Lifespan
  start_facilioo_poller() auf und der Task laeuft.
- bei settings.facilioo_mirror_enabled=False wird der Poller NICHT gestartet.
- nach dem Lifespan-Shutdown ist der Poller-Task wieder weg.

Hinweis: settings.facilioo_mirror_enabled ist im Test-Setup (conftest.py) per
Default `False`. Wir patchen ihn pro Test auf True bzw. lassen False.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app


@pytest.fixture
def lifespan_spy(monkeypatch):
    """Spy auf start_facilioo_poller / stop_facilioo_poller im Lifespan-Modul."""
    state = {"start_calls": 0, "stop_calls": 0}

    async def fake_start():
        state["start_calls"] += 1

    async def fake_stop():
        state["stop_calls"] += 1

    monkeypatch.setattr(main_module, "start_facilioo_poller", fake_start)
    monkeypatch.setattr(main_module, "stop_facilioo_poller", fake_stop)
    return state


def test_lifespan_starts_facilioo_poller_when_enabled(lifespan_spy, monkeypatch):
    """AC1+AC8: facilioo_mirror_enabled=True → Poller wird via Lifespan
    gestartet UND beim Shutdown wieder gestoppt."""
    monkeypatch.setattr(main_module.settings, "facilioo_mirror_enabled", True)

    with TestClient(app):
        # Lifespan-Enter ist hier durch — Mock haette aufgerufen sein muessen
        assert lifespan_spy["start_calls"] == 1
    # Lifespan-Exit (Shutdown) ist hier durch
    assert lifespan_spy["stop_calls"] == 1


def test_lifespan_skips_facilioo_poller_when_disabled(lifespan_spy, monkeypatch):
    """AC1: facilioo_mirror_enabled=False → start_facilioo_poller wird NICHT
    aufgerufen. stop_facilioo_poller wird trotzdem im Shutdown aufgerufen
    (idempotent: returnt fruh wenn _poller_task None)."""
    monkeypatch.setattr(main_module.settings, "facilioo_mirror_enabled", False)

    with TestClient(app):
        assert lifespan_spy["start_calls"] == 0
    # stop wird trotzdem im finally-Block aufgerufen — idempotent.
    assert lifespan_spy["stop_calls"] == 1


@pytest.mark.asyncio
async def test_real_start_poller_creates_named_task(monkeypatch):
    """AC8 expliziter Wortlaut: Task-Name 'facilioo_ticket_mirror_poller' ist
    in asyncio.all_tasks() zu finden, sobald start_poller() gelaufen ist.
    Nach stop_poller() wieder weg."""
    from app.services import facilioo_mirror

    # Lange poll_interval, damit der Loop nicht durchspielt
    monkeypatch.setattr(facilioo_mirror.settings, "facilioo_poll_interval_seconds", 999.0)
    facilioo_mirror._poller_task = None

    try:
        await facilioo_mirror.start_poller()

        task_names = {t.get_name() for t in asyncio.all_tasks()}
        assert "facilioo_ticket_mirror_poller" in task_names
    finally:
        await facilioo_mirror.stop_poller()

    # Nach stop sollte der Task gegen None gesetzt sein
    assert facilioo_mirror._poller_task is None
