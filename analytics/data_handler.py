"""
Data access layer (Unit 4: file handling, `io`, `xml.etree.ElementTree`, pandas I/O).

The tables now live in a SQL database (SQLite by default, PostgreSQL if
DATABASE_URL says so), but the functions keep their old names and shapes:

* load_table(name)  → pandas DataFrame of *text* values ("" for empty), read
                      with pandas.read_sql – exactly what the CSV version returned,
                      so pandas_engine and numpy_stats work unchanged.
* append_row / update_row / find_row / next_id / save_table – one record at a time.

Every writing function takes an optional `conn`. Pass the connection from
`with transaction() as conn:` to make several steps all-or-nothing; leave it
out and the single step runs in its own transaction.

The audit trail is the `audit_events` table; audit_log_bytes() still produces
the same audit_logs.xml file as before, now generated from the database.
"""
from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import (Connection, DateTime, Float, Integer, delete, func, insert, select,
                        update)

from config import DATA_DIR, EXPORT_DIR, SCHEMAS, UPLOAD_DIR  # noqa: F401 (DATA_DIR used by UIs)
from db.engine import get_engine, is_sqlite, reading, transaction  # noqa: F401 (re-exported)
from db.tables import DELETE_ORDER, TABLES, Money, audit_events, metadata

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
# Row order for load_table(). Most ids grow by one (RC-0001, RC-0002 ...), so the id is
# already the order they were added in; donation ids are random, so sort by time instead.
ORDER_BY = {"donations": ["timestamp", "transaction_id"]}


# ======================================================================= set-up
def table(name: str):
    if name not in TABLES:
        raise KeyError(f"Unknown table: {name}")
    return TABLES[name]


def ensure_files() -> None:
    """Create the data folders and bring the database schema up to date (Alembic)."""
    for folder in (DATA_DIR, UPLOAD_DIR, EXPORT_DIR):
        folder.mkdir(parents=True, exist_ok=True)
    from db import init_db
    init_db()


def clear_all(conn: Connection) -> None:
    """Delete every row (children first so no foreign key is broken)."""
    for name in DELETE_ORDER:
        conn.execute(delete(metadata.tables[name]))


def _with(conn: Connection | None, work, write: bool = True):
    """Run work(conn) on the given connection, or open one for it."""
    if conn is not None:
        return work(conn)
    with (transaction() if write else reading()) as own:
        return work(own)


# ======================================================================= text <-> database values
def _to_db(column, value):
    """Text from a form / CSV → the Python type the column needs. "" means NULL."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    kind = column.type
    if isinstance(kind, DateTime):
        if isinstance(value, datetime):
            return value
        text = str(value)
        return datetime.strptime(text[:19], TIME_FORMAT if len(text) > 10 else "%Y-%m-%d")
    if isinstance(kind, Money):
        return Decimal(str(value))
    if isinstance(kind, Integer):
        return int(float(value))
    if isinstance(kind, Float):
        return float(value)
    return str(value)


def _to_text(column, value) -> str:
    """Database value → the text form the rest of the app has always used."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    kind = column.type
    if isinstance(kind, DateTime):
        return pd.Timestamp(value).strftime(TIME_FORMAT)
    if isinstance(kind, Money):
        return f"{Decimal(str(value)):.2f}"
    if isinstance(kind, Integer):
        return str(int(value))
    if isinstance(kind, Float):
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number)
    return str(value)


def _clean_row(name: str, row: dict) -> dict:
    cols = table(name).c
    return {k: _to_db(cols[k], v) for k, v in row.items() if k in cols}


def _text_row(name: str, mapping) -> dict:
    cols = table(name).c
    return {k: _to_text(cols[k], mapping[k]) for k in SCHEMAS[name]}


# ======================================================================= reading
def load_table(name: str, conn: Connection | None = None) -> pd.DataFrame:
    """Whole table as a DataFrame of text (pandas.read_sql + SQLAlchemy select)."""
    t = table(name)
    order = [t.c[col] for col in ORDER_BY.get(name, [])] or list(t.primary_key.columns)
    statement = select(*[t.c[col] for col in SCHEMAS[name]]).order_by(*order)

    def work(c):
        df = pd.read_sql(statement, c)
        for col in SCHEMAS[name]:
            df[col] = [_to_text(t.c[col], value) for value in df[col]]
        return df[SCHEMAS[name]]
    return _with(conn, work, write=False)


def find_row(name: str, key_column: str, key, conn: Connection | None = None) -> dict | None:
    t = table(name)
    statement = select(t).where(t.c[key_column] == _to_db(t.c[key_column], key))

    def work(c):
        found = c.execute(statement).mappings().first()
        return None if found is None else _text_row(name, found)
    return _with(conn, work, write=False)


def next_id(name: str, prefix: str, width: int = 4, conn: Connection | None = None) -> str:
    """Next sequential id, e.g. RC-0046 after RC-0045."""
    t = table(name)
    id_column = t.c[SCHEMAS[name][0]]

    def work(c):
        lock_table(c, name)     # two transactions can't both pick the same number
        numbers = [int(m.group(1)) for (value,) in c.execute(select(id_column))
                   if (m := re.search(r"(\d+)$", str(value)))]
        return f"{prefix}{(max(numbers) + 1 if numbers else 1):0{width}d}"
    return _with(conn, work)


# ======================================================================= writing
def append_row(name: str, row: dict, conn: Connection | None = None) -> None:
    """INSERT one record."""
    values = _clean_row(name, row)
    _with(conn, lambda c: c.execute(insert(table(name)), [values]))


def insert_rows(name: str, rows: list[dict], conn: Connection | None = None) -> int:
    """INSERT many records in one go (used by the seeder and the CSV importer)."""
    values = [_clean_row(name, row) for row in rows]
    if values:
        _with(conn, lambda c: c.execute(insert(table(name)), values))
    return len(values)


def update_row(name: str, key_column: str, key, updates: dict, conn: Connection | None = None,
               expected: dict | None = None) -> bool:
    """
    UPDATE some columns of the row whose key matches. Returns False if no row changed.

    `expected` adds extra WHERE conditions, e.g. expected={"status": "Reported"}.
    The database checks them and changes the row in one atomic step, so if two
    rescuers press "Accept" at the same moment only one UPDATE matches a row.
    """
    t = table(name)
    statement = update(t).where(t.c[key_column] == _to_db(t.c[key_column], key))
    for column, value in (expected or {}).items():
        if isinstance(value, (list, tuple, set)):
            statement = statement.where(t.c[column].in_(list(value)))
        else:
            statement = statement.where(t.c[column] == _to_db(t.c[column], value))
    values = _clean_row(name, {k: v for k, v in updates.items() if k != key_column})
    return _with(conn, lambda c: c.execute(statement.values(**values)).rowcount > 0)


def save_table(name: str, df: pd.DataFrame, conn: Connection | None = None) -> None:
    """Replace the whole table with `df` (delete + insert inside one transaction)."""
    rows = df.reindex(columns=SCHEMAS[name]).fillna("").astype(str).to_dict(orient="records")

    def work(c):
        c.execute(delete(table(name)))
        insert_rows(name, rows, conn=c)
    _with(conn, work)


def lock_table(conn: Connection, name: str) -> None:
    """
    Stop other transactions writing to `name` until this one finishes.
    PostgreSQL: LOCK TABLE. SQLite: already done – our write transactions
    start with BEGIN IMMEDIATE, which locks the whole database file.
    """
    if conn.dialect.name == "postgresql":
        conn.exec_driver_sql(f'LOCK TABLE "{name}" IN SHARE ROW EXCLUSIVE MODE')


# ======================================================================= money
def fund_balance(source_fund: str, conn: Connection | None = None) -> Decimal:
    """Money still available in a fund = successful donations − allocations (exact, in SQL)."""
    donations, allocations = TABLES["donations"], TABLES["allocations"]
    raised = select(func.coalesce(func.sum(donations.c.amount), 0)).where(
        donations.c.contribution_type == source_fund, donations.c.status == "Success")
    used = select(func.coalesce(func.sum(allocations.c.amount), 0)).where(
        allocations.c.source_fund == source_fund)

    def work(c):
        total = Decimal(str(c.execute(raised).scalar_one())) - Decimal(str(c.execute(used).scalar_one()))
        return max(total, Decimal("0.00"))
    return _with(conn, work, write=False)


# ======================================================================= exports
def table_to_csv_bytes(name: str) -> bytes:
    """CSV export through an in-memory buffer (io.StringIO)."""
    df = load_table(name)
    if name == "users":
        df = df.drop(columns=["password_hash"])
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")


def table_to_xml_bytes(name: str, root_tag: str | None = None, row_tag: str = "record") -> bytes:
    """Export any table as structured XML (passwords are never exported)."""
    df = load_table(name)
    if name == "users":
        df = df.drop(columns=["password_hash"])
    root = ET.Element(root_tag or name, {"exported": datetime.now().strftime(TIME_FORMAT),
                                         "count": str(len(df))})
    for record in df.to_dict(orient="records"):
        element = ET.SubElement(root, row_tag)
        for column, value in record.items():
            ET.SubElement(element, column).text = value
    return _xml_bytes(root)


def _xml_bytes(root: ET.Element) -> bytes:
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    buffer = io.BytesIO()
    tree.write(buffer, encoding="utf-8", xml_declaration=True)
    return buffer.getvalue()


def export_backup(names: list[str] | None = None) -> list[Path]:
    """Write CSV + XML copies of the tables into data/exports/<timestamp>/."""
    folder = EXPORT_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name in names or list(SCHEMAS):
        csv_path, xml_path = folder / f"{name}.csv", folder / f"{name}.xml"
        csv_path.write_bytes(table_to_csv_bytes(name))
        xml_path.write_bytes(table_to_xml_bytes(name))
        written += [csv_path, xml_path]
    log_copy = folder / "audit_logs.xml"
    log_copy.write_bytes(audit_log_bytes())
    written.append(log_copy)
    return written


def parse_xml_records(source, row_tag: str = "record") -> pd.DataFrame:
    """Read an XML export back into a DataFrame (used to import offline data)."""
    root = ET.parse(source).getroot()
    rows = [{child.tag: (child.text or "") for child in element} for element in root.iter(row_tag)]
    return pd.DataFrame(rows)


# ======================================================================= audit trail
def log_event(actor: str, role: str, action: str, details: str = "",
              timestamp: str | None = None, conn: Connection | None = None) -> None:
    """Add one row to audit_events."""
    stamp = datetime.strptime(timestamp, TIME_FORMAT) if timestamp else datetime.now().replace(microsecond=0)
    values = {"timestamp": stamp, "actor": (actor or "system")[:60], "role": (role or "System")[:10],
              "action": action[:30], "details": details}
    _with(conn, lambda c: c.execute(insert(audit_events), [values]))


def log_events(events: list[tuple[str, str, str, str, str]], conn: Connection | None = None) -> None:
    """Bulk insert (timestamp, actor, role, action, details) tuples – used by the seeder."""
    rows = [{"timestamp": datetime.strptime(ts, TIME_FORMAT), "actor": actor, "role": role,
             "action": action, "details": details} for ts, actor, role, action, details in events]
    if rows:
        _with(conn, lambda c: c.execute(insert(audit_events), rows))


def read_audit_log() -> pd.DataFrame:
    """Audit events as a DataFrame, newest first (same columns as the old XML reader)."""
    statement = select(audit_events).order_by(audit_events.c.event_id.desc())
    with reading() as conn:
        df = pd.read_sql(statement, conn)
    columns = ["id", "timestamp", "actor", "role", "action", "details"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    df["id"] = [f"EV-{int(n):05d}" for n in df["event_id"]]
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime(TIME_FORMAT)
    df["details"] = df["details"].fillna("")
    return df[columns].reset_index(drop=True)


def audit_log_bytes() -> bytes:
    """The audit trail as audit_logs.xml (same format as the old file), built with ElementTree."""
    root = ET.Element("auditLog", {"system": "PawConnect"})
    with reading() as conn:
        for event in conn.execute(select(audit_events).order_by(audit_events.c.event_id)).mappings():
            ET.SubElement(root, "event", {
                "id": f"EV-{event['event_id']:05d}", "timestamp": event["timestamp"].strftime(TIME_FORMAT),
                "actor": event["actor"], "role": event["role"], "action": event["action"],
            }).text = event["details"] or ""
    return _xml_bytes(root)


def safe_photo_path(case_id: str, original_name: str) -> Path:
    extension = Path(original_name).suffix.lower()
    extension = extension if re.fullmatch(r"\.(jpe?g|png|webp)", extension) else ".jpg"
    return UPLOAD_DIR / f"{case_id}{extension}"
