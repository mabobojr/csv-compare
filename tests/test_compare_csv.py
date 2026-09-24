"""Tests for compare_csv.

Most tests go through ``read_csv`` rather than building DataFrames by hand, so
they exercise the real file-reading path where the type-inference and
missing-value traps live.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from compare_csv import (
    CHANGED,
    COLUMN_MISSING,
    NO_CHANGE,
    REPORT_COLUMNS,
    ROW_KEY_COLUMN,
    ROW_MISSING,
    CompareError,
    build_report,
    main,
    read_csv,
    render_table,
)


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def compare(tmp_path: Path, staging_text: str, prod_text: str, **kwargs):
    """Write both files, read them back, and return the report."""
    staging = write(tmp_path / "staging.csv", staging_text)
    prod = write(tmp_path / "prod.csv", prod_text)
    return build_report(
        read_csv(staging, ",", "utf-8"),
        read_csv(prod, ",", "utf-8"),
        "table1.csv",
        **kwargs,
    )


def status_of(report, column: str, row_key: str | None = None) -> str:
    rows = report[report["column name"] == column]
    if row_key is not None:
        rows = rows[rows[ROW_KEY_COLUMN] == row_key]
    return rows.iloc[0]["status"]


# --------------------------------------------------------------------------
# Report shape
# --------------------------------------------------------------------------


def test_report_has_the_documented_columns(tmp_path):
    report = compare(tmp_path, "id,city\n1,Oslo\n", "id,city\n1,Oslo\n", keys=["id"])

    assert list(report.columns) == [ROW_KEY_COLUMN, *REPORT_COLUMNS]


def test_one_report_row_per_compared_cell(tmp_path):
    report = compare(
        tmp_path,
        "id,city,tier\n1,Oslo,gold\n2,Lima,silver\n",
        "id,city,tier\n1,Oslo,gold\n2,Lima,silver\n",
        keys=["id"],
    )

    assert len(report) == 2 * 3  # 2 rows x 3 columns


def test_file_name_column_uses_the_supplied_name(tmp_path):
    report = compare(tmp_path, "id,city\n1,Oslo\n", "id,city\n1,Oslo\n", keys=["id"])

    assert set(report["csv file name"]) == {"table1.csv"}


# --------------------------------------------------------------------------
# Core comparison
# --------------------------------------------------------------------------


def test_identical_files_are_all_no_change(tmp_path):
    report = compare(
        tmp_path, "id,city\n1,Oslo\n2,Lima\n", "id,city\n1,Oslo\n2,Lima\n", keys=["id"]
    )

    assert set(report["status"]) == {NO_CHANGE}


def test_changed_cell_reports_both_values(tmp_path):
    report = compare(tmp_path, "id,city\n1,Oslo\n", "id,city\n1,Lima\n", keys=["id"])

    city = report[report["column name"] == "city"].iloc[0]
    assert city["status"] == CHANGED
    assert city["staging value"] == "Oslo"
    assert city["prod value"] == "Lima"


def test_unchanged_columns_stay_no_change_when_a_sibling_changes(tmp_path):
    report = compare(
        tmp_path, "id,city,tier\n1,Oslo,gold\n", "id,city,tier\n1,Lima,gold\n", keys=["id"]
    )

    assert status_of(report, "city") == CHANGED
    assert status_of(report, "tier") == NO_CHANGE


# --------------------------------------------------------------------------
# Structural differences
# --------------------------------------------------------------------------


def test_row_only_in_staging_is_row_missing(tmp_path):
    report = compare(
        tmp_path, "id,city\n1,Oslo\n2,Rome\n", "id,city\n1,Oslo\n", keys=["id"]
    )

    missing = report[report[ROW_KEY_COLUMN] == "2"]
    assert set(missing["status"]) == {ROW_MISSING}
    assert set(missing["prod value"]) == {""}
    assert "Rome" in set(missing["staging value"])


def test_row_only_in_prod_is_row_missing_and_appended_last(tmp_path):
    report = compare(
        tmp_path, "id,city\n1,Oslo\n", "id,city\n1,Oslo\n2,Rome\n", keys=["id"]
    )

    missing = report[report[ROW_KEY_COLUMN] == "2"]
    assert set(missing["status"]) == {ROW_MISSING}
    assert set(missing["staging value"]) == {""}
    # Staging order is preserved, prod-only rows come after it.
    assert list(report[ROW_KEY_COLUMN])[-1] == "2"


def test_column_only_in_staging_is_column_missing(tmp_path):
    report = compare(
        tmp_path, "id,city,tier\n1,Oslo,gold\n", "id,city\n1,Oslo\n", keys=["id"]
    )

    assert status_of(report, "tier") == COLUMN_MISSING
    assert status_of(report, "city") == NO_CHANGE


def test_column_only_in_prod_is_column_missing(tmp_path):
    report = compare(
        tmp_path, "id,city\n1,Oslo\n", "id,city,tier\n1,Oslo,gold\n", keys=["id"]
    )

    tier = report[report["column name"] == "tier"].iloc[0]
    assert tier["status"] == COLUMN_MISSING
    assert tier["prod value"] == "gold"


def test_columns_are_matched_by_name_not_position(tmp_path):
    """Reordered columns must still pair correctly."""
    report = compare(
        tmp_path, "id,city,tier\n1,Oslo,gold\n", "id,tier,city\n1,gold,Oslo\n", keys=["id"]
    )

    assert set(report["status"]) == {NO_CHANGE}


# --------------------------------------------------------------------------
# Row alignment
# --------------------------------------------------------------------------


def test_duplicate_keys_pair_in_order_rather_than_joining(tmp_path):
    report = compare(
        tmp_path, "id,city\n1,Oslo\n1,Rome\n", "id,city\n1,Oslo\n1,Lima\n", keys=["id"]
    )

    # 2 rows x 2 columns, not the 8 cells a cartesian join would produce.
    assert len(report) == 4
    assert sorted(report[ROW_KEY_COLUMN].unique()) == ["1", "1 #2"]
    assert status_of(report, "city", row_key="1") == NO_CHANGE
    assert status_of(report, "city", row_key="1 #2") == CHANGED


def test_rows_are_matched_by_position_without_a_key(tmp_path):
    report = compare(tmp_path, "id,city\n1,Oslo\n2,Lima\n", "id,city\n1,Oslo\n2,Lima\n")

    assert sorted(report[ROW_KEY_COLUMN].unique()) == ["row 1", "row 2"]


def test_inserted_row_shifts_positional_matching_but_not_key_matching(tmp_path):
    """The reason --key exists: an inserted row breaks positional alignment."""
    staging = "id,city\n1,Oslo\n2,Lima\n"
    prod = "id,city\n0,Rome\n1,Oslo\n2,Lima\n"

    positional = compare(tmp_path, staging, prod)
    keyed = compare(tmp_path, staging, prod, keys=["id"])

    assert (positional["status"] == CHANGED).sum() == 4
    assert (keyed["status"] == CHANGED).sum() == 0
    assert (keyed["status"] == ROW_MISSING).sum() == 2


def test_multi_column_keys(tmp_path):
    report = compare(
        tmp_path,
        "region,sku,qty\neu,a1,5\neu,a2,7\n",
        "region,sku,qty\neu,a2,9\neu,a1,5\n",
        keys=["region", "sku"],
    )

    assert status_of(report, "qty", row_key="eu|a1") == NO_CHANGE
    assert status_of(report, "qty", row_key="eu|a2") == CHANGED


def test_unknown_key_column_raises(tmp_path):
    staging = write(tmp_path / "a.csv", "id,city\n1,Oslo\n")
    prod = write(tmp_path / "b.csv", "id,city\n1,Oslo\n")

    with pytest.raises(CompareError, match="key column"):
        build_report(
            read_csv(staging, ",", "utf-8"),
            read_csv(prod, ",", "utf-8"),
            "t.csv",
            keys=["nope"],
        )


# --------------------------------------------------------------------------
# Reading values faithfully
# --------------------------------------------------------------------------


def test_blank_cells_are_not_a_difference(tmp_path):
    """Blanks must read as '' not NaN, since NaN != NaN."""
    report = compare(tmp_path, "id,notes\n1,\n", "id,notes\n1,\n", keys=["id"])

    assert status_of(report, "notes") == NO_CHANGE


def test_literal_na_is_text_not_a_missing_value(tmp_path):
    report = compare(tmp_path, "id,code\n1,NA\n", "id,code\n1,NA\n", keys=["id"])

    code = report[report["column name"] == "code"].iloc[0]
    assert code["staging value"] == "NA"
    assert code["status"] == NO_CHANGE


def test_leading_zeros_are_preserved(tmp_path):
    report = compare(tmp_path, "id,code\n1,007\n", "id,code\n1,007\n", keys=["id"])

    assert report[report["column name"] == "code"].iloc[0]["staging value"] == "007"


def test_quoted_value_containing_a_comma(tmp_path):
    report = compare(
        tmp_path, 'id,name\n1,"Doe, Jane"\n', 'id,name\n1,"Doe, John"\n', keys=["id"]
    )

    name = report[report["column name"] == "name"].iloc[0]
    assert name["staging value"] == "Doe, Jane"
    assert name["status"] == CHANGED


def test_missing_file_raises(tmp_path):
    with pytest.raises(CompareError, match="not a readable file"):
        read_csv(tmp_path / "nope.csv", ",", "utf-8")


# --------------------------------------------------------------------------
# Comparison flags
# --------------------------------------------------------------------------


def test_ignore_case(tmp_path):
    args = (tmp_path, "id,city\n1,Oslo\n", "id,city\n1,OSLO\n")

    assert status_of(compare(*args, keys=["id"]), "city") == CHANGED
    assert status_of(compare(*args, keys=["id"], ignore_case=True), "city") == NO_CHANGE


def test_trim(tmp_path):
    args = (tmp_path, "id,city\n1,  Oslo  \n", "id,city\n1,Oslo\n")

    assert status_of(compare(*args, keys=["id"]), "city") == CHANGED
    assert status_of(compare(*args, keys=["id"], trim=True), "city") == NO_CHANGE


def test_original_values_are_reported_even_when_normalised(tmp_path):
    """--ignore-case changes the verdict, never the values shown."""
    report = compare(
        tmp_path, "id,city\n1,Oslo\n", "id,city\n1,OSLO\n", keys=["id"], ignore_case=True
    )

    city = report[report["column name"] == "city"].iloc[0]
    assert city["staging value"] == "Oslo"
    assert city["prod value"] == "OSLO"


def test_ignore_columns_excludes_them_entirely(tmp_path):
    report = compare(
        tmp_path,
        "id,city,tier\n1,Oslo,gold\n",
        "id,city,tier\n1,Lima,silver\n",
        keys=["id"],
        ignore_columns=["tier"],
    )

    assert "tier" not in set(report["column name"])
    assert status_of(report, "city") == CHANGED


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def test_render_table_includes_headers_and_rows(tmp_path):
    report = compare(tmp_path, "id,city\n1,Oslo\n", "id,city\n1,Lima\n", keys=["id"])

    text = render_table(report)

    assert "column name" in text
    assert "Oslo" in text
    assert text.endswith("\n")


def test_render_table_handles_an_empty_frame(tmp_path):
    """An empty report must not blow up on max() of an empty sequence."""
    report = compare(tmp_path, "id,city\n1,Oslo\n", "id,city\n1,Oslo\n", keys=["id"])
    empty = report[report["status"] == CHANGED]

    text = render_table(empty)

    assert "column name" in text


def test_columns_are_aligned_to_a_fixed_width(tmp_path):
    report = compare(
        tmp_path, "id,city\n1,Oslo\n2,Reykjavik\n", "id,city\n1,Oslo\n2,Reykjavik\n",
        keys=["id"],
    )

    lines = render_table(report).splitlines()

    assert len({len(line.rstrip()) for line in lines}) > 1  # ragged right edge
    assert all(line.startswith("row key") or "  " in line for line in lines[:1])


# --------------------------------------------------------------------------
# The CLI contract
# --------------------------------------------------------------------------


def test_exit_code_zero_when_files_are_identical(tmp_path, capsys):
    a = write(tmp_path / "a.csv", "id,city\n1,Oslo\n")
    b = write(tmp_path / "b.csv", "id,city\n1,Oslo\n")

    assert main([str(a), str(b), "--key", "id", "--show", "0"]) == 0


def test_exit_code_one_when_files_differ(tmp_path, capsys):
    a = write(tmp_path / "a.csv", "id,city\n1,Oslo\n")
    b = write(tmp_path / "b.csv", "id,city\n1,Lima\n")

    assert main([str(a), str(b), "--key", "id", "--show", "0"]) == 1


def test_exit_code_two_when_a_file_is_missing(tmp_path, capsys):
    a = write(tmp_path / "a.csv", "id,city\n1,Oslo\n")

    assert main([str(a), str(tmp_path / "nope.csv"), "--show", "0"]) == 2
    assert "error:" in capsys.readouterr().err


def test_exit_zero_flag_suppresses_the_difference_code(tmp_path, capsys):
    a = write(tmp_path / "a.csv", "id,city\n1,Oslo\n")
    b = write(tmp_path / "b.csv", "id,city\n1,Lima\n")

    assert main([str(a), str(b), "--key", "id", "--show", "0", "--exit-zero"]) == 0


def test_txt_output_is_written(tmp_path, capsys):
    a = write(tmp_path / "a.csv", "id,city\n1,Oslo\n")
    b = write(tmp_path / "b.csv", "id,city\n1,Lima\n")
    out = tmp_path / "report.txt"

    main([str(a), str(b), "--key", "id", "--show", "0", "-o", str(out)])

    text = out.read_text(encoding="utf-8")
    assert "staging value" in text
    assert "Oslo" in text


def test_csv_output_is_written_when_the_suffix_says_so(tmp_path, capsys):
    a = write(tmp_path / "a.csv", "id,city\n1,Oslo\n")
    b = write(tmp_path / "b.csv", "id,city\n1,Lima\n")
    out = tmp_path / "report.csv"

    main([str(a), str(b), "--key", "id", "--show", "0", "-o", str(out)])

    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert header == ",".join(REPORT_COLUMNS)


def test_status_changed_filter_drops_unchanged_rows(tmp_path, capsys):
    a = write(tmp_path / "a.csv", "id,city\n1,Oslo\n")
    b = write(tmp_path / "b.csv", "id,city\n1,Lima\n")
    out = tmp_path / "report.txt"

    main([str(a), str(b), "--key", "id", "--show", "0", "--status", "changed",
          "-o", str(out)])

    text = out.read_text(encoding="utf-8")
    assert NO_CHANGE not in text
    assert CHANGED in text


def test_row_key_column_is_hidden_unless_requested(tmp_path, capsys):
    a = write(tmp_path / "a.csv", "id,city\n1,Oslo\n")
    b = write(tmp_path / "b.csv", "id,city\n1,Lima\n")
    plain = tmp_path / "plain.csv"
    keyed = tmp_path / "keyed.csv"

    main([str(a), str(b), "--key", "id", "--show", "0", "-o", str(plain)])
    main([str(a), str(b), "--key", "id", "--show", "0", "-o", str(keyed),
          "--include-row-key"])

    assert plain.read_text(encoding="utf-8").splitlines()[0] == ",".join(REPORT_COLUMNS)
    assert keyed.read_text(encoding="utf-8").splitlines()[0] == ",".join(
        [ROW_KEY_COLUMN, *REPORT_COLUMNS]
    )
