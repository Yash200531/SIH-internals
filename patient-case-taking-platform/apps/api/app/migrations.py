"""Small checksummed PostgreSQL migration runner for the API container."""

import argparse
import asyncio
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg

from app.config import settings

_MIGRATION_PATTERN = re.compile(r"^(?P<version>\d+)_(?P<name>[a-z0-9_]+)\.up\.sql$")
_MIGRATION_LOCK_ID = 707_001
DEFAULT_MIGRATION_DIRECTORY = Path(__file__).parents[1] / "migrations"


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    checksum_sha256: str
    accepted_checksums: frozenset[str]

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")


class MigrationChecksumMismatch(RuntimeError):
    def __init__(self, version: int, expected: str, actual: str):
        del expected, actual
        super().__init__(f"Applied migration {version} has a different checksum")


def discover_migrations(directory: Path = DEFAULT_MIGRATION_DIRECTORY) -> list[Migration]:
    migrations: list[Migration] = []
    seen_versions: set[int] = set()
    for path in directory.glob("*.up.sql"):
        match = _MIGRATION_PATTERN.fullmatch(path.name)
        if match is None:
            continue
        version = int(match.group("version"))
        if version in seen_versions:
            raise ValueError(f"Duplicate migration version: {version}")
        seen_versions.add(version)
        sql = path.read_text(encoding="utf-8")
        canonical_bytes = sql.encode("utf-8")
        crlf_bytes = sql.replace("\n", "\r\n").encode("utf-8")
        migrations.append(
            Migration(
                version=version,
                name=match.group("name"),
                path=path,
                checksum_sha256=hashlib.sha256(canonical_bytes).hexdigest(),
                accepted_checksums=frozenset(
                    {
                        hashlib.sha256(canonical_bytes).hexdigest(),
                        hashlib.sha256(crlf_bytes).hexdigest(),
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                ),
            )
        )
    return sorted(migrations, key=lambda migration: migration.version)


async def apply_migrations(connection: Any, directory: Path = DEFAULT_MIGRATION_DIRECTORY) -> int:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migration (
            version INTEGER PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            checksum_sha256 CHAR(64) NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await connection.execute("SELECT pg_advisory_lock($1)", _MIGRATION_LOCK_ID)
    applied_count = 0
    try:
        rows = await connection.fetch("SELECT version, checksum_sha256 FROM schema_migration")
        applied = {int(row["version"]): str(row["checksum_sha256"]) for row in rows}
        for migration in discover_migrations(directory):
            applied_checksum = applied.get(migration.version)
            if applied_checksum is not None:
                if applied_checksum not in migration.accepted_checksums:
                    raise MigrationChecksumMismatch(
                        migration.version,
                        applied_checksum,
                        migration.checksum_sha256,
                    )
                continue
            async with connection.transaction():
                await connection.execute(migration.sql)
                await connection.execute(
                    """
                    INSERT INTO schema_migration (version, name, checksum_sha256)
                    VALUES ($1, $2, $3)
                    """,
                    migration.version,
                    migration.name,
                    migration.checksum_sha256,
                )
            applied_count += 1
    finally:
        await connection.execute("SELECT pg_advisory_unlock($1)", _MIGRATION_LOCK_ID)
    return applied_count


async def _run() -> None:
    parser = argparse.ArgumentParser(description="Apply MediKiosk PostgreSQL migrations")
    parser.add_argument("command", choices=("up",))
    parser.parse_args()
    connection = await asyncpg.connect(settings.DATABASE_URL)
    try:
        applied_count = await apply_migrations(connection)
    finally:
        await connection.close()
    print(f"Applied {applied_count} migration(s)")


if __name__ == "__main__":
    asyncio.run(_run())
