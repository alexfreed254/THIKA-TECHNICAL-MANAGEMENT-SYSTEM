from pathlib import Path
text = Path('combined_supabase.sql').read_text(encoding='utf-8')
names = [
    'CREATE TABLE IF NOT EXISTS departments',
    'CREATE TABLE IF NOT EXISTS classes',
    'CREATE TABLE IF NOT EXISTS units',
    'CREATE TABLE IF NOT EXISTS user_profiles',
    'CREATE TABLE IF NOT EXISTS attendance',
    'CREATE TABLE IF NOT EXISTS exam_series',
    'CREATE TABLE IF NOT EXISTS exam_bookings',
    'CREATE TABLE IF NOT EXISTS employers',
    'CREATE TABLE IF NOT EXISTS job_postings',
    'CREATE TABLE IF NOT EXISTS job_applications',
    'CREATE TABLE exams',
    'CREATE TABLE courses',
]
for name in names:
    count = text.count(name)
    if count:
        print(f'{name}: {count}')
