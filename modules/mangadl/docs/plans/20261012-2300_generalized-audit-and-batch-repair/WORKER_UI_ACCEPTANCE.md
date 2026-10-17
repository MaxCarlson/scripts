# Shared repair worker/UI acceptance

Run: `20261012-235823-d403c901` (America/Los_Angeles).
Isolated destination: `E:\Temp\md-ui-03895c`; scratch: `E:\Temp`.

The fixture used the original three gallery folder names, valid small placeholder
images for non-target pages, and missing pages 1–3 in each gallery. Production
files were not moved or deleted. Only nine real source images were downloaded.

Repair options: `-w 3 -L 0` with the standard UI enabled. One manager run
dispatched workers 01/02/03 at 23:58:23.884, 23:58:23.994, and 23:58:24.100,
respectively. The normal dashboard displayed all three concurrent workers,
individual target totals of 3 pages, advancing page bars, transfer rates, and
the standard runtime worker controls.

One source request received HTTP 429. gallery-dl waited and retried normally;
the queue completed with three successful jobs and all repairs verified.

The result file confirms 3 verified actions, 0 failures, one archive backup,
and one repair guard. Each folder has every expected numbered page valid:
192/192, 160/160, and 76/76. The scratch manifest finished with `pending=false`.
The fixture remains available at the isolated destination for inspection.

Automated tests additionally prove that three jobs use/reuse a two-worker pool,
each worker receives only its URL's page range, JSON stdout stays clean, and
failed repair queues retain a compatible pending-scratch resume baseline.
Final suite: 276 MangaDL tests passed; Ruff and compilation passed.
