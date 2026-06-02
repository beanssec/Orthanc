#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')
import asyncio
from app.db import AsyncSessionLocal
from app.models.brief import Brief
from sqlalchemy import select, desc
import json

async def query():
    async with AsyncSessionLocal() as session:
        stmt = select(Brief).order_by(Brief.created_at.desc()).limit(5)
        result = await session.execute(stmt)
        briefs = result.scalars().all()
        print(f'Found {len(briefs)} recent briefs')
        for b in briefs:
            print('\n---')
            print(f'ID: {b.id}')
            print(f'Created: {b.created_at}')
            print(f'Model: {b.model_used}')
            print(f'User: {b.user_id}')
            print(f'Structured JSON keys: {list(b.structured_json.keys()) if b.structured_json else "None"}')
            # Print executive summary
            if b.structured_json and 'executive_summary' in b.structured_json:
                print(f'Executive summary: {b.structured_json["executive_summary"][:200]}...')
            else:
                print('No structured JSON')
            # Check for raw content
            if b.raw_content:
                print(f'Raw content length: {len(b.raw_content)}')
                print(f'Raw preview: {b.raw_content[:200]}...')
            else:
                print('No raw content')
            # Check for error
            if b.error:
                print(f'ERROR: {b.error}')
        # Also count total briefs
        total = await session.scalar(select(func.count()).select_from(Brief))
        print(f'\nTotal briefs in DB: {total}')

if __name__ == '__main__':
    asyncio.run(query())