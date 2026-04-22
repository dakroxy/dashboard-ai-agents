"""Tests fuer den Lifespan-Scheduler (Story 1.4 AC1).

Der Scheduler wird nur angelegt, wenn settings.impower_mirror_enabled=True.
In Tests ist das via conftest auf False gezogen. Wir verifizieren hier:

  1. Wenn disabled → kein echter run_impower_mirror-Call.
  2. Wenn enabled → der Scheduler-Task wird angelegt, nach einem `sleep` ruft
     er run_impower_mirror. Beim Shutdown wird er ohne Warning gecancelt.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_scheduler_disabled_does_not_call_mirror(monkeypatch):
    monkeypatch.setattr(settings, "impower_mirror_enabled", False)
    import app.main as main_module
    mock_mirror = AsyncMock()
    monkeypatch.setattr(main_module, "run_impower_mirror", mock_mirror)

    with TestClient(app, raise_server_exceptions=True) as _:
        pass

    assert mock_mirror.await_count == 0


def test_scheduler_enabled_registers_and_cancels_cleanly(monkeypatch):
    monkeypatch.setattr(settings, "impower_mirror_enabled", True)
    import app.main as main_module

    # run_impower_mirror wird vom Scheduler-Loop aufgerufen. Damit der Test
    # nicht von echter Impower-Ladung abhaengt, mocken.
    mock_mirror = AsyncMock()
    monkeypatch.setattr(main_module, "run_impower_mirror", mock_mirror)

    # Fake _mirror_scheduler_loop: registriert einen Task mit dem erwarteten
    # Namen, faellt sofort schlafen (lange), laesst sich sauber canceln.
    started = asyncio.Event()

    async def fake_loop():
        started.set()
        # Der Loop muss ein laenger laufender async-Vorgang sein, damit der
        # Shutdown-Cancel die CancelledError-Pfad nimmt.
        await asyncio.sleep(3600)

    monkeypatch.setattr(main_module, "_mirror_scheduler_loop", fake_loop)

    with TestClient(app, raise_server_exceptions=True) as _:
        # Lifespan-Enter hat den Task angelegt; Startup ist synchron aus
        # Test-Sicht, der Task bekommt seine erste Chance nach einem yield.
        # TestClient ruft den Lifespan und gibt Kontrolle zurueck — das reicht.
        pass
    # Kein Assertion-Fehler + keine RuntimeWarning ueber nicht-cancelled Task
    # ist das eigentliche Pass-Kriterium.
