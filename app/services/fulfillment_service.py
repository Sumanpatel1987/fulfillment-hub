from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.enums import (
    ActivityType,
    Actor,
    ExceptionSource,
    ExceptionType,
    LocationType,
    OrderStatus,
)
from app.models import (
    Courier,
    InventoryAllocation,
    Order,
    OrderItem,
    Shipment,
    WarehouseLocation,
)
from app.services.common import get_order, has_blocking_exception, log_activity
from app.services.errors import (
    BlockingExceptionError,
    InvalidTransitionError,
    NotFoundError,
    WrongBarcodeError,
)
from app.services.exception_service import (
    create_exception,
    find_open_system_exception,
    resolve_system_exception,
)
from app.services.inventory_service import (
    allocated_quantity,
    get_overflow_warehouse,
    get_shipping_warehouse,
    reserve_from_main,
    total_available,
)
from app.utils import utcnow


def _open_blocker_for_item(
    session: Session,
    order_id: int,
    item_id: int,
    exception_type: ExceptionType,
    message: str,
) -> None:
    existing = find_open_system_exception(session, order_id, exception_type, item_id)
    if existing is None:
        create_exception(
            session,
            order_id,
            exception_type,
            message,
            blocking=True,
            source=ExceptionSource.SYSTEM,
            order_item_id=item_id,
            actor=Actor.SYSTEM,
        )


def _order_fully_allocated(session: Session, order: Order) -> bool:
    return all(allocated_quantity(session, item.id) >= item.quantity_ordered for item in order.items)


def prepare_order(session: Session, order_id: int) -> Order:
    order = get_order(session, order_id)
    if order.status != OrderStatus.NEW.value:
        raise InvalidTransitionError("Only NEW orders can be prepared.")

    main = get_shipping_warehouse(session)
    overflow = get_overflow_warehouse(session)

    # Imported lazily because transfer_service depends on inventory helpers used here.
    from app.services.transfer_service import (
        ensure_transfer_for_shortage,
        requested_transfer_quantity,
    )

    # Pass 1: give every order line a chance to reserve stock already present
    # in the shipping warehouse before deciding how much overflow stock is needed.
    # This avoids over-requesting transfers when the same SKU appears on more
    # than one order line.
    for item in order.items:
        missing = item.quantity_ordered - allocated_quantity(session, item.id)
        if missing > 0:
            reserve_from_main(session, item, missing)

    shortages_by_variant: dict[int, list[tuple[OrderItem, int]]] = {}
    for item in order.items:
        missing = item.quantity_ordered - allocated_quantity(session, item.id)
        if missing <= 0:
            resolve_system_exception(
                session,
                order.id,
                ExceptionType.STOCK_SHORTAGE,
                order_item_id=item.id,
            )
            resolve_system_exception(
                session,
                order.id,
                ExceptionType.TRANSFER_REQUIRED,
                order_item_id=item.id,
            )
            continue
        shortages_by_variant.setdefault(item.variant_id, []).append((item, missing))

    # Pass 2: make one transfer decision per SKU, then attach blockers to the
    # individual order lines that are waiting for that stock.
    for variant_id, shortage_lines in shortages_by_variant.items():
        total_missing = sum(missing for _, missing in shortage_lines)
        representative = shortage_lines[0][0]

        transfer_already_reserved = requested_transfer_quantity(order, variant_id)
        overflow_available = (
            total_available(session, variant_id, overflow.id) if overflow is not None else 0
        )
        total_overflow_cover = transfer_already_reserved + overflow_available

        if overflow is not None and total_overflow_cover >= total_missing:
            for item, _missing in shortage_lines:
                # A previous true shortage may become serviceable after
                # replenishment. Replace that stale blocker with the more
                # accurate transfer-required state.
                resolve_system_exception(
                    session,
                    order.id,
                    ExceptionType.STOCK_SHORTAGE,
                    order_item_id=item.id,
                )

            ensure_transfer_for_shortage(
                session,
                order=order,
                order_item=representative,
                quantity=total_missing,
                source_warehouse=overflow,
                destination_warehouse=main,
            )

            for item, missing in shortage_lines:
                _open_blocker_for_item(
                    session,
                    order.id,
                    item.id,
                    ExceptionType.TRANSFER_REQUIRED,
                    f"{missing} unit(s) of {item.variant.sku} must be moved from overflow to main.",
                )
        else:
            for item, missing in shortage_lines:
                _open_blocker_for_item(
                    session,
                    order.id,
                    item.id,
                    ExceptionType.STOCK_SHORTAGE,
                    f"Insufficient stock for {item.variant.sku}; {missing} unit(s) are still required.",
                )

    log_activity(
        session,
        order.id,
        ActivityType.ORDER_PREPARED,
        Actor.OFFICE,
        "Order preparation and inventory allocation completed.",
    )

    if _order_fully_allocated(session, order) and not has_blocking_exception(session, order.id):
        order.status = OrderStatus.READY_TO_PICK.value

    return order


def start_picking(session: Session, order_id: int) -> Order:
    order = get_order(session, order_id)
    if order.status != OrderStatus.READY_TO_PICK.value:
        raise InvalidTransitionError("Order must be READY_TO_PICK before picking starts.")
    if has_blocking_exception(session, order.id):
        raise BlockingExceptionError("Resolve blocking problems before starting to pick.")

    order.status = OrderStatus.PICKING.value
    log_activity(
        session,
        order.id,
        ActivityType.PICKING_STARTED,
        Actor.WAREHOUSE,
        "Picking started.",
    )
    return order


def next_pick_item(order: Order) -> OrderItem | None:
    for item in order.items:
        if item.quantity_picked < item.quantity_ordered:
            return item
    return None


def confirm_scan(session: Session, order_id: int, barcode_or_sku: str) -> OrderItem:
    order = get_order(session, order_id)
    if order.status != OrderStatus.PICKING.value:
        raise InvalidTransitionError("Order is not currently being picked.")
    if has_blocking_exception(session, order.id):
        raise BlockingExceptionError("Resolve blocking problems before continuing picking.")

    item = next_pick_item(order)
    if item is None:
        raise InvalidTransitionError("All items are already picked.")

    scanned = barcode_or_sku.strip()
    expected = item.variant
    if scanned not in {expected.barcode, expected.sku}:
        log_activity(
            session,
            order.id,
            ActivityType.SCAN_REJECTED,
            Actor.WAREHOUSE,
            f"Rejected scan '{scanned}'. Expected {expected.sku} ({expected.variant_name}).",
        )
        raise WrongBarcodeError(
            f"Wrong item. Expected {expected.sku} — {expected.variant_name}."
        )

    allocation = session.scalar(
        select(InventoryAllocation)
        .options(selectinload(InventoryAllocation.inventory))
        .where(
            InventoryAllocation.order_item_id == item.id,
            InventoryAllocation.quantity_picked < InventoryAllocation.quantity_reserved,
        )
        .order_by(InventoryAllocation.id)
    )
    if allocation is None:
        raise InvalidTransitionError("No reserved inventory remains for this item.")

    inventory = allocation.inventory
    if inventory.quantity_on_hand <= 0 or inventory.quantity_reserved <= 0:
        raise InvalidTransitionError("Reserved inventory is no longer available.")

    allocation.quantity_picked += 1
    item.quantity_picked += 1
    inventory.quantity_on_hand -= 1
    inventory.quantity_reserved -= 1

    log_activity(
        session,
        order.id,
        ActivityType.SCAN_ACCEPTED,
        Actor.WAREHOUSE,
        f"Confirmed {expected.sku}; {item.quantity_picked}/{item.quantity_ordered} picked.",
    )
    return item


def pack_order(session: Session, order_id: int) -> Order:
    order = get_order(session, order_id)
    if order.status != OrderStatus.PICKING.value:
        raise InvalidTransitionError("Only an order being picked can be packed.")
    if has_blocking_exception(session, order.id):
        raise BlockingExceptionError("Resolve blocking problems before packing.")
    if any(item.quantity_picked != item.quantity_ordered for item in order.items):
        raise InvalidTransitionError("Every ordered unit must be verified before packing.")

    order.status = OrderStatus.PACKED.value
    log_activity(session, order.id, ActivityType.PACKED, Actor.WAREHOUSE, "Order packed.")
    return order


def stage_order(
    session: Session,
    order_id: int,
    courier_id: int,
    staging_location_id: int,
    pickup_due_at: datetime,
) -> Order:
    order = get_order(session, order_id)
    if order.status != OrderStatus.PACKED.value:
        raise InvalidTransitionError("Only PACKED orders can be staged.")
    if has_blocking_exception(session, order.id):
        raise BlockingExceptionError("Resolve blocking problems before staging.")
    if pickup_due_at <= utcnow():
        raise InvalidTransitionError("Expected courier pickup must be in the future.")

    courier = session.get(Courier, courier_id)
    if courier is None or not courier.active:
        raise NotFoundError("Selected courier is unavailable.")

    location = session.get(WarehouseLocation, staging_location_id)
    if location is None or location.location_type != LocationType.STAGING.value or not location.active:
        raise InvalidTransitionError("Select an active staging location.")

    main = get_shipping_warehouse(session)
    if location.warehouse_id != main.id:
        raise InvalidTransitionError("Orders must be staged in the main warehouse.")

    shipment = order.shipment
    if shipment is None:
        shipment = Shipment(
            order_id=order.id,
            courier_id=courier.id,
            staging_location_id=location.id,
            pickup_due_at=pickup_due_at,
        )
        order.shipment = shipment
        session.add(shipment)
    else:
        shipment.courier_id = courier.id
        shipment.staging_location_id = location.id
        shipment.pickup_due_at = pickup_due_at

    order.status = OrderStatus.STAGED.value
    log_activity(
        session,
        order.id,
        ActivityType.STAGED,
        Actor.WAREHOUSE,
        f"Order staged at {location.code} for {courier.name} {courier.service_name}.",
    )
    return order


def ship_order(session: Session, order_id: int) -> Order:
    order = get_order(session, order_id)
    if order.status != OrderStatus.STAGED.value:
        raise InvalidTransitionError("Only STAGED orders can be marked shipped.")
    if has_blocking_exception(session, order.id):
        raise BlockingExceptionError("Resolve blocking problems before shipment.")
    if order.shipment is None:
        raise InvalidTransitionError("Shipment details are missing.")

    order.shipment.picked_up_at = utcnow()
    order.status = OrderStatus.SHIPPED.value
    log_activity(
        session,
        order.id,
        ActivityType.SHIPPED,
        Actor.WAREHOUSE,
        f"Courier pickup confirmed for {order.shipment.courier.name}.",
    )
    return order
