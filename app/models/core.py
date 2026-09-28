from __future__ import annotations

from datetime import datetime, time

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.enums import (
    ExceptionSource,
    ExceptionStatus,
    LocationType,
    OrderStatus,
    TransferStatus,
)
from app.utils import utcnow


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    ships_orders: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    locations: Mapped[list["WarehouseLocation"]] = relationship(
        back_populates="warehouse", cascade="all, delete-orphan"
    )


class WarehouseLocation(Base):
    __tablename__ = "warehouse_locations"
    __table_args__ = (UniqueConstraint("warehouse_id", "code", name="uq_location_warehouse_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    location_type: Mapped[str] = mapped_column(String(20), default=LocationType.PICK.value, nullable=False)
    pick_sequence: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    warehouse: Mapped["Warehouse"] = relationship(back_populates="locations")
    inventory_rows: Mapped[list["Inventory"]] = relationship(back_populates="location")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    variants: Mapped[list["ProductVariant"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class ProductVariant(Base):
    __tablename__ = "product_variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    barcode: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    variant_name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    product: Mapped["Product"] = relationship(back_populates="variants")
    inventory_rows: Mapped[list["Inventory"]] = relationship(back_populates="variant")


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("variant_id", "location_id", name="uq_inventory_variant_location"),
        CheckConstraint("quantity_on_hand >= 0", name="ck_inventory_on_hand_nonnegative"),
        CheckConstraint("quantity_reserved >= 0", name="ck_inventory_reserved_nonnegative"),
        CheckConstraint("quantity_reserved <= quantity_on_hand", name="ck_inventory_reserved_lte_on_hand"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("product_variants.id"), nullable=False, index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("warehouse_locations.id"), nullable=False, index=True)
    quantity_on_hand: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantity_reserved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    variant: Mapped["ProductVariant"] = relationship(back_populates="inventory_rows")
    location: Mapped["WarehouseLocation"] = relationship(back_populates="inventory_rows")

    @property
    def available_quantity(self) -> int:
        return self.quantity_on_hand - self.quantity_reserved


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    customer_name: Mapped[str] = mapped_column(String(160), nullable=False)
    channel: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=OrderStatus.NEW.value, nullable=False, index=True)
    priority: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    ship_by_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )
    shipment: Mapped["Shipment | None"] = relationship(
        back_populates="order", cascade="all, delete-orphan", uselist=False
    )
    exceptions: Mapped[list["FulfillmentException"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="FulfillmentException.created_at"
    )
    activity_logs: Mapped[list["ActivityLog"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="ActivityLog.created_at"
    )
    transfers: Mapped[list["InventoryTransfer"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity_ordered > 0", name="ck_order_item_ordered_positive"),
        CheckConstraint("quantity_picked >= 0", name="ck_order_item_picked_nonnegative"),
        CheckConstraint("quantity_picked <= quantity_ordered", name="ck_order_item_picked_lte_ordered"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("product_variants.id"), nullable=False, index=True)
    quantity_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_picked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    order: Mapped["Order"] = relationship(back_populates="items")
    variant: Mapped["ProductVariant"] = relationship()
    allocations: Mapped[list["InventoryAllocation"]] = relationship(
        back_populates="order_item", cascade="all, delete-orphan"
    )


class InventoryAllocation(Base):
    __tablename__ = "inventory_allocations"
    __table_args__ = (
        CheckConstraint("quantity_reserved > 0", name="ck_allocation_reserved_positive"),
        CheckConstraint("quantity_picked >= 0", name="ck_allocation_picked_nonnegative"),
        CheckConstraint("quantity_picked <= quantity_reserved", name="ck_allocation_picked_lte_reserved"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id"), nullable=False, index=True)
    inventory_id: Mapped[int] = mapped_column(ForeignKey("inventory.id"), nullable=False, index=True)
    quantity_reserved: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_picked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    order_item: Mapped["OrderItem"] = relationship(back_populates="allocations")
    inventory: Mapped["Inventory"] = relationship()

    @property
    def remaining_quantity(self) -> int:
        return self.quantity_reserved - self.quantity_picked


class Courier(Base):
    __tablename__ = "couriers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    estimated_days: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_cents: Mapped[int | None] = mapped_column(Integer)
    pickup_cutoff_time: Mapped[time | None] = mapped_column(Time)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, unique=True)
    courier_id: Mapped[int] = mapped_column(ForeignKey("couriers.id"), nullable=False)
    staging_location_id: Mapped[int] = mapped_column(ForeignKey("warehouse_locations.id"), nullable=False)
    tracking_number: Mapped[str | None] = mapped_column(String(100))
    pickup_due_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    order: Mapped["Order"] = relationship(back_populates="shipment")
    courier: Mapped["Courier"] = relationship()
    staging_location: Mapped["WarehouseLocation"] = relationship()


class FulfillmentException(Base):
    __tablename__ = "exceptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    order_item_id: Mapped[int | None] = mapped_column(ForeignKey("order_items.id"), index=True)
    exception_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(20), default=ExceptionSource.USER.value, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    blocking: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default=ExceptionStatus.OPEN.value, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)

    order: Mapped["Order"] = relationship(back_populates="exceptions")
    order_item: Mapped["OrderItem | None"] = relationship()


class InventoryTransfer(Base):
    __tablename__ = "inventory_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    from_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    to_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=TransferStatus.REQUESTED.value, nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    order: Mapped["Order"] = relationship(back_populates="transfers")
    from_warehouse: Mapped["Warehouse"] = relationship(foreign_keys=[from_warehouse_id])
    to_warehouse: Mapped["Warehouse"] = relationship(foreign_keys=[to_warehouse_id])
    items: Mapped[list["InventoryTransferItem"]] = relationship(
        back_populates="transfer", cascade="all, delete-orphan"
    )


class InventoryTransferItem(Base):
    __tablename__ = "inventory_transfer_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_transfer_item_quantity_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_id: Mapped[int] = mapped_column(ForeignKey("inventory_transfers.id"), nullable=False, index=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("product_variants.id"), nullable=False)
    source_inventory_id: Mapped[int] = mapped_column(ForeignKey("inventory.id"), nullable=False)
    destination_location_id: Mapped[int] = mapped_column(ForeignKey("warehouse_locations.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    transfer: Mapped["InventoryTransfer"] = relationship(back_populates="items")
    variant: Mapped["ProductVariant"] = relationship()
    source_inventory: Mapped["Inventory"] = relationship()
    destination_location: Mapped["WarehouseLocation"] = relationship()


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)

    order: Mapped["Order"] = relationship(back_populates="activity_logs")
