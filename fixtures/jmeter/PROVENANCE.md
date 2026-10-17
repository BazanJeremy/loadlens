# JMeter fixtures — provenance

Every `.jtl` here was written by a real Apache JMeter run, except where a file is marked
"derived". Nothing was edited by hand.

- **Date:** 2026-10-17
- **JMeter:** 5.6.3, image built from `load/jmeter/Dockerfile` (Temurin 21 JRE, archive
  checksum verified with SHA-512 during the build)
- **Plan and settings:** `load/jmeter/loadlens.jmx` with `load/jmeter/loadlens.properties`
- **Target:** the system under test of commit `c373094` (`docker compose up -d --wait`, nominal
  mode, freshly seeded), reached as `api:8000` on the compose network
- **Machine:** Intel Core i7-9750H, Windows 10 Home 19045, Docker Desktop (engine 29.6.1)

## Files

| File | Run | Rows |
|---|---|---|
| `2026-10-17-nominal-short.jtl` | `-Jramp_s=2 -Jhold_s=20`, default rates (4 / 10 / 6 arrivals per second) | 420 |
| `2026-10-17-all-errors.jtl` | `-Jport=9999 -Jramp_s=1 -Jhold_s=3`: nothing listens on that port, every sample fails with a refused connection | 70 |
| `2026-10-17-single-transaction.jtl` | `-Jramp_s=1 -Jhold_s=5 -Jrate_create_payment=0 -Jrate_get_statement=0` | 55 |
| `2026-10-17-empty.jtl` | `-Jramp_s=1 -Jhold_s=2` with all three rates at 0: JMeter writes the header line only | 0 |
| `2026-10-17-nominal-short-head10.jtl` | **Derived:** header + first 10 data rows of `2026-10-17-nominal-short.jtl` (`head -11`), small enough to check KPIs by hand | 10 |

## Command (PowerShell; `$L` = repository root, `$O` = output folder)

```powershell
docker build -t loadlens-jmeter:5.6.3 "$L\load\jmeter"
docker compose -f "$L\compose.yaml" up -d --wait
docker run --rm --network loadlens-sut_default -v "$L\load\jmeter:/plan:ro" -v "${O}:/out" `
  loadlens-jmeter:5.6.3 -n -t /plan/loadlens.jmx -q /plan/loadlens.properties `
  -l /out/<name>.jtl -j /out/<name>.log -Jhost=api <run options above>
```

## Observed in these files

- 14 columns, in the order fixed by the JMeter manual (section 12.4), LF line endings, no quoted
  field.
- A transport error has a non-numeric `responseCode`
  (`Non HTTP response code: org.apache.http.conn.HttpHostConnectException`) and an empty
  `failureMessage` (the plan has no assertion).
- Arrival counts match the open-model schedule exactly: 84 / 210 / 126 samples for rates
  4 / 10 / 6 per second over 2 s of ramp and 20 s of hold.
