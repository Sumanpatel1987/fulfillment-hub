from __future__ import annotations


def create_app(test_config: dict | None = None):
    # Imports are intentionally local so the domain/services can be used independently
    # of Flask in tests, scripts, or future workers.
    from flask import Flask, render_template

    from app.config import configure_app
    from app.extensions import csrf, db
    from app.routes import ALL_BLUEPRINTS
    from app.utils import utc_naive_to_local

    flask_app = Flask(__name__, instance_relative_config=True)
    configure_app(flask_app)
    if test_config:
        flask_app.config.update(test_config)

    import app.models  # noqa: F401

    db.init_app(flask_app)
    csrf.init_app(flask_app)

    for blueprint in ALL_BLUEPRINTS:
        flask_app.register_blueprint(blueprint)

    from app.cli import register_cli

    register_cli(flask_app)

    @flask_app.template_filter("local_dt")
    def local_dt(value, fmt: str = "%d %b, %H:%M"):
        if value is None:
            return "—"
        return utc_naive_to_local(value, flask_app.config["WAREHOUSE_TIMEZONE"]).strftime(fmt)

    @flask_app.context_processor
    def inject_operational_context():
        return {"warehouse_timezone": flask_app.config["WAREHOUSE_TIMEZONE"]}

    @flask_app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html"), 404

    @flask_app.errorhandler(500)
    def internal_error(_error):
        db.session.rollback()
        return render_template("500.html"), 500

    return flask_app
