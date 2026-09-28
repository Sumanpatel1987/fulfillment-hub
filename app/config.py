from __future__ import annotations

import os
from pathlib import Path


def configure_app(app) -> None:
    instance = Path(app.instance_path)
    instance.mkdir(parents=True, exist_ok=True)

    default_db = f"sqlite:///{instance / 'fulfillment.db'}"
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-only-change-me"),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", default_db),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        WTF_CSRF_TIME_LIMIT=None,
        # Operational timestamps are stored as naive UTC in SQLite, but users
        # enter and read times in the warehouse's local timezone.
        WAREHOUSE_TIMEZONE=os.getenv("WAREHOUSE_TIMEZONE", "Asia/Kolkata"),
    )
