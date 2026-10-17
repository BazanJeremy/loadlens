# JMeter plan

> 🇫🇷 [Version française](README.md)

The `loadlens.jmx` plan loads the three journeys of the system under test, each with its own
arrival rate (**open workload model**): a slower service does not reduce the load sent to it.
JMeter runs in a container (`Dockerfile`: JMeter 5.6.3 on Temurin 21, archive verified by
SHA-512), the same locally and in CI: no Java is needed on the machine.

## Run locally (PowerShell, from the repository root)

```powershell
docker build -t loadlens-jmeter:5.6.3 load/jmeter
docker compose up -d --wait
New-Item -ItemType Directory -Force results | Out-Null
docker run --rm --network loadlens-sut_default `
  -v "${PWD}/load/jmeter:/plan:ro" -v "${PWD}/results:/out" `
  loadlens-jmeter:5.6.3 -n -t /plan/loadlens.jmx -q /plan/loadlens.properties `
  -l /out/jmeter.jtl -j /out/jmeter.log -Jhost=api -Jramp_s=10 -Jhold_s=120
loadlens kpi results/jmeter.jtl --warmup-s 10
docker compose down
```

## Parameters (`-Jname=value`)

| Property | Default | Purpose |
|---|---|---|
| `host`, `port` | `127.0.0.1`, `8000` | Target (`api` / `8000` on the compose network) |
| `ramp_s` | `10` | Linear ramp from 0 to the target rate |
| `hold_s` | `60` | Hold at the target rate |
| `rate_create_payment` | `4` | Arrivals per second on `POST /payments` |
| `rate_get_payment` | `10` | Arrivals per second on `GET /payments/{id}` |
| `rate_get_statement` | `6` | Arrivals per second on `GET /accounts/{id}/statement` |
| `funded_accounts`, `merchants`, `seeded_payments` | `999`, `5000`, `100000` | Bounds of the randomly drawn ids (the empty account no. 1,000 is excluded) |
| `connect_timeout_ms`, `response_timeout_ms` | `5000`, `30000` | HTTP timeouts |

The arrival-schedule seeds are fixed (`101`, `202`, `303`): two runs receive the same schedule.

## JMeter best practices applied

From the [official guide](https://jmeter.apache.org/usermanual/best-practices.html):

- **CLI mode** (`-n`), no listener in the plan;
- **CSV output** limited to the useful columns, set in `loadlens.properties` (loaded with `-q`),
  never by editing `jmeter.properties`;
- **properties for every parameter** (`${__P()}` + `-J`), no hard-coded value;
- **no deprecated element**, no superfluous assertion: the HTTP status decides success;
- **open workload model** (Open Model Thread Group). The documentation recommends it over a
  throughput timer and marks it "experimental", which is why the JMeter version is pinned.

## Local measurement of the CI profile (2026-10-17)

Source: one local run of `ramp_s=10`, `hold_s=120`, rates 4 / 10 / 6, on the machine described
in `fixtures/jmeter/PROVENANCE.md`.

- 2,500 samples over a 130 s schedule; without the 10 s ramp, 2,386 samples at 19.97 requests per
  second (target: 20), 0 errors.
- The container ran for 192.5 s for a 130 s schedule: **cause of the gap unknown**.
- Coefficient of variation of raw latencies: 0.47 overall, 0.32 to 0.38 per transaction.
- JTL latencies are whole milliseconds: with a 9 ms p95, a 10% increase (0.9 ms) is below the
  measurement resolution.

## Limits

- The load generator and the system under test share the same machine: JMeter uses CPU the
  service no longer has.
- The open model starts one JMeter thread per arrival. Whether HTTP connections are reused from
  one arrival to the next has not been verified (the `Connect` column is often 0 ms, which does
  not tell a reused connection from a local connection under a millisecond).
