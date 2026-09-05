"""
Central configuration for the cold outreach bot.
Fill in your API keys in a .env file (see .env.example) — never hardcode them here.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ---------- Required API keys ----------
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")   # Google Cloud Console -> Places API
GROQ_API_KEY = os.getenv("GROQ_API_KEY")                     # console.groq.com
HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")              # optional, hunter.io - improves email discovery
SNOV_CLIENT_ID = os.getenv("SNOV_CLIENT_ID", "")               # optional, snov.io - second free source (50/month)
SNOV_CLIENT_SECRET = os.getenv("SNOV_CLIENT_SECRET", "")

# ---------- Gmail (OAuth2 - see README for one-time setup) ----------
GMAIL_CREDENTIALS_FILE = os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
GMAIL_TOKEN_FILE = os.getenv("GMAIL_TOKEN_FILE", "token.json")
SENDER_EMAIL = "hello.aboobackerrikkas@gmail.com"
REPORT_EMAIL = "rikkas.aboo@gmail.com"

# ---------- Your identity (used in message generation) ----------
YOUR_NAME = "Aboobacker Rikkas"
YOUR_ROLE = "AI Automation Developer"
YOUR_SERVICES = ["Website", "Landing Page", "WhatsApp AI Auto-Reply Agent"]
YOUR_PORTFOLIO_LINK = ""     # add your portfolio / LinkedIn URL
YOUR_CALENDLY_LINK = "https://calendly.com/hello-aboobackerrikkas/30min"

# ---------- Daily volume ----------
DAILY_MIN_EMAILS = 15
DAILY_MAX_EMAILS = 30
DAILY_LEAD_TARGET = 20        # total leads found per run (India + international combined)
INDIA_LEAD_PERCENTAGE = 20    # % of DAILY_LEAD_TARGET allocated to Indian leads
SEND_DELAY_SECONDS = (45, 180)   # random delay range between sends - avoids spam pattern detection

# ---------- Warmup Schedule ----------
WARMUP_START_DATE = "2026-09-05"  # Set to the date you actually start sending (YYYY-MM-DD)
WARMUP_SCHEDULE = [
    (0, 15),    # days 0-6: 15/day
    (7, 25),    # days 7-13: 25/day
    (14, 40),   # days 14-20: 40/day
    (21, 50),   # day 21 onward: 50/day
]

def get_current_daily_cap():
    """
    Calculates days elapsed since WARMUP_START_DATE and returns the correct cap.
    Returns (days_elapsed, cap). If before start date, returns (days_elapsed, 0).
    If WARMUP_START_DATE is missing/invalid, defaults to day 0.
    """
    from datetime import datetime
    
    if not WARMUP_START_DATE:
        return 0, WARMUP_SCHEDULE[0][1]

    try:
        start_date = datetime.strptime(WARMUP_START_DATE, "%Y-%m-%d").date()
    except ValueError:
        return 0, WARMUP_SCHEDULE[0][1]

    today = datetime.now().date()
    days_elapsed = (today - start_date).days

    if days_elapsed < 0:
        print(f"  [!] Warning: Warmup hasn't started yet. Starts on {WARMUP_START_DATE}.")
        return days_elapsed, 0

    current_cap = WARMUP_SCHEDULE[0][1]
    for day_threshold, cap in WARMUP_SCHEDULE:
        if days_elapsed >= day_threshold:
            current_cap = cap
        else:
            break
            
    return days_elapsed, current_cap

# ---------- Lead search targets (international) ----------
# Add/remove categories and locations freely. More combinations = more leads to draw from each day.
SEARCH_CATEGORIES = [
    "dental clinic", "real estate agency", "hair salon", "spa", "restaurant",
    "boutique clothing store", "gym", "law firm", "accounting firm",
    "interior design studio", "photography studio", "car repair shop",
    "eye care clinic", "physiotherapy clinic", "wedding planner",
]

SEARCH_LOCATIONS = [
    # United States
    "Austin, Texas, USA", "Denver, Colorado, USA", "Charlotte, North Carolina, USA",
    "Miami, Florida, USA", "Phoenix, Arizona, USA", "Nashville, Tennessee, USA",
    # United Kingdom
    "Manchester, UK", "Birmingham, UK", "Leeds, UK", "Bristol, UK",
    # UAE
    "Dubai, UAE", "Abu Dhabi, UAE",
    # Other English-speaking markets
    "Toronto, Canada", "Vancouver, Canada", "Sydney, Australia", "Melbourne, Australia",
]

# ---------- Lead search targets (India - manual outreach via WhatsApp/call) ----------
# Uses the same SEARCH_CATEGORIES as international. Only the locations differ.
INDIA_SEARCH_LOCATIONS = [
    # Metros
    "Mumbai, India", "Delhi, India", "Bangalore, India",
    "Hyderabad, India", "Chennai, India", "Kolkata, India",
    # Tier 1
    "Pune, India", "Ahmedabad, India", "Jaipur, India",
    "Surat, India", "Lucknow, India", "Chandigarh, India", "Indore, India",
    # Kerala
    "Kochi, India", "Kozhikode, India", "Thiruvananthapuram, India",
]

# ---------- Need classifier categories ----------
# Businesses in these categories get "Booking or landing page" if they have no real website
BOOKING_PAGE_CATEGORIES = [
    "salon", "spa", "clinic", "dental", "gym", "restaurant", "cafe",
    "boutique", "photography", "physiotherapy", "wedding", "bakery",
    "ayurvedic", "eye care",
]

# ---------- Files ----------
LEADS_LOG_CSV = "data/contacted_leads.csv"     # dedupe log - never email the same business twice
NEEDS_EMAIL_CSV = "data/needs_manual_email.csv"  # leads found but no email discovered - for manual follow-up
PENDING_REVIEW_CSV = "data/pending_review.csv"   # drafts awaiting manual review before sending
INDIA_LEADS_CSV = "data/india_leads.csv"         # India leads - manual WhatsApp/call outreach
DAILY_LOG_DIR = "logs"