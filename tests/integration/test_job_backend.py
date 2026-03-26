"""Tests for Job backend."""

from __future__ import annotations

import asyncio

import pytest

from vellum_core.runtime.defaults import CeleryJobBackend


@pytest.mark.integration
def test_celery_job_backend_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, list[object], str]] = []

    def fake_send_task(*, task_name: str, args: list[object], queue: str) -> None:
        captured.append((task_name, args, queue))

    monkeypatch.setattr("vellum_core.runtime.defaults._send_task", fake_send_task)
    backend = CeleryJobBackend()
    asyncio.run(backend.enqueue("worker.process_proof_job", ["proof-1"], "vellum-queue"))

    assert captured == [("worker.process_proof_job", ["proof-1"], "vellum-queue")]
