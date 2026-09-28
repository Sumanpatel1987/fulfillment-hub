from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, selectinload

from app.enums import ExceptionStatus, OrderStatus
from app.models import FulfillmentException, Order
from app.utils import utcnow


@dataclass(frozen=True)
class DashboardCounts:
    priority_due: int
    ready_to_pick: int
    blocked: int
    waiting_for_courier: int


def risk_level(order: Order) -> str:
    """Return the highest-priority operational risk for an order.

    Courier pickup risk is evaluated before the general ship-by deadline so a
    staged parcel with a missed collection is explicitly visible even when its
    customer ship-by deadline has not yet passed.
    """
    now = utcnow()

    if (
        order.status == OrderStatus.STAGED.value
        and order.shipment is not None
        and order.shipment.pickup_due_at < now
    ):
        return "MISSED_PICKUP"

    if order.status != OrderStatus.SHIPPED.value and order.ship_by_at < now:
        return "OVERDUE"

    if (
        order.priority
        and order.status != OrderStatus.SHIPPED.value
        and order.ship_by_at <= now + timedelta(hours=2)
    ):
        return "DUE_SOON"

    return "NORMAL"


def _open_blocker_exists():
    return exists().where(
        and_(
            FulfillmentException.order_id == Order.id,
            FulfillmentException.status == ExceptionStatus.OPEN.value,
            FulfillmentException.blocking.is_(True),
        )
    )


def list_orders(
    session: Session,
    *,
    search: str = "",
    status: str = "",
    priority_only: bool = False,
    blocked_only: bool = False,
) -> list[Order]:
    stmt = select(Order).options(
        selectinload(Order.exceptions),
        selectinload(Order.shipment),
    )

    if search.strip():
        needle = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Order.order_number.ilike(needle),
                Order.customer_name.ilike(needle),
                Order.channel.ilike(needle),
            )
        )
    if status:
        stmt = stmt.where(Order.status == status)
    if priority_only:
        stmt = stmt.where(Order.priority.is_(True))
    if blocked_only:
        stmt = stmt.where(_open_blocker_exists())

    orders = list(session.scalars(stmt).unique().all())

    def sort_key(order: Order):
        risk = risk_level(order)
        risk_rank = {
            "MISSED_PICKUP": 0,
            "OVERDUE": 1,
            "DUE_SOON": 2,
            "NORMAL": 3,
        }[risk]
        priority_rank = 0 if order.priority else 1
        return (risk_rank, priority_rank, order.ship_by_at, order.created_at)

    return sorted(orders, key=sort_key)


def dashboard_counts(session: Session) -> DashboardCounts:
    now = utcnow()
    due_soon = now + timedelta(hours=24)

    priority_due = len(
        list(
            session.scalars(
                select(Order.id).where(
                    Order.priority.is_(True),
                    Order.status != OrderStatus.SHIPPED.value,
                    Order.ship_by_at <= due_soon,
                )
            )
        )
    )

    # "Ready to pick" should mean actionable work, not merely an order whose
    # status happens to be READY_TO_PICK while a blocking exception is open.
    ready = len(
        list(
            session.scalars(
                select(Order.id).where(
                    Order.status == OrderStatus.READY_TO_PICK.value,
                    ~_open_blocker_exists(),
                )
            )
        )
    )

    blocked = len(
        list(
            session.scalars(
                select(FulfillmentException.order_id)
                .where(
                    FulfillmentException.status == ExceptionStatus.OPEN.value,
                    FulfillmentException.blocking.is_(True),
                )
                .distinct()
            )
        )
    )

    staged = len(
        list(
            session.scalars(
                select(Order.id).where(Order.status == OrderStatus.STAGED.value)
            )
        )
    )

    return DashboardCounts(
        priority_due=priority_due,
        ready_to_pick=ready,
        blocked=blocked,
        waiting_for_courier=staged,
    )
