# ============================================================
# Thika Technical Training Institute
# Tracer Study Monitoring System (TSMS) — Database Setup & Seed Script
# Run this ONCE after applying combined_supabase.sql
# Requires: SUPABASE_SERVICE_KEY or SUPABASE_SERVICE_ROLE_KEY in .env
# Usage: python setup_db.py
# ============================================================

import os
import sys
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', os.environ.get('SUPABASE_SERVICE_ROLE_KEY', ''))

if not SUPABASE_URL or not SERVICE_KEY or SERVICE_KEY in {'your-service-role-key', 'your-service-role-key-here', 'CHANGE_ME'}:
    print('ERROR: Set SUPABASE_SERVICE_KEY or SUPABASE_SERVICE_ROLE_KEY in your .env file first.')
    print('Find it in: Supabase Dashboard > Project Settings > API > service_role key')
    sys.exit(1)

from supabase import create_client
sb = create_client(SUPABASE_URL, SERVICE_KEY)

print('Connected to Supabase with service role key.')

# ── 1. Seed Departments ──────────────────────────────────────
departments = [
    {'name': 'Electrical Engineering',  'code': 'EE', 'description': 'Electrical installation and maintenance'},
    {'name': 'Mechanical Engineering',  'code': 'ME', 'description': 'Mechanical systems and fabrication'},
    {'name': 'Information Technology', 'code': 'IT', 'description': 'Software development and networking'},
    {'name': 'Civil Engineering',       'code': 'CE', 'description': 'Construction and structural engineering'},
    {'name': 'Automotive Engineering',  'code': 'AE', 'description': 'Vehicle mechanics and diagnostics'},
    {'name': 'Welding & Fabrication',   'code': 'WF', 'description': 'Metal welding and fabrication'},
    {'name': 'Plumbing',                'code': 'PL', 'description': 'Plumbing and pipe fitting'},
    {'name': 'Carpentry',               'code': 'CA', 'description': 'Woodwork and furniture making'},
]

existing = sb.table('departments').select('code').execute().data or []
existing_codes = {d['code'] for d in existing}

inserted = 0
for dept in departments:
    if dept['code'] not in existing_codes:
        sb.table('departments').insert(dept).execute()
        inserted += 1

print(f'Departments: {inserted} inserted, {len(existing_codes)} already existed.')

# ── 2. Seed Courses ──────────────────────────────────────────
courses = [
    {'name': 'Certificate in Electrical Installation', 'code': 'CEI', 'duration_months': 24, 'description': 'Domestic and industrial electrical installation'},
    {'name': 'Diploma in Mechanical Engineering',      'code': 'DME', 'duration_months': 36, 'description': 'Mechanical systems design and maintenance'},
    {'name': 'Certificate in ICT',                     'code': 'CICT','duration_months': 24, 'description': 'Information and communication technology'},
    {'name': 'Certificate in Civil Engineering',       'code': 'CCE', 'duration_months': 24, 'description': 'Building and construction technology'},
    {'name': 'Certificate in Automotive Engineering',  'code': 'CAE', 'duration_months': 24, 'description': 'Motor vehicle mechanics'},
    {'name': 'Certificate in Welding',                 'code': 'CW',  'duration_months': 18, 'description': 'Arc and MIG welding techniques'},
    {'name': 'Certificate in Plumbing',                'code': 'CP',  'duration_months': 18, 'description': 'Plumbing and sanitation systems'},
    {'name': 'Certificate in Carpentry',               'code': 'CC',  'duration_months': 18, 'description': 'Furniture making and joinery'},
]

existing_c = sb.table('courses').select('code').execute().data or []
existing_codes_c = {c['code'] for c in existing_c}

inserted_c = 0
for course in courses:
    if course['code'] not in existing_codes_c:
        sb.table('courses').insert(course).execute()
        inserted_c += 1

print(f'Courses: {inserted_c} inserted, {len(existing_codes_c)} already existed.')

# ── 3. Create Storage Bucket ─────────────────────────────────
try:
    buckets = sb.storage.list_buckets()
    bucket_names = [b.name for b in buckets]
    if 'trainee-media' not in bucket_names:
        sb.storage.create_bucket('trainee-media', options={'public': True})
        print("Storage bucket 'trainee-media' created (public).")
    else:
        print("Storage bucket 'trainee-media' already exists.")
except Exception as e:
    print(f'Storage bucket error: {e}')
    print("Create it manually: Supabase Dashboard > Storage > New bucket > 'trainee-media' (public)")

# ── 4. Create Admin User ─────────────────────────────────
print()
create_admin = input('Create an admin user? (y/n): ').strip().lower()
if create_admin == 'y':
    admin_email = input('Admin email: ').strip()
    admin_password = input('Admin password (min 8 chars): ').strip()
    admin_name = input('Admin full name: ').strip()

    if len(admin_password) < 8:
        print('Password too short, skipping.')
    else:
        try:
            resp = sb.auth.admin.create_user({
                'email': admin_email,
                'password': admin_password,
                'email_confirm': True,
                'user_metadata': {'full_name': admin_name}
            })
            if getattr(resp, 'user', None):
                sb.table('profiles').insert({
                    'id': resp.user.id,
                    'role': 'admin',
                    'full_name': admin_name,
                    'email': admin_email,
                    'is_active': True,
                }).execute()
                print(f'Admin user created: {admin_email}')
        except Exception as e:
            print(f'Admin creation error: {e}')

print()
print('Setup complete! You can now run: python run.py')
