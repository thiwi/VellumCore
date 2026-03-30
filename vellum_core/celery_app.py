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
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=settings.celery_task_soft_time_limit_seconds,
    task_time_limit=settings.celery_task_time_limit_seconds,
    worker_max_tasks_per_child=settings.celery_worker_max_tasks_per_child,
)
