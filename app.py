"""
TSA Region 11 Conference at Ranchview
Flask application for conference schedule and live event tracking.
"""

from flask import Flask, render_template, jsonify, request
from datetime import datetime, timedelta
import requests
from icalendar import Calendar
from dateutil import parser as date_parser
from dateutil import tz
import json
import os

app = Flask(__name__)

# =============================================================================
# SUPABASE CONFIGURATION - Persistent cloud storage!
# =============================================================================
# 1. Go to supabase.com and create a free account
# 2. Create a new project
# 3. Go to Settings > API and copy your URL and anon key
# 4. Paste them below:

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")  # e.g., "https://xxxxx.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")  # Your anon/public key

# Initialize Supabase client
supabase_client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✓ Supabase connected!")
    except Exception as e:
        print(f"Supabase connection error: {e}")

# Fallback to local JSON file
LIVE_EVENTS_FILE = os.path.join(os.path.dirname(__file__), 'live_events.json')

def load_live_events():
    """Load live events from Supabase or fallback to JSON file."""
    # Try Supabase first
    if supabase_client:
        try:
            response = supabase_client.table('live_data').select('*').eq('id', 1).execute()
            if response.data and len(response.data) > 0:
                return response.data[0].get('data', {"events": [], "announcements": []})
        except Exception as e:
            print(f"Supabase read error: {e}")
    
    # Fallback to local JSON
    try:
        with open(LIVE_EVENTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"events": [], "announcements": []}

def save_live_events(data):
    """Save live events to Supabase and local JSON file."""
    # Save to Supabase
    if supabase_client:
        try:
            supabase_client.table('live_data').upsert({
                'id': 1,
                'data': data,
                'updated_at': datetime.now().isoformat()
            }).execute()
        except Exception as e:
            print(f"Supabase write error: {e}")
    
    # Also save to local JSON as backup
    with open(LIVE_EVENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# =============================================================================
# GOOGLE CALENDAR CONFIGURATION
# =============================================================================
# To use: Get your Google Calendar's public ICS link:
# 1. Open Google Calendar > Settings > Select your calendar
# 2. Scroll to "Integrate calendar" section
# 3. Copy the "Public address in iCal format" URL
# 4. Paste it below

GOOGLE_CALENDAR_ICS_URL = ""  # Paste your ICS URL here
# Example: "https://calendar.google.com/calendar/ical/your_calendar_id/public/basic.ics"

# =============================================================================
# SEMIFINALIST EVENTS CONFIGURATION
# =============================================================================
# Edit these lists to control which events appear on the semifinalist sign-up page.
# Remove any events that don't have semifinals at your conference.

SEMIFINAL_EVENTS = {
    "hs": {  # High School
        "individual": [
            "Architectural Design",
            "Biotechnology Design",
            "Board Game Design",
            "CAD Architecture",
            "CAD Engineering",
            "Children's Stories",
            "Coding",
            "Data Science and Analytics",
            "Debating Technological Issues",
            "Engineering Design",
            "Essays on Technology",
            "Extemporaneous Speech",
            "Fashion Design and Technology",
            "Flight Endurance",
            "Forensic Science",
            "Music Production",
            "Photographic Technology",
            "Prepared Presentation",
            "Promotional Design",
            "Technology Problem Solving",
        ],
        "team": [
            "Animatronics",
            "Audio Podcasting",
            "Digital Video Production",
            "Dragster Design",
            "Future Technology and Engineering Teacher",
            "On Demand Video",
            "Software Development",
            "Structural Design and Engineering",
            "System Control Technology",
            "Technology Bowl",
            "Video Game Design",
            "Virtual Reality Visualization (VR)",
            "Webmaster",
        ]
    },
    "ms": {  # Middle School
        "individual": [
            "Biotechnology",
            "CAD Foundations",
            "Career Prep",
            "Challenging Technology Issues",
            "Chapter Team",
            "Children's Stories",
            "Coding",
            "Community Service Video",
            "Construction Challenge",
            "Data Science and Analytics",
            "Digital Photography",
            "Dragster",
            "Essays on Technology",
            "Flight",
            "Forensic Technology",
            "Inventions and Innovations",
            "Junior Solar Sprint",
            "Leadership Strategies",
            "Mass Production",
            "Mechanical Engineering",
            "Medical Technology",
            "Microcontroller Design",
            "Off the Grid",
            "Prepared Presentation",
            "Problem Solving",
            "Promotional Marketing",
            "STEM Animation",
            "Structural Engineering",
            "Tech Bowl",
            "Video Game Design",
            "Website Design",
        ],
        "team": []  # Add any MS team events with semifinals here
    }
}

# Category keywords - events containing these words get categorized automatically
CATEGORY_KEYWORDS = {
    "competition": ["competition", "contest", "challenge", "design", "coding", "robotics", "engineering"],
    "ceremony": ["ceremony", "opening", "closing", "awards"],
    "break": ["lunch", "dinner", "breakfast", "break", "meal"],
    "social": ["social", "mixer", "networking", "meet"],
    "general": ["registration", "check-in", "judging", "meeting"]
}

def categorize_event(event_name):
    """Auto-categorize events based on keywords in the name."""
    event_lower = event_name.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in event_lower:
                return category
    return "general"

def fetch_google_calendar_events():
    """Fetch events from Google Calendar ICS feed."""
    if not GOOGLE_CALENDAR_ICS_URL:
        return None  # No calendar configured, use fallback
    
    try:
        response = requests.get(GOOGLE_CALENDAR_ICS_URL, timeout=10)
        response.raise_for_status()
        
        cal = Calendar.from_ical(response.content)
        events_by_day = {}
        local_tz = tz.tzlocal()
        
        for component in cal.walk():
            if component.name == "VEVENT":
                # Get event details
                summary = str(component.get('summary', 'Untitled Event'))
                location = str(component.get('location', 'TBA'))
                description = str(component.get('description', ''))
                
                # Parse start/end times
                dtstart = component.get('dtstart')
                dtend = component.get('dtend')
                
                if dtstart:
                    start_dt = dtstart.dt
                    # Handle all-day events (date vs datetime)
                    if isinstance(start_dt, datetime):
                        start_dt = start_dt.astimezone(local_tz)
                        start_time = start_dt.strftime('%I:%M %p').lstrip('0')
                    else:
                        start_time = "All Day"
                    
                    # Get day name
                    if isinstance(start_dt, datetime):
                        day_key = start_dt.strftime('%A').lower()
                        date_str = start_dt.strftime('%B %d, %Y')
                    else:
                        day_key = start_dt.strftime('%A').lower()
                        date_str = start_dt.strftime('%B %d, %Y')
                    
                    # Parse end time
                    end_time = ""
                    if dtend:
                        end_dt = dtend.dt
                        if isinstance(end_dt, datetime):
                            end_dt = end_dt.astimezone(local_tz)
                            end_time = end_dt.strftime('%I:%M %p').lstrip('0')
                    
                    # Create event dict
                    event = {
                        "time": start_time,
                        "end_time": end_time,
                        "event": summary,
                        "location": location,
                        "category": categorize_event(summary),
                        "description": description
                    }
                    
                    # Group by day
                    if day_key not in events_by_day:
                        events_by_day[day_key] = {
                            "date": date_str,
                            "events": []
                        }
                    events_by_day[day_key]["events"].append(event)
        
        # Sort events by time within each day
        for day in events_by_day.values():
            day["events"].sort(key=lambda x: x["time"])
        
        return events_by_day if events_by_day else None
        
    except Exception as e:
        print(f"Error fetching Google Calendar: {e}")
        return None

# Fallback schedule if Google Calendar is not configured or fails
FALLBACK_SCHEDULE = {
    "friday": {
        "date": "January 30, 2026",
        "events": [
            {"time": "2:00 PM", "end_time": "4:00 PM", "event": "Registration & Check-in", "location": "Main Lobby", "category": "general"},
            {"time": "4:00 PM", "end_time": "5:00 PM", "event": "Opening Ceremony", "location": "Auditorium", "category": "ceremony"},
            {"time": "5:00 PM", "end_time": "6:30 PM", "event": "Dinner Break", "location": "Cafeteria", "category": "break"},
            {"time": "6:30 PM", "end_time": "9:00 PM", "event": "Written Tests & Preliminary Judging", "location": "Various Rooms", "category": "competition"},
            {"time": "9:00 PM", "end_time": "10:00 PM", "event": "Social Mixer & Networking", "location": "Gymnasium", "category": "social"},
        ]
    },
    "saturday": {
        "date": "January 31, 2026",
        "events": [
            {"time": "7:00 AM", "end_time": "8:00 AM", "event": "Breakfast", "location": "Cafeteria", "category": "break"},
            {"time": "8:00 AM", "end_time": "12:00 PM", "event": "Competition Events - Session 1", "location": "Various Rooms", "category": "competition"},
            {"time": "8:30 AM", "end_time": "11:30 AM", "event": "Coding Competition", "location": "Computer Lab A", "category": "competition"},
            {"time": "9:00 AM", "end_time": "11:00 AM", "event": "Video Game Design Showcase", "location": "Room 204", "category": "competition"},
            {"time": "9:00 AM", "end_time": "12:00 PM", "event": "Webmaster Presentations", "location": "Room 301", "category": "competition"},
            {"time": "12:00 PM", "end_time": "1:00 PM", "event": "Lunch Break", "location": "Cafeteria", "category": "break"},
            {"time": "1:00 PM", "end_time": "4:00 PM", "event": "Competition Events - Session 2", "location": "Various Rooms", "category": "competition"},
            {"time": "1:00 PM", "end_time": "3:00 PM", "event": "Robotics Challenge", "location": "Gymnasium", "category": "competition"},
            {"time": "1:30 PM", "end_time": "3:30 PM", "event": "CAD Engineering", "location": "Computer Lab B", "category": "competition"},
            {"time": "2:00 PM", "end_time": "4:00 PM", "event": "Flight Endurance", "location": "Field House", "category": "competition"},
            {"time": "4:00 PM", "end_time": "5:00 PM", "event": "Final Judging & Deliberation", "location": "Judge's Room", "category": "general"},
            {"time": "5:30 PM", "end_time": "7:00 PM", "event": "Awards Ceremony", "location": "Auditorium", "category": "ceremony"},
            {"time": "7:00 PM", "end_time": "7:30 PM", "event": "Closing Remarks", "location": "Auditorium", "category": "ceremony"},
        ]
    }
}

# Live events data - loaded from JSON file
def get_live_events():
    """Get current live events with status from JSON file."""
    data = load_live_events()
    return data.get('events', [])


def get_settings():
    """Get settings from data file."""
    data = load_live_events()
    return data.get('settings', {'semifinalist_signup_visible': False})


def save_settings(settings):
    """Save settings to data file."""
    data = load_live_events()
    data['settings'] = settings
    save_live_events(data)


def get_announcements():
    """Get announcements from JSON file."""
    data = load_live_events()
    return data.get('announcements', [])


def get_schedule():
    """Get schedule from Google Calendar or fallback to static data."""
    calendar_data = fetch_google_calendar_events()
    if calendar_data:
        return calendar_data
    return FALLBACK_SCHEDULE


@app.route('/')
def home():
    """Render the home page."""
    settings = get_settings()
    return render_template('index.html', page='home', settings=settings)


@app.route('/schedule')
def schedule():
    """Render the full schedule page."""
    schedule_data = get_schedule()
    settings = get_settings()
    return render_template('index.html', page='schedule', schedule=schedule_data, settings=settings)


@app.route('/live')
def live():
    """Render the live events board."""
    settings = get_settings()
    return render_template('index.html', page='live', settings=settings)


@app.route('/semifinalists')
def semifinalists():
    """Render the semifinalist signup page (if enabled)."""
    settings = get_settings()
    if not settings.get('semifinalist_signup_visible', False):
        return render_template('index.html', page='home', settings=settings)  # Redirect to home if not visible
    return render_template('semifinalists.html', events=SEMIFINAL_EVENTS)


@app.route('/api/semifinalist-signup', methods=['POST'])
def api_semifinalist_signup():
    """Handle semifinalist signup submissions."""
    try:
        signup_data = request.get_json()
        if not signup_data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        # Load existing data
        data = load_live_events()
        
        # Initialize semifinalist_signups if not exists
        if 'semifinalist_signups' not in data:
            data['semifinalist_signups'] = []
        
        # Add ID and timestamp
        signup_data['id'] = len(data['semifinalist_signups']) + 1
        signup_data['submitted_at'] = datetime.now().isoformat()
        
        # Add to list
        data['semifinalist_signups'].append(signup_data)
        save_live_events(data)
        
        return jsonify({'success': True, 'message': 'Signup submitted successfully!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/settings', methods=['GET'])
def api_admin_get_settings():
    """Get current settings."""
    settings = get_settings()
    return jsonify(settings)


@app.route('/api/admin/settings', methods=['POST'])
def api_admin_save_settings():
    """Save settings."""
    try:
        settings = request.get_json()
        save_settings(settings)
        return jsonify({'success': True, 'message': 'Settings saved!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/semifinalist-signups', methods=['GET'])
def api_admin_get_signups():
    """Get all semifinalist signups."""
    data = load_live_events()
    return jsonify(data.get('semifinalist_signups', []))


@app.route('/api/admin/semifinal-events', methods=['GET'])
def api_admin_get_semifinal_events():
    """Get the configured semifinal events list."""
    return jsonify(SEMIFINAL_EVENTS)


@app.route('/api/admin/semifinalist-signups/<int:signup_id>', methods=['DELETE'])
def api_admin_delete_signup(signup_id):
    """Delete a semifinalist signup."""
    try:
        data = load_live_events()
        original_length = len(data.get('semifinalist_signups', []))
        data['semifinalist_signups'] = [s for s in data.get('semifinalist_signups', []) if s.get('id') != signup_id]
        
        if len(data.get('semifinalist_signups', [])) == original_length:
            return jsonify({'success': False, 'error': 'Signup not found'}), 404
        
        save_live_events(data)
        return jsonify({'success': True, 'message': 'Signup deleted!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/live-events')
def api_live_events():
    """API endpoint to get live event data."""
    events = get_live_events()
    announcements = get_announcements()
    return jsonify({
        'events': events,
        'announcements': announcements,
        'last_updated': datetime.now().strftime('%I:%M:%S %p')
    })


@app.route('/api/schedule')
def api_schedule():
    """API endpoint to get schedule data."""
    return jsonify(get_schedule())


@app.route('/api/calendar-status')
def api_calendar_status():
    """Check if Google Calendar is configured and working."""
    if not GOOGLE_CALENDAR_ICS_URL:
        return jsonify({
            'configured': False,
            'message': 'No Google Calendar URL configured. Using fallback schedule.',
            'url': None
        })
    
    try:
        response = requests.get(GOOGLE_CALENDAR_ICS_URL, timeout=5)
        response.raise_for_status()
        return jsonify({
            'configured': True,
            'message': 'Google Calendar connected successfully!',
            'url': GOOGLE_CALENDAR_ICS_URL[:50] + '...'
        })
    except Exception as e:
        return jsonify({
            'configured': True,
            'message': f'Error connecting to Google Calendar: {str(e)}',
            'url': GOOGLE_CALENDAR_ICS_URL[:50] + '...'
        })


# ============== ADMIN ROUTES ==============

# ============== SECRET ADMIN URL ==============
# Change this to your own secret! Don't share it publicly.
ADMIN_SECRET = "tsa-control-2026"

@app.route(f'/admin-{ADMIN_SECRET}')
def admin():
    """Render the admin control panel."""
    return render_template('admin.html')


@app.route('/api/admin/events', methods=['GET'])
def api_admin_get_events():
    """Get all events and announcements for admin panel."""
    data = load_live_events()
    return jsonify(data)


@app.route('/api/admin/events', methods=['POST'])
def api_admin_save_events():
    """Save all events and announcements from admin panel."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        # Validate structure
        if 'events' not in data or 'announcements' not in data:
            return jsonify({'success': False, 'error': 'Invalid data structure'}), 400
        
        save_live_events(data)
        return jsonify({'success': True, 'message': 'Events saved successfully!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/event/<event_id>', methods=['PUT'])
def api_admin_update_event(event_id):
    """Update a single event."""
    try:
        data = load_live_events()
        event_data = request.get_json()
        
        # Find and update the event
        for i, event in enumerate(data['events']):
            if event['id'] == event_id:
                data['events'][i] = event_data
                save_live_events(data)
                return jsonify({'success': True, 'message': 'Event updated!'})
        
        return jsonify({'success': False, 'error': 'Event not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/event/<event_id>', methods=['DELETE'])
def api_admin_delete_event(event_id):
    """Delete a single event."""
    try:
        data = load_live_events()
        original_length = len(data['events'])
        data['events'] = [e for e in data['events'] if e['id'] != event_id]
        
        if len(data['events']) == original_length:
            return jsonify({'success': False, 'error': 'Event not found'}), 404
        
        save_live_events(data)
        return jsonify({'success': True, 'message': 'Event deleted!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/event', methods=['POST'])
def api_admin_add_event():
    """Add a new event."""
    try:
        data = load_live_events()
        event_data = request.get_json()
        
        # Generate ID if not provided
        if 'id' not in event_data or not event_data['id']:
            existing_ids = [e['id'] for e in data['events'] if e.get('id', '').startswith('EVT')]
            max_num = 0
            for eid in existing_ids:
                try:
                    num = int(eid.replace('EVT', ''))
                    max_num = max(max_num, num)
                except:
                    pass
            event_data['id'] = f'EVT{max_num + 1:03d}'
        
        data['events'].append(event_data)
        save_live_events(data)
        return jsonify({'success': True, 'message': 'Event added!', 'id': event_data['id']})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/announcement', methods=['POST'])
def api_admin_add_announcement():
    """Add a new announcement."""
    try:
        data = load_live_events()
        announcement_data = request.get_json()
        
        # Generate ID if not provided
        if 'id' not in announcement_data or not announcement_data['id']:
            existing_ids = [a.get('id', 0) for a in data['announcements']]
            announcement_data['id'] = max(existing_ids, default=0) + 1
        
        # Add timestamp if not provided
        if 'time' not in announcement_data:
            announcement_data['time'] = datetime.now().strftime('%I:%M %p')
        
        # Insert at beginning (newest first)
        data['announcements'].insert(0, announcement_data)
        save_live_events(data)
        return jsonify({'success': True, 'message': 'Announcement added!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/announcement/<int:announcement_id>', methods=['DELETE'])
def api_admin_delete_announcement(announcement_id):
    """Delete an announcement."""
    try:
        data = load_live_events()
        original_length = len(data['announcements'])
        data['announcements'] = [a for a in data['announcements'] if a.get('id') != announcement_id]
        
        if len(data['announcements']) == original_length:
            return jsonify({'success': False, 'error': 'Announcement not found'}), 404
        
        save_live_events(data)
        return jsonify({'success': True, 'message': 'Announcement deleted!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/schedule')
def api_admin_schedule():
    """Get schedule data for admin editing - from Google Calendar or fallback."""
    schedule_data = get_schedule()
    calendar_status = {
        'connected': bool(GOOGLE_CALENDAR_ICS_URL),
        'url': GOOGLE_CALENDAR_ICS_URL[:50] + '...' if GOOGLE_CALENDAR_ICS_URL else None
    }
    return jsonify({
        'schedule': schedule_data,
        'calendar_status': calendar_status
    })


@app.route('/api/admin/import-to-live', methods=['POST'])
def api_admin_import_to_live():
    """Import schedule events to live events board."""
    try:
        import_data = request.get_json()
        events_to_import = import_data.get('events', [])
        
        data = load_live_events()
        existing_ids = [e['id'] for e in data['events']]
        
        imported_count = 0
        for event in events_to_import:
            # Generate unique ID
            base_id = f"CAL{hash(event['event'] + event.get('time', '')) % 10000:04d}"
            if base_id not in existing_ids:
                new_event = {
                    'id': base_id,
                    'event': event['event'],
                    'location': event.get('location', 'TBD'),
                    'scheduled_time': event.get('time', ''),
                    'status': 'upcoming',
                    'status_text': 'On Schedule',
                    'participants': 0,
                    'notes': f"Category: {event.get('category', 'general')}",
                    'new_time': None,
                    'new_location': None,
                    'alert': None
                }
                data['events'].append(new_event)
                existing_ids.append(base_id)
                imported_count += 1
        
        save_live_events(data)
        return jsonify({'success': True, 'message': f'Imported {imported_count} events to live board!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
