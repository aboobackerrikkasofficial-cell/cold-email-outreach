# Cold Outreach Bot
 
Finds businesses with no website -> writes a unique personalized email for each -> sends it from
`hello.aboobackerrikkas@gmail.com` -> logs everything -> emails you a daily report at
`rikkas.aboo@gmail.com`. Runs automatically every day at 12pm via Windows Task Scheduler.
 
## 1. Install dependencies
 
```powershell
cd cold_outreach_bot
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
 
## 2. Get your API keys (one-time, ~15 minutes total)
 
### Google Places API key (finds the leads)
1. Go to https://console.cloud.google.com/ -> create a new project (or use an existing one).
2. APIs & Services -> Library -> search "Places API" -> Enable.
3. APIs & Services -> Credentials -> Create Credentials -> API key. Copy it.
4. Google requires billing enabled on the project, but Places API has a monthly free tier
   ($200 credit) - realistically this workload stays free or very close to it.
### Groq API key (writes the emails - you already use this for other projects)
1. https://console.groq.com/keys -> Create API Key -> copy it.
### Gmail OAuth credentials (sends the emails as your address)
1. Same Google Cloud project as above -> APIs & Services -> Library -> enable "Gmail API".
2. APIs & Services -> OAuth consent screen -> External -> fill basic app info (name: anything,
   e.g. "Outreach Bot") -> add your own email as a test user.
3. APIs & Services -> Credentials -> Create Credentials -> OAuth client ID -> Application type:
   **Desktop app** -> Create.
4. Download the JSON -> rename it to `credentials.json` -> place it in the `cold_outreach_bot`
   folder.
### Fill in `.env`
Copy `.env.example` to `.env` and paste in your `GOOGLE_PLACES_API_KEY` and `GROQ_API_KEY`.
 
## 3. First run (one-time browser login)
 
```powershell
python main.py
```
 
The first run will open a browser asking you to log into `hello.aboobackerrikkas@gmail.com` and
grant "send email" permission. After you approve once, it saves `token.json` and never asks
again — every future run (including the automated daily one) sends silently in the background.
 
Watch the terminal output. You should see leads being found and emails being sent. Check your
Gmail "Sent" folder to confirm, and check `rikkas.aboo@gmail.com` for the report email.
 
## 4. Schedule it for 12pm daily (Windows Task Scheduler)
 
1. Open **Task Scheduler** (search it in the Start menu).
2. Action -> **Create Task** (not "Basic Task" — you want full control).
3. **General tab**: Name it `Cold Outreach Bot`. Select "Run whether user is logged on or not."
4. **Triggers tab** -> New -> Daily -> set start time to **12:00:00 PM** -> OK.
5. **Actions tab** -> New -> Action: "Start a program":
   - Program/script: full path to your venv's python.exe, e.g.
     `C:\Users\<you>\cold_outreach_bot\venv\Scripts\python.exe`
   - Add arguments: `main.py`
   - Start in: full path to the `cold_outreach_bot` folder, e.g.
     `C:\Users\<you>\cold_outreach_bot`
6. **Conditions tab**: uncheck "Start the task only if the computer is on AC power" (so it still
   runs on battery/laptop).
7. Save. It'll ask for your Windows password to run in the background.
That's it — from tomorrow, it fires on its own at 12pm, no chat, no clicking, no manual send.
 
## 5. What to check periodically
 
- **`data/needs_manual_email.csv`** — leads found that had no discoverable email (common for
  businesses with zero web presence). These are real leads worth a manual WhatsApp/call instead
  of losing them.
- **`data/contacted_leads.csv`** — the full dedupe log. Never delete this or you'll re-email
  people.
- **`logs/`** — you can redirect terminal output here if you want a persistent run history
  (add `>> logs/run.log 2>&1` after `main.py` in the Task Scheduler action if you want this).
## 6. Tuning
 
- `config.py` -> `SEARCH_CATEGORIES` / `SEARCH_LOCATIONS`: add or remove business types and
  cities/countries freely — more combinations means more leads to draw from each day.
- `config.py` -> `DAILY_MIN_EMAILS` / `DAILY_MAX_EMAILS`: adjust volume. Start lower (e.g. 10-15)
  for the first couple of weeks — new Gmail sending patterns get flagged faster than established
  ones, and it's worth confirming reply quality before scaling up.
- `config.py` -> `HUNTER_API_KEY`: optional, but improves how many leads actually get an email
  found (free tier: 25 searches/month at hunter.io). Without it, leads with a proper domain
  still get scraped directly; only fully web-invisible businesses fall through to the manual list.
## Notes on deliverability
 
- Emails automatically include a one-line opt-out ("reply no thanks") — keep this, it's both
  good practice and reduces spam complaints.
- Google Places `website` field is the qualifying signal for "needs a website" — it's reliable,
  since Google pulls it from the business's own listing.
- If you notice replies dropping into spam more than usual, that's Gmail's sending reputation
  system reacting to volume/pattern — pause a few days and lower `DAILY_MAX_EMAILS`.
 