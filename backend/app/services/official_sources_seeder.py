"""Official Sources Seeder — Sprint 32 Checkpoint 3.

Creates Source records for system-level official/sanctions/maritime feeds so
that they carry proper source_class, default_reliability_prior, and ecosystem
metadata. Seeded per-user, idempotent: skips any source already present for
a given user (matched on type + handle).

Covers:
  - Sanctions: OFAC SDN, UK FCDO, UN SC, EU FSF
  - Diplomacy: US State Dept RSS, China MFA
  - Energy:    OPEC Press Releases
  - Maritime:  US MARAD, UKMTO
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.source import Source
from app.models.user import User

logger = logging.getLogger("orthanc.official_sources.seeder")

# ---------------------------------------------------------------------------
# Source definitions
# ---------------------------------------------------------------------------

OFFICIAL_SOURCES: list[dict] = [
    # ── Sanctions ────────────────────────────────────────────────────────────
    {
        "type": "official",
        "handle": "ofac_sdn",
        "display_name": "OFAC SDN List",
        "source_class": "official",
        "default_reliability_prior": "high",
        "ecosystem": "sanctions",
        "risk_note": None,
    },
    {
        "type": "official",
        "handle": "ofac_consolidated",
        "display_name": "OFAC Consolidated Sanctions List",
        "source_class": "official",
        "default_reliability_prior": "high",
        "ecosystem": "sanctions",
        "risk_note": None,
    },
    {
        "type": "official",
        "handle": "ofac_recent_actions",
        "display_name": "OFAC Recent Actions",
        "source_class": "official",
        "default_reliability_prior": "high",
        "ecosystem": "sanctions",
        "risk_note": None,
    },
    {
        "type": "official",
        "handle": "uk_fcdo_sanctions",
        "display_name": "UK FCDO Sanctions List",
        "source_class": "official",
        "default_reliability_prior": "high",
        "ecosystem": "sanctions",
        "risk_note": None,
    },
    {
        "type": "official",
        "handle": "un_sc_sanctions",
        "display_name": "UN Security Council Consolidated Sanctions List",
        "source_class": "official",
        "default_reliability_prior": "high",
        "ecosystem": "sanctions",
        "risk_note": None,
    },
    {
        "type": "official",
        "handle": "eu_fsf_sanctions",
        "display_name": "EU Financial Sanctions Files (FSF)",
        "source_class": "official",
        "default_reliability_prior": "high",
        "ecosystem": "sanctions",
        "risk_note": None,
    },
    # ── Diplomacy ────────────────────────────────────────────────────────────
    {
        "type": "rss",
        "handle": "state_dept_rss",
        "display_name": "US State Department Press Releases",
        "source_class": "official",
        "default_reliability_prior": "high",
        "ecosystem": "diplomacy",
        "risk_note": None,
    },
    {
        "type": "scraper",
        "handle": "china_mfa",
        "display_name": "China MFA Spokesperson Remarks",
        "source_class": "state_media",
        "default_reliability_prior": "medium",
        "ecosystem": "diplomacy",
        "risk_note": "Official Chinese government positions; cross-check with independent sources.",
    },
    # ── Energy ───────────────────────────────────────────────────────────────
    {
        "type": "scraper",
        "handle": "opec_press",
        "display_name": "OPEC Press Releases",
        "source_class": "official",
        "default_reliability_prior": "medium",
        "ecosystem": "energy",
        "risk_note": None,
    },
    # ── Maritime ─────────────────────────────────────────────────────────────
    {
        "type": "scraper",
        "handle": "marad_advisories",
        "display_name": "US MARAD Maritime Safety Advisories",
        "source_class": "official",
        "default_reliability_prior": "high",
        "ecosystem": "maritime",
        "risk_note": None,
    },
    {
        "type": "scraper",
        "handle": "ukmto_warnings",
        "display_name": "UKMTO Warnings & Advisories",
        "source_class": "official",
        "default_reliability_prior": "high",
        "ecosystem": "maritime",
        "risk_note": None,
    },
]


async def seed_official_sources() -> None:
    """Seed official/sanctions/maritime Source records for all users. Idempotent."""
    async with AsyncSessionLocal() as session:
        all_users_result = await session.execute(select(User))
        users = all_users_result.scalars().all()

        if not users:
            logger.info("No users found — official sources seeder will re-run on next startup")
            return

        total_added = 0

        for user in users:
            user_added = 0
            for defn in OFFICIAL_SOURCES:
                handle = defn["handle"]
                src_type = defn["type"]

                existing = await session.execute(
                    select(Source).where(
                        Source.user_id == user.id,
                        Source.type == src_type,
                        Source.handle == handle,
                    )
                )
                if existing.scalars().first():
                    continue  # Already seeded for this user

                source = Source(
                    user_id=user.id,
                    type=src_type,
                    handle=handle,
                    display_name=defn["display_name"],
                    enabled=True,
                    source_class=defn["source_class"],
                    default_reliability_prior=defn["default_reliability_prior"],
                    ecosystem=defn["ecosystem"],
                    risk_note=defn.get("risk_note"),
                    config_json={
                        "source_class": defn["source_class"],
                        "reliability": defn["default_reliability_prior"],
                        "ecosystem": defn["ecosystem"],
                        "seeded_by": "official_sources_seeder",
                    },
                )
                session.add(source)
                user_added += 1

            if user_added:
                logger.info(
                    "Official sources seeder: added %d sources for user %s",
                    user_added,
                    str(user.id),
                )
                total_added += user_added

        await session.commit()

    if total_added:
        logger.info("Official sources seeder: added %d source records total", total_added)
    else:
        logger.info("Official sources seeder: all sources already seeded (no-op)")
