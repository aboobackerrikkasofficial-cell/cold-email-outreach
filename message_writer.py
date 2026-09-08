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
    "website": "Offer to build them a clean, simple website or landing page with a booking system, plus a WhatsApp AI auto-reply agent so they never miss a customer inquiry after hours.",
    "automation": "Since they already have a website, offer to build them a WhatsApp AI Auto-Reply Agent that instantly answers customer questions and books appointments automatically 24/7."
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
        return "automation"
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
            "model": "groq/compound",
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


WHATSAPP_PROMPT = """You write cold outreach WhatsApp messages for {your_name}, an {your_role}.

Voice: Very friendly, casual, and human. Speak like you're texting a friend, not sending a corporate pitch. Use emojis naturally but sparingly. Short and punchy.

Rules:
1. Write ONE short WhatsApp opener (under 50 words).
2. Look at their business details. If they have a website, offer to build them a WhatsApp AI Auto-Reply Agent so they never miss a customer inquiry. If they don't have a website (or just a social link), offer to build a simple Website/Landing Page + Booking System.
3. Personalize it! Mention their specific business name or a genuine detail (like their rating or review count) so it's clearly not a generic blast.
4. End with a soft, casual question (e.g. "Would you be open to a quick chat about this?", "Does that sound useful?").
5. Sign off casually as {your_name_first}.
6. Output STRICT JSON only: {{"whatsapp_message": "..."}}
"""

def write_whatsapp_message(lead):
    """Returns a highly personalized, friendly whatsapp message string or empty string if generation failed."""
    if not config.GROQ_API_KEY:
        return ""
    
    system_prompt = WHATSAPP_PROMPT.format(
        your_name=config.YOUR_NAME,
        your_role=config.YOUR_ROLE,
        your_name_first=config.YOUR_NAME.split()[0] if config.YOUR_NAME else "Me",
    )
    
    user_prompt = f"""Business: {lead.get('name', '') or lead.get('business_name', '')}
Category: {lead.get('category', '')}
Location: {lead.get('location', '') or lead.get('address', '')}
Google rating: {lead.get('rating', 'N/A')} ({lead.get('review_count', 'N/A')} reviews)
Website: {lead.get('website', 'None')}
"""

    try:
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "groq/compound",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.85,
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return parsed.get("whatsapp_message", "")
    except Exception as e:
        print(f"  [!] WhatsApp generation failed: {e}")
        return ""