#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')
import asyncio
import json
import re
from app.db import AsyncSessionLocal
from app.models.brief import Brief
from sqlalchemy import select, desc, func

async def check():
    async with AsyncSessionLocal() as session:
        stmt = select(Brief).order_by(Brief.generated_at.desc()).limit(1)
        result = await session.execute(stmt)
        b = result.scalar_one_or_none()
        if not b:
            print('No briefs found')
            return
        print(f'ID: {b.id}')
        print(f'Generated: {b.generated_at}')
        print(f'Model: {b.model}')
        print(f'Summary length: {len(b.summary)}')
        raw = b.summary
        # Try load as JSON
        try:
            data = json.loads(raw)
            print('✅ Direct JSON load succeeded')
            print('Keys:', list(data.keys()))
            # Print each key with truncated value
            for k, v in data.items():
                if isinstance(v, str):
                    print(f'  {k}: {v[:200]}...')
                elif isinstance(v, list):
                    print(f'  {k}: list length {len(v)}')
                    if v:
                        sample = v[0]
                        if isinstance(sample, str):
                            print(f'    sample: {sample[:200]}')
                        elif isinstance(sample, dict):
                            print(f'    sample dict keys: {list(sample.keys())}')
                else:
                    print(f'  {k}: {type(v)}')
        except json.JSONDecodeError as e:
            print('❌ JSON decode error:', e)
            # Show where error occurs
            print('Error at position', e.pos)
            # Show surrounding text
            start = max(0, e.pos - 100)
            end = min(len(raw), e.pos + 100)
            print('Context:', raw[start:end])
            # Look for possible closing brace missing
            # Count braces
            open_braces = raw.count('{')
            close_braces = raw.count('}')
            print(f'Open braces: {open_braces}, Close braces: {close_braces}')
            # Look for trailing text after JSON
            # Try to find the last '}'
            last_close = raw.rfind('}')
            if last_close != -1:
                after = raw[last_close+1:]
                if after.strip():
                    print(f'Text after last }: {after[:200]}')
                else:
                    print('No text after last }')
            # Also check if there is a markdown fence
            if '```' in raw:
                print('Contains markdown fence')
        # Also run the parse_brief_json function
        text = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        print('\nAfter stripping fences:', text[:500])
        try:
            data2 = json.loads(text)
            print('JSON load after strip succeeded')
        except json.JSONDecodeError as e2:
            print('JSON load after strip failed:', e2)

if __name__ == '__main__':
    asyncio.run(check())