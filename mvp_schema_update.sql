-- MVP Schema Update for TTTI Management System
-- This script adds missing tables and columns required for the MVP

-- ============================================================
-- 1. UPDATE user_profiles TABLE
-- ============================================================

-- Add temporary password fields
ALTER TABLE user_profiles 
ADD COLUMN IF NOT EXISTS is_temp_password BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS temp_expires TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS password_history JSONB DEFAULT '[]'::jsonb;

-- Update role check to include employer
DROP POLICY IF EXISTS profiles_super_admin ON user_profiles;
CREATE POLICY profiles_super_admin ON user_profiles
    FOR ALL TO authenticated
    USING (current_user_role() = 'super_admin' AND current_user_active())
    WITH CHECK (current_user_role() = 'super_admin' AND current_user_active());

-- ============================================================
-- 2. CREATE assessments TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS assessments (
    id              SERIAL PRIMARY KEY,
    trainee_id      INT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    unit_id         INT NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    trainer_id      INT NOT NULL REFERENCES trainers(id) ON DELETE CASCADE,
    class_id        INT NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    year            INT NOT NULL DEFAULT EXTRACT(YEAR FROM NOW())::INT,
    term            INT NOT NULL DEFAULT 1,
    cycle           INT,
    assessment_type VARCHAR(50) NOT NULL CHECK (assessment_type IN ('formative_oral','formative_theory','formative_practical','summative','project','internship')),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','needs_revision')),
    feedback        TEXT,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_assessments_updated_at
    BEFORE UPDATE ON assessments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE assessments ENABLE ROW LEVEL SECURITY;

-- RLS Policies for assessments
CREATE POLICY assessments_super_admin ON assessments
    FOR ALL TO authenticated
    USING (current_user_role() = 'super_admin' AND current_user_active())
    WITH CHECK (current_user_role() = 'super_admin' AND current_user_active());

CREATE POLICY assessments_trainee_own ON assessments
    FOR ALL TO authenticated
    USING (
        current_user_active()
        AND current_user_role() = 'student'
        AND trainee_id IN (SELECT id FROM students WHERE user_id = auth.uid())
    )
    WITH CHECK (
        current_user_active()
        AND current_user_role() = 'student'
        AND trainee_id IN (SELECT id FROM students WHERE user_id = auth.uid())
    );

CREATE POLICY assessments_trainer_assigned ON assessments
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

CREATE POLICY assessments_dept_admin ON assessments
    FOR SELECT TO authenticated
    USING (
        current_user_active()
        AND current_user_role() = 'dept_admin'
        AND class_id IN (SELECT id FROM classes WHERE department_id = current_user_dept())
    );

-- ============================================================
-- 3. CREATE evidence TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS evidence (
    id              SERIAL PRIMARY KEY,
    assessment_id   INT NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    file_url        VARCHAR(500) NOT NULL,
    file_name       VARCHAR(255) NOT NULL,
    file_type       VARCHAR(50) NOT NULL CHECK (file_type IN ('pdf','image','video','document')),
    file_size       BIGINT,
    geolocation_lat NUMERIC(10, 8),
    geolocation_lng NUMERIC(11, 8),
    tags            TEXT[],
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE evidence ENABLE ROW LEVEL SECURITY;

-- RLS Policies for evidence
CREATE POLICY evidence_super_admin ON evidence
    FOR ALL TO authenticated
    USING (current_user_role() = 'super_admin' AND current_user_active())
    WITH CHECK (current_user_role() = 'super_admin' AND current_user_active());

CREATE POLICY evidence_trainee_own ON evidence
    FOR SELECT TO authenticated
    USING (
        current_user_active()
        AND current_user_role() = 'student'
        AND assessment_id IN (
            SELECT id FROM assessments 
            WHERE trainee_id IN (SELECT id FROM students WHERE user_id = auth.uid())
        )
    );

CREATE POLICY evidence_trainer_assigned ON evidence
    FOR SELECT TO authenticated
    USING (
        current_user_active()
        AND current_user_role() = 'trainer'
        AND assessment_id IN (
            SELECT id FROM assessments 
            WHERE trainer_id IN (SELECT id FROM trainers WHERE user_id = auth.uid())
        )
    );

CREATE POLICY evidence_employer_read ON evidence
    FOR SELECT TO authenticated
    USING (
        current_user_active()
        AND current_user_role() = 'employer'
    );

-- ============================================================
-- 4. CREATE employer_recommendations TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS employer_recommendations (
    id              SERIAL PRIMARY KEY,
    trainee_id      INT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    employer_id     INT NOT NULL,
    content         TEXT NOT NULL,
    rating          INT CHECK (rating >= 1 AND rating <= 5),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_employer_recommendations_updated_at
    BEFORE UPDATE ON employer_recommendations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE employer_recommendations ENABLE ROW LEVEL SECURITY;

-- RLS Policies for employer_recommendations
CREATE POLICY recommendations_super_admin ON employer_recommendations
    FOR ALL TO authenticated
    USING (current_user_role() = 'super_admin' AND current_user_active())
    WITH CHECK (current_user_role() = 'super_admin' AND current_user_active());

CREATE POLICY recommendations_trainee_own ON employer_recommendations
    FOR SELECT TO authenticated
    USING (
        current_user_active()
        AND current_user_role() = 'student'
        AND trainee_id IN (SELECT id FROM students WHERE user_id = auth.uid())
    );

CREATE POLICY recommendations_employer_own ON employer_recommendations
    FOR ALL TO authenticated
    USING (
        current_user_active()
        AND current_user_role() = 'employer'
        AND employer_id IN (SELECT id FROM employer_users WHERE user_id = auth.uid())
    )
    WITH CHECK (
        current_user_active()
        AND current_user_role() = 'employer'
        AND employer_id IN (SELECT id FROM employer_users WHERE user_id = auth.uid())
    );

-- ============================================================
-- 5. CREATE employers TABLE (if not exists)
-- ============================================================

CREATE TABLE IF NOT EXISTS employers (
    id              SERIAL PRIMARY KEY,
    company_name    VARCHAR(200) NOT NULL,
    contact_person  VARCHAR(200),
    email           VARCHAR(100),
    phone           VARCHAR(20),
    address         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_employers_updated_at
    BEFORE UPDATE ON employers
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE employers ENABLE ROW LEVEL SECURITY;

CREATE POLICY employers_super_admin ON employers
    FOR ALL TO authenticated
    USING (current_user_role() = 'super_admin' AND current_user_active())
    WITH CHECK (current_user_role() = 'super_admin' AND current_user_active());

-- ============================================================
-- 6. CREATE employer_users TABLE (if not exists)
-- ============================================================

CREATE TABLE IF NOT EXISTS employer_users (
    id              SERIAL PRIMARY KEY,
    user_id         UUID UNIQUE REFERENCES auth.users(id) ON DELETE SET NULL,
    full_name       VARCHAR(200) NOT NULL,
    email           VARCHAR(100) NOT NULL,
    phone           VARCHAR(20),
    employer_id     INT REFERENCES employers(id) ON DELETE SET NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_employer_users_updated_at
    BEFORE UPDATE ON employer_users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE employer_users ENABLE ROW LEVEL SECURITY;

CREATE POLICY employer_users_super_admin ON employer_users
    FOR ALL TO authenticated
    USING (current_user_role() = 'super_admin' AND current_user_active())
    WITH CHECK (current_user_role() = 'super_admin' AND current_user_active());

CREATE POLICY employer_users_own ON employer_users
    FOR ALL TO authenticated
    USING (user_id = auth.uid() AND current_user_active())
    WITH CHECK (user_id = auth.uid() AND current_user_active());

-- ============================================================
-- 7. CREATE clearance_requests TABLE (if not exists)
-- ============================================================

CREATE TABLE IF NOT EXISTS clearance_requests (
    id                      SERIAL PRIMARY KEY,
    student_id              INT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    department_id           INT REFERENCES departments(id) ON DELETE SET NULL,
    status                  VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','dept_cleared','finance_cleared','registrar_cleared','completed','rejected')),
    dept_cleared_by         UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    dept_cleared_at         TIMESTAMPTZ,
    finance_cleared_by      UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    finance_cleared_at      TIMESTAMPTZ,
    registrar_cleared_by    UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    registrar_cleared_at    TIMESTAMPTZ,
    principal_signed_by     UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    principal_signed_at     TIMESTAMPTZ,
    comment                 TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_clearance_requests_updated_at
    BEFORE UPDATE ON clearance_requests
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE clearance_requests ENABLE ROW LEVEL SECURITY;

CREATE POLICY clearance_super_admin ON clearance_requests
    FOR ALL TO authenticated
    USING (current_user_role() = 'super_admin' AND current_user_active())
    WITH CHECK (current_user_role() = 'super_admin' AND current_user_active());

CREATE POLICY clearance_student_own ON clearance_requests
    FOR ALL TO authenticated
    USING (
        current_user_active()
        AND current_user_role() = 'student'
        AND student_id IN (SELECT id FROM students WHERE user_id = auth.uid())
    )
    WITH CHECK (
        current_user_active()
        AND current_user_role() = 'student'
        AND student_id IN (SELECT id FROM students WHERE user_id = auth.uid())
    );

CREATE POLICY clearance_dept_admin ON clearance_requests
    FOR ALL TO authenticated
    USING (
        current_user_active()
        AND current_user_role() = 'dept_admin'
        AND department_id = current_user_dept()
    )
    WITH CHECK (
        current_user_active()
        AND current_user_role() = 'dept_admin'
        AND department_id = current_user_dept()
    );

-- ============================================================
-- 8. UPDATE current_user_role FUNCTION to include employer
-- ============================================================

CREATE OR REPLACE FUNCTION current_user_role()
RETURNS TEXT LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT role FROM user_profiles WHERE id = auth.uid();
$$;

-- ============================================================
-- 9. CREATE INDEXES for performance
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_assessments_trainee ON assessments(trainee_id);
CREATE INDEX IF NOT EXISTS idx_assessments_unit ON assessments(unit_id);
CREATE INDEX IF NOT EXISTS idx_assessments_trainer ON assessments(trainer_id);
CREATE INDEX IF NOT EXISTS idx_assessments_status ON assessments(status);
CREATE INDEX IF NOT EXISTS idx_assessments_year_term ON assessments(year, term);

CREATE INDEX IF NOT EXISTS idx_evidence_assessment ON evidence(assessment_id);
CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(file_type);

CREATE INDEX IF NOT EXISTS idx_recommendations_trainee ON employer_recommendations(trainee_id);
CREATE INDEX IF NOT EXISTS idx_recommendations_employer ON employer_recommendations(employer_id);

CREATE INDEX IF NOT EXISTS idx_clearance_student ON clearance_requests(student_id);
CREATE INDEX IF NOT EXISTS idx_clearance_department ON clearance_requests(department_id);
CREATE INDEX IF NOT EXISTS idx_clearance_status ON clearance_requests(status);

-- ============================================================
-- 10. ADD COMMENTS
-- ============================================================

COMMENT ON TABLE assessments IS 'Trainee assessments with approval workflow';
COMMENT ON COLUMN assessments.assessment_type IS 'Type of assessment: formative_oral, formative_theory, formative_practical, summative, project, internship';
COMMENT ON COLUMN assessments.status IS 'Approval status: pending, approved, rejected, needs_revision';

COMMENT ON TABLE evidence IS 'Evidence files uploaded for assessments with geolocation metadata';
COMMENT ON COLUMN evidence.geolocation_lat IS 'Latitude coordinate for GIS mapping';
COMMENT ON COLUMN evidence.geolocation_lng IS 'Longitude coordinate for GIS mapping';

COMMENT ON TABLE employer_recommendations IS 'Recommendations from employers for trainees';

COMMENT ON TABLE clearance_requests IS 'Student clearance workflow: department, finance, registrar, principal sign-offs';
COMMENT ON COLUMN clearance_requests.status IS 'Clearance status: pending, dept_cleared, finance_cleared, registrar_cleared, completed, rejected';
