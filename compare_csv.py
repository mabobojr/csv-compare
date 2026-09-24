#!/usr/bin/env python3
"""Compare two CSV files row by row and column by column.

The comparison produces a long-format pandas DataFrame with one record per
compared cell:

    csv file name | column name | staging value | prod value | status

The file name and the column names are taken from the staging file. ``status``
is "No change" when the two values match and "Changed" when they do not. Two
further statuses cover structural differences: "Row missing" when a row exists
in only one file, and "Column missing" when a column exists in only one file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

NO_CHANGE = "No change"
CHANGED = "Changed"
ROW_MISSING = "Row missing"
COLUMN_MISSING = "Column missing"

REPORT_COLUMNS = [
    "csv file name",
    "column name",
    "staging value",
    "prod value",
    "status",
]
ROW_KEY_COLUMN = "row key"


class CompareError(Exception):
    """Raised for user-facing problems (missing file, bad key column, ...)."""


def read_csv(path: Path, delimiter: str, encoding: str) -> pd.DataFrame:
    """Read a CSV as plain strings so values are compared exactly as written."""
    if not path.is_file():
        raise CompareError(f"not a readable file: {path}")
    try:
        frame = pd.read_csv(
            path,
            sep=delimiter,
            encoding=encoding,
            dtype=str,
            keep_default_na=False,
            na_filter=False,
        )
    except UnicodeDecodeError as exc:
        raise CompareError(f"{path}: cannot decode as {encoding} ({exc})") from exc
    except pd.errors.ParserError as exc:
        raise CompareError(f"{path}: not valid CSV ({exc})") from exc
    frame.columns = [str(c) for c in frame.columns]
    return frame


def normalise(value: str, *, ignore_case: bool, trim: bool) -> str:
    if trim:
        value = value.strip()
    if ignore_case:
        value = value.casefold()
    return value


def row_keys(frame: pd.DataFrame, keys: list[str] | None) -> list[str]:
    """Build the per-row label used to line the two files up."""
    if not keys:
        return [f"row {i + 1}" for i in range(len(frame))]

    missing = [k for k in keys if k not in frame.columns]
    if missing:
        raise CompareError(f"key column(s) not present in file: {', '.join(missing)}")

    labels: list[str] = []
    seen: dict[str, int] = {}
    for values in zip(*(frame[k].tolist() for k in keys)):
        label = "|".join(str(v) for v in values)
        seen[label] = seen.get(label, 0) + 1
        # Duplicate keys are paired in order of appearance rather than dropped.
        labels.append(label if seen[label] == 1 else f"{label} #{seen[label]}")
    return labels


def align_rows(
    staging_keys: list[str], prod_keys: list[str]
) -> list[tuple[str, int | None, int | None]]:
    """Pair rows by key, keeping staging order and appending prod-only rows."""
    prod_index = {key: i for i, key in enumerate(prod_keys)}
    pairs: list[tuple[str, int | None, int | None]] = [
        (key, i, prod_index.get(key)) for i, key in enumerate(staging_keys)
    ]
    staging_index = set(staging_keys)
    pairs.extend(
        (key, None, i) for i, key in enumerate(prod_keys) if key not in staging_index
    )
    return pairs


def build_report(
    staging: pd.DataFrame,
    prod: pd.DataFrame,
    file_name: str,
    *,
    keys: list[str] | None = None,
    ignore_columns: list[str] | None = None,
    ignore_case: bool = False,
    trim: bool = False,
) -> pd.DataFrame:
    """Compare two frames cell by cell and return the long-format report."""
    ignored = set(ignore_columns or [])
    staging_cols = [c for c in staging.columns if c not in ignored]
    prod_cols = [c for c in prod.columns if c not in ignored]
    # Column by column: staging order first, then columns only present in prod.
    all_cols = staging_cols + [c for c in prod_cols if c not in set(staging_cols)]

    pairs = align_rows(row_keys(staging, keys), row_keys(prod, keys))
    staging_values = {c: staging[c].tolist() for c in staging_cols}
    prod_values = {c: prod[c].tolist() for c in prod_cols}

    records: list[tuple[str, str, str, str, str, str]] = []
    for key, si, pi in pairs:
        for column in all_cols:
            in_staging = column in staging_values and si is not None
            in_prod = column in prod_values and pi is not None
            sval = staging_values[column][si] if in_staging else ""
            pval = prod_values[column][pi] if in_prod else ""

            if column not in staging_values or column not in prod_values:
                status = COLUMN_MISSING
            elif si is None or pi is None:
                status = ROW_MISSING
            elif normalise(sval, ignore_case=ignore_case, trim=trim) == normalise(
                pval, ignore_case=ignore_case, trim=trim
            ):
                status = NO_CHANGE
            else:
                status = CHANGED

            records.append((key, file_name, column, sval, pval, status))

    return pd.DataFrame(records, columns=[ROW_KEY_COLUMN, *REPORT_COLUMNS])


def summarise(report: pd.DataFrame) -> str:
    counts = report["status"].value_counts()
    lines = [
        f"compared {len(report)} cells across "
        f"{report['column name'].nunique()} columns and "
        f"{report[ROW_KEY_COLUMN].nunique()} rows",
    ]
    for status in (NO_CHANGE, CHANGED, ROW_MISSING, COLUMN_MISSING):
        if counts.get(status, 0):
            lines.append(f"  {status:<15}{counts[status]:>7}")

    changed_cols = report[report["status"] == CHANGED]["column name"].value_counts()
    if not changed_cols.empty:
        lines.append("changed cells by column:")
        lines.extend(f"  {col:<20}{n:>4}" for col, n in changed_cols.items())
    return "\n".join(lines)


def render_table(frame: pd.DataFrame) -> str:
    """Render the report as a fixed-width plain-text table."""
    columns = list(frame.columns)
    rows = [[str(v) for v in row] for row in frame.itertuples(index=False)]
    widths = [
        max([len(col), *(len(row[i]) for row in rows)] if rows else [len(col)])
        for i, col in enumerate(columns)
    ]
    lines = [
        "  ".join(col.ljust(w) for col, w in zip(columns, widths)).rstrip(),
        "  ".join("-" * w for w in widths),
    ]
    lines.extend(
        "  ".join(value.ljust(w) for value, w in zip(row, widths)).rstrip()
        for row in rows
    )
    return "\n".join(lines) + "\n"


def write_report(frame: pd.DataFrame, path: Path, fmt: str, encoding: str) -> str:
    """Write the report, choosing the format from ``fmt`` or the file suffix."""
    if fmt == "auto":
        fmt = "txt" if path.suffix.lower() in {".txt", ".text"} else "csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "txt":
        path.write_text(render_table(frame), encoding=encoding)
    else:
        frame.to_csv(path, index=False, encoding=encoding)
    return fmt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="compare_csv",
        description="Compare two CSV files row by row and column by column.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "example:\n"
            "  python compare_csv.py Test1/staging/table1.csv Test1/prod/table1.csv "
            "--key employee_id -o Test1/comparison_report.txt"
        ),
    )
    parser.add_argument("staging", type=Path, help="the staging CSV file")
    parser.add_argument("prod", type=Path, help="the prod CSV file")
    parser.add_argument(
        "--key",
        nargs="+",
        metavar="COL",
        help="column(s) identifying a row; without it rows are matched by position",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="write the report DataFrame to this path (.txt or .csv)",
    )
    parser.add_argument(
        "--format",
        choices=["auto", "txt", "csv"],
        default="auto",
        help="output format; auto picks from the output suffix (default: auto)",
    )
    parser.add_argument(
        "--status",
        choices=["all", "changed", "unchanged"],
        default="all",
        help="restrict the report to rows with this status (default: all)",
    )
    parser.add_argument(
        "--include-row-key",
        action="store_true",
        help="prepend the 'row key' column identifying which row a cell came from",
    )
    parser.add_argument(
        "--ignore-columns",
        nargs="+",
        metavar="COL",
        default=[],
        help="columns to leave out of the comparison entirely",
    )
    parser.add_argument(
        "--name",
        help="value for the 'csv file name' column (default: the staging file name)",
    )
    parser.add_argument("--delimiter", default=",", help="field delimiter (default: ,)")
    parser.add_argument(
        "--encoding", default="utf-8", help="file encoding (default: utf-8)"
    )
    parser.add_argument(
        "--ignore-case", action="store_true", help="compare values case-insensitively"
    )
    parser.add_argument(
        "--trim",
        action="store_true",
        help="ignore leading/trailing whitespace in values",
    )
    parser.add_argument(
        "--show",
        type=int,
        default=10,
        metavar="N",
        help="preview N report rows on stdout, 0 for none (default: 10)",
    )
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="always exit 0; by default differences exit 1",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        staging = read_csv(args.staging, args.delimiter, args.encoding)
        prod = read_csv(args.prod, args.delimiter, args.encoding)
        report = build_report(
            staging,
            prod,
            args.name or args.staging.name,
            keys=args.key,
            ignore_columns=args.ignore_columns,
            ignore_case=args.ignore_case,
            trim=args.trim,
        )
    except CompareError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"staging: {args.staging}")
    print(f"prod   : {args.prod}")
    print(summarise(report))
    differences = int((report["status"] != NO_CHANGE).sum())

    if args.status == "changed":
        report = report[report["status"] != NO_CHANGE]
    elif args.status == "unchanged":
        report = report[report["status"] == NO_CHANGE]
    if not args.include_row_key:
        report = report[REPORT_COLUMNS]
    report = report.reset_index(drop=True)

    if args.show:
        preview = report[report["status"] != NO_CHANGE]
        if preview.empty:
            preview = report
            print(f"\nfirst {min(args.show, len(preview))} report rows:")
        else:
            print(f"\nfirst {min(args.show, len(preview))} differing cells:")
        print(render_table(preview.head(args.show)), end="")

    if args.output:
        fmt = write_report(report, args.output, args.format, args.encoding)
        print(f"\nreport written to {args.output} ({len(report)} rows, {fmt})")

    if differences and not args.exit_zero:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
