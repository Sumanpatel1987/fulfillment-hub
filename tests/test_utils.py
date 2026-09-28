from datetime import datetime

from app.utils import local_naive_to_utc, utc_naive_to_local


def test_datetime_local_is_converted_using_warehouse_timezone():
    local_value = datetime(2026, 9, 27, 18, 0)

    stored_utc = local_naive_to_utc(local_value, "Asia/Kolkata")
    assert stored_utc == datetime(2026, 9, 27, 12, 30)

    displayed = utc_naive_to_local(stored_utc, "Asia/Kolkata")
    assert displayed.replace(tzinfo=None) == local_value
