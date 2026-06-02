#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')
import asyncio
import json
import re
from app.db import AsyncSessionLocal
from app.models.brief import Brief
from sqlalchemy import select, desc

def parse_brief_json(raw: str):
    """Copy of _parse_brief_json from brief_generator"""
    # Strip markdown fences
    text = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if "executive_summary" not in data:
        return None
    optional_sections = {"key_developments", "entity_watch", "narrative_shifts",
                         "recommendations", "regional_breakdown", "risks_and_outlook"}
    if not optional_sections.intersection(data.keys()):
        return None
    return data

async def check():
    async with AsyncSessionLocal() as session:
        stmt = select(Brief).order_by(Brief.generated_at.desc()).limit(5)
        result = await session.execute(stmt)
        briefs = result.scalars().all()
        print(f'Found {len(briefs)} recent briefs')
        for b in briefs:
            print('\n---')
            print(f'ID: {b.id}')
            print(f'Generated: {b.generated_at}')
            print(f'Model: {b.model}')
            print(f'Post count: {b.post_count}')
            print(f'Summary length: {len(b.summary)}')
            # Try parse JSON
            parsed = parse_brief_json(b.summary)
            if parsed:
                print('✅ Structured JSON parsed successfully')
                print('  Keys:', list(parsed.keys()))
                exec_sum = parsed.get('executive_summary', '')
                print(f'  Executive summary preview: {exec_sum[:200]}...')
            else:
                print('❌ JSON parse failed (raw text)')
                # Show first 500 chars of raw
                preview = b.summary[:500]
                print(f'  Raw preview: {preview}')
                # Check if it's markdown or plain text
                if '```json' in b.summary:
                    print('  Contains ```json fence')
                elif '```' in b.summary:
                    print('  Contains ``` fence')
        # Count total briefs
        total = await session.scalar(select(Brief).count())
        print(f'\nTotal briefs in DB: {total}')

if __name__ == '__main__':
    asyncio.run(check())