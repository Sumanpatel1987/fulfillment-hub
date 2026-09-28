from flask import Blueprint, render_template, request

from app.enums import OrderStatus
from app.extensions import db
from app.services.dashboard_service import dashboard_counts, list_orders, risk_level

bp = Blueprint("dashboard", __name__)


@bp.get("/")
def index():
    search = request.args.get("q", "")
    status = request.args.get("status", "")
    priority_only = request.args.get("priority") == "1"
    blocked_only = request.args.get("blocked") == "1"

    orders = list_orders(
        db.session,
        search=search,
        status=status,
        priority_only=priority_only,
        blocked_only=blocked_only,
    )
    counts = dashboard_counts(db.session)
    return render_template(
        "dashboard.html",
        orders=orders,
        counts=counts,
        risk_level=risk_level,
        statuses=[status.value for status in OrderStatus],
        filters={
            "q": search,
            "status": status,
            "priority": priority_only,
            "blocked": blocked_only,
        },
    )
