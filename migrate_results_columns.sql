-- Migration Script: Create result_sheets table with Formative Assessment columns
-- Run this in Supabase SQL Editor to update the database schema

-- Step 1: Create the result_sheets table (if it doesn't exist)
CREATE TABLE IF NOT EXISTS result_sheets (
    id                  BIGSERIAL PRIMARY KEY,
    student_id          INT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    unit_id             INT NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    class_id            INT NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    department_id       INT REFERENCES departments(id) ON DELETE SET NULL,
    exam_series_id      INT REFERENCES exam_series(id) ON DELETE SET NULL,
    year                INT NOT NULL,
    term                INT NOT NULL,
    -- Formative Assessment scores (0-100)
    formative_oral_score      NUMERIC(5,2),
    formative_theory_score    NUMERIC(5,2),
    formative_practical_score NUMERIC(5,2),
    total_score        NUMERIC(5,2),
    grade              VARCHAR(2),
    remarks            VARCHAR(50),
    uploaded_by        UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    upload_method      VARCHAR(20) DEFAULT 'manual',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (student_id, unit_id, year, term)
);

-- Step 2: Create trigger for updated_at
CREATE TRIGGER trg_result_sheets_updated_at
    BEFORE UPDATE ON result_sheets
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Step 3: Enable Row Level Security
ALTER TABLE result_sheets ENABLE ROW LEVEL SECURITY;

-- Step 4: Create policies for result_sheets
-- Super admin: full access
CREATE POLICY sa_full_result_sheets ON result_sheets
    FOR ALL TO authenticated
    USING (current_user_role() = 'super_admin' AND current_user_active())
    WITH CHECK (current_user_role() = 'super_admin' AND current_user_active());

-- Trainers/Dept Admins: read/write for their department
CREATE POLICY dept_result_sheets ON result_sheets
    FOR ALL TO authenticated
    USING (
        department_id IN (
            SELECT department_id FROM user_profiles 
            WHERE id = auth.uid() AND role IN ('trainer', 'dept_admin', 'hod')
        ) AND current_user_active()
    )
    WITH CHECK (
        department_id IN (
            SELECT department_id FROM user_profiles 
            WHERE id = auth.uid() AND role IN ('trainer', 'dept_admin', 'hod')
        ) AND current_user_active()
    );

-- Students: read only their own results
CREATE POLICY student_own_result_sheets ON result_sheets
    FOR SELECT TO authenticated
    USING (
        student_id IN (
            SELECT id FROM students WHERE user_id = auth.uid()
        ) AND current_user_active()
    );

-- Step 5: Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_result_sheets_student ON result_sheets(student_id);
CREATE INDEX IF NOT EXISTS idx_result_sheets_unit ON result_sheets(unit_id);
CREATE INDEX IF NOT EXISTS idx_result_sheets_class ON result_sheets(class_id);
CREATE INDEX IF NOT EXISTS idx_result_sheets_dept ON result_sheets(department_id);
CREATE INDEX IF NOT EXISTS idx_result_sheets_year_term ON result_sheets(year, term);

-- Step 6: Add comments to document the columns
COMMENT ON TABLE result_sheets IS 'Student results/marksheets with formative assessment scores';
COMMENT ON COLUMN result_sheets.formative_oral_score IS 'Formative Assessment - Oral Score (0-100)';
COMMENT ON COLUMN result_sheets.formative_theory_score IS 'Formative Assessment - Theory Score (0-100)';
COMMENT ON COLUMN result_sheets.formative_practical_score IS 'Formative Assessment - Practical Score (0-100)';
COMMENT ON COLUMN result_sheets.total_score IS 'Total score (sum of all formative assessments)';
COMMENT ON COLUMN result_sheets.grade IS 'Grade (A, B, C, D, E)';
COMMENT ON COLUMN result_sheets.remarks IS 'Remarks (Distinction, Credit, Pass, Supplementary, Fail)';
