#!/usr/bin/env python3
"""Live demo: Tavily search + SNIFF principle-5 listing/country filter.

Stdlib only. Not part of the scored engine run.

  python -m integrations.tavily.demo --name "Nicolas Maduro" \\
      --category Sanctions --countries "Venezuela"
"""
from __future__ import annotations

import argparse
import os
import sys

from .client import TavilyNotConfiguredError, is_configured, search_external_intelligence

# Exact listing phrases from system/engine.py LISTING_PHRASES / OTHER_LISTING
# (copied here so this demo never imports system/).
LISTING_PHRASES = {
    "sanctions": "a sanctioned individual",
    "pep": "a politically exposed person",
    "enforcement": "the subject of enforcement action",
    "adverse media": "named in adverse media",
    "soe": "a state-owned enterprise official",
}
OTHER_LISTING = "named on a watchlist"

# Plain category / listing words accepted alongside the exact phrases.
PLAIN_LISTING_WORDS = (
    "sanction",
    "politically exposed",
    "pep",
    "enforcement",
    "charged",
    "convicted",
    "fraud",
)

CLOSING = (
    "Live web results can never clear a hit on their own in SNIFF. "
    "The scored engine uses the search_results file only, for reproducibility."
)


def _listing_match(text: str, category: str) -> bool:
    low = (text or "").lower()
    cat = (category or "").strip().lower()
    phrase = LISTING_PHRASES.get(cat, OTHER_LISTING)
    if phrase.lower() in low:
        return True
    for word in PLAIN_LISTING_WORDS:
        if word.lower() in low:
            return True
    # Also accept the category token itself when it is a meaningful word.
    if cat and len(cat) >= 3 and cat in low:
        return True
    return False


def _country_match(text: str, countries: list[str]) -> bool:
    low = (text or "").lower()
    for c in countries:
        c = (c or "").strip()
        if c and c.lower() in low:
            return True
    return False


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Tavily live search filtered by SNIFF principle 5 (listing + country)."
    )
    p.add_argument("--name", required=True, help="Hit / person name to search")
    p.add_argument("--category", required=True, help="Primary category, e.g. Sanctions")
    p.add_argument(
        "--countries",
        required=True,
        help='Comma-separated countries tied to the hit, e.g. "Venezuela"',
    )
    args = p.parse_args(argv)

    if not is_configured():
        print("Set TAVILY_API_KEY first")
        return 1

    countries = [c.strip() for c in args.countries.split(",") if c.strip()]
    try:
        result = search_external_intelligence(args.name)
    except TavilyNotConfiguredError:
        print("Set TAVILY_API_KEY first")
        return 1

    print(f"query: {result.query!r}  results: {len(result.results)}")
    print(f"category: {args.category}  countries: {', '.join(countries) or '(none)'}")
    print()

    for i, hit in enumerate(result.results, 1):
        text = " ".join(x for x in (hit.title, hit.content, hit.url) if x)
        listing_ok = _listing_match(text, args.category)
        country_ok = _country_match(text, countries)
        keep = listing_ok and country_ok
        label = "KEEP" if keep else "DISCARD"
        print(f"[{i}] {label}")
        print(f"    listing match: {listing_ok}")
        print(f"    country match: {country_ok}")
        print(f"    title: {hit.title}")
        print(f"    url:   {hit.url}")
        print()

    print(CLOSING)
    return 0


if __name__ == "__main__":
    sys.exit(main())
