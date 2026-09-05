import json
import requests

import config

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT_TEMPLATE = """You write cold outreach emails for {your_name}, a {your_role}.

Voice: a real, warm person who actually looked at their business - curious and genuine, not
corporate, not a template, not stiff. Contractions, short sentences, a little personality.

Subject line rules:
- Genuine curiosity, 100% true and specific to this business - never a lie or scare tactic.
- Good patterns: "quick thing about [Business]", "found you on Google Maps - small thing",
  "does [Business] know this?". 3-7 words, casual capitalization.

Body rules - MUST include all of these (this is the fix - previous drafts were too thin):
1. A specific, true opening observation about their business (rating, category, location -
   something that shows you actually looked, not a mail-merge).
2. A brief, genuine self-introduction: who you are and what you do, in one natural sentence -
   not a resume dump, just enough that they know who's emailing them and why you'd know how to
   help (e.g. "I'm {your_name}, I build websites and simple automation tools for small
   businesses").
3. {offer_instruction}
4. A warm, low-pressure closing question - curious, not a hard CTA.
5. A real sign-off with your first name AND a one-line indication of what you do (e.g.
   "- {your_name_first}, web & automation for small businesses") so it doesn't feel
   like it trails off with nothing.
- Length: 90-150 words - enough room to actually say something, not a one-liner.
- Never guarantee results/sales/customers. Never ALL CAPS, no "Dear Sir/Madam", no fake urgency.
{calendly_instruction}
- Output STRICT JSON only, no markdown: {{"subject": "...", "body": "...", "whatsapp_version": "...", "followup": "..."}}
- whatsapp_version: under 60 words and casual, tailored to the same offer.
- followup: a short polite nudge for no response after 4-5 days. Keep it under 60 words.{followup_calendly_note}
"""

OFFER_INSTRUCTIONS = {
    "website": "One clear, concrete idea of what you'd actually do for them and why it'd help THIS specific business (a website build, a booking page, a menu people can find on Google, and optionally a WhatsApp auto-reply so they stop missing DMs after hours).",
    "ads": "One clear, concrete idea of what you'd actually do for them and why it'd help THIS specific business (Instagram/Meta ads to drive traffic to their existing website, getting more local visibility)."
}

# Same list as lead_finder.py — kept in sync so offer logic is consistent
_SOCIAL_ONLY_DOMAINS = (
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

def _is_social_url(url):
    """Returns True if the URL is a social/link-in-bio platform, not a real website."""
    if not url:
        return False
    return any(domain in url.lower() for domain in _SOCIAL_ONLY_DOMAINS)

def _decide_offer(lead):
    website = lead.get("website", "")
    if website and not _is_social_url(website):
        return "ads"
    return "website"


def _build_user_prompt(lead):
    return f"""Business: {lead['name']}
Category: {lead['category']}
Location: {lead.get('address') or lead.get('location')}
Google rating: {lead.get('rating', 'N/A')} ({lead.get('review_count', 'N/A')} reviews)
Website on file: {lead.get('website') or 'None found - no website listed on Google Maps'}
Business types: {lead.get('types', '')}

Write ONE complete, warm, human cold email for this business - subject + body, following ALL
5 body requirements above. Don't skip the self-intro or the concrete idea - those are the parts
that were missing before and made past drafts feel thin and impersonal."""


def write_email(lead, is_followup=False):
    """Returns {'subject': str, 'body': str, 'whatsapp_version': str, 'followup': str, 'offer_type': str} or None if generation failed."""
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set in .env")

    offer_type = _decide_offer(lead)
    offer_instruction = OFFER_INSTRUCTIONS[offer_type]

    # Build Calendly-related prompt fragments
    calendly_link = getattr(config, "YOUR_CALENDLY_LINK", "")
    if calendly_link and is_followup:
        calendly_instruction = (
            f"- Since this is a follow-up or conversation where a call is being proposed, "
            f"naturally include one line offering to hop on a quick call with this booking link: "
            f"{calendly_link} — don't say \"when are you free\" or propose specific times, "
            f"just drop the link casually."
        )
        followup_calendly_note = (
            f" In the followup text, naturally include the booking link {calendly_link} as a "
            f"low-pressure way to continue the conversation."
        )
    elif calendly_link:
        calendly_instruction = ""
        followup_calendly_note = (
            f" In the followup text, naturally include the booking link {calendly_link} as a "
            f"low-pressure way to continue the conversation."
        )
    else:
        calendly_instruction = ""
        followup_calendly_note = ""

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        your_name=config.YOUR_NAME,
        your_role=config.YOUR_ROLE,
        your_name_first=config.YOUR_NAME.split()[0] if config.YOUR_NAME else "Me",
        offer_instruction=offer_instruction,
        calendly_instruction=calendly_instruction,
        followup_calendly_note=followup_calendly_note,
    )

    resp = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {config.GROQ_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _build_user_prompt(lead)},
            ],
            "temperature": 0.85,
            "response_format": {"type": "json_object"},
        },
        timeout=30,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
        if "subject" in parsed and "body" in parsed:
            parsed["offer_type"] = offer_type
            return parsed
    except json.JSONDecodeError:
        pass
    return None