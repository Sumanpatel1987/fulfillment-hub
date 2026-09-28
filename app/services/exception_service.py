from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import ActivityType, Actor, ExceptionSource, ExceptionStatus, ExceptionType
from app.models import FulfillmentException
from app.services.common import get_order, log_activity
from app.services.errors import NotFoundError
from app.utils import utcnow


def create_exception(
    session: Session,
    order_id: int,
    exception_type: ExceptionType | str,
    message: str,
    *,
    blocking: bool = True,
    source: ExceptionSource | str = ExceptionSource.USER,
    order_item_id: int | None = None,
    actor: Actor | str = Actor.OFFICE,
) -> FulfillmentException:
    get_order(session, order_id)
    exc = FulfillmentException(
        order_id=order_id,
        order_item_id=order_item_id,
        exception_type=str(exception_type),
        source=str(source),
        message=message.strip(),
        blocking=blocking,
        status=ExceptionStatus.OPEN.value,
    )
    session.add(exc)
    session.flush()
    log_activity(
        session,
        order_id,
        ActivityType.EXCEPTION_CREATED,
        actor,
        f"Exception opened: {exc.exception_type} — {exc.message}",
    )
    return exc


def find_open_system_exception(
    session: Session,
    order_id: int,
    exception_type: ExceptionType | str,
    order_item_id: int | None = None,
) -> FulfillmentException | None:
    stmt = select(FulfillmentException).where(
        FulfillmentException.order_id == order_id,
        FulfillmentException.exception_type == str(exception_type),
        FulfillmentException.status == ExceptionStatus.OPEN.value,
        FulfillmentException.source == ExceptionSource.SYSTEM.value,
    )
    if order_item_id is not None:
        stmt = stmt.where(FulfillmentException.order_item_id == order_item_id)
    return session.scalar(stmt.order_by(FulfillmentException.id.desc()))


def resolve_system_exception(
    session: Session,
    order_id: int,
    exception_type: ExceptionType | str,
    *,
    order_item_id: int | None = None,
    note: str | None = None,
) -> FulfillmentException | None:
    """Resolve one open system-created exception, if present.

    Centralizing this keeps automatic exception lifecycle behavior consistent
    between order preparation and transfer completion.
    """
    exc = find_open_system_exception(session, order_id, exception_type, order_item_id)
    if exc is None:
        return None

    exc.status = ExceptionStatus.RESOLVED.value
    exc.resolved_at = utcnow()
    suffix = f" — {note.strip()}" if note and note.strip() else ""
    log_activity(
        session,
        order_id,
        ActivityType.EXCEPTION_RESOLVED,
        Actor.SYSTEM,
        f"System resolved {exc.exception_type}{suffix}",
    )
    return exc


def resolve_exception(
    session: Session,
    order_id: int,
    exception_id: int,
    *,
    actor: Actor | str = Actor.OFFICE,
    note: str | None = None,
) -> FulfillmentException:
    exc = session.get(FulfillmentException, exception_id)
    if exc is None or exc.order_id != order_id:
        # Treat a mismatched order/exception pair as not found so one order URL
        # cannot resolve another order's exception.
        raise NotFoundError(f"Exception {exception_id} was not found for order {order_id}.")
    if exc.status == ExceptionStatus.RESOLVED.value:
        return exc

    exc.status = ExceptionStatus.RESOLVED.value
    exc.resolved_at = utcnow()
    suffix = f" — {note.strip()}" if note and note.strip() else ""
    log_activity(
        session,
        exc.order_id,
        ActivityType.EXCEPTION_RESOLVED,
        actor,
        f"Exception resolved: {exc.exception_type}{suffix}",
    )
    return exc
