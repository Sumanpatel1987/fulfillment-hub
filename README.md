# Fulfillment Hub

A small Flask application for running the important parts of an e-commerce fulfillment workflow: prioritizing orders, allocating physical inventory, verifying picks, handling overflow-stock transfers, staging packed boxes, and tracking operational problems.

## Features

- Operations dashboard with priority, overdue, blocked, and staged orders
- Explicit `NEW → READY_TO_PICK → PICKING → PACKED → STAGED → SHIPPED` workflow
- Inventory reservation by warehouse and shelf location
- Main / overflow warehouse stock transfer
- SKU or barcode verification during picking
- Blocking and non-blocking fulfillment exceptions
- Physical staging locations and courier pickup confirmation
- Activity timeline for important order actions
- Deterministic demo data with purpose-built scenarios

## Stack

- Python 3.11+
- Flask 3.1.3 · Jinja2 · Flask-WTF 1.3.0
- Flask-SQLAlchemy 3.1.1 · SQLAlchemy 2.0.x · SQLite
- Alembic · pytest

## Run Locally

```powershell
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Create the instance folder (first time only)
mkdir instance

# Apply schema migrations
alembic upgrade head

# Load demo data
flask --app run seed

# Start the app
python run.py
```

Open `http://127.0.0.1:5000`.

> **Re-seeding:** `flask --app run seed` is deterministic and destructive — it resets the demo fixture so the walkthrough always starts from the same state.

## Architecture

Server-rendered modular monolith:

```
Browser → Flask Routes → Services (business rules) → SQLAlchemy Models → SQLite
```

Routes handle HTTP only. The service layer owns all state transitions, stock reservation, barcode validation, transfers, exceptions, and shipment actions.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for details.

## Demo Scenarios

The seed data contains deliberate business cases rather than random rows.

| Order | Scenario |
|---|---|
| `XYZ-1002` | Priority order. Enter `TSH-BLU-L` to see a wrong variant rejected, then use the correct SKU/barcode. |
| `XYZ-1003` | Main warehouse short on stock; overflow has enough. Complete the transfer to make it pickable. |
| `XYZ-1004` | Neither warehouse has enough stock — blocking shortage exception. |
| `XYZ-1005` | Manual damaged-item blocker prevents picking. |
| `XYZ-1006` | Already packed — ready for staging location and courier. |
| `XYZ-1007` | Staged priority order with an overdue courier pickup. |
| `XYZ-1008` | Completed shipment showing terminal workflow state. |

Barcode demo values for `XYZ-1002`:

```
Wrong SKU:    TSH-BLU-L
Expected SKU: TSH-BLU-M
Barcode:      890100000002
```

## Project Structure

```
app/
  models/       database/domain entities
  services/     fulfillment business logic
  routes/       Flask blueprints
  templates/    server-rendered UI
  static/       CSS and browser helpers
seed/           fixed demonstration fixture
migrations/     Alembic schema history
tests/          service and web smoke tests
```

## Tests

```bash
pytest
pytest --cov=app --cov=seed
```

Key invariants tested:

- Wrong scan never mutates inventory
- Correct scan consumes reserved inventory exactly once
- Blocking exceptions prevent workflow progression
- Incomplete orders cannot be packed
- Overflow transfers move stock and make the order pickable
- True shortages remain blocked

## Notes

- Architecture decisions: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- AI usage: [`AI_USAGE.md`](AI_USAGE.md)
- Demo walkthrough: [`WALKTHROUGH.md`](WALKTHROUGH.md)
