from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import Inventory, InventoryAllocation, Order, OrderItem
from app.services.errors import DomainError, WrongBarcodeError
from app.services.fulfillment_service import confirm_scan, next_pick_item, start_picking

bp = Blueprint("warehouse", __name__, url_prefix="/warehouse")


def _load_order(order_id: int) -> Order | None:
    return db.session.scalar(
        select(Order)
        .options(
            selectinload(Order.items).selectinload(OrderItem.variant),
            selectinload(Order.items)
            .selectinload(OrderItem.allocations)
            .selectinload(InventoryAllocation.inventory)
            .selectinload(Inventory.location),
            selectinload(Order.exceptions),
        )
        .where(Order.id == order_id)
    )


@bp.get("/orders/<int:order_id>/pick")
def pick(order_id: int):
    order = _load_order(order_id)
    if order is None:
        return render_template("404.html"), 404
    return render_template("picking.html", order=order, next_item=next_pick_item(order))


@bp.post("/orders/<int:order_id>/pick/start")
def start(order_id: int):
    try:
        start_picking(db.session, order_id)
        db.session.commit()
        flash("Picking started.", "success")
    except DomainError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("warehouse.pick", order_id=order_id))


@bp.post("/orders/<int:order_id>/pick/scan")
def scan(order_id: int):
    scanned = request.form.get("barcode", "").strip()
    if not scanned:
        flash("Scan or type a SKU/barcode.", "error")
        return redirect(url_for("warehouse.pick", order_id=order_id))

    try:
        confirm_scan(db.session, order_id, scanned)
        db.session.commit()
        flash("Correct item confirmed.", "success")
    except WrongBarcodeError as exc:
        # The service records the rejected attempt. Commit that audit event;
        # no inventory or picked quantity was changed.
        db.session.commit()
        flash(str(exc), "error")
    except DomainError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("warehouse.pick", order_id=order_id))
