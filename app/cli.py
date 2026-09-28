from __future__ import annotations

import click
from flask import Flask
from sqlalchemy import select

from app.extensions import db
from app.models import Order


def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db_command():
        """Create database tables for a quick local demo."""
        db.create_all()
        click.echo("Database tables created.")

    @app.cli.command("seed")
    def seed_command():
        """Reset and load the deterministic demonstration fixture."""
        from seed.seed_data import seed_database

        seed_database(db.session)
        db.session.commit()
        click.echo("Demo data loaded.")

    @app.cli.command("seed-if-empty")
    def seed_if_empty_command():
        """Load demo data only when the orders table has no rows."""
        existing = db.session.scalar(select(Order.id).limit(1))
        if existing is not None:
            click.echo("Database already contains orders; seed skipped.")
            return

        from seed.seed_data import seed_database

        seed_database(db.session)
        db.session.commit()
        click.echo("Demo data loaded.")
