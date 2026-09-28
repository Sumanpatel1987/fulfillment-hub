from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import ActivityType, Actor, ExceptionStatus
from app.models import ActivityLog, FulfillmentException, Order


def get_order(session: Session, order_id: int) -> Order:
    order = session.get(Order, order_id)
    if order is None:
        from app.services.errors import NotFoundError
        raise NotFoundError(f"Order {order_id} was not found.")
    return order


def has_blocking_exception(session: Session, order_id: int) -> bool:
    statement = select(FulfillmentException.id).where(
        FulfillmentException.order_id == order_id,
        FulfillmentException.status == ExceptionStatus.OPEN.value,
        FulfillmentException.blocking.is_(True),
    )
    return session.execute(statement).first() is not None


def log_activity(
    session: Session,
    order_id: int,
    event_type: ActivityType | str,
    actor: Actor | str,
    message: str,
) -> None:
    session.add(
        ActivityLog(
            order_id=order_id,
            event_type=str(event_type),
            actor=str(actor),
            message=message,
        )
    )
