"""Teacher notification endpoints (/api/v1/notifications)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

import db_models as m
from api_schemas import UtcDateTime
from auth import require_teacher
from database import get_db

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class NotificationRead(BaseModel):
    id: int
    kind: str
    title: str
    body: str
    exam_id: int | None
    link_tab: str | None
    count: int
    created_at: UtcDateTime
    read: bool


class NotificationList(BaseModel):
    unread: int
    items: list[NotificationRead]


def _view(n: m.Notification) -> NotificationRead:
    return NotificationRead(
        id=n.id, kind=n.kind, title=n.title, body=n.body, exam_id=n.exam_id,
        link_tab=n.link_tab, count=n.count, created_at=n.created_at, read=n.read_at is not None,
    )


@router.get("", response_model=NotificationList)
def list_notifications(
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
    teacher: m.Teacher = Depends(require_teacher),
) -> NotificationList:
    q = db.query(m.Notification).filter(m.Notification.teacher_id == teacher.id)
    unread = q.filter(m.Notification.read_at.is_(None)).count()
    rows = q.order_by(m.Notification.created_at.desc(), m.Notification.id.desc()).limit(limit).all()
    return NotificationList(unread=unread, items=[_view(n) for n in rows])


@router.post("/read-all", status_code=204)
def read_all(db: Session = Depends(get_db), teacher: m.Teacher = Depends(require_teacher)) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.query(m.Notification).filter(
        m.Notification.teacher_id == teacher.id, m.Notification.read_at.is_(None)
    ).update({m.Notification.read_at: now})
    db.commit()


@router.post("/{notification_id}/read", status_code=204)
def read_one(
    notification_id: int,
    db: Session = Depends(get_db),
    teacher: m.Teacher = Depends(require_teacher),
) -> None:
    n = db.get(m.Notification, notification_id)
    if not n or n.teacher_id != teacher.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    if n.read_at is None:
        n.read_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
