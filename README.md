# Payments Service

A small payments backend that demonstrates secure tokenization, idempotent
payment creation, signed webhook processing, an append-only ledger, and
concurrency safety. Built on the [Vinta Django React Boilerplate](https://github.com/vintasoftware/django-react-boilerplate)
(Django + DRF + React + PostgreSQL).

The first commit in this repository is the untouched, bootstrapped boilerplate.
Everything after that is the implementation described below.

## What it does

- **`mock_processor`** — a self-contained Django app that simulates an external
  processor (Stripe/Adyen). It tokenizes card/bank details, accepts charges, and
  delivers signed webhooks. The payments app treats it as an external system.
- **`payments`** — the payments API, append-only ledger, idempotency, and
  webhook processing.

The two apps are decoupled: `payments` never imports `mock_processor`'s models
or reads its tables. It talks to the processor through a single adapter
(`payments/processor.py`) that calls `mock_processor.gateway` (plain functions +
dataclasses). Swapping in a real processor means replacing only that adapter.

## Architecture

```
            tokenize (card/bank)                 charge (in-process adapter)
 client ───────────────────────▶ mock_processor ◀──────────────────── payments.processor
   │                                   │                                      ▲
   │  POST /api/payments (token)       │  signed webhook                      │
   ▼                                   ▼  POST /webhooks/processor            │
 payments API ─────────────▶ Payment + append-only LedgerEntry ──────────────┘
                                   │
                                   ▼
                        status derived from the ledger
```

- Card/bank data only ever reaches `POST /processor/tokenize`. The payments API
  accepts a token, never raw instrument data.
- `POST /api/payments` asks the processor to charge the token (in-process) and
  gets back a `processor_reference`. The final result arrives later as a webhook.
- Every state change is an append-only ledger row. The current status is derived
  purely by folding the ledger through the state machine.

## Setup (Docker Compose)

Requirements: Docker + Docker Compose. Everything else runs in containers.

```bash
# 1. Config files (both are git-ignored; never commit real secrets)
cp backend/.env.example backend/.env
cp backend/config/settings/local.py.example backend/config/settings/local.py

# 2. Build images and generate the OpenAPI schema + TypeScript client
make docker_setup

# 3. Build the frontend bundle (needed by the frontend smoke test and the UI)
docker compose run --rm frontend pnpm run build

# 4. Apply migrations (migrations are committed; this just applies them)
make docker_migrate

# 5. Run everything
make docker_up
```

Then visit:
- `http://localhost:8000/payments` — read-only React payments list (masked refs).
- `http://localhost:8000/api/schema/swagger-ui/` — API docs.
- `http://localhost:8000/admin/` — Django admin (`make docker_backend_shell` then
  `python manage.py createsuperuser` to create a user).

### Environment variables

See `backend/.env.example`. The ones that matter for this service:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection (defaults to the compose `db`). |
| `PROCESSOR_WEBHOOK_SECRET` | HMAC key for signing/verifying webhooks. Use a strong random value in real environments. |
| `PROCESSOR_WEBHOOK_URL` | Where `simulate_webhooks` posts (defaults to `localhost:8000`). |

## Running the tests

A single command runs the full suite (Django test runner, parallel + keepdb):

```bash
make docker_test
```

The suite (50 tests) covers idempotency, webhook signatures, duplicate/out-of-order/
concurrent delivery, the append-only ledger, and the no-sensitive-data guarantee.
The concurrency tests use real threads with **separate database connections**
(`TransactionTestCase`), not a single shared transaction.

Frontend tests: `docker compose run --rm frontend pnpm test`.

## Using the API

```bash
# 1. Tokenize a card directly against the processor (payments never sees this)
curl -X POST http://localhost:8000/processor/tokenize \
  -H 'Content-Type: application/json' \
  -d '{"method":"card","number":"4242424242424242","exp_month":12,"exp_year":2099,"cvv":"123"}'
# -> {"token":"tok_...","method":"card","last4":"4242","brand_or_bank_type":"visa"}

# 2. Create a payment with the token and an Idempotency-Key
curl -X POST http://localhost:8000/api/payments \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: order-123' \
  -d '{"amount_minor":4200,"currency":"USD","payment_token":"tok_..."}'
# -> 201 {"id":"...","status":"pending","processor_reference":"pr_...","ledger":[...]}

# 3. Deliver the processor's result as webhooks
docker compose exec backend python manage.py simulate_webhooks \
  --reference pr_... --mode normal

# 4. Read current status + ledger history
curl http://localhost:8000/api/payments/<id>
```

### Test values (decide outcome by last 4 digits)

| Last 4 | Card | Bank |
|---|---|---|
| 0002 | failed: `card_declined` | failed: `insufficient_funds` |
| 0119 | failed: `processor_error` | failed: `processor_error` |
| 0341 | pending 15s, then succeeded | pending 15s, then succeeded |
| anything else | succeeded | succeeded |

`4242 4242 4242 4242` is a valid success card.

### Webhook delivery modes

`simulate_webhooks --reference <ref> --mode <mode>`:

- `normal` — one pending event, then the final event.
- `duplicate` — every event delivered twice (same `event_id`).
- `reverse` — final event first, then pending.
- `concurrent` — two copies of the final event sent simultaneously.

Add `--no-delay` to skip the 15s settle wait in `normal`/`duplicate`.

---

## Design notes

### State transitions

A payment is `pending` on creation and moves to exactly one terminal state:
`pending → succeeded` or `pending → failed`. Terminal states are final.

- A **late `pending`** arriving after a terminal event never regresses the
  status.
- **Conflicting terminals** (e.g. `succeeded` then `failed`): **first terminal
  wins**. Once we have reported a payment as captured, we will not silently flip
  it to failed on a contradictory message; a genuine reversal belongs to a
  separate refund/chargeback flow, which is out of scope. The contradictory
  event is still recorded in the ledger for audit.

These rules live in `payments/state.py` as `apply_transition`, applied by folding
the ledger. The status is therefore **derivable purely from the ledger**;
`Payment.status` is only a cache kept in sync inside the same transaction.

### Idempotency

`POST /api/payments` requires an `Idempotency-Key` header. We store the key with
a SHA-256 fingerprint of the canonical request body and the original response.

- Same key + same body → the original response is returned; nothing new is
  created and the processor is not charged again.
- Same key + different body → `409 Conflict`.

The key column is unique. The create path reserves the key by inserting the
`Payment` row first (inside a savepoint); the processor charge happens in the
same savepoint, so a losing concurrent request rolls back without charging.

### Concurrency and webhook races

- **Payment creation races**: the unique `idempotency_key` constraint plus a
  savepoint make exactly one request win; the loser blocks on
  `SELECT … FOR UPDATE` until the winner commits, then returns the winner's
  response. Result: one payment, one charge.
- **Webhook races**: each delivery takes a `SELECT … FOR UPDATE` row lock on the
  payment, serialising processing. At-most-once is enforced by a **partial unique
  index on `event_id`** — a duplicate delivery fails the insert and is treated as
  a no-op. So two truly concurrent deliveries of the same event produce exactly
  one ledger entry and one correct state.

### Locks and constraints used (and why)

- `SELECT … FOR UPDATE` on the `Payment` row — serialises webhook processing and
  idempotent-create contention without locking the whole table.
- Unique `idempotency_key` — guarantees one payment per key under concurrency.
- Partial unique index on `LedgerEntry.event_id` — at-most-once webhook
  processing and "exactly one ledger entry per event".
- Unique `processor_reference` — one payment per processor charge.

### Append-only ledger — how it is enforced

Two layers:

1. **Database (authoritative)**: migration `payments/0002_ledger_append_only`
   installs a Postgres trigger that raises on any `UPDATE` or `DELETE` of
   `payments_ledgerentry`. No code path — ORM, raw SQL, admin, or a future bug —
   can mutate or delete a ledger row.
2. **Application**: `LedgerEntry.save()` rejects updates and `delete()` is
   disabled, so mistakes fail fast in Python.

Both are covered by tests in `payments/tests/test_append_only.py`.

### What I would change at 10x volume

- Move the processor charge out of the request's transaction (enqueue a Celery
  task after commit) so the `Payment` row lock is not held across an external
  call; return `pending` immediately.
- Add a dedicated `processed_events` table (or keep the ledger) partitioned by
  time, and index the ledger by `(payment_id, id)` for fast folds; cache the
  derived status (already done) and only re-fold on demand.
- Replace the in-process processor call with a real HTTP client behind a circuit
  breaker and retries with idempotency keys.
- Consider sharding/queueing webhook processing by `payment_id` so row-lock
  contention stays local; the current design already scales horizontally because
  all safety comes from DB constraints, not in-memory state.

### Assumptions

- **USD only**, amounts in integer minor units (cents); other currencies are
  rejected at the API boundary.
- Tokenization is a real HTTP endpoint the client calls directly; the charge call
  is in-process (allowed by the brief) behind an adapter that mimics an external
  client.
- Idempotent replay returns the **original** stored response (per the brief),
  even if the live status has since advanced. `GET /api/payments/{id}` always
  reflects the current state.
- The admin-only `POST /api/payments/{id}/replay` re-requests a stuck payment's
  result and applies any terminal outcome via a deterministic `event_id`, so it
  can never double-process against a later real webhook.
- Bank "type" is cosmetic metadata (`checking`/`savings`); routing numbers are
  validated as exactly 9 digits per the brief (no ABA checksum).

## Notable deviations from the boilerplate

- `docker-compose.yml` pins `postgres:16-alpine` (the unpinned `postgres:alpine`
  now resolves to v18, whose data-dir layout breaks the compose volume).
- The generated API client (`frontend/js/api/`) and `backend/schema.yml` are
  committed for reproducibility; regenerate with `make docker_backend_update_schema`
  and `make docker_frontend_update_api`.
- The boilerplate's hand-written frontend was aligned to the generated client's
  `api`-prefixed function names.

## License

The boilerplate is MIT-licensed (see `LICENSE.txt`).
