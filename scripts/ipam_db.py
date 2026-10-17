#!/usr/bin/env python3
"""ipam_db.py - PostgreSQL CLI helper for the IPAM agent.

Usage:
    python3 scripts/ipam_db.py init                 # Apply sql/schema.sql
    python3 scripts/ipam_db.py query "SELECT ..."   # Read-only query (table or --json output)
    python3 scripts/ipam_db.py exec "INSERT ..."    # Execute a write statement (DML/DDL)

Connection is read from the IPAM_DB_URL environment variable, or a .env
file at the project root (never commit .env).
"""
import argparse
import json
import os
import sys
from pathlib import Path

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    print("FAILURE: psycopg is not installed. Run: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    """Load .env from the project root without overriding real env vars."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_conn(read_only=False):
    """Open a connection using IPAM_DB_URL."""
    load_env()
    url = os.environ.get("IPAM_DB_URL")
    if not url:
        print("FAILURE: IPAM_DB_URL is not set. Copy .env.example to .env and fill in your "
              "Azure Database for PostgreSQL connection string.", file=sys.stderr)
        sys.exit(1)
    options = "-c default_transaction_read_only=on" if read_only else None
    return psycopg.connect(url, row_factory=dict_row, options=options)


def print_table(rows):
    """Print rows (list of dicts) as an aligned text table."""
    if not rows:
        print("(0 rows)")
        return
    columns = list(rows[0].keys())
    data = [[("" if r[c] is None else str(r[c])) for c in columns] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in data)) for i, c in enumerate(columns)]
    print("  ".join(c.ljust(widths[i]) for i, c in enumerate(columns)))
    print("  ".join("-" * widths[i] for i in range(len(columns))))
    for row in data:
        print("  ".join(val.ljust(widths[i]) for i, val in enumerate(row)))
    print("({} row{})".format(len(rows), "" if len(rows) == 1 else "s"))


def cmd_init(_args):
    schema = (ROOT / "sql" / "schema.sql").read_text()
    with get_conn() as conn:
        conn.execute(schema)
        conn.commit()
    print("SUCCESS: Schema applied.")


def cmd_query(args):
    with get_conn(read_only=True) as conn:
        rows = conn.execute(args.sql).fetchall()
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        print_table(rows)


def cmd_exec(args):
    with get_conn() as conn:
        result = conn.execute(args.sql)
        conn.commit()
    print("SUCCESS: {} row(s) affected.".format(result.rowcount))


def main():
    load_env()
    parser = argparse.ArgumentParser(description="IPAM PostgreSQL helper.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Apply sql/schema.sql to the database.")

    p_query = sub.add_parser("query", help="Run a read-only SQL query.")
    p_query.add_argument("sql", help="SQL SELECT statement.")
    p_query.add_argument("--json", action="store_true", help="Output rows as JSON.")

    p_exec = sub.add_parser("exec", help="Run a write SQL statement (INSERT/UPDATE/DELETE/DDL).")
    p_exec.add_argument("sql", help="SQL statement to execute.")

    args = parser.parse_args()
    try:
        {"init": cmd_init, "query": cmd_query, "exec": cmd_exec}[args.command](args)
    except psycopg.Error as e:
        print("FAILURE: {}".format(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
