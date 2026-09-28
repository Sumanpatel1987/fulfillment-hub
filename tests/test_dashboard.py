from sqlalchemy import select

from app.models import Order
from app.services.dashboard_service import dashboard_counts, list_orders, risk_level
from app.utils import utcnow


def by_number(session, number: str) -> Order:
    return session.scalar(select(Order).where(Order.order_number == number))


def test_missed_pickup_surfaces_ahead_of_normal_work(session):
    orders = list_orders(session)
    assert orders

    staged = by_number(session, "XYZ-1007")
    assert staged.ship_by_at > utcnow()
    assert staged.shipment.pickup_due_at < utcnow()
    assert risk_level(staged) == "MISSED_PICKUP"
    assert orders[0].order_number == "XYZ-1007"


def test_ready_to_pick_count_excludes_blocked_orders(session):
    counts = dashboard_counts(session)

    # XYZ-1001 and XYZ-1002 are actionable. XYZ-1005 has READY_TO_PICK
    # status but a blocking damaged-item exception, so it must not inflate this KPI.
    assert counts.ready_to_pick == 2
    assert counts.priority_due >= 1
    assert counts.blocked >= 1
    assert counts.waiting_for_courier >= 1
