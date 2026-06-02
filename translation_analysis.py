#!/usr/bin/env python3
"""
Analyze translation misclassifications and LLM usage.
"""
import asyncio
import sys
sys.path.insert(0, '/app')

from app.db import AsyncSessionLocal
from app.models.post import Post
from sqlalchemy import select, func
from app.services.translator import translator

async def analyze():
    async with AsyncSessionLocal() as session:
        # Total posts
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
        translated_count = await session.scalar(stmt)
        print(f'\nPosts with translated_content: {translated_count}')
        
        # Count of posts where detected_language != 'en' but content is actually English (false positive)
        # We'll sample a subset for efficiency
        stmt = select(Post).where(
            Post.detected_language != 'en',
            Post.detected_language.is_not(None)
        ).limit(1000)
        result = await session.execute(stmt)
        false_positives = []
        for post in result.scalars():
            # Use translator to re-detect (with fixed regex)
            new_lang = await translator.detect_language(post.content or '')
            if new_lang == 'en':
                false_positives.append(post)
        print(f'\nSample false positives (detected != en, actually en): {len(false_positives)}')
        for i, post in enumerate(false_positives[:5]):
            print(f'  {i+1}. ID: {post.id}, Author: {post.author}, Detected: {post.detected_language}')
            print(f'     Content preview: {post.content[:100] if post.content else ""}')
        
        # Count of posts where detected_language = 'en' but translated_content not null (unnecessary translation)
        stmt = select(Post).where(
            Post.detected_language == 'en',
            Post.translated_content.is_not(None)
        ).limit(1000)
        result = await session.execute(stmt)
        unnecessary = list(result.scalars())
        print(f'\nPosts with detected_language=en but translated_content exists: {len(unnecessary)}')
        for i, post in enumerate(unnecessary[:5]):
            print(f'  {i+1}. ID: {post.id}, Author: {post.author}')
            print(f'     Translation model: {post.translation_model}')
        
        # Count of posts where translation_model is set (indicates LLM usage)
        stmt = select(Post.translation_model, func.count(Post.id)).where(
            Post.translation_model.is_not(None)
        ).group_by(Post.translation_model)
        result = await session.execute(stmt)
        print('\nTranslation model usage counts:')
        for model, cnt in result:
            print(f'  {model}: {cnt}')
        
        # Estimate cost: assume average tokens per translation. Hard to know without logs.
        # We'll just output raw counts.
        
        # Also check for posts where detected_language is NULL but content exists
        stmt = select(func.count(Post.id)).where(
            Post.detected_language.is_(None),
            Post.content.is_not(None)
        )
        null_detected = await session.scalar(stmt)
        print(f'\nPosts with NULL detected_language but content exists: {null_detected}')
        
        # Sample of such posts
        stmt = select(Post).where(
            Post.detected_language.is_(None),
            Post.content.is_not(None)
        ).limit(5)
        result = await session.execute(stmt)
        print('Sample NULL detected posts:')
        for post in result.scalars():
            print(f'  ID: {post.id}, Author: {post.author}')
            new_lang = await translator.detect_language(post.content or '')
            print(f'    New detection: {new_lang}')
        
        # Summary recommendations
        print('\n--- Recommendations ---')
        if false_positives:
            print(f'* Found {len(false_positives)} false positive non-English detections in sample.')
            print('  Consider updating all posts where detected_language != "en" but content is English.')
        if unnecessary:
            print(f'* Found {len(unnecessary)} posts where English content was translated unnecessarily.')
            print('  Consider clearing translated_content for English posts.')
        if null_detected:
            print(f'* Found {null_detected} posts with NULL detected_language.')
            print('  Consider running detection on them.')

if __name__ == '__main__':
    asyncio.run(analyze())