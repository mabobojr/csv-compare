"""Generate the Test1 sample data: a staging table1.csv and a prod table1.csv.

Both files share the same 20-column schema and hold 100 data rows. The prod copy
is the staging data with a deterministic slice of cell values modified, so the
comparison tool has a known mix of unchanged and changed values to report on.
"""

from __future__ import annotations

import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGING = ROOT / "Test1" / "staging" / "table1.csv"
PROD = ROOT / "Test1" / "prod" / "table1.csv"

ROW_COUNT = 100
CHANGE_RATE = 0.08  # share of cells rewritten in the prod copy

COLUMNS = [
    "employee_id",
    "first_name",
    "last_name",
    "email",
    "department",
    "job_title",
    "salary",
    "bonus_pct",
    "currency",
    "hire_date",
    "country",
    "city",
    "phone",
    "manager_id",
    "cost_center",
    "employment_status",
    "level",
    "is_active",
    "last_login",
    "notes",
]

FIRST_NAMES = [
    "Avery", "Blair", "Casey", "Dakota", "Emerson", "Finley", "Greer", "Harper",
    "Indigo", "Jordan", "Kai", "Logan", "Marlow", "Noor", "Oakley", "Parker",
    "Quinn", "Reese", "Sawyer", "Tatum", "Umber", "Vesper", "Wren", "Xael",
    "Yuki", "Zion",
]
LAST_NAMES = [
    "Alvarez", "Bennett", "Chowdhury", "Delgado", "Ellison", "Fontaine",
    "Garrity", "Hollis", "Iyer", "Janssen", "Kowalski", "Larkin", "Mbeki",
    "Nakamura", "Osei", "Petrov", "Quintero", "Rasmussen", "Sokolova",
    "Thibault", "Ueda", "Vasquez", "Whitfield", "Ximenes", "Yardley", "Zeller",
]
DEPARTMENTS = [
    "Engineering", "Finance", "Marketing", "Operations", "People",
    "Customer Success", "Legal", "Data",
]
JOB_TITLES = [
    "Analyst", "Associate", "Manager", "Senior Manager", "Director",
    "Engineer", "Senior Engineer", "Staff Engineer", "Specialist", "Lead",
]
COUNTRIES = {
    "United States": ["Austin", "Denver", "Seattle", "Boston", "Chicago"],
    "Canada": ["Toronto", "Vancouver", "Montreal"],
    "United Kingdom": ["London", "Manchester", "Bristol"],
    "Germany": ["Berlin", "Munich", "Hamburg"],
    "Japan": ["Tokyo", "Osaka", "Fukuoka"],
    "Brazil": ["Sao Paulo", "Recife", "Curitiba"],
}
CURRENCIES = ["USD", "CAD", "GBP", "EUR", "JPY", "BRL"]
STATUSES = ["Active", "On Leave", "Contractor", "Probation"]
LEVELS = ["L1", "L2", "L3", "L4", "L5", "L6"]
NOTES = [
    "Relocation pending",
    "Awaiting badge issue",
    "Transferred from Ops",
    "Mentor programme",
    "Part-time schedule",
    "",
]


def build_staging(rng: random.Random) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for i in range(ROW_COUNT):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        country = rng.choice(list(COUNTRIES))
        hire = date(2015, 1, 1) + timedelta(days=rng.randrange(0, 3600))
        last_login = datetime(2026, 9, 1) + timedelta(
            days=rng.randrange(0, 22), minutes=rng.randrange(0, 1440)
        )
        rows.append(
            {
                "employee_id": f"E{1001 + i}",
                "first_name": first,
                "last_name": last,
                "email": f"{first.lower()}.{last.lower()}@example.com",
                "department": rng.choice(DEPARTMENTS),
                "job_title": rng.choice(JOB_TITLES),
                "salary": str(rng.randrange(52_000, 215_000, 500)),
                "bonus_pct": f"{rng.uniform(0, 22):.1f}",
                "currency": rng.choice(CURRENCIES),
                "hire_date": hire.isoformat(),
                "country": country,
                "city": rng.choice(COUNTRIES[country]),
                "phone": f"+1-{rng.randrange(200, 999)}-{rng.randrange(200, 999)}-{rng.randrange(1000, 9999)}",
                "manager_id": f"E{rng.randrange(1001, 1101)}",
                "cost_center": f"CC-{rng.randrange(100, 999)}",
                "employment_status": rng.choice(STATUSES),
                "level": rng.choice(LEVELS),
                "is_active": rng.choice(["true", "false"]),
                "last_login": last_login.strftime("%Y-%m-%d %H:%M"),
                "notes": rng.choice(NOTES),
            }
        )
    return rows


def mutate(column: str, value: str, rng: random.Random) -> str:
    """Return a plausible but different value for ``column``."""
    if column == "salary":
        return str(int(value) + rng.randrange(1_000, 18_000, 500))
    if column == "bonus_pct":
        return f"{float(value) + rng.uniform(0.5, 6.0):.1f}"
    if column == "hire_date":
        return (date.fromisoformat(value) + timedelta(days=rng.randrange(1, 400))).isoformat()
    if column == "last_login":
        moved = datetime.strptime(value, "%Y-%m-%d %H:%M") + timedelta(
            days=rng.randrange(1, 9), minutes=rng.randrange(1, 900)
        )
        return moved.strftime("%Y-%m-%d %H:%M")
    if column == "is_active":
        return "false" if value == "true" else "true"
    if column == "manager_id":
        return f"E{rng.randrange(1001, 1101)}"
    if column == "cost_center":
        return f"CC-{rng.randrange(100, 999)}"
    if column == "phone":
        return f"+1-{rng.randrange(200, 999)}-{rng.randrange(200, 999)}-{rng.randrange(1000, 9999)}"
    if column == "email":
        local, _, domain = value.partition("@")
        return f"{local}{rng.randrange(2, 9)}@{domain}"
    if column == "employee_id":  # keep the join key stable
        return value

    pools = {
        "first_name": FIRST_NAMES,
        "last_name": LAST_NAMES,
        "department": DEPARTMENTS,
        "job_title": JOB_TITLES,
        "currency": CURRENCIES,
        "country": list(COUNTRIES),
        "city": [c for cities in COUNTRIES.values() for c in cities],
        "employment_status": STATUSES,
        "level": LEVELS,
        "notes": NOTES,
    }
    pool = [v for v in pools.get(column, []) if v != value]
    return rng.choice(pool) if pool else f"{value}-x"


def build_prod(staging: list[dict[str, str]], rng: random.Random) -> list[dict[str, str]]:
    prod = [dict(row) for row in staging]
    # employee_id is the join key and is deliberately left untouched.
    editable = [c for c in COLUMNS if c != "employee_id"]
    cells = [(r, c) for r in range(ROW_COUNT) for c in editable]
    for row_idx, column in rng.sample(cells, k=round(len(cells) * CHANGE_RATE)):
        prod[row_idx][column] = mutate(column, prod[row_idx][column], rng)
    return prod


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path.relative_to(ROOT)} ({len(rows)} rows x {len(COLUMNS)} columns)")


def main() -> None:
    rng = random.Random(20260923)
    staging = build_staging(rng)
    prod = build_prod(staging, rng)
    write_csv(STAGING, staging)
    write_csv(PROD, prod)

    changed = sum(
        1
        for s, p in zip(staging, prod)
        for column in COLUMNS
        if s[column] != p[column]
    )
    print(f"{changed} of {ROW_COUNT * len(COLUMNS)} cells differ between the two files")


if __name__ == "__main__":
    main()
