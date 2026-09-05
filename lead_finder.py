"""
Finds businesses that likely need a website / landing page / WhatsApp AI agent.

Uses Places API (New) - https://places.googleapis.com/v1/places:searchText
(the older "legacy" Places API is being phased out by Google and requires a separate,
no-longer-recommended enablement step, so we use the current one directly).

Strategy:
  1. Search Places (New) Text Search across category x location combos.
  2. A lead qualifies if:
       - no "websiteUri" field at all  -> definitely needs a website/landing page, OR
       - website exists but is just a Facebook/Instagram page link -> needs a real site
  3. Skip anything already in the contacted-leads log (dedupe).
  4. India leads are split off into a separate list for manual WhatsApp/call outreach.
"""
import csv
import math
import os
import random
import re
import requests

import config

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.websiteUri",
    "places.nationalPhoneNumber",
    "places.rating",
    "places.userRatingCount",
    "places.types",
])

SOCIAL_ONLY_DOMAINS = (
    "facebook.com", "fb.com",
    "instagram.com",
    "linktr.ee", "linktree.com",
    "linkedin.com",
    "tiktok.com",
    "twitter.com", "x.com",
    "youtube.com",
    "wa.me", "whatsapp.com",
    "beacons.ai", "bio.link", "linkbio.co",
)


# ---------------------------------------------------------------------------
# Dedupe helpers
# ---------------------------------------------------------------------------

def _load_contacted_place_ids():
    """Load place_ids from contacted_leads.csv, pending_review.csv, AND india_leads.csv."""
    ids = set()

    if os.path.exists(config.LEADS_LOG_CSV):
        with open(config.LEADS_LOG_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pid = row.get("place_id", "")
                if pid:
                    ids.add(pid)

    pending_path = getattr(config, "PENDING_REVIEW_CSV", "data/pending_review.csv")
    if os.path.exists(pending_path):
        with open(pending_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pid = row.get("id", "")
                if pid:
                    ids.add(pid)

    india_path = getattr(config, "INDIA_LEADS_CSV", "data/india_leads.csv")
    if os.path.exists(india_path):
        with open(india_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pid = row.get("place_id", "")
                if pid:
                    ids.add(pid)

    return ids


# ---------------------------------------------------------------------------
# Places API
# ---------------------------------------------------------------------------

def _search_places(query):
    resp = requests.post(
        SEARCH_URL,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": config.GOOGLE_PLACES_API_KEY,
            "X-Goog-FieldMask": FIELD_MASK,
        },
        json={"textQuery": query},
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"  [!] Places API error for '{query}': {resp.status_code} - {resp.text[:300]}")
        return []
    return resp.json().get("places", [])


# ---------------------------------------------------------------------------
# URL / need classification helpers
# ---------------------------------------------------------------------------

def _is_social_url(url):
    """Returns True if the URL belongs to a social/link-in-bio platform, not a real website."""
    if not url:
        return False
    return any(domain in url.lower() for domain in SOCIAL_ONLY_DOMAINS)


def _needs_website(website_url):
    if not website_url:
        return True
    return _is_social_url(website_url)


def _suggest_need(lead):
    """
    Rule-based need classifier. Returns one of:
      - "Website"
      - "Booking or landing page"
      - "Meta/Instagram ads"
    """
    website = lead.get("website", "")
    has_real_website = bool(website) and not _is_social_url(website)

    if has_real_website:
        return "Meta/Instagram ads"

    # No real website — check if the category suggests a booking/landing page
    category_lower = lead.get("category", "").lower()
    booking_keywords = getattr(config, "BOOKING_PAGE_CATEGORIES", [])
    for keyword in booking_keywords:
        if keyword in category_lower:
            return "Booking or landing page"

    return "Website"


def _phone_to_whatsapp_link(phone, country_code="91"):
    """Convert a phone number to a wa.me link with Indian country code."""
    if not phone:
        return ""
    digits = re.sub(r"[^\d]", "", phone)
    # If it already starts with the country code, use as-is
    if digits.startswith(country_code) and len(digits) > 10:
        return f"https://wa.me/{digits}"
    # Strip leading 0 if present (common in Indian local numbers)
    if digits.startswith("0"):
        digits = digits[1:]
    return f"https://wa.me/{country_code}{digits}"


# ---------------------------------------------------------------------------
# Lead normalization (shared between India and international)
# ---------------------------------------------------------------------------

def _normalize_place(r, category, location, already_contacted):
    """
    Normalizes a Places API result into a lead dict.
    Returns None if the lead should be skipped (already contacted, has real website).
    """
    place_id = r.get("id")
    if not place_id or place_id in already_contacted:
        return None

    if not _needs_website(r.get("websiteUri")):
        return None  # they already have a real website - not a fit

    raw_website = r.get("websiteUri", "")
    if _is_social_url(raw_website):
        real_website = ""
        social_links = raw_website
    else:
        real_website = raw_website
        social_links = ""

    return {
        "place_id": place_id,
        "name": r.get("displayName", {}).get("text", ""),
        "address": r.get("formattedAddress", ""),
        "phone": r.get("nationalPhoneNumber", ""),
        "website": real_website,
        "social_links": social_links,
        "rating": r.get("rating", ""),
        "review_count": r.get("userRatingCount", ""),
        "category": category,
        "location": location,
        "types": ", ".join(r.get("types", [])),
    }


# ---------------------------------------------------------------------------
# Public finders
# ---------------------------------------------------------------------------

def find_leads(target_count=30, max_searches=40):
    """
    Returns a list of qualified INTERNATIONAL lead dicts, capped at target_count.
    Uses config.SEARCH_CATEGORIES x config.SEARCH_LOCATIONS.
    """
    if not config.GOOGLE_PLACES_API_KEY or "your_google" in config.GOOGLE_PLACES_API_KEY:
        print("  [!] GOOGLE_PLACES_API_KEY is missing or still the placeholder value in .env")
        return []

    already_contacted = _load_contacted_place_ids()
    leads = []
    searches_done = 0

    combos = [(cat, loc) for cat in config.SEARCH_CATEGORIES for loc in config.SEARCH_LOCATIONS]
    random.shuffle(combos)

    for category, location in combos:
        if len(leads) >= target_count or searches_done >= max_searches:
            break
        query = f"{category} in {location}"
        results = _search_places(query)
        searches_done += 1

        for r in results:
            if len(leads) >= target_count:
                break
            lead = _normalize_place(r, category, location, already_contacted)
            if lead:
                leads.append(lead)

    return leads


def find_india_leads(target_count=4, max_searches=20):
    """
    Returns a list of qualified INDIA lead dicts, capped at target_count.
    Uses config.INDIA_SEARCH_CATEGORIES x config.INDIA_SEARCH_LOCATIONS.
    """
    if not config.GOOGLE_PLACES_API_KEY or "your_google" in config.GOOGLE_PLACES_API_KEY:
        print("  [!] GOOGLE_PLACES_API_KEY is missing or still the placeholder value in .env")
        return []

    india_categories = getattr(config, "INDIA_SEARCH_CATEGORIES", None) or config.SEARCH_CATEGORIES
    india_locations = getattr(config, "INDIA_SEARCH_LOCATIONS", [])
    if not india_categories or not india_locations:
        return []

    already_contacted = _load_contacted_place_ids()
    leads = []
    searches_done = 0

    combos = [(cat, loc) for cat in india_categories for loc in india_locations]
    random.shuffle(combos)

    for category, location in combos:
        if len(leads) >= target_count or searches_done >= max_searches:
            break
        query = f"{category} in {location}"
        results = _search_places(query)
        searches_done += 1

        for r in results:
            if len(leads) >= target_count:
                break
            lead = _normalize_place(r, category, location, already_contacted)
            if lead:
                leads.append(lead)

    return leads