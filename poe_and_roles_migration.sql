-- ============================================================
-- MIGRATION: poe_documents table + expanded roles
-- Run this in Supabase SQL Editor
-- ============================================================

-- ── 1. Create poe_documents table ────────────────────────────
CREATE TABLE IF NOT EXISTS poe_documents (
    id              SERIAL PRIMARY KEY,
    trainer_id      INT  NOT NULL REFERENCES trainers(id) ON DELETE CASCADE,
    doc_category    VARCHAR(100) NOT NULL,
    doc_title       VARCHAR(200) NOT NULL,
    description     TEXT,
    file_url        TEXT NOT NULL,
    file_name       VARCHAR(200),
    file_type       VARCHAR(20) DEFAULT 'document',
    google_drive_id VARCHAR(200),
    is_verified     BOOLEAN NOT NULL DEFAULT FALSE,
    verified_by     UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    verified_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_poe_documents_updated_at
    BEFORE UPDATE ON poe_documents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE poe_documents ENABLE ROW LEVEL SECURITY;

-- Super admin: full access
CREATE POLICY poe_super_admin ON poe_documents
    FOR ALL TO authenticated
    USING (current_user_role() = 'super_admin' AND current_user_active())
    WITH CHECK (current_user_role() = 'super_admin' AND current_user_active());

-- Dept admin: read/write docs for trainers in their department
CREATE POLICY poe_dept_admin ON poe_documents
    FOR ALL TO authenticated
    USING (
        current_user_active()
        AND current_user_role() IN ('dept_admin','external_verifier','quality_assurance')
        AND trainer_id IN (
            SELECT id FROM trainers WHERE department_id = current_user_dept()
        )
    )
    WITH CHECK (
        current_user_active()
        AND current_user_role() IN ('dept_admin','external_verifier','quality_assurance')
        AND trainer_id IN (
            SELECT id FROM trainers WHERE department_id = current_user_dept()
        )
    );

-- Trainer: own documents only
CREATE POLICY poe_trainer_own ON poe_documents
    FOR ALL TO authenticated
    USING (
        current_user_active()
        AND current_user_role() = 'trainer'
        AND trainer_id IN (SELECT id FROM trainers WHERE user_id = auth.uid())
    )
    WITH CHECK (
        current_user_active()
        AND current_user_role() = 'trainer'
        AND trainer_id IN (SELECT id FROM trainers WHERE user_id = auth.uid())
    );

CREATE INDEX IF NOT EXISTS idx_poe_docs_trainer   ON poe_documents(trainer_id);
CREATE INDEX IF NOT EXISTS idx_poe_docs_category  ON poe_documents(doc_category);
CREATE INDEX IF NOT EXISTS idx_poe_docs_verified  ON poe_documents(is_verified);


-- ── 2. Expand user_profiles role CHECK constraint ─────────────
-- Drop old constraint and add new one with all roles
ALTER TABLE user_profiles
    DROP CONSTRAINT IF EXISTS user_profiles_role_check;

ALTER TABLE user_profiles
    ADD CONSTRAINT user_profiles_role_check
    CHECK (role IN (
        'super_admin',
        'dept_admin',
        'trainer',
        'student',
        'employer',
        'industrial_supervisor',
        'external_verifier',
        'quality_assurance'
    ));

-- Add must_change_password column (safe to run multiple times)
ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;


-- ── 3. Update the auth trigger to accept new roles ────────────
CREATE OR REPLACE FUNCTION handle_new_auth_user()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_role      TEXT;
    v_full_name TEXT;
    valid_roles TEXT[] := ARRAY[
        'super_admin','dept_admin','trainer','student',
        'employer','industrial_supervisor','external_verifier','quality_assurance'
    ];
BEGIN
    v_role := COALESCE(
        NULLIF(TRIM(NEW.raw_user_meta_data->>'role'), ''),
        'student'
    );

    IF NOT (v_role = ANY(valid_roles)) THEN
        v_role := 'student';
    END IF;

    v_full_name := COALESCE(
        NULLIF(TRIM(NEW.raw_user_meta_data->>'full_name'), ''),
        NEW.email
    );

    INSERT INTO public.user_profiles (id, full_name, role, is_active)
    VALUES (NEW.id, v_full_name, v_role, TRUE)
    ON CONFLICT (id) DO NOTHING;

    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'handle_new_auth_user failed for %: %', NEW.id, SQLERRM;
    RETURN NEW;
END;
$$;

-- ── 4. Add employer/supervisor tables if not exist ────────────
-- employer_users: links an employer company to a Supabase auth user
CREATE TABLE IF NOT EXISTS employer_users (
    id              SERIAL PRIMARY KEY,
    user_id         UUID UNIQUE REFERENCES auth.users(id) ON DELETE SET NULL,
    employer_id     INT  REFERENCES employers(id) ON DELETE SET NULL,
    full_name       VARCHAR(200) NOT NULL,
    email           VARCHAR(100),
    phone           VARCHAR(30),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE employer_users ENABLE ROW LEVEL SECURITY;
CREATE POLICY eu_super_admin ON employer_users
    FOR ALL TO authenticated
    USING (current_user_role() = 'super_admin' AND current_user_active())
    WITH CHECK (current_user_role() = 'super_admin' AND current_user_active());

-- quality_assurance_officers
CREATE TABLE IF NOT EXISTS qa_officers (
    id              SERIAL PRIMARY KEY,
    user_id         UUID UNIQUE REFERENCES auth.users(id) ON DELETE SET NULL,
    full_name       VARCHAR(200) NOT NULL,
    email           VARCHAR(100),
    organization    VARCHAR(200),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE qa_officers ENABLE ROW LEVEL SECURITY;
CREATE POLICY qa_super_admin ON qa_officers
    FOR ALL TO authenticated
    USING (current_user_role() = 'super_admin' AND current_user_active())
    WITH CHECK (current_user_role() = 'super_admin' AND current_user_active());
