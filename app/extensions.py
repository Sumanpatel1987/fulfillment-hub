from __future__ import annotations

from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

from app.db import Base

db = SQLAlchemy(model_class=Base)
csrf = CSRFProtect()
