"""Maintenance-only provisioning of explicit internal identity grants."""

import argparse
import asyncio
from pathlib import Path
from uuid import UUID

import asyncpg

from app.auth.identity_repository import IdentityBinding, IdentityRepository
from app.config import settings


async def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--operator-id", type=UUID, required=True)
    parser.add_argument("--expected-version", type=int, required=True)
    parser.add_argument("--reason-code", required=True)
    args = parser.parse_args()
    if not settings.DATABASE_MAINTENANCE_URL:
        raise RuntimeError("DATABASE_MAINTENANCE_URL required for identity provisioning")
    if args.binding.stat().st_size > 16384:
        raise ValueError("Binding file exceeds 16 KiB")
    binding = IdentityBinding.model_validate_json(args.binding.read_text(encoding="utf-8"))
    pool = await asyncpg.create_pool(settings.DATABASE_MAINTENANCE_URL, min_size=1, max_size=1)
    try:
        version = await IdentityRepository(pool).grant(
            binding, operator_id=args.operator_id, reason_code=args.reason_code,
            expected_version=args.expected_version,
        )
        print(f"Identity grant version={version}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(run())
