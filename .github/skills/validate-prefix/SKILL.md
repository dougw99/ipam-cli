---
name: validate-prefix
description: "Validates IP address prefixes against the IPAM PostgreSQL database and ensures no overlaps. Use when: checking if a new VNET or Subnet prefix is valid, verifying that a proposed CIDR does not conflict with existing entries, or confirming a subnet fits within its parent VNET. This skill leverages the `scripts/validate_prefix.py` script for standardized validation."
argument-hint: "<prefix> [vnet|subnet] [parent-vnet]"
user-invocable: true
---

# IP Prefix Validation (IPAM)

> **AUTHORITATIVE GUIDANCE**
>
> Use `scripts/validate_prefix.py` for ALL prefix validation tasks. Always validate BEFORE any INSERT or UPDATE via the `postgres-crud` skill. A prefix that fails validation must never be written to the database.

---

## When to Use

- Verify a CIDR notation (e.g. `10.0.0.0/24`) is syntactically correct.
- Check a proposed VNET prefix does not overlap any existing VNET.
- Check a proposed subnet prefix does not overlap siblings and fits inside its parent VNET.

---

## Prerequisites

1. **Python 3.x** with `pip install -r requirements.txt`.
2. `.env` configured with `IPAM_DB_URL` (the script queries the database; use `--skip-db` for syntax-only checks when the database is intentionally unavailable).

---

## How to Run

### Syntax + overlap check (VNET prefix)
```bash
python3 scripts/validate_prefix.py 10.0.0.0/16 --as vnet
# SUCCESS: '10.0.0.0/16' is a valid VNET prefix and has no overlaps.
```

### Syntax + containment + overlap check (subnet prefix)
```bash
python3 scripts/validate_prefix.py 10.0.1.0/24 --as subnet --vnet HUBVNET
# SUCCESS: '10.0.1.0/24' is within VNET 'HUBVNET' and has no overlapping subnets.
```

### Syntax check only (offline)
```bash
python3 scripts/validate_prefix.py 10.0.0.256/24 --skip-db
# Error: Invalid prefix format '10.0.0.256/24'. ...
# FAILURE: '10.0.0.256/24' is not a valid prefix.
```

### Re-validate a record that is being updated
An existing row overlaps itself, so exclude it by name when validating a change to that same record:
```bash
python3 scripts/validate_prefix.py 10.0.0.0/16 --as vnet --exclude-name HUBVNET
python3 scripts/validate_prefix.py 10.0.2.0/24 --as subnet --vnet HUBVNET --exclude-name GatewaySubnet
```

---

## What the Script Checks

1. **Syntax**: the prefix parses as a valid IPv4/IPv6 network (host bits are normalized, e.g. `10.0.1.30/24` → `10.0.1.0/24`).
2. **VNET mode**: no existing VNET in the database overlaps the prefix.
3. **Subnet mode**:
   - the named parent VNET exists,
   - the prefix is fully contained within the parent VNET's prefix,
   - no existing subnet in that VNET overlaps the prefix.

Exit code `0` means SUCCESS; `1` means FAILURE (the output states the reason, e.g. which existing prefixes overlap).

---

## Implementation Strategy for AI Agents

1. **Input Parsing**: Extract the prefix, whether it is a VNET or subnet, and the parent VNET name (if a subnet) from the user prompt.
2. **Execution**: Run the matching command above.
3. **Interpretation**:
   - Exit code 0 → proceed with the write using the `postgres-crud` skill.
   - Exit code 1 → STOP. Report the exact FAILURE line to the user (overlaps found, not contained in parent, unknown VNET, or invalid syntax) and suggest the conflicting prefixes. Do NOT attempt the write.
4. **Never skip validation** because "the database will reject it anyway" — the database constraints exist as a safety net, not as the validation step.
