from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
import app.models  # noqa: F401
from seed.seed_data import seed_database


@pytest.fixture()
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        seed_database(db_session)
        db_session.commit()
        yield db_session
        db_session.rollback()
