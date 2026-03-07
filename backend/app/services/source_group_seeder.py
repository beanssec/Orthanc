"""Seed default source groups and auto-assign sources."""
import logging
from sqlalchemy import select
from app.db import AsyncSessionLocal
from app.models.narrative import SourceGroup, SourceGroupMember
from app.models.source import Source

logger = logging.getLogger("orthanc.narrative.seeder")

DEFAULT_GROUPS = {
    "western": {
        "display_name": "Western Media",
        "color": "#3b82f6",
        "description": "Western mainstream media and think tanks",
        "keywords": ["BBC", "NYT", "Reuters", "Al Jazeera", "Defense One", "Foreign Policy",
                     "Breaking Defense", "Defense News", "Stars and Stripes", "The Diplomat",
                     "War on the Rocks", "The War Zone", "Naval News", "CENTCOM", "sentdefender",
                     "Andrew Fox", "ASPI"],
    },
    "russian": {
        "display_name": "Russian/Eastern Media",
        "color": "#ef4444",
        "description": "Russian state and pro-Russian sources",
        "keywords": ["TASS", "Rybar", "Two Majors", "dva_majors", "Intel Slava", "inteIIigeance",
                     "South Front", "SouthFront", "Legitimny", "legitimniy"],
    },
    "ukrainian": {
        "display_name": "Ukrainian Sources",
        "color": "#fbbf24",
        "description": "Ukrainian government and media sources",
        "keywords": ["Ukrinform", "Kyiv Independent", "DeepState", "DeepStateUA"],
    },
    "osint": {
        "display_name": "OSINT Community",
        "color": "#10b981",
        "description": "Open-source intelligence analysts and investigators",
        "keywords": ["Bellingcat", "Osinttechnical", "UAWeapons", "DefMon3", "GeoConfirmed",
                     "IntelCrab", "ELINTNews", "RALee85", "christogrozev", "EliotHiggins",
                     "AricToler", "TankerTrackers", "SquawkMilitary", "AircraftSpots",
                     "AMK", "CyberspecNews", "OSINT"],
    },
    "independent": {
        "display_name": "Independent Analysis",
        "color": "#f59e0b",
        "description": "Independent research, think tanks, and policy analysis",
        "keywords": ["Arms Control", "Bulletin", "IAEA", "ReliefWeb", "geopolitics",
                     "CredibleDefense", "syriancivilwar", "UkraineRussiaReport"],
    },
    "cyber": {
        "display_name": "Cyber Intelligence",
        "color": "#8b5cf6",
        "description": "Cybersecurity news and threat intelligence",
        "keywords": ["The Record", "BleepingComputer", "Krebs", "CyberScoop", "Cyberspec"],
    },
    "maritime": {
        "display_name": "Maritime/Logistics",
        "color": "#06b6d4",
        "description": "Maritime trade, logistics, and shipping",
        "keywords": ["gCaptain", "FreightWaves", "Splash247", "OilPrice", "Rigzone"],
    },
}


async def seed_source_groups():
    """Create default source groups and auto-assign sources by keyword matching."""
    async with AsyncSessionLocal() as session:
        # Check if groups already seeded
        existing = await session.execute(select(SourceGroup).limit(1))
        if existing.scalars().first():
            return  # Already seeded

        # Get all sources
        all_sources = await session.execute(select(Source))
        sources = all_sources.scalars().all()

        for group_name, group_data in DEFAULT_GROUPS.items():
            # Create group
            group = SourceGroup(
                name=group_name,
                display_name=group_data["display_name"],
                color=group_data["color"],
                description=group_data["description"],
            )
            session.add(group)
            await session.flush()  # Get ID

            # Auto-assign sources by keyword matching on display_name or handle
            keywords = group_data["keywords"]
            assigned = 0
            for source in sources:
                source_text = f"{source.display_name or ''} {source.handle}".lower()
                if any(kw.lower() in source_text for kw in keywords):
                    member = SourceGroupMember(
                        source_group_id=group.id,
                        source_id=source.id,
                    )
                    session.add(member)
                    assigned += 1

            logger.info("Source group '%s': assigned %d sources", group_name, assigned)

        await session.commit()
        logger.info("Default source groups seeded")
