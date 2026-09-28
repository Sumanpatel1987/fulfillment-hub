from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.enums import ActivityType, Actor, LocationType
from app.models import (
    Inventory,
    InventoryAllocation,
    OrderItem,
    Warehouse,
    WarehouseLocation,
)
from app.services.common import log_activity
from app.services.errors import InsufficientInventoryError


def get_shipping_warehouse(session: Session) -> Warehouse:
    warehouse = session.scalar(select(Warehouse).where(Warehouse.ships_orders.is_(True)))
    if warehouse is None:
        raise InsufficientInventoryError("No shipping warehouse is configured.")
    return warehouse


def get_overflow_warehouse(session: Session) -> Warehouse | None:
    return session.scalar(
        select(Warehouse).where(Warehouse.ships_orders.is_(False)).order_by(Warehouse.id)
    )


def allocated_quantity(session: Session, order_item_id: int) -> int:
    value = session.scalar(
        select(func.coalesce(func.sum(InventoryAllocation.quantity_reserved), 0)).where(
            InventoryAllocation.order_item_id == order_item_id
        )
    )
    return int(value or 0)


def available_inventory_rows(
    session: Session,
    variant_id: int,
    warehouse_id: int,
) -> list[Inventory]:
    stmt = (
        select(Inventory)
        .join(Inventory.location)
        .options(selectinload(Inventory.location))
        .where(
            Inventory.variant_id == variant_id,
            WarehouseLocation.warehouse_id == warehouse_id,
            WarehouseLocation.location_type == LocationType.PICK.value,
            WarehouseLocation.active.is_(True),
            Inventory.quantity_on_hand > Inventory.quantity_reserved,
        )
        .order_by(
            WarehouseLocation.pick_sequence.is_(None),
            WarehouseLocation.pick_sequence,
            WarehouseLocation.code,
        )
    )
    return list(session.scalars(stmt).all())


def total_available(
    session: Session,
    variant_id: int,
    warehouse_id: int,
) -> int:
    rows = available_inventory_rows(session, variant_id, warehouse_id)
    return sum(row.available_quantity for row in rows)


def reserve_from_main(
    session: Session,
    order_item: OrderItem,
    quantity_needed: int,
) -> int:
    if quantity_needed <= 0:
        return 0

    main = get_shipping_warehouse(session)
    remaining = quantity_needed
    reserved = 0

    for inventory in available_inventory_rows(session, order_item.variant_id, main.id):
        if remaining <= 0:
            break
        amount = min(remaining, inventory.available_quantity)
        if amount <= 0:
            continue

        inventory.quantity_reserved += amount
        allocation = InventoryAllocation(
            order_item_id=order_item.id,
            inventory_id=inventory.id,
            quantity_reserved=amount,
            quantity_picked=0,
        )
        session.add(allocation)
        remaining -= amount
        reserved += amount

    if reserved:
        log_activity(
            session,
            order_item.order_id,
            ActivityType.INVENTORY_RESERVED,
            Actor.SYSTEM,
            f"Reserved {reserved} unit(s) of {order_item.variant.sku} in the main warehouse.",
        )
    return reserved


def get_default_main_pick_location(session: Session) -> WarehouseLocation:
    main = get_shipping_warehouse(session)
    location = session.scalar(
        select(WarehouseLocation)
        .where(
            WarehouseLocation.warehouse_id == main.id,
            WarehouseLocation.location_type == LocationType.PICK.value,
            WarehouseLocation.active.is_(True),
        )
        .order_by(
            WarehouseLocation.pick_sequence.is_(None),
            WarehouseLocation.pick_sequence,
            WarehouseLocation.code,
        )
    )
    if location is None:
        raise InsufficientInventoryError("No main-warehouse picking location is configured.")
    return location
