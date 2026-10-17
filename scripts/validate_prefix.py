#!/usr/bin/env python3
"""Validate IP prefixes against the IPAM PostgreSQL database.

Usage:
    python3 scripts/validate_prefix.py <prefix> --as vnet
    python3 scripts/validate_prefix.py <prefix> --as subnet --vnet <VNET_NAME>
    python3 scripts/validate_prefix.py <prefix> --skip-db      # syntax check only

Exit codes: 0 = SUCCESS, 1 = FAILURE.
"""
import argparse
import ipaddress
import sys


def validate_prefix(prefix):
    """Validates if the given string is a valid IP prefix."""
    try:
        return ipaddress.ip_network(prefix, strict=False)
    except ValueError as e:
        print(f"Error: Invalid prefix format '{prefix}'. {e}")
        return None


def check_overlaps(target_net, existing_prefixes):
    """Returns the list of existing prefixes that overlap target_net."""
    overlaps = []
    for existing in existing_prefixes:
        try:
            existing_net = ipaddress.ip_network(str(existing), strict=False)
            if target_net.overlaps(existing_net):
                overlaps.append(str(existing))
        except ValueError:
            continue  # Skip invalid existing prefixes
    return overlaps


def validate_as_vnet(conn, target_net, exclude_name=None):
    rows = conn.execute("SELECT name, prefix FROM vnets").fetchall()
    existing = [r["prefix"] for r in rows if r["name"] != exclude_name]
    return check_overlaps(target_net, existing)


def validate_as_subnet(conn, target_net, vnet_name, exclude_name=None):
    vnet = conn.execute(
        "SELECT id, name, prefix FROM vnets WHERE name = %s", (vnet_name,)
    ).fetchone()
    if vnet is None:
        print(f"FAILURE: Parent VNET '{vnet_name}' does not exist.")
        return None

    parent = ipaddress.ip_network(str(vnet["prefix"]), strict=False)
    if not target_net.subnet_of(parent):
        print(f"FAILURE: '{target_net}' is not contained within VNET '{vnet_name}' ({parent}).")
        return None  # fatal: do not continue to overlap check

    rows = conn.execute(
        "SELECT name, prefix FROM subnets WHERE vnet_id = %s", (vnet["id"],)
    ).fetchall()
    existing = [r["prefix"] for r in rows if r["name"] != exclude_name]
    return check_overlaps(target_net, existing)


def main():
    parser = argparse.ArgumentParser(description="Validate an IP prefix against the IPAM database.")
    parser.add_argument("prefix", help="The IP prefix to validate (e.g. 10.0.0.0/24)")
    parser.add_argument("--as", dest="role", choices=["vnet", "subnet"], default="vnet",
                        help="Validate as a VNET prefix (default) or a subnet prefix.")
    parser.add_argument("--vnet", help="Parent VNET name (required when --as subnet).")
    parser.add_argument("--exclude-name", dest="exclude_name",
                        help="Ignore the existing row with this name when checking overlaps "
                             "(use when re-validating a record that is being updated).")
    parser.add_argument("--skip-db", action="store_true",
                        help="Only check syntax; do not connect to the database.")

    args = parser.parse_args()

    if args.role == "subnet" and not args.vnet:
        print("FAILURE: --vnet <VNET_NAME> is required when validating a subnet prefix.")
        sys.exit(1)

    # 1. Validate the prefix itself
    target_net = validate_prefix(args.prefix)
    if not target_net:
        print(f"FAILURE: '{args.prefix}' is not a valid prefix.")
        sys.exit(1)

    if args.skip_db:
        print(f"SUCCESS: '{args.prefix}' is a valid prefix (syntax check only).")
        print(f"Network: {target_net}")
        sys.exit(0)

    # 2. Check against the database
    try:
        from ipam_db import get_conn  # deferred so --skip-db works without psycopg installed
        with get_conn(read_only=True) as conn:
            if args.role == "vnet":
                overlaps = validate_as_vnet(conn, target_net, exclude_name=args.exclude_name)
            else:
                overlaps = validate_as_subnet(conn, target_net, args.vnet,
                                              exclude_name=args.exclude_name)
    except Exception as e:
        print(f"FAILURE: Could not query the IPAM database: {e}", file=sys.stderr)
        sys.exit(1)

    if overlaps is None:  # e.g. parent VNET does not exist
        sys.exit(1)
    if overlaps:
        scope = "VNET" if args.role == "vnet" else f"VNET '{args.vnet}'"
        print(f"FAILURE: '{args.prefix}' overlaps with existing prefixes in {scope}: {', '.join(overlaps)}")
        sys.exit(1)

    if args.role == "subnet":
        print(f"SUCCESS: '{args.prefix}' is within VNET '{args.vnet}' and has no overlapping subnets.")
    else:
        print(f"SUCCESS: '{args.prefix}' is a valid VNET prefix and has no overlaps.")
    print(f"Network: {target_net}")
    sys.exit(0)


if __name__ == "__main__":
    main()
