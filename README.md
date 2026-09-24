# csv-compare

A command-line tool that compares two CSV files **row by row and column by
column**, and reports every cell as either unchanged or changed.

Built for the common data-engineering problem of proving what actually differs
between a staging extract and a production one.

```
csv file name  column name  staging value                prod value                    status
-------------  -----------  ---------------------------  ----------------------------  ---------
table1.csv     employee_id  E1001                        E1001                         No change
table1.csv     hire_date    2024-09-29                   2025-10-07                    Changed
table1.csv     cost_center  CC-115                       CC-423                        Changed
table1.csv     email        sawyer.nakamura@example.com  sawyer.nakamura2@example.com  Changed
```

Running it against the included sample data:

```
compared 2000 cells across 20 columns and 100 rows
  No change         1848
  Changed            152
changed cells by column:
  salary                14
  cost_center           10
  currency              10
  ...
```

## Install

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e .        # Windows
# source .venv/bin/activate && pip install -e .     # macOS / Linux
```

That installs a `compare-csv` command. Without installing, call the script
directly with `python compare_csv.py ...`.

## Use

```bash
compare-csv staging.csv prod.csv --key employee_id -o report.txt
```

`--key` names the column that identifies a row. Without it, rows are matched by
position — which means a single inserted row makes everything after it look
changed. Match by key whenever the data has one.

Try it against the bundled sample data:

```bash
python generate_test_data.py     # writes Test1/staging and Test1/prod
compare-csv Test1/staging/table1.csv Test1/prod/table1.csv --key employee_id -o Test1/comparison_report.txt
```

## The report

One row per compared cell:

| column          | meaning                                        |
| --------------- | ---------------------------------------------- |
| `csv file name` | the staging file's name                        |
| `column name`   | the column, taken from the staging file        |
| `staging value` | the value as written in the staging file       |
| `prod value`    | the value as written in the prod file          |
| `status`        | `No change` or `Changed`                       |

Two further statuses appear only when the files differ structurally:
`Row missing` (a row in one file only) and `Column missing` (a column in one
file only).

Output format follows the `--output` suffix: `.txt` writes an aligned
plain-text table, anything else writes CSV.

## Options

| flag                               | effect                                                        |
| ---------------------------------- | ------------------------------------------------------------- |
| `--key COL [COL ...]`              | match rows by these columns instead of by position             |
| `-o, --output PATH`                | write the report (`.txt` or `.csv`)                            |
| `--format {auto,txt,csv}`          | override the format inferred from the suffix                   |
| `--status {all,changed,unchanged}` | filter which rows reach the report                             |
| `--include-row-key`                | add a `row key` column identifying each row                    |
| `--ignore-columns COL [COL ...]`   | exclude columns from the comparison                            |
| `--name NAME`                      | override the `csv file name` value                             |
| `--delimiter`, `--encoding`        | non-default CSV dialect                                        |
| `--ignore-case`, `--trim`          | loosen value matching                                          |
| `--show N`                         | preview N rows on stdout (default 10, `0` for none)            |
| `--exit-zero`                      | always exit 0                                                  |

Exit codes follow the `diff` convention: `0` identical, `1` differences found,
`2` error — so it composes with shell scripts and CI.

```bash
compare-csv staging.csv prod.csv --key id || echo "drift detected"
```

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

36 tests covering the comparison logic, row and column alignment, value
fidelity when reading, every comparison flag, and the CLI's exit-code contract.
Most run through the file-reading path rather than hand-built DataFrames, so
they exercise the code where type-inference and missing-value bugs actually
live.

The suite was checked by mutation testing — deliberately breaking the code in
eight ways and confirming tests fail each time:

| mutation                             | tests failed |
| ------------------------------------ | ------------ |
| remove `dtype=str`                   | 4            |
| never flag `Row missing`             | 3            |
| never flag `Column missing`          | 2            |
| drop prod-only rows from alignment   | 2            |
| remove NA handling                   | 2            |
| drop duplicate-key suffixing         | 1            |
| ignore `--trim`                      | 1            |
| ignore `--ignore-case`               | 1            |

## Design notes

**Rows and columns align independently.** Columns match by name, so reordering
them between files changes nothing. Rows match by key when `--key` is given and
by position otherwise. Keeping these separate is what lets the tool report *one
added row* rather than *every row changed* when a row is inserted.

**Values are read as text.** `read_csv` disables pandas' type inference and
missing-value conversion. Without that, `007` becomes `7`, and — more subtly —
blank cells become `NaN`, which is never equal to itself, so two empty cells
would report as changed.

**Duplicate keys pair in order of appearance.** A key appearing three times in
both files produces three comparisons, not the nine a SQL-style join would
give, and nothing is silently dropped.

**Normalisation affects the verdict, not the record.** `--ignore-case` and
`--trim` change whether a cell counts as changed; the report still shows the
original values as written.

**The difference count is taken before any display filtering**, so the exit
code reflects the data rather than the flags used to view it.

## Known limits

- The report is held in memory as a long-format frame at roughly 330 bytes per
  cell, so a pair of million-row files would need several GB. There is no
  chunking; this is sized for files that fit comfortably in RAM.
- The comparison loop is Python rather than vectorised pandas — around 700k
  cells/second, chosen for readability over throughput.
- Duplicate column names within one file are mangled by pandas (`name`,
  `name.1`) and reported under the mangled name.

## Note on authorship

This project was built with AI assistance (Claude), with the design decisions,
review, and testing direction my own. The design notes above describe choices I
can speak to in detail.

## License

MIT — see [LICENSE](LICENSE).
