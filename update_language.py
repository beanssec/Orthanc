#!/usr/bin/env python3
"""
Update detected_language for posts that were misclassified due to regex bug.
Focus on AMK Mapping posts first, then optionally all zh posts.
"""
import asyncio
import sys
sys.path.insert(0, '/app')

from app.db import AsyncSessionLocal
from app.models.post import Post
from sqlalchemy import select, update
from app.services.translator import translator

async def update_amk_mapping():
    """Set detected_language = 'en' for AMK Mapping posts currently zh."""
    async with AsyncSessionLocal() as session:
        # Select posts where author contains AMK and detected_language = 'zh'
        stmt = select(Post).where(
            Post.author.ilike('%AMK%'),
            Post.detected_language == 'zh'
        )
        result = await session.execute(stmt)
        posts = result.scalars().all()
        print(f'Found {len(posts)} AMK Mapping posts with detected_language = zh')
        updated = 0
        for post in posts:
            # Re-evaluate language with corrected detection
            new_lang = await translator.detect_language(post.content or '')
            if new_lang != 'zh':
                post.detected_language = new_lang
                updated += 1
                print(f'  Updating {post.id} from zh to {new_lang}')
            else:
                print(f'  Keeping zh for {post.id}')
        if updated:
            await session.commit()
            print(f'Committed {updated} updates')
        else:
            print('No updates needed')
        return updated

async def update_all_zh():
    """Re-evaluate all posts with detected_language = 'zh' and correct if wrong."""
    async with AsyncSessionLocal() as session:
        stmt = select(Post).where(Post.detected_language == 'zh')
        result = await session.execute(stmt)
        posts = result.scalars().all()
        print(f'Found {len(posts)} posts with detected_language = zh')
        updated = 0
        for post in posts:
            new_lang = await translator.detect_language(post.content or '')
            if new_lang != 'zh':
                post.detected_language = new_lang
                updated += 1
                print(f'  Updating {post.id} from zh to {new_lang}')
        if updated:
            await session.commit()
            print(f'Committed {updated} updates')
        else:
            print('No updates needed')
        return updated

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--scope', choices=['amk', 'all'], default='amk',
                        help='Scope of posts to update')
    parser.add_argument('--dry-run', action='store_true',
                        help='Dry run, do not commit')
    args = parser.parse_args()
    
    if args.dry_run:
        print('DRY RUN - no changes will be committed')
        # monkey-patch commit to do nothing
        original_commit = AsyncSessionLocal.commit
        AsyncSessionLocal.commit = lambda self: None
    
    if args.scope == 'amk':
        await update_amk_mapping()
    else:
        await update_all_zh()

if __name__ == '__main__':
    asyncio.run(main())