from __future__ import annotations

import pytest


@pytest.fixture()
def app(tmp_path):
    flask = pytest.importorskip("flask")
    pytest.importorskip("flask_sqlalchemy")
    pytest.importorskip("flask_wtf")

    from app import create_app
    from app.extensions import db
    from seed.seed_data import seed_database

    application = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'web.db'}",
            "SECRET_KEY": "test",
        }
    )
    with application.app_context():
        db.create_all()
        seed_database(db.session)
        db.session.commit()
    return application


def test_dashboard_renders(app):
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert b"Today's fulfillment" in response.data
    assert b"XYZ-1002" in response.data


def test_order_detail_renders(app):
    client = app.test_client()
    response = client.get("/orders/2")
    assert response.status_code == 200
    assert b"Warehouse picking" not in response.data
    assert b"TSH-BLU-M" in response.data


def test_wrong_scan_shows_error_without_500(app):
    client = app.test_client()
    client.post("/warehouse/orders/2/pick/start")
    response = client.post(
        "/warehouse/orders/2/pick/scan",
        data={"barcode": "TSH-BLU-L"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Wrong item" in response.data
