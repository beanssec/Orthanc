#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')
import asyncio
import json
import re
from app.db import AsyncSessionLocal
from app.models.brief import Brief
from sqlalchemy import select, delete

async def delete_broken_brief(brief_id):
    async with AsyncSessionLocal() as session:
        stmt = select(Brief).where(Brief.id == brief_id)
        result = await session.execute(stmt)
        b = result.scalar_one_or_none()
        if not b:
            print(f'Brief {brief_id} not found')
            return
        print(f'Deleting brief {brief_id} generated at {b.generated_at}')
        await session.delete(b)
        await session.commit()
        print('Deleted.')

async def delete_all_broken():
    """Delete briefs where JSON parse fails."""
    async with AsyncSessionLocal() as session:
        stmt = select(Brief)
        result = await session.execute(stmt)
        all_briefs = result.scalars().all()
        deleted = 0
        for b in all_briefs:
            # Try parse
            try:
                data = json.loads(b.summary)
                # Ensure required keys
                if isinstance(data, dict) and 'executive_summary' in data:
                    continue
            except json.JSONDecodeError:
                pass
            # If we get here, parse failed
            print(f'Deleting broken brief {b.id}')
            await session.delete(b)
            deleted += 1
        if deleted:
            await session.commit()
            print(f'Deleted {deleted} broken briefs.')
        else:
            print('No broken briefs found.')

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--id', help='Delete specific brief ID')
    parser.add_argument('--all-broken', action='store_true', help='Delete all briefs where JSON parse fails')
    args = parser.parse_args()
    if args.id:
        asyncio.run(delete_broken_brief(args.id))
    elif args.all_broken:
        asyncio.run(delete_all_broken())
    else:
        print('Specify --id or --all-broken')