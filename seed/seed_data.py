from __future__ import annotations

from datetime import time, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.enums import (
    Actor,
    ExceptionType,
    LocationType,
    OrderStatus,
)
from app.models import (
    ActivityLog,
    Courier,
    FulfillmentException,
    Inventory,
    InventoryAllocation,
    InventoryTransfer,
    InventoryTransferItem,
    Order,
    OrderItem,
    Product,
    ProductVariant,
    Shipment,
    Warehouse,
    WarehouseLocation,
)
from app.services.exception_service import create_exception
from app.services.fulfillment_service import (
    confirm_scan,
    pack_order,
    prepare_order,
    ship_order,
    stage_order,
    start_picking,
)
from app.utils import utcnow


def _clear(session: Session) -> None:
    # Deterministic demo reset. Delete children before parents.
    for model in [
        ActivityLog,
        FulfillmentException,
        Shipment,
        InventoryTransferItem,
        InventoryTransfer,
        InventoryAllocation,
        OrderItem,
        Order,
        Inventory,
        ProductVariant,
        Product,
        WarehouseLocation,
        Warehouse,
        Courier,
    ]:
        session.execute(delete(model))
    session.flush()


def _add_order(
    session: Session,
    *,
    number: str,
    customer: str,
    channel: str,
    ship_delta_hours: int,
    priority: bool,
    lines: list[tuple[ProductVariant, int]],
) -> Order:
    order = Order(
        order_number=number,
        customer_name=customer,
        channel=channel,
        priority=priority,
        ship_by_at=utcnow() + timedelta(hours=ship_delta_hours),
        status=OrderStatus.NEW.value,
        created_at=utcnow() - timedelta(hours=max(1, 12 - ship_delta_hours // 2)),
    )
    session.add(order)
    session.flush()
    for variant, qty in lines:
        session.add(
            OrderItem(
                order_id=order.id,
                variant_id=variant.id,
                quantity_ordered=qty,
                quantity_picked=0,
            )
        )
    session.flush()
    session.refresh(order)
    return order


def _pick_all(session: Session, order: Order) -> None:
    start_picking(session, order.id)
    for item in order.items:
        for _ in range(item.quantity_ordered):
            confirm_scan(session, order.id, item.variant.barcode)


def seed_database(session: Session) -> None:
    """Load one fixed, intentionally designed dataset for the demo.

    This is not a random generator. Every record exists to demonstrate a workflow case.
    """
    _clear(session)

    main = Warehouse(code="MAIN", name="Main Warehouse", ships_orders=True)
    overflow = Warehouse(code="OVERFLOW", name="Overflow Warehouse", ships_orders=False)
    session.add_all([main, overflow])
    session.flush()

    locations = {
        "A-01-01": WarehouseLocation(warehouse_id=main.id, code="A-01-01", location_type=LocationType.PICK.value, pick_sequence=10),
        "A-01-02": WarehouseLocation(warehouse_id=main.id, code="A-01-02", location_type=LocationType.PICK.value, pick_sequence=20),
        "A-02-01": WarehouseLocation(warehouse_id=main.id, code="A-02-01", location_type=LocationType.PICK.value, pick_sequence=30),
        "A-02-02": WarehouseLocation(warehouse_id=main.id, code="A-02-02", location_type=LocationType.PICK.value, pick_sequence=40),
        "A-03-01": WarehouseLocation(warehouse_id=main.id, code="A-03-01", location_type=LocationType.PICK.value, pick_sequence=50),
        "TRANSFER-IN": WarehouseLocation(warehouse_id=main.id, code="TRANSFER-IN", location_type=LocationType.PICK.value, pick_sequence=5),
        "STAGE-A1": WarehouseLocation(warehouse_id=main.id, code="STAGE-A1", location_type=LocationType.STAGING.value),
        "STAGE-A2": WarehouseLocation(warehouse_id=main.id, code="STAGE-A2", location_type=LocationType.STAGING.value),
        "STAGE-B1": WarehouseLocation(warehouse_id=main.id, code="STAGE-B1", location_type=LocationType.STAGING.value),
        "B-01-01": WarehouseLocation(warehouse_id=overflow.id, code="B-01-01", location_type=LocationType.PICK.value, pick_sequence=10),
        "B-01-02": WarehouseLocation(warehouse_id=overflow.id, code="B-01-02", location_type=LocationType.PICK.value, pick_sequence=20),
        "B-02-01": WarehouseLocation(warehouse_id=overflow.id, code="B-02-01", location_type=LocationType.PICK.value, pick_sequence=30),
    }
    session.add_all(locations.values())
    session.flush()

    def product(name: str, variants: list[tuple[str, str, str]]) -> dict[str, ProductVariant]:
        p = Product(name=name, active=True)
        session.add(p)
        session.flush()
        result = {}
        for sku, barcode, variant_name in variants:
            v = ProductVariant(
                product_id=p.id,
                sku=sku,
                barcode=barcode,
                variant_name=variant_name,
                active=True,
            )
            session.add(v)
            result[sku] = v
        session.flush()
        return result

    variants: dict[str, ProductVariant] = {}
    variants |= product("Classic T-Shirt", [
        ("TSH-BLU-S", "890100000001", "Blue / Small"),
        ("TSH-BLU-M", "890100000002", "Blue / Medium"),
        ("TSH-BLU-L", "890100000003", "Blue / Large"),
    ])
    variants |= product("Ceramic Mug", [
        ("MUG-BLK", "890100000011", "Black"),
        ("MUG-WHT", "890100000012", "White"),
    ])
    variants |= product("Wireless Headphones", [
        ("HEAD-BLK", "890100000021", "Black"),
    ])
    variants |= product("Phone Case", [
        ("CASE-CLR", "890100000031", "Clear"),
        ("CASE-BLU", "890100000032", "Blue"),
    ])
    variants |= product("Everyday Socks", [
        ("SOCK-M", "890100000041", "Medium"),
        ("SOCK-L", "890100000042", "Large"),
    ])
    variants |= product("Steel Bottle", [
        ("BOT-750", "890100000051", "750 ml"),
    ])
    variants |= product("A5 Notebook", [
        ("NOTE-A5-BLK", "890100000061", "Black"),
    ])
    variants |= product("USB-C Charger", [
        ("CHG-USBC-65", "890100000071", "65 W"),
    ])
    variants |= product("Canvas Cap", [
        ("CAP-BLK", "890100000081", "Black"),
    ])

    def stock(sku: str, location: str, on_hand: int) -> None:
        session.add(
            Inventory(
                variant_id=variants[sku].id,
                location_id=locations[location].id,
                quantity_on_hand=on_hand,
                quantity_reserved=0,
            )
        )

    # Main stock for normal flows.
    stock("TSH-BLU-S", "A-01-01", 18)
    stock("TSH-BLU-M", "A-01-01", 20)
    stock("TSH-BLU-L", "A-01-02", 15)
    stock("MUG-BLK", "A-02-01", 14)
    stock("MUG-WHT", "A-02-01", 12)
    stock("HEAD-BLK", "A-02-02", 9)
    stock("CASE-CLR", "A-03-01", 20)
    stock("CASE-BLU", "A-03-01", 18)
    stock("SOCK-M", "A-01-02", 20)
    stock("SOCK-L", "A-01-02", 20)
    stock("BOT-750", "A-02-02", 11)
    stock("CAP-BLK", "A-03-01", 12)

    # Purpose-built shortage / transfer scenarios.
    stock("CHG-USBC-65", "A-03-01", 1)
    stock("CHG-USBC-65", "B-01-01", 8)
    stock("NOTE-A5-BLK", "A-03-01", 1)

    # Some overflow stock for normal variants.
    stock("TSH-BLU-M", "B-01-02", 30)
    stock("MUG-BLK", "B-02-01", 18)
    stock("BOT-750", "B-02-01", 10)

    couriers = [
        Courier(name="SwiftShip", service_name="Express", estimated_days=1, estimated_cost_cents=12900, pickup_cutoff_time=time(17, 0)),
        Courier(name="ParcelGo", service_name="Standard", estimated_days=3, estimated_cost_cents=6900, pickup_cutoff_time=time(18, 0)),
        Courier(name="MetroCourier", service_name="Same Day", estimated_days=0, estimated_cost_cents=15900, pickup_cutoff_time=time(15, 30)),
    ]
    session.add_all(couriers)
    session.flush()

    # A: normal ready-to-pick order.
    normal = _add_order(
        session,
        number="XYZ-1001",
        customer="Aarav Mehta",
        channel="Web Store",
        ship_delta_hours=9,
        priority=False,
        lines=[(variants["MUG-BLK"], 1), (variants["CASE-CLR"], 1)],
    )
    prepare_order(session, normal.id)

    # B: priority order used for the wrong-variant demonstration.
    priority = _add_order(
        session,
        number="XYZ-1002",
        customer="Maya Sharma",
        channel="Marketplace A",
        ship_delta_hours=1,
        priority=True,
        lines=[(variants["TSH-BLU-M"], 2)],
    )
    prepare_order(session, priority.id)

    # C: overflow transfer required.
    transfer_order = _add_order(
        session,
        number="XYZ-1003",
        customer="Kabir Jain",
        channel="Web Store",
        ship_delta_hours=5,
        priority=True,
        lines=[(variants["CHG-USBC-65"], 3)],
    )
    prepare_order(session, transfer_order.id)

    # D: true shortage.
    shortage = _add_order(
        session,
        number="XYZ-1004",
        customer="Riya Kapoor",
        channel="Marketplace B",
        ship_delta_hours=14,
        priority=False,
        lines=[(variants["NOTE-A5-BLK"], 3)],
    )
    prepare_order(session, shortage.id)

    # E: damaged-item blocker.
    damaged = _add_order(
        session,
        number="XYZ-1005",
        customer="Dev Malhotra",
        channel="Web Store",
        ship_delta_hours=7,
        priority=True,
        lines=[(variants["BOT-750"], 1)],
    )
    prepare_order(session, damaged.id)
    create_exception(
        session,
        damaged.id,
        ExceptionType.DAMAGED_ITEM,
        "Bottle has a dent and needs replacement before picking.",
        blocking=True,
        actor=Actor.OFFICE,
    )

    # F: a fully packed order ready to stage.
    packed = _add_order(
        session,
        number="XYZ-1006",
        customer="Ananya Rao",
        channel="Marketplace A",
        ship_delta_hours=6,
        priority=False,
        lines=[(variants["SOCK-M"], 1), (variants["CAP-BLK"], 1)],
    )
    prepare_order(session, packed.id)
    _pick_all(session, packed)
    pack_order(session, packed.id)

    # G: staged order whose courier pickup is already overdue even though the
    # customer-facing ship-by deadline is still in the future. This makes the
    # missed-pickup risk independently demonstrable.
    staged = _add_order(
        session,
        number="XYZ-1007",
        customer="Ishaan Verma",
        channel="Web Store",
        ship_delta_hours=4,
        priority=True,
        lines=[(variants["MUG-WHT"], 1)],
    )
    prepare_order(session, staged.id)
    _pick_all(session, staged)
    pack_order(session, staged.id)
    stage_order(
        session,
        staged.id,
        courier_id=couriers[0].id,
        staging_location_id=locations["STAGE-A1"].id,
        pickup_due_at=utcnow() + timedelta(minutes=15),
    )
    # Simulate that time passed and the courier failed to collect the parcel.
    staged.shipment.pickup_due_at = utcnow() - timedelta(minutes=45)

    # H: completed shipment for historical context.
    shipped = _add_order(
        session,
        number="XYZ-1008",
        customer="Neha Singh",
        channel="Marketplace B",
        ship_delta_hours=12,
        priority=False,
        lines=[(variants["HEAD-BLK"], 1)],
    )
    prepare_order(session, shipped.id)
    _pick_all(session, shipped)
    pack_order(session, shipped.id)
    stage_order(
        session,
        shipped.id,
        courier_id=couriers[1].id,
        staging_location_id=locations["STAGE-A2"].id,
        pickup_due_at=utcnow() + timedelta(hours=2),
    )
    ship_order(session, shipped.id)

    # A few fresh orders awaiting office preparation.
    _add_order(
        session,
        number="XYZ-1009",
        customer="Vihaan Bose",
        channel="Web Store",
        ship_delta_hours=18,
        priority=False,
        lines=[(variants["CASE-BLU"], 1)],
    )
    _add_order(
        session,
        number="XYZ-1010",
        customer="Sara Iyer",
        channel="Marketplace A",
        ship_delta_hours=3,
        priority=True,
        lines=[(variants["TSH-BLU-S"], 1), (variants["SOCK-L"], 2)],
    )
    _add_order(
        session,
        number="XYZ-1011",
        customer="Arjun Nair",
        channel="Web Store",
        ship_delta_hours=22,
        priority=False,
        lines=[(variants["MUG-BLK"], 2)],
    )
    _add_order(
        session,
        number="XYZ-1012",
        customer="Diya Patel",
        channel="Marketplace B",
        ship_delta_hours=30,
        priority=False,
        lines=[(variants["CASE-CLR"], 1), (variants["BOT-750"], 1)],
    )

    session.flush()
