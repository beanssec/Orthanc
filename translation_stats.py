#!/usr/bin/env python3
"""
Post-fix translation stats.
"""
import asyncio
import sys
sys.path.insert(0, '/app')

from app.db import AsyncSessionLocal
from app.models.post import Post
from sqlalchemy import select, func

async def stats():
    async with AsyncSessionLocal() as session:
        total = await session.scalar(select(func.count(Post.id)))
        print(f'Total posts: {total}')
        
        # Count by detected_language
        stmt = select(Post.detected_language, func.count(Post.id)).group_by(Post.detected_language)
        result = await session.execute(stmt)
        print('\nDetected language counts:')
        for lang, cnt in result:
            print(f'  {lang or "NULL"}: {cnt}')
        
        # Count of posts with translated_content not null
        stmt = select(func.count(Post.id)).where(Post.translated_content.is_not(None))
        translated = await session.scalar(stmt)
        print(f'\nPosts with translated_content: {translated}')
        
        # Count of posts where detected_language = 'zh'
        stmt = select(func.count(Post.id)).where(Post.detected_language == 'zh')
        zh_count = await session.scalar(stmt)
        print(f'Posts still detected as Chinese (zh): {zh_count}')
        
        # Sample a few zh posts to verify they are actually Chinese
        stmt = select(Post).where(Post.detected_language == 'zh').limit(5)
        result = await session.execute(stmt)
        print('\nSample zh posts:')
        for post in result.scalars():
            preview = post.content[:100] if post.content else ''
            print(f'  ID: {post.id}, Author: {post.author}')
            print(f'    Content: {preview}')
        
        # Count of posts where detected_language != 'en' but content is English (should be zero now)
        # We'll sample 100
        stmt = select(Post).where(
            Post.detected_language != 'en',
            Post.detected_language.is_not(None)
        ).limit(100)
        result = await session.execute(stmt)
        false_positives = []
        for post in result.scalars():
            # Quick heuristic: check if content contains Chinese characters
            import re
            chinese = re.compile(r'[\u4E00-\u9FFF\u3400-\u4DBF\U00020000-\U0002A6DF]')
            if not chinese.search(post.content or ''):
                # likely English
                false_positives.append(post)
        print(f'\nSample false positives remaining (non-English detection but no Chinese chars): {len(false_positives)}')
        for i, post in enumerate(false_positives[:3]):
            print(f'  {i+1}. ID: {post.id}, Detected: {post.detected_language}')
            print(f'     Preview: {post.content[:100] if post.content else ""}')
        
        # Translation model usage
        stmt = select(Post.translation_model, func.count(Post.id)).where(
            Post.translation_model.is_not(None)
        ).group_by(Post.translation_model)
        result = await session.execute(stmt)
        print('\nTranslation model usage counts:')
        for model, cnt in result:
            print(f'  {model}: {cnt}')
        
        # Posts with NULL detection
        stmt = select(func.count(Post.id)).where(Post.detected_language.is_(None))
        null_count = await session.scalar(stmt)
        print(f'\nPosts with NULL detected_language: {null_count}')
        
        # Posts with detected_language = 'en' but translated_content not null (should be zero)
        stmt = select(func.count(Post.id)).where(
            Post.detected_language == 'en',
            Post.translated_content.is_not(None)
        )
        en_translated = await session.scalar(stmt)
        print(f'English posts with translation (should be zero): {en_translated}')

if __name__ == '__main__':
    asyncio.run(stats())