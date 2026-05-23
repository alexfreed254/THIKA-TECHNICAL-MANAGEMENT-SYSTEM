# Thika Technical Training Institute — Flask + Supabase Workspace

This repository contains a unified Flask + Supabase project workspace with multiple integrated modules:
- Attendance Management System
- Online E-Portfolio Management System
- Tracer Study Monitoring System (TSMS)

The application is served from `app.py` and mounted through blueprints in `routes/`.

## What is included

- `app.py` — main Flask app entrypoint
- `config.py` — canonical Flask configuration loader
- `run.py` — canonical local development launcher
- `wsgi.py` — canonical production WSGI entrypoint for Gunicorn / Render
- `setup_db.py` — canonical database seed/setup helper
- `routes/` — Flask blueprints for auth, dashboards, attendance, portfolio, verification, and more
- `templates/` & `static/` — shared UI templates, assets, and frontend resources
- `combined_supabase.sql` — consolidated Supabase schema + migrations for this workspace
- `Procfile` + `runtime.txt` — runtime config for Render deployment
- `.env.example` — canonical environment variables for local and hosted deployment

## Quick Start

1. Install dependencies:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

2. Copy the example environment file:

```bash
copy .env.example .env
```

> A root `.env` file already exists in this workspace. Review it and update `SECRET_KEY` if needed.

3. Update `.env` with your Supabase credentials and a strong `SECRET_KEY`.

4. Run the database setup in Supabase:

- Open Supabase SQL Editor
- Run the full contents of `combined_supabase.sql`

5. If needed, run the helper seeding/setup script:

```bash
python setup_db.py
```

6. Start the app locally:

```bash
python run.py
```

Or use Flask directly:

```bash
set FLASK_APP=app.py
flask run
```

## Database and Auth

This project uses Supabase for:
- PostgreSQL database
- Authentication
- Row Level Security (RLS)
- Storage buckets for uploaded media

The consolidated SQL file is `combined_supabase.sql`, which merges schema, auth/profile migrations, module schemas, RLS/policy fixes, and support triggers.

## Environment Variables

The canonical example is provided in `.env.example`.

Required variables:
- `SECRET_KEY` — Flask session secret
- `FLASK_ENV` — `development` or `production`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `INSTITUTION_NAME`
- `BUCKET_SCRIPTS`
- `BUCKET_EVIDENCE`
- `MAX_CONTENT_LENGTH`
- `ALLOWED_EXTENSIONS`

## Deployment

This repo is configured for Render with:
- `render.yaml`
- `Procfile`
- `runtime.txt`

The deployed web process uses:

```text
web: gunicorn app:app
```

Render should also define the same environment variables used locally.

## Package Requirements

Install from `requirements.txt`.

If you need to add new dependencies, update `requirements.txt` and keep the file pinned to known compatible versions.

## App Routes and Modules

The core Flask routes are mounted under several prefixes:

- `/` — landing and dashboard routes
- `/auth` — login, logout, password reset
- `/super-admin` — super admin portal
- `/dept-admin` — department admin portal
- `/lecturer` — trainer portal
- `/student` — student portal
- `/exam` — exam booking
- `/verification` — verification workflows
- `/dual-training` — dual training management
- `/logbook` — logbook entries
- `/results` — results reporting
- `/clearance` — clearance workflows
- `/poe` — proof-of-evidence workflows
- `/notifications` — notifications

E-Portfolio features are mounted through the portfolio blueprint under the same app.

## Notes

- `app.py` is the primary Flask application object.
- `config.py` is the canonical configuration module.
- `run.py` is the canonical local development startup script.
- `wsgi.py` is the canonical production WSGI entrypoint.
- `setup_db.py` is the canonical post-schema seed helper script.
- `combined_supabase.sql` is the single canonical SQL file for all current database setup.

# THIKA-TECHNICAL-MANAGEMENT-SYSTEM
# THIKA-TECHNICAL-MANAGEMENT-SYSTEM
