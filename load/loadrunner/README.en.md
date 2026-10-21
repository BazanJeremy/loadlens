# DevWeb script (LoadRunner)

> 🇫🇷 [Version française](README.md)

`main.js` loads the three journeys of the system under test with **OpenText Performance
Engineering for Developers** (formerly LoadRunner Developer, DevWeb protocol). loadlens then reads
the result database DevWeb writes (`devWebDB.db`) and gives a verdict on the SLOs. LoadRunner never
runs in CI: its results are produced locally, then committed with a date in
[`fixtures/loadrunner/`](../../fixtures/loadrunner/PROVENANCE.md) (ADR-001).

## The script

- One iteration calls each journey once, each in its own transaction: `create_payment` (passes on
  201), `get_payment` and `get_statement` (pass on 200). Any other code, or a transport error,
  fails it, and the iteration goes on with the next journey.
- Identifiers are drawn at random within the ranges of the seed data, the same as in the
  [JMeter plan](../jmeter/README.en.md).
- `scenario.yml`: **closed model**, 6 virtual users, 10 s of ramp-up then 60 s of load, `intervals`
  pacing of 1 s. According to the DevWeb help, this pacing sets the time from one iteration start
  to the next, and an iteration waits for the previous one to finish: as long as an iteration takes
  less than a second, the declared rate is **6 per second per transaction**. The help spells it
  `interval`, which DevWeb 26.3 refuses.

## Run locally (PowerShell)

Prerequisites: DevWeb extracted in a folder (`$DW` below), Docker Desktop running. `$L` is the
repository root, `$W` a working folder outside the repository (DevWeb writes `results\` there).

```powershell
New-Item -ItemType Directory -Force $W | Out-Null
Copy-Item "$L\load\loadrunner\main.js", "$L\load\loadrunner\scenario.yml" $W
docker compose -f "$L\compose.yaml" up -d --wait --build
Push-Location $W; & "$DW\DevWeb.exe" -mode=load -summary json $W; Pop-Location
docker compose -f "$L\compose.yaml" down
loadlens verdict --config "$L\config\slo.yaml" --candidate "$W\results\devWebDB.db" `
  --utc-offset +02:00 --warmup-s 10 `
  --target-rps create_payment=6 --target-rps get_payment=6 --target-rps get_statement=6
```

`--utc-offset` is required: the timestamps in `devWebDB.db` are local time, without an offset. The
`startTime` of the `replay_summary.json` DevWeb writes gives it.

## Licence

The free edition (community licence) is limited to **50 virtual users**, one test at a time and
the DevWeb protocol only, for test development and proof-of-concept use; any commercial use is
prohibited (OpenText, Additional License Authorizations 5200-1957, read on 2026-10-16). Its
binaries are never committed nor downloaded in CI. The same licence forbids publishing detailed
comparisons with other tools: loadlens publishes no JMeter and LoadRunner figures side by side.

## Known limitations (v1)

- **Verdict on SLOs alone**: p99 and error rate (hard), p95, Apdex and throughput (soft).
  `loadlens verdict` refuses a baseline (`--baseline`) with a DevWeb result: the regression
  detector was calibrated on JMeter results only ([docs/calibration.md](../../docs/calibration.md)).
- **No A-B-B-A protocol and no verdict parity on the LoadRunner side**: the proof that the N+1
  regression ends FAIL exists for the JMeter chain only.
- No HTTP code per transaction in `devWebDB.db`; a transaction's start is computed (end timestamp
  minus duration), see the [provenance](../../fixtures/loadrunner/PROVENANCE.md).
