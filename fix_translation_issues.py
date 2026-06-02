#!/usr/bin/env python3
"""
Fix translation misclassifications and clear unnecessary translations.
"""
import asyncio
import sys
sys.path.insert(0, '/app')

from app.db import AsyncSessionLocal
from app.models.post import Post
from sqlalchemy import select, update, and_
from app.services.translator import translator

BATCH_SIZE = 500

async def fix_false_positives(dry_run=False, limit=5000):
    """Update posts where detected_language != 'en' but content is actually English."""
    async with AsyncSessionLocal() as session:
        # Select posts with non-English detection, excluding NULL
        stmt = select(Post).where(
            Post.detected_language != 'en',
            Post.detected_language.is_not(None),
            Post.content.is_not(None)
        ).limit(limit)
        result = await session.execute(stmt)
        posts = result.scalars().all()
        print(f'Found {len(posts)} posts with detected_language != "en"')
        updated = 0
        for post in posts:
            new_lang = await translator.detect_language(post.content or '')
            if new_lang == 'en':
                if not dry_run:
                    post.detected_language = 'en'
                    post.translated_content = None
                    post.translation_model = None
                updated += 1
                if updated % 100 == 0:
                    print(f'  Updated {updated} posts...')
        if updated and not dry_run:
            await session.commit()
            print(f'Committed {updated} false positive corrections.')
        elif updated:
            print(f'Would have updated {updated} false positive posts (dry-run).')
        else:
            print('No false positives found.')
        return updated

async def clear_unnecessary_translations(dry_run=False):
    """Clear translated_content for posts where detected_language = 'en'."""
    async with AsyncSessionLocal() as session:
        stmt = select(Post).where(
            Post.detected_language == 'en',
            Post.translated_content.is_not(None)
        )
        result = await session.execute(stmt)
        posts = result.scalars().all()
        print(f'Found {len(posts)} posts with detected_language=en but translation present')
        updated = 0
        for post in posts:
            if not dry_run:
                post.translated_content = None
                post.translation_model = None
            updated += 1
        if updated and not dry_run:
            await session.commit()
            print(f'Cleared translations for {updated} English posts.')
        elif updated:
            print(f'Would have cleared translations for {updated} English posts (dry-run).')
        else:
            print('No unnecessary translations found.')
        return updated

async def backfill_null_detection(dry_run=False, limit=2000):
    """Run detection on posts where detected_language is NULL."""
    async with AsyncSessionLocal() as session:
        stmt = select(Post).where(
            Post.detected_language.is_(None),
            Post.content.is_not(None),
            (Post.content != '') & (Post.content != ' ')
        ).limit(limit)
        result = await session.execute(stmt)
        posts = result.scalars().all()
        print(f'Found {len(posts)} posts with NULL detection')
        updated = 0
        for post in posts:
            lang = await translator.detect_language(post.content or '')
            if not dry_run:
                post.detected_language = lang
                # If lang != 'en', translation will be triggered later by auto_translator
            updated += 1
            if updated % 100 == 0:
                print(f'  Updated {updated} posts...')
        if updated and not dry_run:
            await session.commit()
            print(f'Updated detection for {updated} NULL posts.')
        elif updated:
            print(f'Would have updated detection for {updated} NULL posts (dry-run).')
        else:
            print('No NULL detection posts found.')
        return updated

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Dry run, no commits')
    parser.add_argument('--limit', type=int, default=5000, help='Max posts to process per step')
    parser.add_argument('--steps', choices=['false-positives', 'unnecessary-translations', 'null-detection', 'all'], default='all')
    args = parser.parse_args()
    
    if args.steps in ['false-positives', 'all']:
        print('\n=== Fixing false positives ===')
        await fix_false_positives(dry_run=args.dry_run, limit=args.limit)
    if args.steps in ['unnecessary-translations', 'all']:
        print('\n=== Clearing unnecessary translations ===')
        await clear_unnecessary_translations(dry_run=args.dry_run)
    if args.steps in ['null-detection', 'all']:
        print('\n=== Backfilling NULL detection ===')
        await backfill_null_detection(dry_run=args.dry_run, limit=args.limit)
    
    print('\nDone.')

if __name__ == '__main__':
    asyncio.run(main())