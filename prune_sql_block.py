from pathlib import Path
path = Path('combined_supabase.sql')
text = path.read_text(encoding='utf-8')
old = '''FROM auth.users au
WHERE lower(au.email) = lower('superadmin@ttieportfolio.ac.ke')
ON CONFLICT (id) DO UPDATE SET
  role      = EXCLUDED.role,
  full_name = EXCLUDED.full_name,
  is_active = TRUE;


-- ─────────────────────────────────────────────────────────────
-- COURSES  (e.g. "Electrical Engineering")
-- ─────────────────────────────────────────────────────────────
CREATE TABLE courses (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    code            TEXT NOT NULL,
    department_id   UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(code, department_id)
);

-- ─────────────────────────────────────────────────────────────
-- UNITS  (units of competency per course)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE units (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL,
    code        TEXT,
    course_id   UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    created_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────
-- CLASSES  (e.g. "EEN_L6 1A SEPT 2024")
-- ─────────────────────────────────────────────────────────────
CREATE TABLE classes (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL UNIQUE,
    course_id       UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    department_id   UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    intake_year     INTEGER,
    intake_month    TEXT,
    level           TEXT CHECK (level IN ('Level 3','Level 4','Level 5','Level 6')),
    cycle           TEXT CHECK (cycle IN ('Cycle 1','Cycle 2','Cycle 3','Cycle 3 Moderated')),
    created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────
-- CLASS ↔ UNIT  (many-to-many)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE class_units (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    class_id    UUID NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    unit_id     UUID NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    UNIQUE(class_id, unit_id)
);

-- ─────────────────────────────────────────────────────────────
-- TRAINER ↔ UNIT  (which units each trainer is responsible for)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE trainer_units (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trainer_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    unit_id     UUID NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(trainer_id, unit_id)
);

-- ─────────────────────────────────────────────────────────────
-- TRAINEE ↔ CLASS  (enrollment)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE enrollments (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trainee_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    class_id    UUID NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    enrolled_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(trainee_id, class_id)
);

-- ─────────────────────────────────────────────────────────────
-- ASSESSMENTS  (the marked PDF scripts uploaded by trainees)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE assessments (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trainee_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    class_id        UUID NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    unit_id         UUID NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    assessment_type TEXT NOT NULL CHECK (assessment_type IN ('PRACTICAL','THEORY','ORAL')),
    assessment_no   INTEGER NOT NULL,
    term            INTEGER NOT NULL CHECK (term IN (1,2,3)),
    cycle           INTEGER NOT NULL CHECK (cycle IN (1,2,3)),
    year            INTEGER NOT NULL,
    -- PDF script file (stored in Supabase Storage)
    script_file_path    TEXT,
    script_file_name    TEXT,
    script_file_size    BIGINT,
    -- Status
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','approved','rejected')),
    reviewed_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at     TIMESTAMPTZ,
    review_note     TEXT,
    -- Metadata
    uploaded_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────
-- EVIDENCE  (photos/videos linked to an assessment)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE evidence (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    assessment_id   UUID NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    trainee_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    file_path       TEXT NOT NULL,
    file_name       TEXT NOT NULL,
    file_type       TEXT NOT NULL CHECK (file_type IN ('photo','video')),
    file_size       BIGINT,
    caption         TEXT,
    uploaded_at     TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────
-- SYSTEM LOGS  (super_admin view)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE system_logs (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    action      TEXT NOT NULL,
    entity      TEXT,
    entity_id   TEXT,
    detail      TEXT,
    ip_address  TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────
-- FIRST SUPER ADMIN: run bootstrap_super_admin.sql once in the
-- Supabase SQL Editor (or insert via Table Editor). Additional
-- users are created from Super Admin → All Users in the app.
-- ─────────────────────────────────────────────────────────────

-- ─────────────────────────────────────────────────────────────
-- ROW LEVEL SECURITY (basic — tighten per your policy)
-- ─────────────────────────────────────────────────────────────
ALTER TABLE trainer_units  ENABLE ROW LEVEL SECURITY;
ALTER TABLE users        ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessments  ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence     ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_logs  ENABLE ROW LEVEL SECURITY;

-- Service-role key bypasses RLS (used by Flask backend)



-- ============================================================
-- SOURCE: supabase_promote_superadmin.sql
'''
new = '''FROM auth.users au
WHERE lower(au.email) = lower('superadmin@ttieportfolio.ac.ke')
ON CONFLICT (id) DO UPDATE SET
  role      = EXCLUDED.role,
  full_name = EXCLUDED.full_name,
  is_active = TRUE;


-- ============================================================
-- SOURCE: supabase_promote_superadmin.sql
'''
if old not in text:
    print('Old block not found')
    exit(1)
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')
print('Pruned extraneous schema1 content')
