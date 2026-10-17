---
name: postgres-crud
description: "Perform CRUD operations on the IPAM PostgreSQL database using scripts/ipam_db.py. Use when: creating, listing, updating, or deleting VNETs and subnets; querying IPAM records; allocating or releasing address space; viewing the audit log. Triggers: 'create vnet', 'add subnet', 'delete vnet', 'list vnets', 'update subnet', 'release subnet', 'postgres', 'ipam database'."
argument-hint: "[create|list|update|delete|query] <vnet|subnet> [name]"
user-invocable: true
---

# IPAM PostgreSQL CRUD

> **AUTHORITATIVE GUIDANCE**
>
> Use `scripts/ipam_db.py` for ALL database access. Never hardcode credentials — the connection string lives in `.env` (read via the `IPAM_DB_URL` variable). ALWAYS run the `validate-prefix` skill before any INSERT or UPDATE that changes a prefix. Prefer small, targeted queries over `SELECT *`.

---

## When to Use

- Create, list, update, or delete VNETs and subnets.
- Query IPAM records (by VNET, region, resource group, or name).
- Inspect the audit log of changes.

---

## Prerequisites

1. Python 3.x with `pip install -r requirements.txt`.
2. `.env` configured (copy from `.env.example`) with your Azure Database for PostgreSQL connection string (`?sslmode=require`).
3. Schema applied once per database: `python3 scripts/ipam_db.py init`.

---

## Data Model

### `vnets`

| Column | Type | Description |
|--------|------|-------------|
| `name` | text (unique) | VNET name, e.g. `HUBVNET` |
| `prefix` | inet | VNET CIDR, e.g. `10.0.0.0/16` |
| `description` | text | Free-form description |
| `subscription_id` | text | Azure Subscription ID |
| `resource_group` | text | Azure Resource Group name |
| `region` | text | Azure region, e.g. `eastus2` |

### `subnets`

| Column | Type | Description |
|--------|------|-------------|
| `vnet_id` | bigint (FK → vnets) | Parent VNET (`ON DELETE CASCADE`) |
| `name` | text (unique) | Subnet name, e.g. `GatewaySubnet` |
| `prefix` | inet | Subnet CIDR, e.g. `10.0.1.0/24` |
| `description` | text | Free-form description |

### `audit_log`

Every INSERT/UPDATE/DELETE on `vnets` and `subnets` is recorded automatically by trigger (old/new row as JSONB, user, timestamp).

### Database-enforced safety nets

- No overlapping VNET prefixes (`EXCLUDE USING gist ... WITH &&`).
- No overlapping subnets within the same VNET (trigger).
- Subnet prefix must be fully contained in its parent VNET (trigger).
- Changing a VNET prefix re-checks all of its subnets (trigger fires on UPDATE too).

These constraints make writes safe even if validation is skipped — but ALWAYS validate first anyway for clearer error messages.

---

## CRUD Operations

### Create a VNET

```bash
# 1. Validate first (must return SUCCESS)
python3 scripts/validate_prefix.py 10.0.0.0/16 --as vnet

# 2. Insert
python3 scripts/ipam_db.py exec "INSERT INTO vnets (name, prefix, description, subscription_id, resource_group, region) VALUES ('HUBVNET', '10.0.0.0/16', 'Hub network', '00000000-0000-0000-0000-000000000000', 'rg-network', 'eastus2')"
```

### Create a Subnet

```bash
# 1. Validate against the parent VNET
python3 scripts/validate_prefix.py 10.0.1.0/24 --as subnet --vnet HUBVNET

# 2. Insert (resolve vnet_id inline)
python3 scripts/ipam_db.py exec "INSERT INTO subnets (vnet_id, name, prefix, description) VALUES ((SELECT id FROM vnets WHERE name = 'HUBVNET'), 'GatewaySubnet', '10.0.1.0/24', 'Gateway subnet')"
```

### List / Query

```bash
# All VNETs
python3 scripts/ipam_db.py query "SELECT name, prefix, region, description FROM vnets ORDER BY prefix"

# Subnets of a VNET with usage
python3 scripts/ipam_db.py query "SELECT s.name, s.prefix, s.description FROM subnets s JOIN vnets v ON v.id = s.vnet_id WHERE v.name = 'HUBVNET' ORDER BY s.prefix"

# JSON output for further processing
python3 scripts/ipam_db.py query "SELECT * FROM vnets" --json

# Audit trail
python3 scripts/ipam_db.py query "SELECT changed_at, table_name, operation, new_data FROM audit_log ORDER BY changed_at DESC LIMIT 20"
```

### Update

```bash
# Change a subnet description
python3 scripts/ipam_db.py exec "UPDATE subnets SET description = 'Renamed purpose' WHERE name = 'GatewaySubnet'"

# Reallocate a subnet to another VNET or new prefix: re-validate (excluding itself), then update
python3 scripts/validate_prefix.py 10.0.2.0/24 --as subnet --vnet HUBVNET --exclude-name GatewaySubnet
python3 scripts/ipam_db.py exec "UPDATE subnets SET prefix = '10.0.2.0/24' WHERE name = 'GatewaySubnet'"
```

> Note: the `--exclude-name` flag is required when re-validating a record being updated — otherwise its current prefix counts as an overlap against itself.

### Delete (release address space)

> **Confirm with the user before any DELETE.** Deleting a VNET cascades and deletes all of its subnets.

```bash
# Always check children first
python3 scripts/ipam_db.py query "SELECT s.name, s.prefix FROM subnets s JOIN vnets v ON v.id = s.vnet_id WHERE v.name = 'HUBVNET'"

# Delete a subnet
python3 scripts/ipam_db.py exec "DELETE FROM subnets WHERE name = 'TestSubnet'"

# Delete a VNET (cascades to subnets)
python3 scripts/ipam_db.py exec "DELETE FROM vnets WHERE name = 'HUBVNET'"
```

---

## IPAM Workflows

### Allocate address space
1. `validate-prefix` skill: `python3 scripts/validate_prefix.py <prefix> --as vnet` (or `--as subnet --vnet <NAME>`).
2. Only on SUCCESS, run the corresponding INSERT above.
3. Report the new record back to the user (re-query if needed).

### Release address space
1. Query children/dependents of the target.
2. Confirm the deletion with the user.
3. DELETE, then verify with a follow-up query.

### Change a prefix
1. Re-validate the NEW prefix with the `validate-prefix` skill (in the context of its parent VNET).
2. UPDATE the row.
3. If the DB rejects it (overlap/containment), report the constraint error clearly — never retry blindly.

---

## Error Handling

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| `exclusion violation` (23P01) | VNET prefix overlaps an existing VNET | Re-run `validate-prefix`; pick a non-overlapping prefix |
| `subnet prefix ... overlaps existing subnet` | Overlaps another subnet in the same VNET | Validate with `--as subnet --vnet <NAME>` |
| `subnet prefix ... is not within parent vnet` | Subnet larger than or outside its VNET | Pick a prefix inside the parent VNET |
| `cannot change vnet ... prefix ... subnets outside new prefix` | New VNET prefix strands existing subnets | Move or delete the listed subnets first, then retry |
| `foreign key constraint` (23503) | Parent VNET name doesn't exist | Create the VNET first, or fix the name |
| `duplicate key` (23505) | VNET/subnet name already exists | Query first; use UPDATE for changes |
| `password authentication failed` / SSL error (28xxx) | Bad credentials or missing SSL | Check `.env`; ensure `?sslmode=require` |
| `could not connect` | Wrong host / firewall / no network | Verify server name; check Azure firewall rules |
| `psycopg is not installed` | Dependencies missing | `pip install -r requirements.txt` |

---

## Token Efficiency

- Project only needed columns; use `--json` when the output feeds another step.
- Chain validation and write as two commands, but do not re-validate on failure without changing the prefix.
- Reuse the `validate_prefix.py` / `ipam_db.py` scripts instead of writing ad-hoc Python.
