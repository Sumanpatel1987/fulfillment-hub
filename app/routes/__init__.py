from app.routes.dashboard import bp as dashboard_bp
from app.routes.inventory import bp as inventory_bp
from app.routes.orders import bp as orders_bp
from app.routes.transfers import bp as transfers_bp
from app.routes.warehouse import bp as warehouse_bp

ALL_BLUEPRINTS = [
    dashboard_bp,
    orders_bp,
    warehouse_bp,
    transfers_bp,
    inventory_bp,
]
