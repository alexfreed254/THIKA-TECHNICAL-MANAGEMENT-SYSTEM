from pathlib import Path
text = Path('combined_supabase.sql').read_text(encoding='utf-8')
lines = text.splitlines(keepends=True)
for i, line in enumerate(lines):
    if line.startswith('-- SOURCE:'):
        print('MARKER', i+1, line.strip())
        for j in range(i+1, min(i+15, len(lines))):
            print(j+1, lines[j].rstrip())
        print('---')
