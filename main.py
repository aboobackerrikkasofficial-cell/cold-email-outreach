"""
Daily cold outreach run. Triggered by Windows Task Scheduler at 12:00pm (see README.md).

Pipeline:
  1. Queue follow-ups for leads that haven't replied after 4+ days.
  2. Check the daily draft cap before generating anything new.
  3. Find fresh leads (Google Places, deduped against contacted + pending + india by place_id).
     - 80% international -> Hunter/Snov -> Groq -> pending_review.csv -> dashboard -> Gmail
     - 20% India -> saved directly to india_leads.csv for manual WhatsApp/call outreach
  4. For each international lead: find an email; if none found, log for manual follow-up and skip.
  5. Write a unique personalized email via Groq.
  6. Save it to data/pending_review.csv for manual review (NOT auto-sent).
  7. Send a summary report to rikkas.aboo@gmail.com.
"""
import csv
import math
import os
import random
import time
from datetime import datetime, timedelta

import config
import lead_finder
import email_finder
import message_writer
import email_sender


PENDING_CSV = config.PENDING_REVIEW_CSV
CONTACTED_CSV = config.LEADS_LOG_CSV
INDIA_CSV = config.INDIA_LEADS_CSV

PENDING_FIELDNAMES = [
    "id", "business_name", "email", "industry_or_category", "location",
    "offer_type", "subject", "email_body", "whatsapp_version", "followup",
    "reviewed", "status", "created_date", "is_followup",
]

CONTACTED_FIELDNAMES = [
    "place_id", "name", "email", "subject", "category", "location",
    "sent_at", "gmail_message_id", "status", "offer_type", "email_body",
    "whatsapp_version", "followup", "sent_date", "followup_sent", "reply_status",
]

INDIA_FIELDNAMES = [
    "place_id", "business_name", "category", "location", "suggested_need",
    "phone", "whatsapp_link", "email", "social_links", "rating",
    "review_count", "contacted", "date_found",
]


def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_csv(path, rows, fieldnames):
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _append_csv(path, row, fieldnames):
    file_exists = os.path.exists(path)
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


# ---------------------------------------------------------------------------
# Dedupe helpers
# ---------------------------------------------------------------------------

def _load_all_known_place_ids():
    """Returns a set of place_ids from contacted_leads.csv, pending_review.csv, and india_leads.csv."""
    ids = set()

    for row in _read_csv(CONTACTED_CSV):
        pid = row.get("place_id", "")
        if pid:
            ids.add(pid)

    for row in _read_csv(PENDING_CSV):
        pid = row.get("id", "")
        if pid:
            ids.add(pid)

    for row in _read_csv(INDIA_CSV):
        pid = row.get("place_id", "")
        if pid:
            ids.add(pid)

    return ids


# ---------------------------------------------------------------------------
# Daily cap helpers
# ---------------------------------------------------------------------------

def _count_drafts_today():
    """Count how many rows in pending_review.csv were created today."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    count = 0
    for row in _read_csv(PENDING_CSV):
        created = row.get("created_date", "")
        if created.startswith(today_str):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Follow-up automation
# ---------------------------------------------------------------------------

def _queue_followups():
    """
    For every contacted lead where:
      - reply_status is "no_response" (or empty, which defaults to no_response)
      - followup_sent is not True
      - sent_date is at least 4 days ago
    Queue a follow-up into pending_review.csv using the stored followup text.
    Mark followup_sent=True on the original row immediately.
    """
    contacted = _read_csv(CONTACTED_CSV)
    if not contacted:
        return 0

    cutoff = datetime.now() - timedelta(days=4)
    queued = 0
    modified = False

    # Collect existing pending place_ids so we don't double-queue
    pending_ids = {row.get("id", "") for row in _read_csv(PENDING_CSV)}

    for row in contacted:
        reply_status = row.get("reply_status", "no_response") or "no_response"
        followup_sent = row.get("followup_sent", "False")
        followup_text = row.get("followup", "")

        if reply_status != "no_response":
            continue
        if followup_sent == "True":
            continue
        if not followup_text:
            continue

        # Check sent_date
        sent_date_str = row.get("sent_date", "") or row.get("sent_at", "")
        if not sent_date_str:
            continue
        try:
            sent_date = datetime.fromisoformat(sent_date_str.split("T")[0])
        except (ValueError, IndexError):
            continue
        if sent_date > cutoff:
            continue

        place_id = row.get("place_id", "")
        if place_id in pending_ids:
            continue  # already has a pending draft

        # Queue followup into pending_review.csv
        pending_row = {
            "id": place_id,
            "business_name": row.get("name", ""),
            "email": row.get("email", ""),
            "industry_or_category": row.get("category", ""),
            "location": row.get("location", ""),
            "offer_type": row.get("offer_type", ""),
            "subject": f"Re: {row.get('subject', '')}",
            "email_body": followup_text,
            "whatsapp_version": "",
            "followup": "",
            "reviewed": "False",
            "status": "draft",
            "created_date": datetime.now().strftime("%Y-%m-%d"),
            "is_followup": "True",
        }
        _append_csv(PENDING_CSV, pending_row, fieldnames=PENDING_FIELDNAMES)
        pending_ids.add(place_id)

        # Mark followup_sent on the original row
        row["followup_sent"] = "True"
        modified = True
        queued += 1

    if modified:
        # Ensure all fieldnames are present
        fieldnames = list(contacted[0].keys())
        for fn in CONTACTED_FIELDNAMES:
            if fn not in fieldnames:
                fieldnames.append(fn)
        _write_csv(CONTACTED_CSV, contacted, fieldnames)

    return queued


# ---------------------------------------------------------------------------
# India lead processing
# ---------------------------------------------------------------------------

def _process_india_leads(india_leads, today_str):
    """Save India leads directly to india_leads.csv. No Hunter/Snov/Groq/Gmail."""
    saved = 0
    for lead in india_leads:
        record = {
            "place_id": lead["place_id"],
            "business_name": lead["name"],
            "category": lead["category"],
            "location": lead.get("location", ""),
            "suggested_need": lead_finder._suggest_need(lead),
            "phone": lead.get("phone", ""),
            "whatsapp_link": lead_finder._phone_to_whatsapp_link(lead.get("phone", "")),
            "email": "",
            "social_links": lead.get("social_links", ""),
            "rating": lead.get("rating", ""),
            "review_count": lead.get("review_count", ""),
            "contacted": "False",
            "date_found": today_str,
        }
        _append_csv(INDIA_CSV, record, fieldnames=INDIA_FIELDNAMES)
        saved += 1
        print(f"  [🇮🇳] {lead['name']} ({lead['category']}, {lead['location']}) -> india_leads.csv")
    return saved


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run():
    started_at = datetime.now()
    today_str = started_at.strftime("%Y-%m-%d")

    # Step 0: Queue follow-ups for leads that haven't replied after 4+ days
    followups_queued = _queue_followups()
    if followups_queued:
        print(f"[followup] Queued {followups_queued} follow-up(s) for review.")

    # Step 1: Check daily cap (applies to international email drafts only)
    days_elapsed, current_cap = config.get_current_daily_cap()
    
    if days_elapsed < 0:
        print(f"[{started_at}] Warmup hasn't started. Next steps delayed.")
        # We can still find India leads, so we won't strictly exit, just set cap to 0
        
    print(f"[{started_at}] Day {max(0, days_elapsed)} of warmup - cap is {current_cap}/day")
    
    drafts_today = _count_drafts_today()
    remaining_cap = current_cap - drafts_today

    # Step 2: Compute India vs international targets
    total_target = config.DAILY_LEAD_TARGET
    india_target = max(1, math.ceil(total_target * config.INDIA_LEAD_PERCENTAGE / 100))
    intl_target = total_target - india_target

    # Cap international target to remaining email draft cap
    if remaining_cap <= 0:
        print(f"[cap] Daily email cap reached ({current_cap} drafts already exist for {today_str}). Skipping international leads.")
        intl_target = 0
    else:
        intl_target = min(intl_target, remaining_cap)

    print(f"[{started_at}] Targeting {india_target} India + {intl_target} international leads (cap: {current_cap}, drafts today: {drafts_today}).")


    # Step 3a: Find and save India leads
    india_leads = lead_finder.find_india_leads(target_count=india_target * 2)
    # Extra dedupe against pending/contacted (lead_finder already dedupes internally)
    known_ids = _load_all_known_place_ids()
    india_leads = [l for l in india_leads if l["place_id"] not in known_ids][:india_target]
    india_saved = _process_india_leads(india_leads, today_str)

    # Step 3b: Find international leads
    if intl_target > 0:
        leads = lead_finder.find_leads(target_count=intl_target * 2)
        print(f"Found {len(leads)} candidate international leads.")

        # Extra dedupe against pending_review.csv
        pending_ids = {row.get("id", "") for row in _read_csv(PENDING_CSV)}
        leads = [l for l in leads if l["place_id"] not in pending_ids]
    else:
        leads = []

    # Step 4: Process international leads through Hunter/Snov -> Groq -> pending_review.csv
    sent_log = []
    skipped_no_email = []

    for lead in leads:
        if len(sent_log) >= intl_target:
            break

        contact = email_finder.find_contact_info(lead)
        email_address = contact["email"]
        if not email_address:
            lead_with_social = dict(lead)
            lead_with_social["social_links"] = " | ".join(contact["social_links"]) or "none found"
            skipped_no_email.append(lead_with_social)
            _append_csv(
                config.NEEDS_EMAIL_CSV, lead_with_social,
                fieldnames=list(lead_with_social.keys()),
            )
            continue

        try:
            message = message_writer.write_email(lead)
        except Exception as e:
            print(f"  [!] message generation failed for {lead['name']}: {e}")
            continue
        if not message:
            print(f"  [!] no message generated for {lead['name']}, skipping.")
            continue

        record = {
            "id": lead["place_id"],
            "business_name": lead["name"],
            "email": email_address,
            "industry_or_category": lead["category"],
            "location": lead.get("location", ""),
            "offer_type": message.get("offer_type", ""),
            "subject": message["subject"],
            "email_body": message["body"],
            "whatsapp_version": message.get("whatsapp_version", ""),
            "followup": message.get("followup", ""),
            "reviewed": "False",
            "status": "draft",
            "created_date": today_str,
            "is_followup": "False",
        }

        _append_csv(PENDING_CSV, record, fieldnames=PENDING_FIELDNAMES)
        sent_log.append(record)
        print(f"  [x] drafted for {lead['name']} <{email_address}> -> pending review")

        time.sleep(random.uniform(*config.SEND_DELAY_SECONDS))

    _send_report(sent_log, skipped_no_email, followups_queued, india_saved, started_at)
    print(f"Done. Drafted {len(sent_log)} intl emails, {india_saved} India leads saved, "
          f"{followups_queued} follow-ups queued, {len(skipped_no_email)} leads need manual email lookup.")


def _send_report(sent_log, skipped_no_email, followups_queued, india_saved, started_at):
    lines = [
        f"Cold outreach report - {started_at.strftime('%Y-%m-%d')}",
        f"International drafts created: {len(sent_log)}",
        f"India leads saved (manual outreach): {india_saved}",
        f"Follow-ups queued: {followups_queued}",
        f"Leads found but skipped (no email discovered): {len(skipped_no_email)}",
        "",
        "--- Drafted today (international) ---",
    ]
    for r in sent_log:
        lines.append(f"- {r['business_name']} ({r['industry_or_category']}, {r['location']}) -> {r['email']} | \"{r['subject']}\"")

    if skipped_no_email:
        lines.append("")
        lines.append("--- Needs manual contact (saved to needs_manual_email.csv) ---")
        for lead in skipped_no_email[:15]:
            social = lead.get("social_links", "none found")
            lines.append(f"- {lead['name']} | {lead.get('phone', 'no phone')} | {lead.get('address', '')} | social: {social}")

    body = "\n".join(lines)
    try:
        email_sender.send_email(
            config.REPORT_EMAIL,
            f"Outreach report: {len(sent_log)} drafted, {india_saved} India - {started_at.strftime('%d %b')}",
            body,
            from_address=config.SENDER_EMAIL,
        )
    except FileNotFoundError:
        print(f"[!] failed to send daily report: {config.GMAIL_CREDENTIALS_FILE} not found in this folder. "
              f"Download it from Google Cloud Console (README step 2, Gmail part) and place it here.")
    except Exception as e:
        print(f"[!] failed to send daily report: {e}")


if __name__ == "__main__":
    run()