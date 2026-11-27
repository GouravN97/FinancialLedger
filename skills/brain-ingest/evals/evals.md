# brain-ingest evaluation cases (SK-8, TQ-7)

Run each case before a stage submission and record the result in the table at the bottom.

| # | Input | Expected result |
|---|---|---|
| 1 | URL https://www.sqlite.org/wal.html, requirements not given | New `brain/inbox/sqlite-wal-mode.md` (or similar slug); `requirements` includes FR-3; sources lists the URL; all four body headings present; one new row in `brain/log.md` |
| 2 | Pasted paragraph explaining idempotency keys, author `VishudhaSood` | Note with `requirements: [FR-2]`, author filled, summary in own words (no copied paragraph) |
| 3 | Same URL as case 1 again | Creates `<slug>-2.md` and the reply flags a possible duplicate; the first note is unchanged |
| 4 | A file path that does not exist | No note created, no log row; reply says the source could not be read |
| 5 | Source containing an API key string | Note does not contain the key |

## Results

| Date | Case | Pass/Fail | Notes | Run by |
|---|---|---|---|---|
| | | | | |
