# KUWorkspace

CLI program for managing shared-office room reservations and equipment rentals. It provides separate guest, user, and admin flows, persists state in local JSON Lines files under `data/`, and applies operational rules such as no-show handling, late-cancel penalties, temporary booking restrictions, and admin-managed check-in / return workflows.

> [!NOTE]
> This repository is a local-file CLI application, not a web service. Data is stored in text files in `data/`, and the project currently does not pin a specific Python version or ship a packaged release.

## What It Does

- Guest flow for sign up, login, and exit
- User flow for room reservations, equipment reservations, booking changes, cancellations, checkout / return requests, and personal status lookup
- Admin flow for room / equipment status changes, global booking inspection, manual check-in / checkout processing, and damage / contamination penalties
- Automatic policy checks for no-shows, expired restrictions, 90-day penalty resets, and automatic cancellation of future bookings for banned users
- File-based persistence with global locking and a Unit of Work layer for multi-file atomic writes

## Core Rules

- Booking UI is date-range based, with a fixed daily usage window of `09:00` to `18:00`
- A booking can start from tomorrow and extend for up to 14 days
- Booking requests can be made up to 6 months ahead
- No-show: `+3` points after a 15-minute grace period
- Late cancel: `+2` points when cancelling within 1 hour of start
- Late checkout / return: `ceil(delay_minutes / 10)` points
- `3-5` penalty points restrict the user to 1 active booking
- `6+` penalty points ban usage for 30 days and automatically cancel future reserved bookings
- Every 10 consecutive normal uses reduces penalty points by 1

## Repository Layout

| Path | Purpose |
| --- | --- |
| `main.py` | Application entrypoint and top-level menu loop |
| `src/cli/` | Guest, user, and admin terminal menus plus input/format helpers |
| `src/domain/` | Booking, auth, policy, and penalty services with domain models |
| `src/storage/` | JSONL repositories, file locking, and atomic write helpers |
| `scripts/seed_data.py` | Seeds an admin account plus sample rooms and equipment |
| `data/` | Runtime storage for users, bookings, penalties, and audit logs |
| `tests/` | Unit, integration, and end-to-end test suites |
| `flow.md` | Current end-to-end CLI flow and rule documentation |
| `PLAN.md`, `PLAN2.md` | Planning documents for features and concurrency design |

## Setup

Install dependencies from the repository root:

```bash
python -m pip install -r requirements.txt
```

Seed sample data:

```bash
python scripts/seed_data.py
```

The seed script creates:

- Admin account: `admin / admin123`
- Sample rooms across 4-person, 6-person, and 8-person capacities
- Sample equipment such as projectors, laptops, cables, and webcams

## Quick Start

Run the CLI:

```bash
python main.py
```

Typical first-run flow:

1. Run `python scripts/seed_data.py`
2. Start the app with `python main.py`
3. Log in as `admin / admin123` to inspect assets and bookings
4. Create a normal user account from the guest menu and test the user booking flow

## Data Model and Storage

Runtime data lives in plain text files under `data/`:

- `users.txt`
- `rooms.txt`
- `equipment_assets.txt`
- `room_bookings.txt`
- `equipment_bookings.txt`
- `penalties.txt`
- `audit_log.txt`

The storage layer reads and writes JSON Lines records through repository classes in `src/storage/repositories.py`. Write paths require a global file lock, and multi-file updates are staged through `UnitOfWork` before being committed atomically.

## Testing

Run the test suite with:

```bash
pytest
```

The repository includes:

- Unit tests for auth, policy, booking, menu, and data handling logic
- Integration tests for repositories, locking, and concurrency behavior
- End-to-end tests for signup/login, booking flows, penalties, and admin operations

## Caveats

- Passwords are stored in plain text as part of the assignment constraints
- The CLI currently exposes a date-range booking flow even though some lower-level services also support time-based methods
- The project uses local file storage and is intended for coursework / small-scale local execution, not concurrent distributed deployment
- Sample runtime data under `data/` may change as the application is used
