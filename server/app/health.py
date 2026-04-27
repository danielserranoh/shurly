"""
Phase 4.2 — Health-check endpoints for ECS/ALB.

Two flavors:

- ``GET /api/v1/health`` is the **liveness** probe used by the ALB target group
  and the Docker HEALTHCHECK. It must be cheap, must not touch the database,
  and must return 200 as long as the process can serve HTTP — that's the
  contract ECS uses to decide whether the task is healthy.

- ``GET /api/v1/health/db`` does a one-row SELECT against PostgreSQL. Useful
  for synthetic monitoring (e.g. CloudWatch Synthetics) that wants to detect
  database connectivity issues separately from app process issues. It is NOT
  wired up to the ALB on purpose — we don't want every load-balancer health
  check to consume an RDS connection.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from server.core import get_db

health_router = APIRouter()


@health_router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    responses={200: {"description": "Process is up"}},
)
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get(
    "/health/db",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Database round-trip OK"},
        503: {"description": "Database is unreachable"},
    },
)
def readiness(db: Session = Depends(get_db)) -> dict[str, str]:
    # `SELECT 1` is the canonical zero-cost connectivity probe — no real I/O
    # beyond the round-trip — and it doesn't depend on any application table.
    db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "ok"}
