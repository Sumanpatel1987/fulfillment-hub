# User Guide & Feature Walkthrough

A page-by-page guide to what the Fulfillment Hub does and how to use it.

---

## Dashboard (`/`)

**What it does:** The main operations view. Shows every active order and surfaces what needs attention right now.

**Key elements:**

| Element | What it means |
|---|---|
| **Priority due** | Orders flagged as priority that are approaching their ship-by deadline |
| **Ready to pick** | Orders fully allocated and waiting for a warehouse worker to start |
| **Blocked** | Orders with an open blocking exception that prevents workflow progress |
| **Waiting for courier** | Staged orders whose pickup window is approaching or overdue |

**Status badges** on each order row reflect the exact workflow state:
`NEW` → `READY_TO_PICK` → `PICKING` → `PACKED` → `STAGED` → `SHIPPED`

**Try it:**
- Use the search bar to find an order by number or customer name
- Filter by status or toggle **Priority only** / **Blocked only**
- Orders with an overdue ship-by deadline are visually highlighted

---

## Order Detail (`/orders/<id>`)

**What it does:** Shows the full state of a single order — items, inventory allocations, active exceptions, shipment info, and activity timeline.

**Sections:**

- **Order items** — each line shows the product, variant, SKU, quantities ordered and picked, and the allocated shelf location
- **Exceptions** — any open blocking or informational issues raised against the order
- **Shipment** — courier, staging location, and pickup due time (once staged)
- **Activity log** — timestamped record of every significant action taken on the order

**Actions available** depend on the current status:

| Status | Available action |
|---|---|
| `NEW` | Prepare (allocates inventory and transitions to `READY_TO_PICK` if stock is available) |
| `READY_TO_PICK` | Start picking |
| `PICKING` | Scan barcodes / SKUs; confirm pack when all units verified |
| `PACKED` | Assign staging location, courier, and pickup time |
| `STAGED` | Confirm courier pickup → `SHIPPED` |

You can also raise a manual exception (damaged item, missing stock, wrong item, courier issue) from any order detail page.

**Demo orders to try:**

| Order | What to explore |
|---|---|
| `XYZ-1002` | Start picking. Enter `TSH-BLU-L` — the app rejects it because the order needs `TSH-BLU-M`. Enter `TSH-BLU-M` or barcode `890100000002` to accept. A rejected scan never changes inventory. |
| `XYZ-1003` | Blocked by `TRANSFER_REQUIRED` — main warehouse is short, overflow can cover. Go to Transfers, complete it, come back to see the order become `READY_TO_PICK`. |
| `XYZ-1004` | Blocked by `STOCK_SHORTAGE` — neither warehouse can satisfy the order. |
| `XYZ-1005` | Blocked by a manual `DAMAGED_ITEM` exception. Resolve the exception to unblock picking. |
| `XYZ-1006` | Already packed. Assign a staging location and courier to move it to `STAGED`. |
| `XYZ-1007` | Staged with an overdue courier pickup — visible as a risk on the dashboard. |
| `XYZ-1008` | Fully shipped — shows the terminal state and complete activity log. |

---

## Picking Screen (`/orders/<id>/pick`)

**What it does:** Guides a warehouse worker through picking one item at a time.

**How it works:**

1. The screen shows exactly one thing: which shelf to go to, which product and variant to pick, and how many units remain
2. The worker scans the barcode or types the SKU into the input field
3. The app validates the scan server-side:
   - **Correct** → consumes one unit of reserved stock, updates picked quantity, moves to next item
   - **Wrong** → shows a clear error, records an audit event, no inventory change
4. When all units are verified the order can be packed

---

## Transfers (`/transfers`)

**What it does:** Lists all pending and completed warehouse-to-warehouse stock transfers.

**How transfers arise:** When an order needs stock that the main warehouse doesn't have, but the overflow warehouse does, the preparation step automatically creates a transfer request and blocks the order with `TRANSFER_REQUIRED`.

**Completing a transfer:**

1. Open the transfer on this page
2. Click **Complete transfer**
3. The app atomically:
   - Decreases overflow warehouse `on_hand` and `reserved`
   - Increases main warehouse `on_hand`
   - Allocates the moved stock to the waiting order
   - Resolves the `TRANSFER_REQUIRED` blocker
   - Transitions the order to `READY_TO_PICK` if fully allocated

---

## Inventory (`/inventory`)

**What it does:** Shows current stock levels across all warehouse locations.

**Columns:**

| Column | Meaning |
|---|---|
| **On hand** | Physical units present at this location |
| **Reserved** | Units promised to existing orders |
| **Available** | `on_hand − reserved` — what is actually free to allocate |

Stock is tracked at the variant + shelf location level, not just as a global SKU total. This allows the picking screen to direct workers to the exact shelf.

---

## Business Rules at a Glance

```
reserved ≤ on_hand
picked ≤ ordered

PACKED    requires every ordered unit to be verified
STAGED    requires PACKED + courier + staging location + pickup time
SHIPPED   requires STAGED + explicit courier pickup confirmation

A blocking exception prevents any forward workflow movement.
A rejected barcode scan never alters stock or order quantities.
Orders only pick from the main warehouse.
```
