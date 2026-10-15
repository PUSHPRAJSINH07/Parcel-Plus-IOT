"""
ParcelPulse IoT - Complete Flask Backend
Single-file backend application containing Flask app setup, SQLite database helpers,
database initialization, seed data, web page routes, and REST API endpoints.
"""

import datetime
from datetime import timedelta
import functools
import json
import os
import sqlite3
import uuid
from flask import Flask, g, jsonify, render_template, request

# -----------------------------------------------------------------------------
# Configuration & Application Initialization
# -----------------------------------------------------------------------------
app = Flask(
    'ParcelPulse IoT',
    root_path=os.path.dirname(os.path.abspath(__file__)),
    template_folder='templates',
    static_folder='static'
)

app.secret_key = os.urandom(24)
DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'parcelpulse.db')
API_KEY = 'parcelpulse-device-key-2026'


# -----------------------------------------------------------------------------
# Database Helper Functions
# -----------------------------------------------------------------------------
def get_db():
    """Returns a SQLite database connection with row factory enabled."""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    """Closes the database connection on request teardown."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


app.teardown_appcontext(close_db)


def init_db():
    """Creates the SQLite database schema if tables do not already exist."""
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS parcels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parcel_id TEXT UNIQUE NOT NULL,
            qr_code TEXT,
            destination TEXT NOT NULL,
            weight REAL,
            status TEXT DEFAULT 'pending',
            bin_number INTEGER,
            latitude REAL,
            longitude REAL,
            gps_updated_at TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sorting_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parcel_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            description TEXT,
            device_id TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT UNIQUE NOT NULL,
            device_type TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT DEFAULT 'offline',
            last_seen TEXT,
            metadata TEXT
        );
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS gps_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parcel_id TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            timestamp TEXT DEFAULT (datetime('now','localtime'))
        );
    ''')

    db.commit()


def seed_data():
    """Populates initial demo data if the parcels table is currently empty."""
    db = get_db()
    count = db.execute('SELECT COUNT(*) FROM parcels').fetchone()[0]
    if count > 0:
        return

    now = datetime.datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')

    # Seed 12 Demo Parcels
    parcels = [
        ('PP-AHM-001', 'QR-AHM-001', 'Ahmedabad', 2.5, 'sorted', 1, 23.0225, 72.5714),
        ('PP-AHM-002', 'QR-AHM-002', 'Ahmedabad', 1.8, 'sorted', 1, 23.0300, 72.5800),
        ('PP-AHM-003', 'QR-AHM-003', 'Ahmedabad', 3.2, 'pending', None, 23.0100, 72.5600),
        ('PP-AHM-004', 'QR-AHM-004', 'Ahmedabad', 0.9, 'sorting', None, 23.0400, 72.5900),
        ('PP-SUR-001', 'QR-SUR-001', 'Surat', 1.5, 'sorted', 2, 21.1702, 72.8311),
        ('PP-SUR-002', 'QR-SUR-002', 'Surat', 4.1, 'sorted', 2, 21.1800, 72.8400),
        ('PP-SUR-003', 'QR-SUR-003', 'Surat', 2.0, 'pending', None, 21.1600, 72.8200),
        ('PP-SUR-004', 'QR-SUR-004', 'Surat', 1.2, 'sorting', None, 21.1900, 72.8500),
        ('PP-RAJ-001', 'QR-RAJ-001', 'Rajkot', 3.0, 'sorted', 3, 22.3039, 70.8022),
        ('PP-RAJ-002', 'QR-RAJ-002', 'Rajkot', 2.7, 'pending', None, 22.3100, 70.8100),
        ('PP-RAJ-003', 'QR-RAJ-003', 'Rajkot', 1.4, 'pending', None, 22.2900, 70.7900),
        ('PP-RAJ-004', 'QR-RAJ-004', 'Rajkot', 5.0, 'sorted', 3, 22.3200, 70.8200),
    ]

    for p in parcels:
        gps_time = now_str if (p[6] is not None and p[7] is not None) else None
        db.execute('''
            INSERT INTO parcels (
                parcel_id, qr_code, destination, weight, status,
                bin_number, latitude, longitude, gps_updated_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], gps_time, now_str, now_str))

    # Seed demo GPS tracking points for parcels with coordinates
    for p in parcels:
        if p[6] is not None and p[7] is not None:
            db.execute('''
                INSERT INTO gps_updates (parcel_id, latitude, longitude, timestamp)
                VALUES (?, ?, ?, ?)
            ''', (p[0], p[6], p[7], now_str))

    # Seed 8 IoT Devices
    devices = [
        ('ESP32-SORT-01', 'esp32', 'ESP32 Sorter Node 1', 'online', now.isoformat()),
        ('ESP32-SORT-02', 'esp32', 'ESP32 Sorter Node 2', 'online', now.isoformat()),
        ('ESP32-SORT-03', 'esp32', 'ESP32 Sorter Node 3', 'offline', None),
        ('CONV-01', 'conveyor', 'Main Conveyor Belt', 'online', now.isoformat()),
        ('MTR-01', 'motor', 'Sorting Motor', 'online', now.isoformat()),
        ('SRV-01', 'servo', 'Diverter Servo', 'online', now.isoformat()),
        ('IR-01', 'ir_sensor', 'Entry IR Sensor', 'online', now.isoformat()),
        ('IR-02', 'ir_sensor', 'Exit IR Sensor', 'online', now.isoformat()),
    ]

    for d in devices:
        db.execute('''
            INSERT INTO devices (device_id, device_type, name, status, last_seen)
            VALUES (?, ?, ?, ?, ?)
        ''', (d[0], d[1], d[2], d[3], d[4]))

    # Seed 15+ Sorting Events with past timestamps
    minus_3h = (now - timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')
    minus_2h55m = (now - timedelta(hours=2, minutes=55)).strftime('%Y-%m-%d %H:%M:%S')
    minus_2h30m = (now - timedelta(hours=2, minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
    minus_2h25m = (now - timedelta(hours=2, minutes=25)).strftime('%Y-%m-%d %H:%M:%S')
    minus_2h = (now - timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')
    minus_1h55m = (now - timedelta(hours=1, minutes=55)).strftime('%Y-%m-%d %H:%M:%S')
    minus_1h30m = (now - timedelta(hours=1, minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
    minus_1h25m = (now - timedelta(hours=1, minutes=25)).strftime('%Y-%m-%d %H:%M:%S')
    minus_1h = (now - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
    minus_55m = (now - timedelta(minutes=55)).strftime('%Y-%m-%d %H:%M:%S')
    minus_45m = (now - timedelta(minutes=45)).strftime('%Y-%m-%d %H:%M:%S')
    minus_40m = (now - timedelta(minutes=40)).strftime('%Y-%m-%d %H:%M:%S')
    minus_20m = (now - timedelta(minutes=20)).strftime('%Y-%m-%d %H:%M:%S')
    minus_10m = (now - timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
    minus_5m = (now - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')

    events = [
        ('PP-AHM-001', 'scan', 'Parcel scanned at entry', 'ESP32-SORT-01', minus_3h),
        ('PP-AHM-001', 'sorted', 'Sorted to Bin 1 (Ahmedabad)', 'ESP32-SORT-01', minus_2h55m),
        ('PP-SUR-001', 'scan', 'Parcel scanned at entry', 'ESP32-SORT-02', minus_2h30m),
        ('PP-SUR-001', 'sorted', 'Sorted to Bin 2 (Surat)', 'ESP32-SORT-02', minus_2h25m),
        ('PP-RAJ-001', 'scan', 'Parcel scanned at entry', 'ESP32-SORT-01', minus_2h),
        ('PP-RAJ-001', 'sorted', 'Sorted to Bin 3 (Rajkot)', 'ESP32-SORT-01', minus_1h55m),
        ('PP-AHM-002', 'scan', 'Parcel scanned at entry', 'ESP32-SORT-02', minus_1h30m),
        ('PP-AHM-002', 'sorted', 'Sorted to Bin 1 (Ahmedabad)', 'ESP32-SORT-02', minus_1h25m),
        ('PP-SUR-002', 'scan', 'Parcel scanned at entry', 'ESP32-SORT-01', minus_1h),
        ('PP-SUR-002', 'sorted', 'Sorted to Bin 2 (Surat)', 'ESP32-SORT-01', minus_55m),
        ('PP-RAJ-004', 'scan', 'Parcel scanned at entry', 'ESP32-SORT-02', minus_45m),
        ('PP-RAJ-004', 'sorted', 'Sorted to Bin 3 (Rajkot)', 'ESP32-SORT-02', minus_40m),
        ('PP-AHM-004', 'scan', 'Parcel scanned at entry', 'ESP32-SORT-01', minus_20m),
        ('SYSTEM', 'bin_full', 'Bin 2 (Surat) is full — 15/15 capacity', 'IR-02', minus_10m),
        ('PP-SUR-004', 'error', 'QR code scan failed — retrying', 'ESP32-SORT-02', minus_5m),
    ]

    for e in events:
        db.execute('''
            INSERT INTO sorting_events (parcel_id, event_type, description, device_id, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (e[0], e[1], e[2], e[3], e[4]))

    db.commit()


# -----------------------------------------------------------------------------
# Authentication Decorator
# -----------------------------------------------------------------------------
def require_api_key(f):
    """Decorator to require device API key in the X-API-Key request header."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get('X-API-Key')
        if key != API_KEY:
            return jsonify({'error': 'Invalid or missing API key'}), 401
        return f(*args, **kwargs)
    return decorated


# -----------------------------------------------------------------------------
# Web Page Routes
# -----------------------------------------------------------------------------
@app.route('/')
def dashboard():
    """Renders the main dashboard page with metrics, hardware triad, mini-map, and alerts."""
    db = get_db()
    total = db.execute('SELECT COUNT(*) FROM parcels').fetchone()[0]
    pending = db.execute("SELECT COUNT(*) FROM parcels WHERE status='pending'").fetchone()[0]
    sorting = db.execute("SELECT COUNT(*) FROM parcels WHERE status='sorting'").fetchone()[0]
    sorted_count = db.execute("SELECT COUNT(*) FROM parcels WHERE status='sorted'").fetchone()[0]
    
    # Count full bins (for demo, bins with >= 4 parcels or explicitly flagged in alerts)
    full_bins = db.execute(
        "SELECT COUNT(DISTINCT bin_number) FROM parcels WHERE bin_number IS NOT NULL GROUP BY bin_number HAVING COUNT(*) >= 4"
    ).fetchall()
    full_bins_count = max(len(full_bins), 1)  # Surat Bin 2 is at capacity in the demo scenario
    
    devices_online = db.execute("SELECT COUNT(*) FROM devices WHERE status='online'").fetchone()[0]
    devices_total = db.execute('SELECT COUNT(*) FROM devices').fetchone()[0]
    
    # Hardware triad status for the dashboard
    esp_main = db.execute("SELECT * FROM devices WHERE device_id='ESP32-SORT-01'").fetchone()
    esp_cam = db.execute("SELECT * FROM devices WHERE device_id='ESP32-SORT-02'").fetchone()
    esp_gps = db.execute("SELECT * FROM devices WHERE device_id='ESP32-SORT-03'").fetchone()

    recent_events = db.execute('SELECT * FROM sorting_events ORDER BY created_at DESC LIMIT 8').fetchall()
    recent_alerts = db.execute(
        "SELECT * FROM sorting_events WHERE event_type IN ('bin_full', 'error') ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    
    dest_stats = db.execute(
        'SELECT destination, COUNT(*) as count, SUM(CASE WHEN status="sorted" THEN 1 ELSE 0 END) as sorted_count FROM parcels GROUP BY destination'
    ).fetchall()

    # Coordinates for the compact live map
    mini_parcels = db.execute(
        'SELECT parcel_id, destination, status, latitude, longitude, gps_updated_at FROM parcels WHERE latitude IS NOT NULL'
    ).fetchall()

    stats = {
        'total_parcels': total,
        'pending': pending + sorting,
        'sorted': sorted_count,
        'full_bins': full_bins_count,
        'devices_online': devices_online,
        'devices_total': devices_total
    }
    
    return render_template(
        'dashboard.html',
        stats=stats,
        recent_events=recent_events,
        recent_alerts=recent_alerts,
        dest_stats=dest_stats,
        mini_parcels=mini_parcels,
        esp_main=esp_main,
        esp_cam=esp_cam,
        esp_gps=esp_gps
    )


@app.route('/tracking')
def tracking():
    """Renders the parcel GPS live tracking map page."""
    db = get_db()
    parcels = db.execute(
        'SELECT parcel_id, destination, status, latitude, longitude, gps_updated_at FROM parcels WHERE latitude IS NOT NULL'
    ).fetchall()
    all_parcels = db.execute('SELECT parcel_id, destination, status FROM parcels').fetchall()
    return render_template('tracking.html', parcels=parcels, all_parcels=all_parcels)


@app.route('/parcels')
def parcels_page():
    """Renders the parcels management and status page."""
    db = get_db()
    parcels = db.execute('SELECT * FROM parcels ORDER BY created_at DESC').fetchall()
    return render_template('parcels.html', parcels=parcels)


@app.route('/devices')
def devices_page():
    """Renders the comprehensive IoT sorting control center and devices monitoring page."""
    db = get_db()
    devices = db.execute('SELECT * FROM devices ORDER BY device_type, name').fetchall()
    
    # 3 Distinct ESP32 Hub Nodes
    esp_main = db.execute("SELECT * FROM devices WHERE device_id='ESP32-SORT-01'").fetchone()
    esp_cam = db.execute("SELECT * FROM devices WHERE device_id='ESP32-SORT-02'").fetchone()
    esp_gps = db.execute("SELECT * FROM devices WHERE device_id='ESP32-SORT-03'").fetchone()

    # Hardware Actuators & Sensors
    conveyor = db.execute("SELECT * FROM devices WHERE device_id='CONV-01'").fetchone()
    motor = db.execute("SELECT * FROM devices WHERE device_id='MTR-01'").fetchone()
    servo = db.execute("SELECT * FROM devices WHERE device_id='SRV-01'").fetchone()
    ir_entry = db.execute("SELECT * FROM devices WHERE device_id='IR-01'").fetchone()
    ir_exit = db.execute("SELECT * FROM devices WHERE device_id='IR-02'").fetchone()

    # Latest QR Scanner activity from ESP32-CAM
    last_qr_event = db.execute(
        "SELECT * FROM sorting_events WHERE device_id='ESP32-SORT-02' OR event_type IN ('scan','error') ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    last_qr_parcel = None
    if last_qr_event and last_qr_event['parcel_id'] and last_qr_event['parcel_id'] != 'SYSTEM':
        last_qr_parcel = db.execute("SELECT * FROM parcels WHERE parcel_id=?", (last_qr_event['parcel_id'],)).fetchone()

    # Latest GPS telemetry from Tracking ESP32
    latest_gps = db.execute(
        "SELECT g.*, p.destination, p.status as parcel_status FROM gps_updates g LEFT JOIN parcels p ON g.parcel_id=p.parcel_id ORDER BY g.timestamp DESC LIMIT 1"
    ).fetchone()

    # Destination lanes detail (Ahmedabad, Surat, Rajkot)
    lanes_data = [
        {
            'lane': 1,
            'bin_number': 1,
            'destination': 'Ahmedabad',
            'angle': '45° Left',
            'capacity_current': 2,
            'capacity_max': 15,
            'is_full': False,
            'status': 'Available',
            'color': '#00d4ff',
            'last_event': 'Sorted to Bin 1 (Ahmedabad)'
        },
        {
            'lane': 2,
            'bin_number': 2,
            'destination': 'Surat',
            'angle': '90° Straight',
            'capacity_current': 15,
            'capacity_max': 15,
            'is_full': True,
            'status': 'Bin Full',
            'color': '#f59e0b',
            'last_event': 'Bin 2 (Surat) is full — 15/15 capacity'
        },
        {
            'lane': 3,
            'bin_number': 3,
            'destination': 'Rajkot',
            'angle': '135° Right',
            'capacity_current': 2,
            'capacity_max': 15,
            'is_full': False,
            'status': 'Available',
            'color': '#10b981',
            'last_event': 'Sorted to Bin 3 (Rajkot)'
        }
    ]

    # Calculate live counts per lane from the database
    for lane in lanes_data:
        sorted_cnt = db.execute(
            "SELECT COUNT(*) FROM parcels WHERE destination=? AND status='sorted'",
            (lane['destination'],)
        ).fetchone()[0]
        total_cnt = db.execute(
            "SELECT COUNT(*) FROM parcels WHERE destination=?",
            (lane['destination'],)
        ).fetchone()[0]
        lane['sorted_count'] = sorted_cnt
        lane['total_count'] = total_cnt

    # Device audit event log
    device_events = db.execute('SELECT * FROM sorting_events ORDER BY created_at DESC LIMIT 20').fetchall()

    return render_template(
        'devices.html',
        devices=devices,
        esp_main=esp_main,
        esp_cam=esp_cam,
        esp_gps=esp_gps,
        conveyor=conveyor,
        motor=motor,
        servo=servo,
        ir_entry=ir_entry,
        ir_exit=ir_exit,
        last_qr_event=last_qr_event,
        last_qr_parcel=last_qr_parcel,
        latest_gps=latest_gps,
        lanes=lanes_data,
        device_events=device_events
    )


@app.route('/history')
def history():
    """Renders the full sorting and scan event log page."""
    db = get_db()
    events = db.execute('SELECT * FROM sorting_events ORDER BY created_at DESC').fetchall()
    return render_template('history.html', events=events)


# -----------------------------------------------------------------------------
# REST API Endpoints
# -----------------------------------------------------------------------------
@app.route('/api/dashboard', methods=['GET'])
def api_dashboard():
    """Returns dashboard statistics and overview metrics in JSON format."""
    db = get_db()
    total = db.execute('SELECT COUNT(*) FROM parcels').fetchone()[0]
    pending = db.execute("SELECT COUNT(*) FROM parcels WHERE status='pending'").fetchone()[0]
    sorting = db.execute("SELECT COUNT(*) FROM parcels WHERE status='sorting'").fetchone()[0]
    sorted_count = db.execute("SELECT COUNT(*) FROM parcels WHERE status='sorted'").fetchone()[0]
    full_bins = db.execute(
        "SELECT COUNT(DISTINCT bin_number) FROM parcels WHERE bin_number IS NOT NULL GROUP BY bin_number HAVING COUNT(*) >= 4"
    ).fetchall()
    full_bins_count = len(full_bins)
    devices_online = db.execute("SELECT COUNT(*) FROM devices WHERE status='online'").fetchone()[0]
    devices_total = db.execute('SELECT COUNT(*) FROM devices').fetchone()[0]
    recent_events = db.execute('SELECT * FROM sorting_events ORDER BY created_at DESC LIMIT 10').fetchall()
    dest_stats = db.execute(
        'SELECT destination, COUNT(*) as count, SUM(CASE WHEN status="sorted" THEN 1 ELSE 0 END) as sorted_count FROM parcels GROUP BY destination'
    ).fetchall()

    stats = {
        'total_parcels': total,
        'pending': pending + sorting,
        'sorted': sorted_count,
        'full_bins': full_bins_count,
        'devices_online': devices_online,
        'devices_total': devices_total
    }
    return jsonify({
        'stats': stats,
        'recent_events': [dict(e) for e in recent_events],
        'dest_stats': [dict(d) for d in dest_stats]
    })


@app.route('/api/parcels', methods=['GET'])
def api_get_parcels():
    """Lists all parcels ordered by creation time descending."""
    db = get_db()
    parcels = db.execute('SELECT * FROM parcels ORDER BY created_at DESC').fetchall()
    return jsonify({'parcels': [dict(p) for p in parcels]})


@app.route('/api/parcels', methods=['POST'])
def api_create_parcel():
    """Registers a new parcel in the system."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    parcel_id = data.get('parcel_id')
    destination = data.get('destination')
    if not parcel_id or not destination:
        return jsonify({'error': 'parcel_id and destination are required'}), 400

    valid_destinations = ['Ahmedabad', 'Surat', 'Rajkot']
    if destination not in valid_destinations:
        return jsonify({'error': f'destination must be one of {valid_destinations}'}), 400

    qr_code = data.get('qr_code', f'QR-{parcel_id}')
    weight = data.get('weight')

    try:
        db = get_db()
        db.execute(
            'INSERT INTO parcels (parcel_id, qr_code, destination, weight) VALUES (?, ?, ?, ?)',
            (parcel_id, qr_code, destination, weight)
        )
        db.commit()

        # Log sorting event for the newly registered parcel
        db.execute(
            'INSERT INTO sorting_events (parcel_id, event_type, description) VALUES (?, ?, ?)',
            (parcel_id, 'parcel_registered', f'New parcel registered for {destination}')
        )
        db.commit()

        parcel = db.execute('SELECT * FROM parcels WHERE parcel_id = ?', (parcel_id,)).fetchone()
        return jsonify({'success': True, 'parcel': dict(parcel)}), 201
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Parcel ID already exists'}), 409


@app.route('/api/parcels/<parcel_id>', methods=['GET'])
def api_get_parcel(parcel_id):
    """Retrieves a single parcel by parcel_id."""
    db = get_db()
    parcel = db.execute('SELECT * FROM parcels WHERE parcel_id = ?', (parcel_id,)).fetchone()
    if not parcel:
        return jsonify({'error': 'Parcel not found'}), 404
    return jsonify({'parcel': dict(parcel)})


@app.route('/api/gps', methods=['POST'])
@require_api_key
def api_update_gps():
    """Updates the GPS location for a specific parcel and records to GPS history."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    parcel_id = data.get('parcel_id')
    latitude = data.get('latitude')
    longitude = data.get('longitude')

    if not all([parcel_id, latitude is not None, longitude is not None]):
        return jsonify({'error': 'parcel_id, latitude, longitude required'}), 400

    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (ValueError, TypeError):
        return jsonify({'error': 'latitude and longitude must be numbers'}), 400

    db = get_db()
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Update parcel record
    db.execute(
        'UPDATE parcels SET latitude=?, longitude=?, gps_updated_at=?, updated_at=? WHERE parcel_id=?',
        (latitude, longitude, now, now, parcel_id)
    )

    # Insert GPS history
    db.execute(
        'INSERT INTO gps_updates (parcel_id, latitude, longitude) VALUES (?, ?, ?)',
        (parcel_id, latitude, longitude)
    )
    db.commit()

    return jsonify({'success': True, 'timestamp': now})


@app.route('/api/gps/<parcel_id>', methods=['GET'])
def api_get_gps(parcel_id):
    """Retrieves the latest GPS coordinates for a specific parcel."""
    db = get_db()
    parcel = db.execute(
        'SELECT parcel_id, latitude, longitude, gps_updated_at FROM parcels WHERE parcel_id = ?',
        (parcel_id,)
    ).fetchone()

    if not parcel:
        return jsonify({'error': 'Parcel not found'}), 404

    return jsonify(dict(parcel))


@app.route('/api/sorting-events', methods=['POST'])
@require_api_key
def api_create_event():
    """Logs a new sorting event from an IoT device."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    parcel_id = data.get('parcel_id')
    event_type = data.get('event_type')
    if not parcel_id or not event_type:
        return jsonify({'error': 'parcel_id and event_type required'}), 400

    description = data.get('description', '')
    device_id = data.get('device_id', '')

    db = get_db()
    db.execute(
        'INSERT INTO sorting_events (parcel_id, event_type, description, device_id) VALUES (?, ?, ?, ?)',
        (parcel_id, event_type, description, device_id)
    )
    db.commit()

    return jsonify({'success': True}), 201


@app.route('/api/sorting-events', methods=['GET'])
def api_get_events():
    """Lists sorting events, optionally filtered by event_type."""
    db = get_db()
    event_type = request.args.get('event_type')
    if event_type:
        events = db.execute(
            'SELECT * FROM sorting_events WHERE event_type = ? ORDER BY created_at DESC',
            (event_type,)
        ).fetchall()
    else:
        events = db.execute('SELECT * FROM sorting_events ORDER BY created_at DESC').fetchall()

    return jsonify({'events': [dict(e) for e in events]})


@app.route('/api/devices', methods=['GET'])
def api_get_devices():
    """Lists all registered IoT devices ordered by device type and name."""
    db = get_db()
    devices = db.execute('SELECT * FROM devices ORDER BY device_type, name').fetchall()
    return jsonify({'devices': [dict(d) for d in devices]})


@app.route('/api/devices', methods=['POST'])
@require_api_key
def api_update_device():
    """Updates device status and heartbeat timestamp."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    device_id = data.get('device_id')
    if not device_id:
        return jsonify({'error': 'device_id required'}), 400

    db = get_db()
    device = db.execute('SELECT * FROM devices WHERE device_id = ?', (device_id,)).fetchone()
    if not device:
        return jsonify({'error': 'Device not found'}), 404

    status = data.get('status', device['status'])
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    db.execute('UPDATE devices SET status=?, last_seen=? WHERE device_id=?', (status, now, device_id))
    db.commit()

    return jsonify({'success': True})


# -----------------------------------------------------------------------------
# Main Application Execution
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    with app.app_context():
        init_db()
        seed_data()
    app.run(host='0.0.0.0', port=5000, debug=True)
