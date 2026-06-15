import os
from dotenv import load_dotenv
import psycopg

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found")

# .env dùng scheme SQLAlchemy (postgresql+psycopg://) — psycopg thuần cần postgresql://
DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

try:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            version = cur.fetchone()

            cur.execute("SELECT NOW();")
            now = cur.fetchone()

            print("✅ Connected successfully!")
            print(f"Postgres: {version[0]}")
            print(f"Server time: {now[0]}")

except Exception as e:
    print(f"❌ Connection failed: {e}")