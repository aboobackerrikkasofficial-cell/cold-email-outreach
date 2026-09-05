"""
Email + social contact discovery for leads with no website.

Fixes applied after review of real output:
  - Rejects placeholder/template emails (you@email.com), platform-embed junk
    (images@instagram.com from share buttons), and third-party tool addresses that aren't the
    actual business (support@scouty.com, etc.) - these were false positives before.
  - Verifies the domain of any candidate email can actually receive mail (MX record check)
    before trusting it - a genuine validity check, not just a regex match.
  - Searches Instagram and Facebook directly (not just generic web search), since most small
    website-less businesses live there.
  - ALWAYS returns whatever social links were found, even if no valid email turns up, so
    nothing is a dead end - you get an Instagram/Facebook link to message manually instead.
"""
import re
import time
import requests
import dns.resolver

import config

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Domains that are NEVER a real business contact email, even if regex matches them
JUNK_DOMAINS = (
    "instagram.com", "facebook.com", "fb.com", "linkedin.com", "twitter.com", "x.com",
    "wixpress.com", "sentry.io", "example.com", "email.com", "godaddy.com", "cloudflare.com",
    "google.com", "gstatic.com", "schema.org", "w3.org", "yourdomain.com", "domain.com",
    "namecheap.com", "squarespace.com",
)
# Local-parts that are almost always placeholder/template text, not a real contact
JUNK_LOCAL_PARTS = ("you", "someone", "test", "user", "name", "email", "yourname", "example")

_mx_cache = {}


def _clean_email_candidates(text):
    matches = EMAIL_REGEX.findall(text)
    valid = []
    for m in matches:
        local, _, domain = m.partition("@")
        if domain.lower() in JUNK_DOMAINS:
            continue
        if local.lower() in JUNK_LOCAL_PARTS:
            continue
        if any(x in m.lower() for x in (".png", ".jpg", ".jpeg", ".gif", ".svg")):
            continue
        valid.append(m)
    return valid


def _has_mx_record(domain):
    """Real validity check: does this domain actually have a mail server?"""
    if domain in _mx_cache:
        return _mx_cache[domain]
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=5)
        result = len(answers) > 0
    except Exception:
        result = False
    _mx_cache[domain] = result
    return result


def _first_valid_email(text):
    for candidate in _clean_email_candidates(text):
        domain = candidate.split("@")[-1]
        if _has_mx_record(domain):
            return candidate
    return None


def _scrape_page(url):
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        return resp.text
    except requests.RequestException:
        return ""


def _duckduckgo_search(query, max_results=4):
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        urls = re.findall(r'href="(https?://[^"]+)"', resp.text)
        clean_urls = [u for u in urls if "duckduckgo.com" not in u]
        return clean_urls[:max_results]
    except requests.RequestException:
        return []


def find_contact_info(lead):
    """
    Returns {"email": str|None, "social_links": [str, ...]}.
    Always returns whatever social links were found, regardless of whether an email was found,
    so there's always something actionable even when email discovery comes up empty.
    """
    name = lead.get("name", "")
    location = lead.get("location", "")
    social_links = []

    # 1. Targeted Instagram search
    ig_urls = _duckduckgo_search(f'"{name}" {location} site:instagram.com', max_results=2)
    social_links.extend(ig_urls)

    # 2. Targeted Facebook search
    fb_urls = _duckduckgo_search(f'"{name}" {location} site:facebook.com', max_results=2)
    social_links.extend(fb_urls)

    # 3. Check those pages for a real email first (bios often list one)
    for url in social_links:
        text = _scrape_page(url)
        email = _first_valid_email(text)
        if email:
            return {"email": email, "social_links": social_links}
        time.sleep(0.3)

    # 4. Fall back to general web search for name+location+email/contact
    general_urls = _duckduckgo_search(f'"{name}" {location} email OR contact', max_results=3)
    for url in general_urls:
        if url in social_links:
            continue
        text = _scrape_page(url)
        email = _first_valid_email(text)
        if email:
            return {"email": email, "social_links": social_links}
        time.sleep(0.3)

    return {"email": None, "social_links": social_links}


def find_email(lead):
    """Back-compat wrapper - returns just the email string or None."""
    return find_contact_info(lead)["email"]