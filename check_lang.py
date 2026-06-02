import asyncio
import re
from app.db import AsyncSessionLocal
from app.models.post import Post
from sqlalchemy import select

CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")
FARSI_SPECIFIC = re.compile(r"[\u06C0-\u06D3\u06F0-\u06FF\u0750-\u077F]")
CHINESE_RE = re.compile(r"[\u4E00-\u9FFF\u3400-\u4DBF\u20000-\u2A6DF]")
KOREAN_RE = re.compile(r"[\uAC00-\uD7AF\u1100-\u11FF]")
HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
LATIN_RE = re.compile(r"[a-zA-Z]")

async def analyze():
    async with AsyncSessionLocal() as session:
        stmt = select(Post).where(Post.author.ilike('%AMK%')).limit(20)
        result = await session.execute(stmt)
        for post in result.scalars():
            print('---')
            print('ID:', post.id)
            print('Author:', post.author)
            print('Detected language:', post.detected_language)
            content = post.content or ''
            print('Content length:', len(content))
            # Show first 300 chars with repr
            print('Content (repr):', repr(content[:300]))
            # Count characters
            total = len(content)
            if total == 0:
                continue
            chinese = len(CHINESE_RE.findall(content))
            cyrillic = len(CYRILLIC_RE.findall(content))
            arabic = len(ARABIC_RE.findall(content))
            latin = len(LATIN_RE.findall(content))
            print(f'Chinese chars: {chinese} ({chinese/total*100:.1f}%)')
            print(f'Cyrillic chars: {cyrillic}')
            print(f'Arabic chars: {arabic}')
            print(f'Latin letters: {latin}')
            # Check for any non-Latin characters
            non_latin = total - latin
            print(f'Non-Latin chars: {non_latin}')
            # Detect language using same heuristic
            if chinese / total > 0.20:
                print('Heuristic says: zh')
            elif cyrillic / total > 0.20:
                print('Heuristic says: ru/uk')
            elif arabic / total > 0.20:
                print('Heuristic says: ar/fa')
            else:
                print('Heuristic says: en')

asyncio.run(analyze())