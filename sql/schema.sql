-- IPAM PostgreSQL Schema
-- Apply with: python3 scripts/ipam_db.py init
-- Note: uses only core extensions so it runs on Azure Database for PostgreSQL
-- without any allow-list changes (subnet overlap is enforced by trigger,
-- since btree_gist is not allow-listed by default).

CREATE TABLE IF NOT EXISTS vnets (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    prefix          INET NOT NULL,
    description     TEXT,
    subscription_id TEXT,
    resource_group  TEXT,
    region          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- No two VNETs may overlap
    CONSTRAINT vnets_no_overlap EXCLUDE USING gist (prefix inet_ops WITH &&)
);

CREATE TABLE IF NOT EXISTS subnets (
    id          BIGSERIAL PRIMARY KEY,
    vnet_id     BIGINT NOT NULL REFERENCES vnets(id) ON DELETE CASCADE,
    name        TEXT NOT NULL UNIQUE,
    prefix      INET NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         BIGSERIAL PRIMARY KEY,
    table_name TEXT NOT NULL,
    operation  TEXT NOT NULL,
    row_id     BIGINT,
    old_data   JSONB,
    new_data   JSONB,
    changed_by TEXT NOT NULL DEFAULT current_user,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- updated_at maintenance
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS vnets_set_updated_at ON vnets;
CREATE TRIGGER vnets_set_updated_at
    BEFORE UPDATE ON vnets
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS subnets_set_updated_at ON subnets;
CREATE TRIGGER subnets_set_updated_at
    BEFORE UPDATE ON subnets
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- A subnet must be fully contained within its parent VNET
CREATE OR REPLACE FUNCTION check_subnet_within_vnet() RETURNS trigger AS $$
DECLARE
    parent_prefix INET;
BEGIN
    SELECT prefix INTO parent_prefix FROM vnets WHERE id = NEW.vnet_id;
    IF parent_prefix IS NULL THEN
        RAISE EXCEPTION 'vnet id % does not exist', NEW.vnet_id;
    END IF;
    IF NOT (NEW.prefix <<= parent_prefix) THEN
        RAISE EXCEPTION 'subnet prefix % is not within parent vnet prefix %', NEW.prefix, parent_prefix;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS subnets_within_vnet ON subnets;
CREATE TRIGGER subnets_within_vnet
    BEFORE INSERT OR UPDATE OF prefix, vnet_id ON subnets
    FOR EACH ROW EXECUTE FUNCTION check_subnet_within_vnet();

-- No two subnets in the same VNET may overlap
-- (enforced here instead of a GiST exclusion constraint, which would need btree_gist)
CREATE OR REPLACE FUNCTION check_subnet_overlap() RETURNS trigger AS $$
DECLARE
    clash TEXT;
BEGIN
    SELECT s.name || ' (' || s.prefix || ')' INTO clash
    FROM subnets s
    WHERE s.vnet_id = NEW.vnet_id
      AND s.id IS DISTINCT FROM NEW.id
      AND s.prefix && NEW.prefix
    LIMIT 1;
    IF clash IS NOT NULL THEN
        RAISE EXCEPTION 'subnet prefix % overlaps existing subnet % in the same vnet', NEW.prefix, clash;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS subnets_no_overlap ON subnets;
CREATE TRIGGER subnets_no_overlap
    BEFORE INSERT OR UPDATE OF prefix, vnet_id ON subnets
    FOR EACH ROW EXECUTE FUNCTION check_subnet_overlap();

-- Changing a VNET prefix must not strand existing subnets outside it
CREATE OR REPLACE FUNCTION check_vnet_prefix_update() RETURNS trigger AS $$
DECLARE
    strays TEXT;
BEGIN
    IF OLD.prefix IS DISTINCT FROM NEW.prefix THEN
        SELECT string_agg(s.name || ' (' || s.prefix || ')', ', ') INTO strays
        FROM subnets s
        WHERE s.vnet_id = NEW.id
          AND NOT (s.prefix <<= NEW.prefix);
        IF strays IS NOT NULL THEN
            RAISE EXCEPTION 'cannot change vnet % prefix from % to %: subnets outside new prefix: %',
                NEW.name, OLD.prefix, NEW.prefix, strays;
        END IF;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS vnets_prefix_check ON vnets;
CREATE TRIGGER vnets_prefix_check
    BEFORE UPDATE OF prefix ON vnets
    FOR EACH ROW EXECUTE FUNCTION check_vnet_prefix_update();

-- Audit trail for all changes
CREATE OR REPLACE FUNCTION audit_ipam_changes() RETURNS trigger AS $$
BEGIN
    INSERT INTO audit_log (table_name, operation, row_id, old_data, new_data)
    VALUES (
        TG_TABLE_NAME,
        TG_OP,
        COALESCE(NEW.id, OLD.id),
        CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) END,
        CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN to_jsonb(NEW) END
    );
    RETURN COALESCE(NEW, OLD);
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS vnets_audit ON vnets;
CREATE TRIGGER vnets_audit
    AFTER INSERT OR UPDATE OR DELETE ON vnets
    FOR EACH ROW EXECUTE FUNCTION audit_ipam_changes();

DROP TRIGGER IF EXISTS subnets_audit ON subnets;
CREATE TRIGGER subnets_audit
    AFTER INSERT OR UPDATE OR DELETE ON subnets
    FOR EACH ROW EXECUTE FUNCTION audit_ipam_changes();
