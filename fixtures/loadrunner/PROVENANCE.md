# LoadRunner DevWeb fixtures — provenance

Every file here was written by a real run of OpenText Performance Engineering for Developers
(formerly LoadRunner Developer) on the maintainer's machine, and copied byte for byte. Nothing was
edited by hand. LoadRunner never runs in CI (ADR-001).

- **Tool:** DevWeb 26.3.0, build `Release_26.3.0_3751` (console banner and `BUILD_ID.txt`),
  community edition (at most 50 virtual users).
- **Machine:** Intel Core i7-9750H (6 cores, 12 logical processors), Windows 10 Home 19045, DevWeb
  on the host, the system under test in Docker Desktop, reached at `127.0.0.1:8000`.
- **Clock:** local time, UTC+02:00 on these dates (the `startTime` of each `replay_summary.json`).

## Files

| File | Run | Transactions |
|---|---|---|
| `2026-10-17-devweb-probe.db` | Format probe of 2026-10-17, 14:39:19 to 14:39:50 local: 2 virtual users for 30 s, 1 s delay pacing; each iteration requests an existing payment (`get_payment`, passes on 200) and a payment that does not exist (`get_missing_payment`, the API answers 404, so it fails). Nominal mode; the exact commit of the system under test was not recorded. | 120 (60 passed, 60 failed) |
| `2026-10-17-devweb-probe.replay_summary.json` | DevWeb's own summary of the same run | — |
| `2026-10-21-devweb-nominal.db` | The three journeys of `load/loadrunner/` (`main.js`, `scenario.yml`: 6 virtual users, 10 s ramp-up, 60 s, `intervals` pacing of 1 s), 2026-10-21, 14:19:59 to 14:21:10 local. System under test of commit `1e0b00b`, nominal mode (the three regressions set to 0), freshly seeded, Docker engine 29.6.1. | 1,161 (387 per journey, all passed) |
| `2026-10-21-devweb-nominal.replay_summary.json` | DevWeb's own summary of the same run | — |

`*.db` is the `results/devWebDB.db` DevWeb wrote in the script folder. The probe's exact command
line was not recorded. The nominal run (PowerShell; `$L` = repository root, `$W` = a working folder
holding copies of `main.js` and `scenario.yml`):

```powershell
docker compose -f "$L\compose.yaml" up -d --wait --build
Push-Location $W; & DevWeb.exe -mode=load -summary json $W; Pop-Location
docker compose -f "$L\compose.yaml" down
```

DevWeb ran 74 s and exited with 0; `replay_summary.json` was written in the script folder, which
was also the working directory.

## Observed in these files

- 15 tables; only `Transactions (uid, timestamp, name, duration, thinkTime, status)` is read.
  `uid` is the virtual user, `duration` and `thinkTime` are integer milliseconds (`thinkTime` is
  0 on every row), `status` is `Passed` or `Failed`.
- `timestamp` is local time without a UTC offset, written with 3 fraction digits, or fewer when the
  last ones are 0 (`2026-10-17T14:39:20.62`): probe 107 rows with 3 digits, 13 with 2; nominal run
  1,018 with 3, 120 with 2, 23 with 1. None without a fraction was seen.
- `timestamp` marks the **end** of the transaction. Every script here sends each request inside a
  transaction, so each row of table `Hits` (one per request, with its HTTP code) must fall inside
  a transaction of the same virtual user. With spans [timestamp - duration, timestamp], no
  request falls outside every span (probe 0 of 120, nominal run 0 of 1,161); with
  [timestamp, timestamp + duration], many do (53 of 120, 486 of 1,161). A test checks it on both
  files.
- No HTTP status code per transaction: codes are in `Hits`, with no column linking a request to
  its transaction.
- Conformity with DevWeb's own summary: per transaction, the pass and fail counts and the minimum
  and maximum durations of `Transactions` equal those of `replay_summary.json` (both files, checked
  by a test). The summary has one percentile, `90%`, whose method is undocumented.
- DevWeb 26.3 refuses `pacing: type: interval` ("valid values are: delay or intervals"), the
  spelling of its help page and of the comments in its bundled examples; `intervals` is accepted.
