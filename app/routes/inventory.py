from flask import Blueprint, render_template, request
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import Inventory, Product, ProductVariant, WarehouseLocation

bp = Blueprint("inventory", __name__, url_prefix="/inventory")


@bp.get("")
def index():
    q = request.args.get("q", "").strip()
    stmt = (
        select(Inventory)
        .join(Inventory.variant)
        .join(ProductVariant.product)
        .options(
            selectinload(Inventory.variant).selectinload(ProductVariant.product),
            selectinload(Inventory.location).selectinload(WarehouseLocation.warehouse),
        )
        .order_by(Product.name, ProductVariant.variant_name)
    )
    if q:
        needle = f"%{q}%"
        stmt = stmt.where(
            or_(
                Product.name.ilike(needle),
                ProductVariant.sku.ilike(needle),
                ProductVariant.barcode.ilike(needle),
            )
        )
    rows = list(db.session.scalars(stmt).unique().all())
    return render_template("inventory.html", rows=rows, q=q)
