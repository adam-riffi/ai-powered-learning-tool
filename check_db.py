import sqlite3
conn = sqlite3.connect('learn_ai.db')
tables = conn.execute(\
SELECT
name
FROM
sqlite_master
WHERE
type=table\).fetchall()
print('Tables:', tables)
for t in tables:
    try:
        rows = conn.execute(f'SELECT title, length(content), substr(content,1,300) FROM {t[0]} LIMIT 2').fetchall()
        for r in rows:
            print(r)
    except: pass
conn.close()
