"""Celery application configuration for asynchronous proof job execution."""

from __future__ import annotations

from celery import Celery

from vellum_core.config import Settings


settings = Settings.from_env()

celery_app = Celery(
    "vellum-worker",
    broker=settings.celery_broker_url,
    backend=None,
)
celery_app.conf.update(
    task_default_queue=settings.celery_queue,
    task_routes={"worker.process_proof_job": {"queue": settings.celery_queue}},
)
