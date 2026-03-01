import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()
cur.execute("SELECT setval('conversaciones_id_seq', (SELECT MAX(id) FROM conversaciones))")
cur.execute("SELECT setval('alertas_id_seq', (SELECT MAX(id) FROM alertas))")
conn.commit()
conn.close()
print('✅ Secuencias corregidas')
