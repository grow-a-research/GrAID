"""Teacher notifications: creation helpers (the HTTP routes live in
routers/notifications_api.py).

Notifications are in-app. Email can be layered on top later by sending from
`notify()`; nothing else needs to change.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

import db_models as m


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def notify(
    db: Session,
    exam: m.Exam,
    kind: str,
    title: str,
    body: str = "",
    link_tab: str | None = None,
) -> m.Notification | None:
    """Add a notification for the teacher who owns this exam's class.

    Classes that predate accounts have no teacher; nothing is created for them.
    """
    course = exam.course_class
    teacher_id = course.teacher_id if course else None
    if teacher_id is None:
        return None
    row = m.Notification(
        teacher_id=teacher_id, kind=kind, title=title, body=body,
        exam_id=exam.id, link_tab=link_tab, created_at=_now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def notify_student_submitted(db: Session, exam: m.Exam, student_name: str, late: bool) -> None:
    """A student turned in their paper.

    Submissions to the same exam are folded into one unread notification
    ("5 new submissions") so a whole class submitting doesn't bury the bell.
    """
    course = exam.course_class
    teacher_id = course.teacher_id if course else None
    if teacher_id is None:
        return
    latest = f"Latest: {student_name}{' (late)' if late else ''}"
    row = (
        db.query(m.Notification)
        .filter(
            m.Notification.teacher_id == teacher_id,
            m.Notification.kind == "submitted",
            m.Notification.exam_id == exam.id,
            m.Notification.read_at.is_(None),
        )
        .order_by(m.Notification.id.desc())
        .first()
    )
    if row:
        row.count += 1
        row.title = f"{row.count} new submissions — {exam.title}"
        row.body = latest
        row.created_at = _now()
        db.commit()
        return
    notify(db, exam, "submitted", f"New submission — {exam.title}", latest, link_tab="submissions")
