from flask import Blueprint, flash, redirect, render_template, url_for
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import InventoryTransfer
from app.services.errors import DomainError
from app.services.transfer_service import complete_transfer

bp = Blueprint("transfers", __name__, url_prefix="/transfers")


@bp.get("")
def index():
    transfers = list(
        db.session.scalars(
            select(InventoryTransfer)
            .options(
                selectinload(InventoryTransfer.order),
                selectinload(InventoryTransfer.from_warehouse),
                selectinload(InventoryTransfer.to_warehouse),
                selectinload(InventoryTransfer.items),
            )
            .order_by(InventoryTransfer.requested_at.desc())
        ).unique().all()
    )
    return render_template("transfers.html", transfers=transfers)


@bp.post("/<int:transfer_id>/complete")
def complete(transfer_id: int):
    order_id = None
    try:
        transfer = complete_transfer(db.session, transfer_id)
        order_id = transfer.order_id
        db.session.commit()
        flash("Transfer completed. Main-warehouse allocation was refreshed.", "success")
    except DomainError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    if order_id:
        return redirect(url_for("orders.detail", order_id=order_id))
    return redirect(url_for("transfers.index"))
