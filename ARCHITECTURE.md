# Architecture — Fulfillment Hub

**Stack:** Python · Flask · Jinja · SQLAlchemy · SQLite  
**Pattern:** Server-rendered modular monolith

---

## Overview

A small operational tool for an e-commerce warehouse. The backend owns all business rules; the browser only submits actions and displays the updated state.

**Core problems it solves:**
- No visibility into order status or priorities
- Wrong products being picked and shipped
- Stock scattered across two warehouses
- Courier pickups being missed
- Operational problems disappearing without being tracked

---

## Architecture

One Flask process, one SQLite database, four layers:

```
Routes (Blueprints)
    └── Services (fulfillment, inventory, transfer, exception)
            └── Models (SQLAlchemy ORM)
                    └── SQLite DB
```

- **Routes** — read request, call one service, commit or rollback, render/redirect. No business logic.
- **Services** — own all domain rules: state transitions, inventory reservation, scan verification, blocker enforcement.
- **Models** — persisted state + database constraints.
- **No repository layer** — SQLAlchemy already provides the persistence abstraction.

---

## Fulfillment State Machine

```
NEW → READY_TO_PICK → PICKING → PACKED → STAGED → SHIPPED
```

| Transition | Preconditions |
|---|---|
| NEW → READY_TO_PICK | all lines allocated, no blocker |
| READY_TO_PICK → PICKING | no blocker |
| PICKING → PACKED | all units verified, no blocker |
| PACKED → STAGED | staging location + courier + pickup time, no blocker |
| STAGED → SHIPPED | courier pickup explicitly confirmed |

Blockers (e.g. `STOCK_SHORTAGE`) are a separate flag, not extra statuses. This avoids state explosion like `PICKING_BLOCKED`, `PACKED_BLOCKED`, etc.

---

## Inventory Model

Inventory is physical — tracked per variant, per shelf location:

```
available = quantity_on_hand − quantity_reserved
```

`InventoryAllocation` links each `OrderItem` to the exact `Inventory` row it reserved, enabling precise picking locations and correct consumption.

---

## Two-Warehouse Transfer

Only the main warehouse ships orders. When main stock is short:

1. Check overflow warehouse for available stock
2. If sufficient → reserve overflow stock + create transfer + block order (`TRANSFER_REQUIRED`)
3. If not → block order (`STOCK_SHORTAGE`)
4. When transfer is completed → stock moves to main, order is reallocated, blocker resolved

Overflow stock is reserved immediately to prevent two orders claiming the same units.

---

## Pick Verification

The UI shows one item at a time (shelf, product, variant, quantity). Each scan is validated server-side:

- **Correct scan** → decrement `on_hand` and `reserved`, increment picked quantities
- **Wrong scan** → no inventory change, audit event recorded, error shown

Available stock for other orders is never affected by an in-progress pick.

---

## Key Design Decisions

| Decision | Reason |
|---|---|
| Monolith over microservices | One domain, few users, no independent scaling need |
| Jinja over React | No complex client state; server owns the state machine |
| SQLite over PostgreSQL | Zero-install for demo; domain layer is DB-agnostic |
| Flask over FastAPI | Server-rendered UI, not an API-first product |
| No generic repository | SQLAlchemy already abstracts persistence sufficiently |

---

## Out of Scope

Authentication, real courier APIs, label printing, payments, returns, batch picking, background workers, mobile app.
