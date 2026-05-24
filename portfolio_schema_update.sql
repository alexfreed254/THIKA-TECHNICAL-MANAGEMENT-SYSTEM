-- ============================================================
-- PORTFOLIO SCHEMA UPDATE
-- Add missing fields for E-Portfolio functionality
-- ============================================================

-- Add missing columns to assessments table
ALTER TABLE assessments 
ADD COLUMN IF NOT EXISTS assessment_number VARCHAR(20),
ADD COLUMN IF NOT EXISTS title VARCHAR(255),
ADD COLUMN IF NOT EXISTS script_path VARCHAR(500),
ADD COLUMN IF NOT EXISTS script_file_name VARCHAR(255),
ADD COLUMN IF NOT EXISTS evidence_paths TEXT[],
ADD COLUMN IF NOT EXISTS reviewed_filename VARCHAR(255),
ADD COLUMN IF NOT EXISTS reviewer_comments TEXT;

-- Update evidence table to include file_path
ALTER TABLE evidence 
ADD COLUMN IF NOT EXISTS file_path VARCHAR(500);

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_assessments_script_path ON assessments(script_path);
CREATE INDEX IF NOT EXISTS idx_assessments_assessment_number ON assessments(assessment_number);
CREATE INDEX IF NOT EXISTS idx_evidence_file_path ON evidence(file_path);

-- Update RLS policies to allow trainers to see assessments for their assigned units
DROP POLICY IF EXISTS assessments_trainer_assigned ON assessments;

CREATE POLICY assessments_trainer_assigned ON assessments
    FOR SELECT TO authenticated
    USING (
        current_user_active()
        AND current_user_role() = 'trainer'
        AND unit_id IN (
            SELECT unit_id FROM class_units 
            WHERE trainer_id IN (SELECT id FROM trainers WHERE user_id = auth.uid())
        )
    );

CREATE POLICY assessments_trainer_update ON assessments
    FOR UPDATE TO authenticated
    USING (
        current_user_active()
        AND current_user_role() = 'trainer'
        AND unit_id IN (
            SELECT unit_id FROM class_units 
            WHERE trainer_id IN (SELECT id FROM trainers WHERE user_id = auth.uid())
        )
    )
    WITH CHECK (
        current_user_active()
        AND current_user_role() = 'trainer'
        AND unit_id IN (
            SELECT unit_id FROM class_units 
            WHERE trainer_id IN (SELECT id FROM trainers WHERE user_id = auth.uid())
        )
    );

-- ============================================================
-- TRAINEE POE TABLES
-- ============================================================

-- Trainee POE Components table
CREATE TABLE IF NOT EXISTS trainee_poe_components (
    id SERIAL PRIMARY KEY,
    trainee_id INT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    component_category VARCHAR(50) NOT NULL,
    component_title VARCHAR(255) NOT NULL,
    description TEXT,
    file_path VARCHAR(500),
    file_name VARCHAR(255),
    file_type VARCHAR(20),
    file_url VARCHAR(500),
    is_verified BOOLEAN DEFAULT FALSE,
    verified_by UUID REFERENCES user_profiles(id),
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Add indexes for trainee POE
CREATE INDEX IF NOT EXISTS idx_trainee_poe_trainee ON trainee_poe_components(trainee_id);
CREATE INDEX IF NOT EXISTS idx_trainee_poe_category ON trainee_poe_components(component_category);
CREATE INDEX IF NOT EXISTS idx_trainee_poe_verified ON trainee_poe_components(is_verified);

-- Enable RLS on trainee POE
ALTER TABLE trainee_poe_components ENABLE ROW LEVEL SECURITY;

-- RLS Policies for trainee POE
CREATE POLICY trainee_poe_trainee_own ON trainee_poe_components
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

CREATE POLICY trainee_poe_trainer_view ON trainee_poe_components
    FOR SELECT TO authenticated
    USING (
        current_user_active()
        AND current_user_role() IN ('trainer', 'dept_admin', 'super_admin', 'hod')
    );

CREATE POLICY trainee_poe_trainer_verify ON trainee_poe_components
    FOR UPDATE TO authenticated
    USING (
        current_user_active()
        AND current_user_role() IN ('trainer', 'dept_admin', 'super_admin', 'hod')
    )
    WITH CHECK (
        current_user_active()
        AND current_user_role() IN ('trainer', 'dept_admin', 'super_admin', 'hod')
    );

-- Trigger for updated_at
DROP TRIGGER IF EXISTS trg_trainee_poe_updated_at ON trainee_poe_components;
CREATE TRIGGER trg_trainee_poe_updated_at
    BEFORE UPDATE ON trainee_poe_components
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Grant necessary permissions for storage operations
-- Note: Storage bucket policies need to be configured in Supabase dashboard
-- Buckets needed: assessment-scripts, assessment-evidence, poe-components
