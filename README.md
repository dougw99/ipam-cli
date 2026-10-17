# IPAM using AI Agents
This project is an AI-driven IP Address Management (IPAM) solution. AI agents manage IP address space through skills and Python scripts, with all data stored in a PostgreSQL database (Azure Database for PostgreSQL). There is no web interface — the agent is the interface.

# What does this do?
- Stores VNETs and subnets in a PostgreSQL database with a full audit trail of changes.
- Validates VNET prefixes to ensure there are no overlapping address spaces before any change is written.
- Validates subnet prefixes to ensure they do not overlap sibling subnets and are fully contained within their parent VNET.
- Enforces all of the above a second time at the database level (exclusion constraints + triggers), so unsafe writes are impossible even if validation is skipped.

# How does this work?
- `scripts/validate_prefix.py` validates prefixes against the live database. Used by the AI skill `validate-prefix`.
- `scripts/ipam_db.py` is the single entry point for all database access (init/query/exec). Used by the AI skill `postgres-crud`.
- `sql/schema.sql` defines the schema, safety constraints, and audit triggers.

# Data Schema (PostgreSQL)

### `vnets`
- **name** (unique, e.g. `HUBVNET`)
- **prefix** (`inet`, e.g. `10.0.0.0/16`) — no overlaps between VNETs
- **description**, **subscription_id**, **resource_group**, **region**

### `subnets`
- **vnet_id** (foreign key to `vnets`; deleting a VNET cascades to its subnets)
- **name** (unique, e.g. `GatewaySubnet`)
- **prefix** (`inet`, e.g. `10.0.1.0/24`) — no overlaps within a VNET, must be contained in the parent VNET
- **description**

### `audit_log`
- Automatic record of every INSERT/UPDATE/DELETE: table, operation, old and new row (JSONB), user, timestamp.

# Setup
1. Create an Azure Database for PostgreSQL flexible server and a database named `ipam`.
2. Allow your client IP (or use a jump host) in the server's firewall rules.
3. Configure and connect:
   ```bash
   cp .env.example .env    # fill in your connection string (sslmode=require)
   pip install -r requirements.txt
   python3 scripts/ipam_db.py init
   ```

# How to use
Just tell it what you want:
   - `List all vnets in my IPAM database`
   - `List subnets for <VNET>`
 