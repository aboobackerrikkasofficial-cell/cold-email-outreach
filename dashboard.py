import os
import csv
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify

import config
import email_sender

app = Flask(__name__)

PENDING_CSV = config.PENDING_REVIEW_CSV
CONTACTED_CSV = config.LEADS_LOG_CSV
INDIA_CSV = config.INDIA_LEADS_CSV

def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def write_csv(path, rows, fieldnames):
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def append_csv(path, row, fieldnames):
    file_exists = os.path.exists(path)
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None

    existing_fieldnames = []
    if file_exists:
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            try:
                existing_fieldnames = next(reader)
            except StopIteration:
                pass

    all_fields = existing_fieldnames if existing_fieldnames else list(fieldnames)
    for fn in fieldnames:
        if fn not in all_fields:
            all_fields.append(fn)

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_fields)
        if not file_exists or not existing_fieldnames:
            writer.writeheader()
        writer.writerow(row)

TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Cold Outreach Dashboard</title>
    <style>
        body { font-family: sans-serif; max-width: 1200px; margin: auto; padding: 20px; background: #f9f9f9; }
        .top-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
        .calendly-link { background: #6c5ce7; color: white; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-size: 13px; cursor: pointer; }
        .calendly-link:hover { background: #5a4bd1; }
        .stats { display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap; }
        .stat-box { background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); flex: 1; text-align: center; min-width: 100px; }
        .stat-box h3 { margin: 0 0 10px 0; font-size: 14px; color: #666; }
        .stat-box p { margin: 0; font-size: 24px; font-weight: bold; color: #333; }
        table { width: 100%; border-collapse: collapse; background: white; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 30px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #f0f0f0; }
        .details { display: none; background: #fafafa; padding: 15px; border-left: 3px solid #007bff; }
        .open { display: block; }
        .btn { padding: 6px 12px; cursor: pointer; border: none; border-radius: 4px; background: #007bff; color: white; font-size: 13px; }
        .btn:disabled { background: #ccc; cursor: default; }
        .btn-success { background: #28a745; }
        .btn-whatsapp { background: #25D366; color: white; padding: 6px 14px; border-radius: 4px; text-decoration: none; font-size: 13px; }
        .btn-whatsapp:hover { background: #1da851; }
        .badge-followup { background: #fd79a8; color: white; padding: 2px 8px; border-radius: 10px; font-size: 11px; }
        .badge-need { padding: 3px 10px; border-radius: 10px; font-size: 11px; font-weight: bold; display: inline-block; }
        .badge-website { background: #0984e3; color: white; }
        .badge-booking { background: #e17055; color: white; }
        .badge-ads { background: #00b894; color: white; }
        .india-section { background: #fff3e0; border: 2px solid #ff9800; border-radius: 10px; padding: 20px; margin-top: 30px; }
        .india-section h2 { color: #e65100; margin-top: 0; }
        .india-section table { box-shadow: none; }
        .india-section th { background: #ffe0b2; }
        .india-stats { display: flex; gap: 15px; margin-bottom: 15px; flex-wrap: wrap; }
        .india-stat { background: white; border: 1px solid #ffcc80; padding: 10px 15px; border-radius: 6px; text-align: center; }
        .india-stat h4 { margin: 0 0 5px 0; font-size: 12px; color: #888; }
        .india-stat p { margin: 0; font-size: 20px; font-weight: bold; color: #e65100; }
    </style>
</head>
<body>
    <div class="top-bar">
        <h1>Outreach Dashboard</h1>
        <a class="calendly-link" href="{{ calendly_link }}" target="_blank" title="Click to open, or copy link">📅 Calendly: {{ calendly_link }}</a>
    </div>

    <div class="stats">
        <div class="stat-box"><h3>Total Drafts</h3><p>{{ stats.drafts }}</p></div>
        <div class="stat-box"><h3>Sent</h3><p>{{ stats.sent }}</p></div>
        <div class="stat-box"><h3>Replied</h3><p>{{ stats.replied }}</p></div>
        <div class="stat-box"><h3>Booked Call</h3><p>{{ stats.booked }}</p></div>
        <div class="stat-box"><h3>In Conversation</h3><p>{{ stats.in_conv }}</p></div>
        <div class="stat-box"><h3>No Response</h3><p>{{ stats.no_resp }}</p></div>
    </div>

    <div style="margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center;">
        <h2>International Leads</h2>
        <button class="btn btn-success" onclick="sendAllReviewed()">Send All Reviewed</button>
    </div>

    <table>
        <thead>
            <tr>
                <th>Business Name</th>
                <th>Offer Type</th>
                <th>Subject</th>
                <th>Status</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {% for row in leads %}
            <tr>
                <td>
                    <b>{{ row.business_name or row.name }}</b>
                    {% if row.is_followup == 'True' %} <span class="badge-followup">follow-up</span>{% endif %}
                    <br>
                    <small>{{ row.industry_or_category or row.category }} | {{ row.location }}</small>
                </td>
                <td>{{ row.offer_type }}</td>
                <td>{{ row.subject }}</td>
                <td>
                    {% if row.type == 'pending' %}
                        <span>Draft</span>
                    {% else %}
                        {% set rs = row.reply_status or row.status or 'no_response' %}
                        <select onchange="updateStatus('{{ row.place_id }}', this.value)">
                            <option value="no_response" {% if rs == 'no_response' %}selected{% endif %}>No response</option>
                            <option value="replied" {% if rs == 'replied' %}selected{% endif %}>Replied</option>
                            <option value="booked a call" {% if rs == 'booked a call' %}selected{% endif %}>Booked a call</option>
                            <option value="in conversation" {% if rs == 'in conversation' %}selected{% endif %}>In conversation</option>
                        </select>
                    {% endif %}
                </td>
                <td>
                    <button class="btn" onclick="toggleDetails('{{ row.id or row.place_id }}')">View</button>
                    {% if row.type == 'pending' %}
                        <input type="checkbox" id="check_{{ row.id }}" {% if row.reviewed == 'True' %}checked{% endif %} onchange="toggleReviewed('{{ row.id }}', this.checked)">
                        <label for="check_{{ row.id }}">Reviewed</label>
                        <button class="btn btn-success" id="send_{{ row.id }}" {% if row.reviewed != 'True' %}disabled{% endif %} onclick="sendDraft('{{ row.id }}')">Send</button>
                    {% endif %}
                </td>
            </tr>
            <tr id="details_{{ row.id or row.place_id }}" class="details">
                <td colspan="5">
                    <strong>Email Body:</strong>
                    <pre style="white-space: pre-wrap; font-family: sans-serif;">{{ row.email_body or row.body or "Not recorded" }}</pre>
                    {% if row.whatsapp_version %}
                    <strong>WhatsApp Version:</strong>
                    <p>{{ row.whatsapp_version }}</p>
                    {% endif %}
                    {% if row.followup %}
                    <strong>Followup:</strong>
                    <p>{{ row.followup }}</p>
                    {% endif %}
                    {% if row.sent_date %}
                    <small style="color: #888;">Sent: {{ row.sent_date }}</small>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <!-- ======================== INDIA LEADS SECTION ======================== -->
    <div class="india-section">
        <h2>🇮🇳 India Leads — Contact Directly</h2>
        <div class="india-stats">
            <div class="india-stat"><h4>Total</h4><p>{{ india_stats.total }}</p></div>
            <div class="india-stat"><h4>Not Contacted</h4><p>{{ india_stats.not_contacted }}</p></div>
            <div class="india-stat"><h4>Contacted</h4><p>{{ india_stats.contacted }}</p></div>
        </div>
        {% if india_leads %}
        <table>
            <thead>
                <tr>
                    <th>Business</th>
                    <th>Suggested Need</th>
                    <th>Phone</th>
                    <th>WhatsApp</th>
                    <th>Rating</th>
                    <th>Social</th>
                    <th>Found</th>
                    <th>Contacted</th>
                </tr>
            </thead>
            <tbody>
                {% for il in india_leads %}
                <tr>
                    <td>
                        <b>{{ il.business_name }}</b><br>
                        <small>{{ il.category }} | {{ il.location }}</small>
                    </td>
                    <td>
                        {% if il.suggested_need == 'Website' %}
                            <span class="badge-need badge-website">Website</span>
                        {% elif il.suggested_need == 'Booking or landing page' %}
                            <span class="badge-need badge-booking">Booking / LP</span>
                        {% else %}
                            <span class="badge-need badge-ads">Ads</span>
                        {% endif %}
                    </td>
                    <td>{% if il.phone %}<a href="tel:{{ il.phone }}">{{ il.phone }}</a>{% else %}-{% endif %}</td>
                    <td>{% if il.whatsapp_link %}<a class="btn-whatsapp" href="{{ il.whatsapp_link }}" target="_blank">💬 WhatsApp</a>{% else %}-{% endif %}</td>
                    <td>{{ il.rating or '-' }} {% if il.review_count %}({{ il.review_count }}){% endif %}</td>
                    <td>{% if il.social_links %}<a href="{{ il.social_links }}" target="_blank">🔗</a>{% else %}-{% endif %}</td>
                    <td><small>{{ il.date_found or '-' }}</small></td>
                    <td>
                        <input type="checkbox" {% if il.contacted == 'True' %}checked{% endif %}
                            onchange="markIndiaContacted('{{ il.place_id }}', this.checked)">
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p style="color: #888;">No India leads yet. Run <code>python main.py</code> to find some.</p>
        {% endif %}
    </div>

    <script>
        function toggleDetails(id) {
            document.getElementById('details_' + id).classList.toggle('open');
        }

        async function toggleReviewed(id, isChecked) {
            await fetch('/api/update_draft', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: id, reviewed: isChecked})
            });
            document.getElementById('send_' + id).disabled = !isChecked;
        }

        async function sendDraft(id) {
            const res = await fetch('/api/send_draft', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: id})
            });
            if(res.ok) {
                location.reload();
            } else {
                alert('Failed to send');
            }
        }

        async function sendAllReviewed() {
            const res = await fetch('/api/send_all', { method: 'POST' });
            if(res.ok) {
                location.reload();
            } else {
                alert('Failed to send all');
            }
        }

        async function updateStatus(placeId, status) {
            await fetch('/api/update_status', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({place_id: placeId, reply_status: status})
            });
            location.reload();
        }

        async function markIndiaContacted(placeId, isContacted) {
            await fetch('/api/india_contacted', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({place_id: placeId, contacted: isContacted})
            });
        }
    </script>
</body>
</html>
"""

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

@app.route("/")
def index():
    pending = read_csv(PENDING_CSV)
    for p in pending:
        p['type'] = 'pending'

    contacted = read_csv(CONTACTED_CSV)
    for c in contacted:
        c['type'] = 'contacted'
        if 'reply_status' not in c or not c['reply_status']:
            c['reply_status'] = 'no_response'

    leads = pending + contacted

    stats = {
        'drafts': len(pending),
        'sent': len(contacted),
        'replied': sum(1 for c in contacted if c.get('reply_status') == 'replied'),
        'booked': sum(1 for c in contacted if c.get('reply_status') == 'booked a call'),
        'in_conv': sum(1 for c in contacted if c.get('reply_status') == 'in conversation'),
        'no_resp': sum(1 for c in contacted if c.get('reply_status', 'no_response') == 'no_response'),
    }

    # India leads
    india_leads = read_csv(INDIA_CSV)
    india_stats = {
        'total': len(india_leads),
        'contacted': sum(1 for il in india_leads if il.get('contacted') == 'True'),
        'not_contacted': sum(1 for il in india_leads if il.get('contacted', 'False') != 'True'),
    }

    calendly_link = getattr(config, "YOUR_CALENDLY_LINK", "")
    return render_template_string(
        TEMPLATE, leads=leads, stats=stats,
        india_leads=india_leads, india_stats=india_stats,
        calendly_link=calendly_link,
    )

@app.route("/api/update_draft", methods=["POST"])
def update_draft():
    data = request.json
    pending = read_csv(PENDING_CSV)
    if not pending:
        return jsonify({"status": "ok"})
    fieldnames = list(pending[0].keys())

    for row in pending:
        if row["id"] == data["id"]:
            row["reviewed"] = str(data["reviewed"])
            break

    write_csv(PENDING_CSV, pending, fieldnames)
    return jsonify({"status": "ok"})

def _send_and_move(row):
    """Send the email via Gmail and move the row from pending to contacted."""
    msg_id = email_sender.send_email(row["email"], row["subject"], row["email_body"])
    now = datetime.now()

    contacted_record = {
        "place_id": row["id"],
        "name": row["business_name"],
        "email": row["email"],
        "subject": row["subject"],
        "category": row["industry_or_category"],
        "location": row["location"],
        "sent_at": now.isoformat(),
        "gmail_message_id": msg_id,
        "status": "sent",
        "offer_type": row.get("offer_type", ""),
        "email_body": row["email_body"],
        "whatsapp_version": row.get("whatsapp_version", ""),
        "followup": row.get("followup", ""),
        "sent_date": now.strftime("%Y-%m-%d"),
        "followup_sent": "False",
        "reply_status": "no_response",
    }

    append_csv(CONTACTED_CSV, contacted_record, fieldnames=CONTACTED_FIELDNAMES)
    return True

@app.route("/api/send_draft", methods=["POST"])
def send_draft():
    data = request.json
    pending = read_csv(PENDING_CSV)

    row_to_send = None
    remaining = []
    for row in pending:
        if row["id"] == data["id"]:
            row_to_send = row
        else:
            remaining.append(row)

    if row_to_send:
        _send_and_move(row_to_send)
        if remaining:
            write_csv(PENDING_CSV, remaining, list(remaining[0].keys()))
        else:
            if os.path.exists(PENDING_CSV):
                os.remove(PENDING_CSV)

    return jsonify({"status": "ok"})

@app.route("/api/send_all", methods=["POST"])
def send_all():
    pending = read_csv(PENDING_CSV)
    remaining = []

    for row in pending:
        if row.get("reviewed") == "True":
            _send_and_move(row)
        else:
            remaining.append(row)

    if remaining:
        write_csv(PENDING_CSV, remaining, list(remaining[0].keys()))
    else:
        if os.path.exists(PENDING_CSV):
            os.remove(PENDING_CSV)

    return jsonify({"status": "ok"})

@app.route("/api/update_status", methods=["POST"])
def update_status():
    data = request.json
    contacted = read_csv(CONTACTED_CSV)
    if not contacted:
        return jsonify({"status": "ok"})

    # Build fieldnames ensuring all expected columns exist
    fieldnames = list(contacted[0].keys())
    for fn in CONTACTED_FIELDNAMES:
        if fn not in fieldnames:
            fieldnames.append(fn)

    for row in contacted:
        if row.get("place_id") == data["place_id"]:
            row["reply_status"] = data["reply_status"]
            break

    write_csv(CONTACTED_CSV, contacted, fieldnames)
    return jsonify({"status": "ok"})

@app.route("/api/india_contacted", methods=["POST"])
def india_contacted():
    data = request.json
    india = read_csv(INDIA_CSV)
    if not india:
        return jsonify({"status": "ok"})

    fieldnames = list(india[0].keys())
    for fn in INDIA_FIELDNAMES:
        if fn not in fieldnames:
            fieldnames.append(fn)

    for row in india:
        if row.get("place_id") == data["place_id"]:
            row["contacted"] = str(data["contacted"])
            break

    write_csv(INDIA_CSV, india, fieldnames)
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
