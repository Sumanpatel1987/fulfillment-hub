from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.enums import Actor, ExceptionType, LocationType
from app.extensions import db
from app.models import (
    Courier,
    Inventory,
    InventoryAllocation,
    Order,
    OrderItem,
    Shipment,
    WarehouseLocation,
)
from app.services.dashboard_service import risk_level
from app.services.errors import DomainError
from app.services.exception_service import create_exception, resolve_exception
from app.services.fulfillment_service import pack_order, prepare_order, ship_order, stage_order
from app.utils import local_naive_to_utc

bp = Blueprint("orders", __name__, url_prefix="/orders")


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
            selectinload(Order.activity_logs),
            selectinload(Order.shipment).selectinload(Shipment.courier),
            selectinload(Order.shipment).selectinload(Shipment.staging_location),
            selectinload(Order.transfers),
        )
        .where(Order.id == order_id)
    )


@bp.get("/<int:order_id>")
def detail(order_id: int):
    order = _load_order(order_id)
    if order is None:
        return render_template("404.html"), 404

    couriers = list(db.session.scalars(select(Courier).where(Courier.active.is_(True))).all())
    staging_locations = list(
        db.session.scalars(
            select(WarehouseLocation)
            .where(
                WarehouseLocation.location_type == LocationType.STAGING.value,
                WarehouseLocation.active.is_(True),
            )
            .order_by(WarehouseLocation.code)
        ).all()
    )
    return render_template(
        "order_detail.html",
        order=order,
        couriers=couriers,
        staging_locations=staging_locations,
        risk=risk_level(order),
        exception_types=[
            ExceptionType.STOCK_MISSING.value,
            ExceptionType.DAMAGED_ITEM.value,
            ExceptionType.WRONG_ITEM.value,
            ExceptionType.COURIER_ISSUE.value,
            ExceptionType.OTHER.value,
        ],
    )


def _run_and_redirect(order_id: int, fn, success_message: str):
    try:
        fn()
        db.session.commit()
        flash(success_message, "success")
    except (DomainError, ValueError, KeyError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("orders.detail", order_id=order_id))


@bp.post("/<int:order_id>/prepare")
def prepare(order_id: int):
    return _run_and_redirect(
        order_id,
        lambda: prepare_order(db.session, order_id),
        "Order prepared. Inventory allocation is up to date.",
    )


@bp.post("/<int:order_id>/pack")
def pack(order_id: int):
    return _run_and_redirect(
        order_id,
        lambda: pack_order(db.session, order_id),
        "Order packed.",
    )


@bp.post("/<int:order_id>/stage")
def stage(order_id: int):
    def action():
        courier_id = int(request.form["courier_id"])
        staging_location_id = int(request.form["staging_location_id"])
        pickup_local = datetime.fromisoformat(request.form["pickup_due_at"])
        pickup_due_at = local_naive_to_utc(
            pickup_local, current_app.config["WAREHOUSE_TIMEZONE"]
        )
        stage_order(
            db.session,
            order_id,
            courier_id=courier_id,
            staging_location_id=staging_location_id,
            pickup_due_at=pickup_due_at,
        )

    return _run_and_redirect(order_id, action, "Order staged for courier pickup.")


@bp.post("/<int:order_id>/ship")
def ship(order_id: int):
    return _run_and_redirect(
        order_id,
        lambda: ship_order(db.session, order_id),
        "Courier pickup confirmed. Order shipped.",
    )


@bp.post("/<int:order_id>/exceptions")
def add_exception(order_id: int):
    def action():
        message = request.form.get("message", "").strip()
        if not message:
            raise DomainError("Describe the problem before saving it.")
        create_exception(
            db.session,
            order_id,
            request.form.get("exception_type", ExceptionType.OTHER.value),
            message,
            blocking=request.form.get("blocking") == "1",
            actor=Actor.OFFICE,
        )

    return _run_and_redirect(order_id, action, "Problem recorded.")


@bp.post("/<int:order_id>/exceptions/<int:exception_id>/resolve")
def resolve(order_id: int, exception_id: int):
    return _run_and_redirect(
        order_id,
        lambda: resolve_exception(
            db.session,
            order_id,
            exception_id,
            actor=Actor.OFFICE,
            note=request.form.get("note"),
        ),
        "Problem resolved.",
    )
