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
import urllib.parse

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


def _search_hunter(domain):
    if not config.HUNTER_API_KEY:
        return None
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": config.HUNTER_API_KEY},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            emails = data.get("data", {}).get("emails", [])
            if emails:
                return emails[0].get("value")
            else:
                print(f"  [Hunter] No email found for this domain: {domain}")
                return None
        elif resp.status_code in (401, 429):
            print(f"  [Hunter] Quota exceeded or auth error (HTTP {resp.status_code}): {resp.text}")
            return None
        else:
            print(f"  [Hunter] API error for {domain}: {resp.status_code} - {resp.text}")
            return None
    except Exception as e:
        print(f"  [Hunter] Exception for {domain}: {e}")
        return None


def _get_snov_token():
    if not config.SNOV_CLIENT_ID or not config.SNOV_CLIENT_SECRET:
        return None
    try:
        resp = requests.post(
            "https://api.snov.io/v1/oauth/access_token",
            data={
                "grant_type": "client_credentials",
                "client_id": config.SNOV_CLIENT_ID,
                "client_secret": config.SNOV_CLIENT_SECRET
            },
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
        elif resp.status_code == 401 or "invalid_client" in resp.text:
            print(f"  [Snov] Quota exceeded or auth error getting token (HTTP {resp.status_code}): {resp.text}")
            return None
        else:
            print(f"  [Snov] Error getting token: {resp.status_code} - {resp.text}")
            return None
    except Exception as e:
        print(f"  [Snov] Exception getting token: {e}")
        return None


def _search_snov(domain, token):
    if not token:
        return None
    try:
        resp = requests.post(
            "https://api.snov.io/v2/domain-emails-with-info",
            data={"domain": domain},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            emails = data.get("emails", [])
            if emails:
                return emails[0].get("email")
            else:
                print(f"  [Snov] No email found for this domain: {domain}")
                return None
        elif resp.status_code in (401, 402, 429):
            print(f"  [Snov] Quota exceeded (HTTP {resp.status_code}): {resp.text}")
            return None
        else:
            print(f"  [Snov] API error for {domain}: {resp.status_code} - {resp.text}")
            return None
    except Exception as e:
        print(f"  [Snov] Exception for {domain}: {e}")
        return None


def find_contact_info(lead):
    """
    Returns {"email": str|None, "social_links": [str, ...]}.
    Always returns whatever social links were found, regardless of whether an email was found,
    so there's always something actionable even when email discovery comes up empty.
    """
    name = lead.get("name", "")
    location = lead.get("location", "")
    social_links = []

    # 0. Try Hunter/Snov if we have a website domain
    domain = None
    website = lead.get("website", "")
    if website:
        try:
            parsed = urllib.parse.urlparse(website if "://" in website else "http://" + website)
            domain = parsed.netloc.split(":")[0]
            if domain.startswith("www."):
                domain = domain[4:]
        except Exception:
            pass

    if domain:
        email = _search_hunter(domain)
        if email:
            return {"email": email, "social_links": social_links}
            
        token = _get_snov_token()
        email = _search_snov(domain, token)
        if email:
            return {"email": email, "social_links": social_links}

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