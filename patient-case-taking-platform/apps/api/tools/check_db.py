"""Quick DB connection check."""
import asyncio
import os
import sys

import asyncpg

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://notmid:notmid-local-only@127.0.0.1:5432/notmid"
)

async def main():
    print(f"Connecting to: {DATABASE_URL}")
    try:
        conn = await asyncpg.connect(DATABASE_URL, timeout=5)
        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        version = await conn.fetchval("SELECT version()")
        print("Connected OK")
        print(f"PostgreSQL: {version[:50]}")
        print(f"Tables: {len(tables)}")
        for t in tables[:10]:
            print(f"  {t['tablename']}")
        if len(tables) > 10:
            print(f"  ... and {len(tables)-10} more")
        await conn.close()

        if len(tables) < 5:
            print()
            print("WARNING: Very few tables — run migrations:")
            print("  python -m app.migrations up")
        else:
            print()
            print("Database is ready.")

    except asyncpg.InvalidPasswordError:
        print("FAIL: Wrong password. The local Postgres may have different credentials.")
        print("Try: postgresql://postgres:postgres@127.0.0.1:5432/notmid")
    except asyncpg.InvalidCatalogNameError:
        print("FAIL: Database 'notmid' does not exist.")
        print("Create it: createdb -U postgres notmid")
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        sys.exit(1)

asyncio.run(main())
