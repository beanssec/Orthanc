#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')
import asyncio
import json
import re
from app.db import AsyncSessionLocal
from app.models.brief import Brief
from sqlalchemy import select, desc

async def check():
    async with AsyncSessionLocal() as session:
        stmt = select(Brief).order_by(Brief.generated_at.desc()).limit(1)
        result = await session.execute(stmt)
        b = result.scalar_one_or_none()
        if not b:
            return
        raw = b.summary
        print('Length:', len(raw))
        # Show last 1000 chars
        tail = raw[-1000:]
        print('\n--- Tail 1000 chars ---')
        print(tail)
        # Show from error position -50 to end
        error_pos = 11289
        start = max(0, error_pos - 50)
        end = len(raw)
        print('\n--- Around error position ---')
        print(raw[start:end])
        # Count braces in whole text
        open_braces = raw.count('{')
        close_braces = raw.count('}')
        print(f'\nOpen braces: {open_braces}, Close braces: {close_braces}')
        # Find positions of braces
        opens = [i for i, ch in enumerate(raw) if ch == '{']
        closes = [i for i, ch in enumerate(raw) if ch == '}']
        print(f'First open at {opens[0] if opens else -1}')
        print(f'Last close at {closes[-1] if closes else -1}')
        # Check if there is a missing quote
        # Let's see the substring around error pos
        sub = raw[error_pos-20:error_pos+20]
        print(f'\nSubstring around error: {repr(sub)}')
        # Try to fix by adding a closing quote and maybe braces
        # Let's attempt to close the string and add missing braces
        # We'll try to find the last comma before error pos
        # Actually the error is "Unterminated string starting at: line 1 column 11290"
        # Means a string started but not closed before end of JSON.
        # Let's find the starting quote of that string.
        # Search backwards from error_pos for a double quote not escaped
        pos = error_pos
        while pos >= 0 and raw[pos] != '"':
            pos -= 1
        if pos >= 0:
            # Check if escaped
            if raw[pos-1] != '\\':
                print(f'String starts at position {pos}')
                # The string is not closed before end of data.
                # Let's see the content after start
                string_content = raw[pos+1:error_pos]
                print(f'String content (partial): {string_content[:200]}')
        # Attempt to fix by adding a closing quote at end and then close braces
        # But we need to know the structure. Let's attempt to parse as JSON with repair using json_repair maybe not installed.
        # We'll just manually add missing braces based on count.
        diff = open_braces - close_braces
        print(f'Braces difference: {diff}')
        if diff > 0:
            # missing closing braces
            repaired = raw + '}' * diff
            print('Added', diff, 'closing braces')
            # Try parse
            try:
                json.loads(repaired)
                print('Repaired JSON parses!')
            except json.JSONDecodeError as e:
                print('Still fails:', e)
        # Also check if there is a missing closing bracket for array
        open_brackets = raw.count('[')
        close_brackets = raw.count(']')
        print(f'Open brackets: {open_brackets}, Close brackets: {close_brackets}')
        # Maybe the JSON is truncated mid-string. Let's see if the raw ends with a comma or something.
        print('\nRaw ends with:', repr(raw[-50:]))

if __name__ == '__main__':
    asyncio.run(check())