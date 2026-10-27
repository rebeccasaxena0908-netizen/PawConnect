"""
One-time import of the old CSV files (and audit_logs.xml) into the database.

    python scripts/import_csv_to_db.py                 # import data/*.csv into an EMPTY database
    python scripts/import_csv_to_db.py --replace       # wipe the database first, then import
    python scripts/import_csv_to_db.py --from backup/  # read the CSVs from another folder

Everything happens in one transaction: if any row breaks a rule (unknown status,
duplicate e-mail, donation from a user who doesn't exist...) nothing is imported
and the error says which table and row caused it.
"""
import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
from sqlalchemy.exc import IntegrityError, StatementError  # noqa: E402

from analytics import data_handler as dh  # noqa: E402
from config import BASE_DIR, DATABASE_URL, SCHEMAS  # noqa: E402

# Parents before children, so every foreign key already has its target row.
IMPORT_ORDER = ["users", "rescue_cases", "donations", "allocations", "animals",
                "adoption_applications", "inventory"]


def read_csv(folder: Path, name: str) -> list[dict]:
    path = folder / f"{name}.csv"
    if not path.exists():
        print(f"  – {name}.csv not found, skipped")
        return []
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = set(SCHEMAS[name]) - set(df.columns)
    for column in missing:          # older files may lack a newer column
        df[column] = ""
    return df[SCHEMAS[name]].to_dict(orient="records")


def read_audit_xml(folder: Path) -> list[tuple[str, str, str, str, str]]:
    path = folder / "audit_logs.xml"
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    return [(e.get("timestamp"), e.get("actor") or "system", e.get("role") or "System",
             e.get("action") or "UNKNOWN", (e.text or "").strip()) for e in root.iter("event")]


def import_folder(folder: Path, replace: bool = False) -> dict[str, int]:
    dh.ensure_files()                     # run the Alembic migrations first
    counts = {}
    with dh.transaction() as conn:
        if replace:
            dh.clear_all(conn)
        elif not dh.load_table("users", conn=conn).empty:
            raise SystemExit("The database already has data. Use --replace to overwrite it.")
        for name in IMPORT_ORDER:
            rows = read_csv(folder, name)
            for number, row in enumerate(rows, start=2):          # row 1 is the header
                try:
                    dh.append_row(name, row, conn=conn)
                except (IntegrityError, StatementError, ValueError) as error:
                    reason = str(getattr(error, "orig", error)).splitlines()[0]
                    raise SystemExit(f"{name}.csv row {number} can't be imported: {reason}\n"
                                     "Nothing was imported.") from None
            counts[name] = len(rows)
        events = read_audit_xml(folder)
        dh.log_events(events, conn=conn)
        counts["audit_events"] = len(events)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="folder", default=str(BASE_DIR / "data"),
                        help="folder that holds the CSV files (default: data/)")
    parser.add_argument("--replace", action="store_true", help="delete existing rows first")
    args = parser.parse_args()
    print(f"Importing {args.folder} → {DATABASE_URL.split('@')[-1]}")
    counts = import_folder(Path(args.folder), replace=args.replace)
    for name, count in counts.items():
        print(f"  ✅ {name}: {count} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
