from pathlib import Path
text = Path('combined_supabase.sql').read_text(encoding='utf-8')
start = text.index("ON CONFLICT (id) DO UPDATE SET")
end = text.index("-- ============================================================\n-- SOURCE: supabase_promote_superadmin.sql")
chunk = text[start:end]
print(repr(chunk))
print('length', len(chunk))
