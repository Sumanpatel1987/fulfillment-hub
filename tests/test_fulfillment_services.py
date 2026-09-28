from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.enums import (
    ActivityType,
    ExceptionStatus,
    ExceptionType,
    LocationType,
    OrderStatus,
)
from app.models import (
    ActivityLog,
    Courier,
    FulfillmentException,
    Inventory,
    InventoryTransfer,
    Order,
    OrderItem,
    ProductVariant,
    Warehouse,
    WarehouseLocation,
)
from app.services.errors import (
    BlockingExceptionError,
    InvalidTransitionError,
    NotFoundError,
    WrongBarcodeError,
)
from app.services.exception_service import create_exception, resolve_exception
from app.services.fulfillment_service import (
    confirm_scan,
    pack_order,
    prepare_order,
    stage_order,
    start_picking,
)
from app.services.transfer_service import complete_transfer
from app.utils import utcnow


def by_number(session, number: str) -> Order:
    return session.scalar(select(Order).where(Order.order_number == number))


def test_seed_contains_intentional_operational_scenarios(session):
    assert by_number(session, "XYZ-1002").status == OrderStatus.READY_TO_PICK.value
    assert by_number(session, "XYZ-1003").status == OrderStatus.NEW.value
    assert by_number(session, "XYZ-1006").status == OrderStatus.PACKED.value
    assert by_number(session, "XYZ-1007").status == OrderStatus.STAGED.value
    assert by_number(session, "XYZ-1008").status == OrderStatus.SHIPPED.value


def test_wrong_variant_does_not_change_inventory_or_pick_count(session):
    order = by_number(session, "XYZ-1002")
    start_picking(session, order.id)

    item = order.items[0]
    allocation = item.allocations[0]
    inventory = session.get(Inventory, allocation.inventory_id)
    before = (inventory.quantity_on_hand, inventory.quantity_reserved, item.quantity_picked)

    with pytest.raises(WrongBarcodeError):
        confirm_scan(session, order.id, "TSH-BLU-L")

    after = (inventory.quantity_on_hand, inventory.quantity_reserved, item.quantity_picked)
    assert after == before

    rejected = session.scalar(
        select(ActivityLog).where(
            ActivityLog.order_id == order.id,
            ActivityLog.event_type == ActivityType.SCAN_REJECTED.value,
        )
    )
    assert rejected is not None


def test_correct_scan_consumes_one_reserved_unit(session):
    order = by_number(session, "XYZ-1002")
    start_picking(session, order.id)

    item = order.items[0]
    allocation = item.allocations[0]
    inventory = session.get(Inventory, allocation.inventory_id)
    on_hand_before = inventory.quantity_on_hand
    reserved_before = inventory.quantity_reserved

    confirm_scan(session, order.id, item.variant.barcode)

    assert item.quantity_picked == 1
    assert allocation.quantity_picked == 1
    assert inventory.quantity_on_hand == on_hand_before - 1
    assert inventory.quantity_reserved == reserved_before - 1


def test_cannot_pack_until_every_item_is_verified(session):
    order = by_number(session, "XYZ-1002")
    start_picking(session, order.id)
    confirm_scan(session, order.id, order.items[0].variant.barcode)

    with pytest.raises(InvalidTransitionError):
        pack_order(session, order.id)


def test_blocking_exception_prevents_picking(session):
    order = by_number(session, "XYZ-1005")
    with pytest.raises(BlockingExceptionError):
        start_picking(session, order.id)


def test_transfer_completion_makes_order_pickable(session):
    order = by_number(session, "XYZ-1003")
    transfer = session.scalar(
        select(InventoryTransfer).where(InventoryTransfer.order_id == order.id)
    )
    assert transfer is not None

    complete_transfer(session, transfer.id)
    session.flush()

    assert order.status == OrderStatus.READY_TO_PICK.value
    open_blocker = session.scalar(
        select(FulfillmentException).where(
            FulfillmentException.order_id == order.id,
            FulfillmentException.status == ExceptionStatus.OPEN.value,
            FulfillmentException.blocking.is_(True),
        )
    )
    assert open_blocker is None


def test_true_shortage_remains_blocked(session):
    order = by_number(session, "XYZ-1004")
    blocker = session.scalar(
        select(FulfillmentException).where(
            FulfillmentException.order_id == order.id,
            FulfillmentException.status == ExceptionStatus.OPEN.value,
        )
    )
    assert blocker is not None
    assert blocker.exception_type == ExceptionType.STOCK_SHORTAGE.value
    assert blocker.blocking is True


def test_replenished_shortage_changes_to_transfer_and_unblocks_after_completion(session):
    order = by_number(session, "XYZ-1004")
    item = order.items[0]

    overflow = session.scalar(select(Warehouse).where(Warehouse.ships_orders.is_(False)))
    overflow_location = session.scalar(
        select(WarehouseLocation).where(
            WarehouseLocation.warehouse_id == overflow.id,
            WarehouseLocation.location_type == LocationType.PICK.value,
        )
    )
    session.add(
        Inventory(
            variant_id=item.variant_id,
            location_id=overflow_location.id,
            quantity_on_hand=2,
            quantity_reserved=0,
        )
    )
    session.flush()

    prepare_order(session, order.id)
    session.flush()

    open_types = set(
        session.scalars(
            select(FulfillmentException.exception_type).where(
                FulfillmentException.order_id == order.id,
                FulfillmentException.status == ExceptionStatus.OPEN.value,
            )
        ).all()
    )
    assert ExceptionType.STOCK_SHORTAGE.value not in open_types
    assert ExceptionType.TRANSFER_REQUIRED.value in open_types

    transfer = session.scalar(
        select(InventoryTransfer).where(
            InventoryTransfer.order_id == order.id,
            InventoryTransfer.status == "REQUESTED",
        )
    )
    complete_transfer(session, transfer.id)
    session.flush()

    assert order.status == OrderStatus.READY_TO_PICK.value
    remaining_blocker = session.scalar(
        select(FulfillmentException.id).where(
            FulfillmentException.order_id == order.id,
            FulfillmentException.status == ExceptionStatus.OPEN.value,
            FulfillmentException.blocking.is_(True),
        )
    )
    assert remaining_blocker is None


def test_duplicate_sku_lines_request_the_combined_shortage_once(session):
    source_order = by_number(session, "XYZ-1003")
    variant: ProductVariant = source_order.items[0].variant

    main = session.scalar(select(Warehouse).where(Warehouse.ships_orders.is_(True)))
    overflow = session.scalar(select(Warehouse).where(Warehouse.ships_orders.is_(False)))
    main_location = session.scalar(
        select(WarehouseLocation).where(
            WarehouseLocation.warehouse_id == main.id,
            WarehouseLocation.location_type == LocationType.PICK.value,
        )
    )
    overflow_location = session.scalar(
        select(WarehouseLocation).where(
            WarehouseLocation.warehouse_id == overflow.id,
            WarehouseLocation.location_type == LocationType.PICK.value,
        )
    )

    # Use a fresh SKU so existing seeded reservations do not affect the test.
    duplicate_variant = ProductVariant(
        product_id=variant.product_id,
        sku="DUP-TEST-SKU",
        barcode="999999999999",
        variant_name="Duplicate-line test",
        active=True,
    )
    session.add(duplicate_variant)
    session.flush()
    session.add_all(
        [
            Inventory(
                variant_id=duplicate_variant.id,
                location_id=main_location.id,
                quantity_on_hand=1,
                quantity_reserved=0,
            ),
            Inventory(
                variant_id=duplicate_variant.id,
                location_id=overflow_location.id,
                quantity_on_hand=10,
                quantity_reserved=0,
            ),
        ]
    )

    order = Order(
        order_number="DUP-ORDER",
        customer_name="Duplicate Test",
        channel="Test",
        status=OrderStatus.NEW.value,
        priority=False,
        ship_by_at=utcnow() + timedelta(hours=4),
    )
    session.add(order)
    session.flush()
    session.add_all(
        [
            OrderItem(order_id=order.id, variant_id=duplicate_variant.id, quantity_ordered=2),
            OrderItem(order_id=order.id, variant_id=duplicate_variant.id, quantity_ordered=2),
        ]
    )
    session.flush()
    session.refresh(order)

    prepare_order(session, order.id)
    session.flush()

    transfer = session.scalar(
        select(InventoryTransfer).where(InventoryTransfer.order_id == order.id)
    )
    assert transfer is not None
    transferred = sum(item.quantity for item in transfer.items)

    # Four ordered units - one main-warehouse unit = three overflow units.
    assert transferred == 3

    # Re-preparing while the transfer is still requested must be idempotent.
    prepare_order(session, order.id)
    session.flush()
    assert sum(item.quantity for item in transfer.items) == 3


def test_staging_rejects_past_pickup_time(session):
    order = by_number(session, "XYZ-1006")
    courier = session.scalar(select(Courier).where(Courier.active.is_(True)))
    staging = session.scalar(
        select(WarehouseLocation).where(
            WarehouseLocation.location_type == LocationType.STAGING.value,
            WarehouseLocation.active.is_(True),
        )
    )

    with pytest.raises(InvalidTransitionError):
        stage_order(
            session,
            order.id,
            courier_id=courier.id,
            staging_location_id=staging.id,
            pickup_due_at=utcnow() - timedelta(minutes=1),
        )


def test_exception_cannot_be_resolved_through_another_order_url(session):
    order_a = by_number(session, "XYZ-1001")
    order_b = by_number(session, "XYZ-1002")
    exc = create_exception(
        session,
        order_a.id,
        ExceptionType.OTHER,
        "Ownership test",
    )
    session.flush()

    with pytest.raises(NotFoundError):
        resolve_exception(session, order_b.id, exc.id)

    assert exc.status == ExceptionStatus.OPEN.value
