from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import ActivityType, Actor, ExceptionStatus, ExceptionType, OrderStatus, TransferStatus
from app.models import (
    FulfillmentException,
    Inventory,
    InventoryTransfer,
    InventoryTransferItem,
    Order,
    OrderItem,
    Warehouse,
)
from app.services.common import log_activity
from app.services.errors import NotFoundError, TransferError
from app.services.exception_service import resolve_system_exception
from app.services.inventory_service import (
    allocated_quantity,
    available_inventory_rows,
    get_default_main_pick_location,
    reserve_from_main,
)
from app.utils import utcnow


def requested_transfer_quantity(order: Order, variant_id: int) -> int:
    """Return stock already reserved in requested transfers for this order/SKU."""
    return sum(
        transfer_item.quantity
        for transfer in order.transfers
        if transfer.status == TransferStatus.REQUESTED.value
        for transfer_item in transfer.items
        if transfer_item.variant_id == variant_id
    )


def ensure_transfer_for_shortage(
    session: Session,
    *,
    order: Order,
    order_item: OrderItem,
    quantity: int,
    source_warehouse: Warehouse,
    destination_warehouse: Warehouse,
) -> InventoryTransfer:
    """Ensure a requested transfer covers the desired total shortage for a SKU.

    ``quantity`` is the desired total transfer quantity for the variant across
    the whole order. This makes the operation idempotent and also handles the
    edge case where an order contains more than one line for the same SKU.
    """
    if quantity <= 0:
        raise TransferError("Transfer quantity must be positive.")

    existing_transfer = session.scalar(
        select(InventoryTransfer).where(
            InventoryTransfer.order_id == order.id,
            InventoryTransfer.status == TransferStatus.REQUESTED.value,
            InventoryTransfer.from_warehouse_id == source_warehouse.id,
            InventoryTransfer.to_warehouse_id == destination_warehouse.id,
        )
    )
    transfer = existing_transfer or InventoryTransfer(
        order_id=order.id,
        from_warehouse_id=source_warehouse.id,
        to_warehouse_id=destination_warehouse.id,
        status=TransferStatus.REQUESTED.value,
    )
    if existing_transfer is None:
        session.add(transfer)
        session.flush()

    already = sum(
        transfer_item.quantity
        for transfer_item in transfer.items
        if transfer_item.variant_id == order_item.variant_id
    )
    need = quantity - already
    if need <= 0:
        return transfer

    destination = get_default_main_pick_location(session)
    remaining = need
    for source_inventory in available_inventory_rows(
        session, order_item.variant_id, source_warehouse.id
    ):
        if remaining <= 0:
            break
        amount = min(remaining, source_inventory.available_quantity)
        if amount <= 0:
            continue

        # Reserve overflow stock for this transfer so separate orders cannot
        # promise the same physical units twice.
        source_inventory.quantity_reserved += amount
        transfer.items.append(
            InventoryTransferItem(
                variant_id=order_item.variant_id,
                source_inventory_id=source_inventory.id,
                destination_location_id=destination.id,
                quantity=amount,
            )
        )
        remaining -= amount

    if remaining:
        raise TransferError("Overflow inventory changed before the transfer could be reserved.")

    log_activity(
        session,
        order.id,
        ActivityType.TRANSFER_CREATED,
        Actor.SYSTEM,
        f"Transfer requested for {need} additional unit(s) of {order_item.variant.sku}.",
    )
    return transfer


def complete_transfer(session: Session, transfer_id: int) -> InventoryTransfer:
    transfer = session.get(InventoryTransfer, transfer_id)
    if transfer is None:
        raise NotFoundError(f"Transfer {transfer_id} was not found.")
    if transfer.status != TransferStatus.REQUESTED.value:
        raise TransferError("Only requested transfers can be completed.")

    for transfer_item in transfer.items:
        source = transfer_item.source_inventory
        qty = transfer_item.quantity

        if source.quantity_on_hand < qty or source.quantity_reserved < qty:
            raise TransferError("Reserved overflow stock is no longer available.")

        source.quantity_on_hand -= qty
        source.quantity_reserved -= qty

        destination = session.scalar(
            select(Inventory).where(
                Inventory.variant_id == transfer_item.variant_id,
                Inventory.location_id == transfer_item.destination_location_id,
            )
        )
        if destination is None:
            destination = Inventory(
                variant_id=transfer_item.variant_id,
                location_id=transfer_item.destination_location_id,
                quantity_on_hand=0,
                quantity_reserved=0,
            )
            session.add(destination)
            session.flush()
        destination.quantity_on_hand += qty

    transfer.status = TransferStatus.COMPLETED.value
    transfer.completed_at = utcnow()

    order = transfer.order

    # Newly moved stock can now satisfy the outstanding main-warehouse allocation.
    for item in order.items:
        missing = item.quantity_ordered - allocated_quantity(session, item.id)
        if missing > 0:
            reserve_from_main(session, item, missing)

    # Any inventory blocker that is no longer true must be closed. Resolving
    # STOCK_SHORTAGE here as well prevents an order from staying blocked after
    # later replenishment made a transfer possible.
    for item in order.items:
        if allocated_quantity(session, item.id) >= item.quantity_ordered:
            resolve_system_exception(
                session,
                order.id,
                ExceptionType.TRANSFER_REQUIRED,
                order_item_id=item.id,
            )
            resolve_system_exception(
                session,
                order.id,
                ExceptionType.STOCK_SHORTAGE,
                order_item_id=item.id,
            )

    log_activity(
        session,
        order.id,
        ActivityType.TRANSFER_COMPLETED,
        Actor.WAREHOUSE,
        f"Transfer #{transfer.id} completed and stock moved to the main warehouse.",
    )

    fully_allocated = all(
        allocated_quantity(session, item.id) >= item.quantity_ordered for item in order.items
    )
    blocking_remaining = session.scalar(
        select(FulfillmentException.id).where(
            FulfillmentException.order_id == order.id,
            FulfillmentException.status == ExceptionStatus.OPEN.value,
            FulfillmentException.blocking.is_(True),
        )
    )
    if fully_allocated and blocking_remaining is None and order.status == OrderStatus.NEW.value:
        order.status = OrderStatus.READY_TO_PICK.value

    return transfer
