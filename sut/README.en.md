# System under test: payments API

> 🇫🇷 [Version française](README.md)

An HTTP payments API (FastAPI + PostgreSQL), bundled with loadlens so that regression detection
works on real slowdowns. Three realistic regressions can be switched on with environment
variables; all are off by default.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/payments` | Debits an account in favour of a merchant. `201`, `404` (unknown account or merchant), `409` (`insufficient_funds`), `422` (invalid body) |
| `GET` | `/payments/{id}` | Reads a payment. `200`, `404`, `422` |
| `GET` | `/accounts/{id}/statement` | Paginated statement, newest first. `limit` 1–200 (default 50), `cursor` = `next_cursor` of the previous page |
| `GET` | `/health` | Database status and active regressions |

The account debit is an atomic `UPDATE … WHERE balance_cents >= amount`: two simultaneous
payments cannot lose an update (tested with 20 concurrent payments).

## Run

```powershell
docker compose up -d --build --wait
python -m pytest sut/tests
docker compose down
```

Every `docker compose up` re-runs the `seed` job, which **drops and reloads** the database: every
run starts from the same data.

## Seed data

Generated deterministically (`payments_api/seed_data.py`, seed `42`): 1,000 accounts, 5,000
merchants, 100,000 payments. Tunable through `SEED_ACCOUNTS`, `SEED_MERCHANTS`, `SEED_PAYMENTS`
and `SEED_RANDOM_SEED`. The last account (no. 1,000 by default) is created **empty and without
payments**, to exercise the insufficient-funds path: a load plan must not target it.

## Switchable regressions

| Variable | Mechanism | Where it shows |
|---|---|---|
| `SUT_REGRESSION_N_PLUS_ONE=1` | The statement no longer joins merchants: each distinct merchant on the page is loaded by its own query, i.e. up to 50 extra queries for a page of 50 (exact count not measured) | `GET /accounts/{id}/statement`, even without concurrency |
| `SUT_REGRESSION_LOCK=1` | Every payment updates the same daily-total row inside its transaction: all payments queue on its lock until commit | `POST /payments` under concurrency |
| `SUT_REGRESSION_POOL=1` | Connection pool shrunk to 1 (instead of 10 + 10 overflow) | Any request under concurrency |

The functional tests pass identically in all four modes: a regression changes performance, never
results.

## Hand measurements (2026-10-17)

Source: `sut/measurements/2026-10-17-manual.jsonl`, produced by `sut/tools/measure.py`.

- **Machine:** Intel Core i7-9750H, Windows 10 Home 19045, Docker Desktop (engine 29.6.1,
  12 CPUs, 7.7 GiB allotted). The Python client runs on the host and goes through Docker
  Desktop's port proxy: absolute values measure the whole chain. Only comparisons between modes on
  this machine are meaningful.
- **Protocol:** database reloaded before each mode, 50 warm-up requests discarded, order
  nominal → N+1 → LOCK → POOL → nominal. **One run per mode**: these are orders of magnitude, not
  baselines.

p50 / p95 in ms, then throughput in requests per second:

| Scenario | Nominal | N+1 | LOCK | POOL | Nominal (2nd run) |
|---|---|---|---|---|---|
| Statement, concurrency 1, 300 req. | 6.0 / 6.8 · 160 | **29.0 / 33.7 · 34** | 6.1 / 7.4 · 157 | 6.8 / 9.5 · 138 | 6.2 / 8.2 · 151 |
| Payment read, concurrency 32, 2,000 req. | 84.2 / 113.4 · 363 | 84.9 / 118.3 · 356 | 98.7 / 143.0 · 308 | **105.9 / 172.6 · 274** | 86.8 / 120.7 · 346 |
| Payment write, concurrency 32, 2,000 req. | 171.9 / 239.2 · 182 | 176.8 / 250.4 · 176 | **171.7 / 589.2 · 137** | 169.2 / 222.3 · 182 | 176.0 / 248.5 · 178 |

What these measurements show:

- **N+1** multiplies the statement's median latency by 4.7 to 4.8 (depending on the nominal run
  taken as reference), even without concurrency.
- **LOCK** only acts on the tail of the distribution: the write median does not move, but p95
  goes from 239–249 to 589 ms and p99 from about 264–289 to 932 ms. A median-centred indicator
  would miss this regression.
- **POOL** degrades concurrent reads (p95 +43 to +52%, throughput −21 to −25% against the two
  nominal runs). On writes, at this concurrency, no net effect shows: **cause unknown**.
- **Noise:** between the two nominal runs, the statement p95 moves from 6.8 to 8.2 ms (+21%).
  Shifts with no known mechanism also appear (LOCK on reads, POOL on the statement at
  concurrency 1): **cause unknown**. These shifts are of the same order as some thresholds; this
  is why loadlens will not conclude from a single run.

## Limits

- Schema created by `metadata.create_all`, without migrations: the database is disposable by
  design.
- The PostgreSQL credentials `sut` / `sut` only serve this local container.
- One API instance, one Uvicorn process, no access log: a measurement target, not a production
  service.
