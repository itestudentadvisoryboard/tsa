from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import csv
import os
import json
import re

app = Flask(__name__)
app.secret_key = 'tsa-region11-secret-key-2026'

ADMIN_PASSWORD = 'region11@dmin'
DATA_FILE = os.path.join(os.path.dirname(__file__), 'admin_data.json')


def load_data():
    """Load admin data from JSON file."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'semifinalists': {}, 'overrides': {}, 'announcements': []}


def save_data(data):
    """Save admin data to JSON file."""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def classify_cell(cell_text):
    """Classify a cell's content as setup, judging, semifinalists, or activity."""
    t = cell_text.lower().strip()
    if not t:
        return None, ''
    if 'setup' in t or 'turn-in' in t or 'sign up' in t or 'sign ups' in t or 'set up' in t:
        return 'setup', cell_text.strip()
    if 'semi-final' in t or 'semi final' in t or 'semifinal' in t:
        return 'semifinal', cell_text.strip()
    if 'judging' in t and 'project' not in t:
        return 'judging', cell_text.strip()
    return 'activity', cell_text.strip()


# Saturday CSV has no event type row, so we map manually
SATURDAY_EVENT_TYPES = {
    'Animatronics': ['HS'],
    'Architectural Design': ['HS'],
    'Audio Podcasting': ['HS'],
    'Biotechnology Design': ['HS'],
    'Board Game Design': ['MS'],
    'Chapter Team': ['MS', 'HS'],
    'Children\'s Stories': ['HS'],
    'Coding': ['HS'],
    'CAD Architecture': ['HS'],
    'CAD Engineering': ['HS'],
    'Data Science & Analytics': ['HS'],
    'Debating Technological Issues': ['HS'],
    'Digital Video Production': ['HS'],
    'Engineering Design': ['MS'],
    'Extemporaneous Speech': ['HS'],
    'Fashion Design': ['HS'],
    'Forensic Science': ['HS'],
    'Future Technology Teacher': ['HS'],
    'Geospatial Technology': ['HS'],
    'Manufacturing Prototype': ['HS'],
    'Music Production': ['HS'],
    'On Demand Video': ['HS'],
    'Photographic Technology': ['HS'],
    'Prepared Presentation': ['HS'],
    'Promotional Design': ['MS'],
    'Software Development': ['HS'],
    'STEM Mass Media': ['MS'],
    'Structural Design & Engineering': ['MS'],
    'System Control Technology': ['HS'],
    'Technology Bowl': ['MS', 'HS'],
    'Technological Problem Solving': ['MS'],
    'Transportation Modeling': ['MS'],
    'Video Game Design': ['HS'],
    'Virtual Reality (VR)': ['HS'],
    'Webmaster': ['HS'],
    'Candidate Forum': ['NQE'],
    'Lonestar Exam': ['UTE'],
}


def clean_event_name(name):
    """Shorten overly long event names (e.g. HP codes from UTE events)."""
    # HP code events: "HP30000 Mechanical Engineering - Free Hand Sketch of a Single..."
    hp_match = re.match(r'(HP\d+)\s+(.+)', name)
    if hp_match:
        code = hp_match.group(1)
        desc = hp_match.group(2)
        # Remove trailing instructions like ". Pen or Pencil Only."
        desc = re.sub(r'\. (Pen|Must|Use|No ).*$', '', desc)
        # Remove bracket content like [CADD]
        desc = re.sub(r'\s*\[.*?\]', '', desc)
        # Trim to reasonable length
        if len(desc) > 50:
            desc = desc[:47] + '...'
        return f"{code} {desc}"
    # Skip description-only cells (not real event names)
    skip_phrases = ['students must bring', 'voting delegates', 'there are', 'judge']
    if any(p in name.lower() for p in skip_phrases):
        return None
    # General long names: trim
    if len(name) > 60:
        return name[:57] + '...'
    return name


def parse_schedule_file(filename, event_name_row, room_row, event_type_row, data_start_row, max_cols=36, fallback_types=None):
    """Parse a CSV schedule with event types and phase time blocks."""
    csv_path = os.path.join(os.path.dirname(__file__), filename)
    if not os.path.exists(csv_path):
        return []

    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = list(csv.reader(f))

    rooms = reader[room_row] if room_row < len(reader) else []
    event_names = reader[event_name_row] if event_name_row < len(reader) else []
    event_types = reader[event_type_row] if event_type_row is not None and event_type_row < len(reader) else []
    events = []

    for col in range(1, min(len(event_names), max_cols)):
        raw_name = event_names[col].strip()
        if not raw_name:
            continue
        name = clean_event_name(raw_name)
        if not name:
            continue

        room = rooms[col].strip() if col < len(rooms) else ''

        # Get event type (MS / HS / NQE / UTE)
        raw_type = event_types[col].strip() if event_type_row is not None and col < len(event_types) else ''
        tags = []
        if raw_type:
            for part in re.split(r'[/,]', raw_type):
                p = part.strip().upper()
                if p in ('MS', 'HS', 'NQE', 'UTE'):
                    tags.append(p)
            # Special cases
            if 'LONE STAR' in raw_type.upper():
                tags = ['UTE']
            elif 'CANDIDATE' in raw_type.upper():
                tags = []
        elif fallback_types and name in fallback_types:
            tags = fallback_types[name]

        # Scan cells to find time blocks for each phase
        first_time = None
        last_time = None
        setup_start = None
        setup_end = None
        judging_start = None
        judging_end = None
        semi_start = None
        semi_end = None
        activity_start = None
        activity_end = None

        for row_idx in range(data_start_row, len(reader)):
            time_label = reader[row_idx][0].strip() if reader[row_idx][0] else ''
            cell = reader[row_idx][col].strip() if col < len(reader[row_idx]) else ''
            if not time_label or not cell:
                continue

            phase, _ = classify_cell(cell)
            if not phase:
                continue

            if first_time is None:
                first_time = time_label
            last_time = time_label

            if phase == 'setup':
                if setup_start is None:
                    setup_start = time_label
                setup_end = time_label
            elif phase == 'judging':
                if judging_start is None:
                    judging_start = time_label
                judging_end = time_label
            elif phase == 'semifinal':
                if semi_start is None:
                    semi_start = time_label
                semi_end = time_label
            elif phase == 'activity':
                if activity_start is None:
                    activity_start = time_label
                activity_end = time_label

        if first_time:
            events.append({
                'name': name,
                'room': room,
                'tags': tags,
                'start': first_time,
                'end': last_time,
                'setup_start': setup_start,
                'setup_end': setup_end,
                'judging_start': judging_start,
                'judging_end': judging_end,
                'semi_start': semi_start,
                'semi_end': semi_end,
                'activity_start': activity_start,
                'activity_end': activity_end,
            })

    return events


def apply_overrides(events, day):
    """Apply admin overrides to event list. Adds override fields for display."""
    data = load_data()
    overrides = data.get('overrides', {})

    for event in events:
        key = f"{day}::{event['name']}"
        if key in overrides:
            ov = overrides[key]
            event['delayed'] = True
            event['original_start'] = event['start']
            event['original_end'] = event['end']
            event['original_room'] = event['room']
            if ov.get('new_start'):
                event['start'] = ov['new_start']
            if ov.get('new_end'):
                event['end'] = ov['new_end']
            if ov.get('new_room'):
                event['room'] = ov['new_room']
        else:
            event['delayed'] = False

    return events


def get_all_schedules():
    """Parse both Friday and Saturday schedules with overrides applied."""
    friday = parse_schedule_file(
        'WORKING TSA Region 11 Conference Calendar 2026 - Friday, Feb 6.csv',
        event_name_row=5, room_row=3, event_type_row=4, data_start_row=9, max_cols=44
    )
    saturday = parse_schedule_file(
        'WORKING TSA Region 11 Conference Calendar 2026 - Saturday, Feb 7.csv',
        event_name_row=4, room_row=3, event_type_row=None, data_start_row=7, max_cols=36,
        fallback_types=SATURDAY_EVENT_TYPES
    )
    friday = apply_overrides(friday, 'friday')
    saturday = apply_overrides(saturday, 'saturday')
    return friday, saturday


# ── Public Routes ──────────────────────────────────────────

@app.route('/')
def index():
    data = load_data()
    announcements = data.get('announcements', [])
    return render_template('index.html', announcements=announcements)

@app.route('/schedule')
def schedule():
    friday, saturday = get_all_schedules()
    return render_template('schedule.html', friday=friday, saturday=saturday)

@app.route('/live')
def live_events():
    friday, saturday = get_all_schedules()
    data = load_data()
    announcements = data.get('announcements', [])
    return render_template('live_events.html', friday=friday, saturday=saturday, announcements=announcements)


@app.route('/api/live')
def api_live():
    """JSON API for live event data - polled by the live page."""
    friday, saturday = get_all_schedules()
    data = load_data()
    announcements = data.get('announcements', [])
    return jsonify({
        'friday': friday,
        'saturday': saturday,
        'announcements': announcements
    })

@app.route('/semifinalists')
def semifinalists():
    data = load_data()
    semis = data.get('semifinalists', {})
    return render_template('semifinalists.html', semifinalists=semis)

@app.route('/semifinalist-signup')
def semifinalist_signup():
    return render_template('semifinalist_signup.html')


# ── Admin Auth ─────────────────────────────────────────────

import hashlib

ADMIN_TOKEN = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()[:16]


def check_admin_token():
    """Check if the admin token is valid from query string or form data."""
    token = request.args.get('token') or request.form.get('token')
    return token == ADMIN_TOKEN


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == ADMIN_PASSWORD:
            return redirect(url_for('admin', token=ADMIN_TOKEN))
        else:
            error = 'Incorrect password. Please try again.'
    return render_template('login.html', error=error)


# ── Admin Routes ───────────────────────────────────────────

@app.route('/admin')
def admin():
    if not check_admin_token():
        return redirect(url_for('admin_login'))
    data = load_data()
    friday, saturday = get_all_schedules()
    all_events = []
    for e in friday:
        all_events.append({'day': 'friday', 'name': e['name'], 'room': e['room'],
                           'start': e['start'], 'end': e['end']})
    for e in saturday:
        all_events.append({'day': 'saturday', 'name': e['name'], 'room': e['room'],
                           'start': e['start'], 'end': e['end']})
    return render_template('admin.html', data=data, events=all_events, token=ADMIN_TOKEN)

@app.route('/admin/semifinalists', methods=['POST'])
def admin_semifinalists():
    if not check_admin_token():
        return redirect(url_for('admin_login'))
    data = load_data()
    event_name = request.form.get('event_name', '').strip()
    teams_text = request.form.get('teams', '').strip()

    if event_name and teams_text:
        teams = [t.strip() for t in teams_text.split('\n') if t.strip()]
        data['semifinalists'][event_name] = teams
        save_data(data)

    return redirect(url_for('admin', token=ADMIN_TOKEN))

@app.route('/admin/semifinalists/delete', methods=['POST'])
def admin_delete_semifinalists():
    if not check_admin_token():
        return redirect(url_for('admin_login'))
    data = load_data()
    event_name = request.form.get('event_name', '').strip()
    if event_name in data['semifinalists']:
        del data['semifinalists'][event_name]
        save_data(data)
    return redirect(url_for('admin', token=ADMIN_TOKEN))

@app.route('/admin/override', methods=['POST'])
def admin_override():
    if not check_admin_token():
        return redirect(url_for('admin_login'))
    data = load_data()
    day = request.form.get('day', '').strip()
    event_name = request.form.get('event_name', '').strip()
    new_start = request.form.get('new_start', '').strip()
    new_end = request.form.get('new_end', '').strip()
    new_room = request.form.get('new_room', '').strip()

    if day and event_name:
        key = f"{day}::{event_name}"
        data['overrides'][key] = {
            'new_start': new_start,
            'new_end': new_end,
            'new_room': new_room
        }
        save_data(data)

    return redirect(url_for('admin', token=ADMIN_TOKEN))

@app.route('/admin/override/delete', methods=['POST'])
def admin_delete_override():
    if not check_admin_token():
        return redirect(url_for('admin_login'))
    data = load_data()
    key = request.form.get('key', '').strip()
    if key in data['overrides']:
        del data['overrides'][key]
        save_data(data)
    return redirect(url_for('admin', token=ADMIN_TOKEN))


@app.route('/admin/announcement', methods=['POST'])
def admin_announcement():
    if not check_admin_token():
        return redirect(url_for('admin_login'))
    data = load_data()
    title = request.form.get('title', '').strip()
    message = request.form.get('message', '').strip()
    level = request.form.get('level', 'info').strip()

    if message:
        from datetime import datetime
        data.setdefault('announcements', []).insert(0, {
            'title': title,
            'message': message,
            'level': level,
            'time': datetime.now().strftime('%I:%M %p')
        })
        save_data(data)

    return redirect(url_for('admin', token=ADMIN_TOKEN))

@app.route('/admin/announcement/delete', methods=['POST'])
def admin_delete_announcement():
    if not check_admin_token():
        return redirect(url_for('admin_login'))
    data = load_data()
    idx = request.form.get('index', '')
    announcements = data.get('announcements', [])
    try:
        idx = int(idx)
        if 0 <= idx < len(announcements):
            announcements.pop(idx)
            data['announcements'] = announcements
            save_data(data)
    except (ValueError, IndexError):
        pass
    return redirect(url_for('admin', token=ADMIN_TOKEN))


if __name__ == '__main__':
    app.run(debug=True)
