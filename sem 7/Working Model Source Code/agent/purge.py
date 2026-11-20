import sqlite3
import json

conn = sqlite3.connect('data/quantplus.db')
c = conn.cursor()
c.execute("SELECT id, decision FROM sessions WHERE decision LIKE '%Oracle guarantee%'")
rows = c.fetchall()

out = [{'id': r[0], 'decision': r[1]} for r in rows]
with open('data/oracle_tainted_sessions_DO_NOT_USE.json', 'w') as f:
    json.dump(out, f, indent=2)

c.execute("DELETE FROM sessions WHERE decision LIKE '%Oracle guarantee%'")
conn.commit()
print(f'Purged {len(rows)} tainted sessions.')
