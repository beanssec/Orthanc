"""Static entity alias/abbreviation map for normalization.

Each entry is ``(canonical_normalized, [alias_normalized, ...])``.

*canonical* — the preferred normalized form (stored in DB ``canonical_name``).
*aliases*   — common abbreviations and variants that collapse to the canonical.

All strings are **lowercase, alphanumeric + spaces only, single-spaced**.

The upstream normalization pipeline converts dotted abbreviations before
this lookup, e.g.  U.S.A. → "u s a",  I.R.G.C. → "i r g c",  so list
those spaced forms here rather than the dotted originals.

To extend: append entries to ``ALIAS_GROUPS`` below.  Run the module
directly (``python entity_aliases.py``) to print the full lookup table
and verify for conflicts.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("orthanc.entity_aliases")

# ---------------------------------------------------------------------------
# ALIAS GROUPS
# Format: (canonical, [alias, alias, ...])
# ---------------------------------------------------------------------------

ALIAS_GROUPS: list[tuple[str, list[str]]] = [

    # ── Countries / Territories (GPE) ──────────────────────────────────────

    ("united states", [
        "us", "u s",
        "usa", "u s a",
    ]),

    ("united kingdom", [
        "uk", "u k",
        "gb",                           # ISO 3166-1
        "great britain",                # colloquial (technically excludes NI)
        "britain",                      # colloquial
    ]),

    ("united arab emirates", [
        "uae", "u a e",
    ]),

    ("european union", [
        "eu", "e u",
    ]),

    ("united nations", [
        "un", "u n",
    ]),

    ("peoples republic of china", [
        "prc", "p r c",
    ]),

    ("south korea", [
        "rok", "r o k",
        "republic of korea",
    ]),

    ("north korea", [
        "dprk", "d p r k",
        "democratic peoples republic of korea",
    ]),

    # ── Military & Intelligence Organisations (ORG) ─────────────────────────

    ("nato", [
        "n a t o",
        "north atlantic treaty organization",
        "north atlantic treaty organisation",
    ]),

    ("irgc", [
        "i r g c",
        "islamic revolutionary guard corps",
        "islamic revolutionary guards corps",
        "iranian revolutionary guard corps",
    ]),

    ("idf", [
        "i d f",
        "israel defense forces",
        "israeli defense forces",
        "israel defence forces",
    ]),

    ("cia", [
        "c i a",
        "central intelligence agency",
    ]),

    ("fbi", [
        "f b i",
        "federal bureau of investigation",
    ]),

    ("nsa", [
        "n s a",
        "national security agency",
    ]),

    ("fsb", [
        "f s b",
        "federal security service",         # Russia's domestic intel
    ]),

    ("gru", [
        "g r u",
        "main intelligence directorate",
        "main directorate of the general staff",
    ]),

    ("mi6", [
        "m i 6",
        "secret intelligence service",
    ]),

    ("mi5", [
        "m i 5",
    ]),

    ("mossad", [
        "ha mossad",
        "institute for intelligence and special operations",
    ]),

    ("interpol", [
        "international criminal police organization",
        "international criminal police organisation",
    ]),

    # ── Militant / Non-State Actors (ORG / NORP) ────────────────────────────

    ("hamas", [
        "harakat al muqawama al islamiyya",
        "islamic resistance movement",
    ]),

    ("hezbollah", [
        "hizballah", "hizbullah", "hizbollah",
        "hizb allah",
        "party of god",
        "islamic jihad organization",       # known alias in some contexts
    ]),

    ("al qaeda", [
        "al qaida",
        "al qa ida",
        "al qai da",
        "qaeda",
        "qaida",
    ]),

    ("isis", [
        "isil",
        "daesh",
        "islamic state",
        "islamic state of iraq and syria",
        "islamic state of iraq and the levant",
    ]),

    # ── International Bodies (ORG) ──────────────────────────────────────────

    ("un security council", [
        "unsc", "u n s c",
    ]),

    ("un general assembly", [
        "unga", "u n g a",
    ]),

    ("international monetary fund", [
        "imf", "i m f",
    ]),

    ("world health organization", [
        "who", "w h o",
        "world health organisation",
    ]),

    ("world trade organization", [
        "wto", "w t o",
        "world trade organisation",
    ]),

    ("international atomic energy agency", [
        "iaea", "i a e a",
    ]),

    ("international criminal court", [
        "icc", "i c c",
    ]),

    ("international court of justice", [
        "icj", "i c j",
    ]),

    ("organization of the petroleum exporting countries", [
        "opec", "o p e c",
    ]),

    ("african union", [
        "au", "a u",
    ]),

    ("association of southeast asian nations", [
        "asean", "a s e a n",
    ]),

    ("world bank", [
        "ibrd",                             # International Bank for Reconstruction and Development
        "international bank for reconstruction and development",
    ]),
]


def build_lookup() -> dict[str, str]:
    """Return a flat ``alias → canonical`` dict from :data:`ALIAS_GROUPS`.

    The canonical itself is mapped to itself so the result is always safe
    to use as a no-op pass-through (``lookup.get(n, n)``).

    Conflicts (same alias claimed by two canonicals) are logged as warnings
    and the *first* definition wins.
    """
    lookup: dict[str, str] = {}
    for canonical, aliases in ALIAS_GROUPS:
        lookup.setdefault(canonical, canonical)
        for alias in aliases:
            if alias in lookup and lookup[alias] != canonical:
                logger.warning(
                    "Alias conflict: %r maps to both %r and %r — keeping first",
                    alias, lookup[alias], canonical,
                )
                continue
            lookup[alias] = canonical
    return lookup


# Pre-built at import time; import this symbol in entity_extractor.
ALIAS_LOOKUP: dict[str, str] = build_lookup()


# ---------------------------------------------------------------------------
# CLI sanity helper — run `python entity_aliases.py` to dump the table
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        # Quick spot-check for a hard-coded set of expected mappings
        cases = [
            ("us",                     "united states"),
            ("u s",                    "united states"),
            ("usa",                    "united states"),
            ("u s a",                  "united states"),
            ("united states",          "united states"),
            ("uk",                     "united kingdom"),
            ("u k",                    "united kingdom"),
            ("great britain",          "united kingdom"),
            ("britain",                "united kingdom"),
            ("uae",                    "united arab emirates"),
            ("u a e",                  "united arab emirates"),
            ("eu",                     "european union"),
            ("un",                     "united nations"),
            ("nato",                   "nato"),
            ("n a t o",                "nato"),
            ("north atlantic treaty organization", "nato"),
            ("irgc",                   "irgc"),
            ("i r g c",                "irgc"),
            ("islamic revolutionary guard corps", "irgc"),
            ("idf",                    "idf"),
            ("i d f",                  "idf"),
            ("israel defense forces",  "idf"),
            ("cia",                    "cia"),
            ("fbi",                    "fbi"),
            ("who",                    "world health organization"),
            ("isis",                   "isis"),
            ("isil",                   "isis"),
            ("daesh",                  "isis"),
            ("al qaida",               "al qaeda"),
            ("hizballah",              "hezbollah"),
        ]
        failed = 0
        for alias, expected in cases:
            got = ALIAS_LOOKUP.get(alias, alias)
            status = "OK" if got == expected else "FAIL"
            if status == "FAIL":
                failed += 1
            print(f"  {status}  {alias!r:45s} → {got!r}  (expected {expected!r})")
        print(f"\n{'All checks passed.' if not failed else f'{failed} check(s) FAILED.'}")
        sys.exit(1 if failed else 0)
    else:
        print(f"ALIAS_LOOKUP ({len(ALIAS_LOOKUP)} entries):\n")
        for k, v in sorted(ALIAS_LOOKUP.items()):
            if k != v:
                print(f"  {k!r:50s} → {v!r}")
