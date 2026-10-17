# IPAM AI Agent Guide (AGENT.md)
On startup when someone prompts with `hello` or `hi` ask: **Do you want to list all the vnets in the ipam database?**

## Input
- **Database**: Azure Database for PostgreSQL, connection string in `.env` (`IPAM_DB_URL`)

## Project Overview
The `ipam-cli` project is an AI-driven IP Address Management (IPAM) solution. AI agents manage IP address space — VNETs and subnets — in a PostgreSQL database using skills and Python scripts. There is no web interface; the agent is the interface. All changes are validated before writes and recorded in an audit log.

## Tech Stack
- **Language**: Python 3.x
- **Database Driver**: PostgreSQL via `psycopg` 3 (`scripts/ipam_db.py`)
- **Database**: Azure Database for PostgreSQL (flexible server)
- **Validation**: Python `ipaddress` module + live DB queries (`scripts/validate_prefix.py`)

## Folder Map
- `.github/skills/`: AI agent skills (instruction files) that define how agents behave for specific tasks.
- `.github/skills/<skill-name>/SKILL.md`: The core instruction file for a specific skill.
- `scripts/`: Utility scripts used by agents (`ipam_db.py`, `validate_prefix.py`).
- `sql/schema.sql`: Database schema, safety constraints, and audit triggers.
- `AGENT.md`: This guide for AI agents.

## Core Workflows & Skills

### 1. Prefix Validation
- **Skill**: `validate-prefix`
- **Tool**: `scripts/validate_prefix.py`
- **Usage**: ALWAYS validate a proposed VNET or Subnet prefix before any write. Subnet validation also checks containment in the parent VNET.

  ```bash
  python3 scripts/validate_prefix.py 10.0.0.0/16 --as vnet
  python3 scripts/validate_prefix.py 10.0.1.0/24 --as subnet --vnet HUBVNET
  ```

### 2. Database CRUD
- **Skill**: `postgres-crud`
- **Tool**: `scripts/ipam_db.py` (`init` / `query` / `exec`)
- **Usage**: Perform allocation, release, and query operations on the `vnets` and `subnets` tables. `query` runs read-only; `exec` runs writes.

## Development & Testing Commands

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Apply the Schema (once per database)
```bash
python3 scripts/ipam_db.py init
```

### Run a Query
```bash
python3 scripts/ipam_db.py query "SELECT name, prefix, region FROM vnets ORDER BY prefix"
```

### Connectivity Smoke Test
```bash
python3 scripts/ipam_db.py query "SELECT current_database(), version()"
```

## Agent Guidelines & Best Practices

- **Validate First**: Before any write (CRUD), always run the `validate-prefix` skill. The DB constraints are a safety net, not the validation step.
- **Confirm Destructive Actions**: Ask the user to confirm before any DELETE. Deleting a VNET cascades to all of its subnets — list children first.
- **No Secrets**: Never hardcode credentials or put the connection string in scripts, skills, or commits. It lives only in `.env`.
- **Use Skills**: When performing tasks, refer to the relevant `SKILL.md` in `.github/skills/`.
- **Interpret Constraint Errors**: If the database rejects a write (exclusion violation, containment trigger, unique/FK violation), report the exact reason and the conflicting records — never retry blindly.
- **Minimalism**: Keep changes targeted and follow the project's coding standards.
