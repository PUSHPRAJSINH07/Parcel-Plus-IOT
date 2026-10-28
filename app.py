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
import threading
import uuid
from flask import Flask, g, jsonify, render_template, request

# Try importing paho-mqtt
try:
    import paho.mqtt.client as mqtt
    PAHO_AVAILABLE = True
except ImportError:
    PAHO_AVAILABLE = False

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
    """Initializes default device slots as offline if not present. Does NOT inject sample parcels or fake events."""
    db = get_db()
    cursor = db.cursor()

    # Ensure 8 device slots exist with status 'offline' and no fake timestamps
    devices = [
        ('ESP32-SORT-01', 'esp32', 'Main ESP32 Sorter', 'offline'),
        ('ESP32-SORT-02', 'esp32', 'ESP32-CAM Vision', 'offline'),
        ('ESP32-SORT-03', 'esp32', 'Tracking ESP32', 'offline'),
        ('CONV-01', 'conveyor', 'Main Conveyor Belt', 'offline'),
        ('MTR-01', 'motor', 'Sorting Motor Driver', 'offline'),
        ('SRV-01', 'servo', 'Diverter Servo', 'offline'),
        ('IR-01', 'ir_sensor', 'Entry IR Sensor', 'offline'),
        ('IR-02', 'ir_sensor', 'Exit IR Sensor', 'offline'),
    ]

    for d in devices:
        cursor.execute('''
            INSERT OR IGNORE INTO devices (device_id, device_type, name, status, last_seen)
            VALUES (?, ?, ?, ?, NULL)
        ''', (d[0], d[1], d[2], d[3]))

    db.commit()


# -----------------------------------------------------------------------------
# MQTT Client Integration & Live Scan Pipeline
# -----------------------------------------------------------------------------
MQTT_BROKER = os.environ.get('MQTT_BROKER', 'broker.hivemq.com')
MQTT_PORT = int(os.environ.get('MQTT_PORT', 1883))
MQTT_TOPIC_SCAN = os.environ.get('MQTT_TOPIC_SCAN', 'parcelpulse/scan')
MQTT_TOPIC_HEARTBEAT = os.environ.get('MQTT_TOPIC_HEARTBEAT', 'parcelpulse/heartbeat')
MQTT_TOPIC_GPS = os.environ.get('MQTT_TOPIC_GPS', 'parcelpulse/gps')
MQTT_TOPIC_SORT_CMD = os.environ.get('MQTT_TOPIC_SORT_CMD', 'parcelpulse/sort_command')

mqtt_client = None
mqtt_connected = False


def determine_destination(parcel_id, dest_hint=None):
    """Infers destination from explicit hint or parcel identifier prefix (AHM, SUR, RAJ)."""
    if dest_hint:
        for valid in ['Ahmedabad', 'Surat', 'Rajkot']:
            if valid.lower() in dest_hint.lower():
                return valid
    pid = (parcel_id or '').upper()
    if 'AHM' in pid:
        return 'Ahmedabad'
    elif 'SUR' in pid:
        return 'Surat'
    elif 'RAJ' in pid:
        return 'Rajkot'
    return 'Ahmedabad'


def get_routing_info(destination):
    """Maps destination to conveyor sorting lane, bin number, and diverter servo angle."""
    if destination == 'Ahmedabad':
        return {'lane': 1, 'bin_number': 1, 'servo_angle': 45}
    elif destination == 'Surat':
        return {'lane': 2, 'bin_number': 2, 'servo_angle': 90}
    elif destination == 'Rajkot':
        return {'lane': 3, 'bin_number': 3, 'servo_angle': 135}
    return {'lane': 1, 'bin_number': 1, 'servo_angle': 45}


def process_live_scan(parcel_id, destination=None, qr_code=None, device_id='ESP32-SORT-02'):
    """Records real-time QR scan event, updates parcel status, and pings ESP32-CAM device heartbeat."""
    if not parcel_id:
        return None

    dest = determine_destination(parcel_id, destination)
    routing = get_routing_info(dest)
    qr_token = qr_code or f"QR-{parcel_id}"
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    existing = cur.execute('SELECT * FROM parcels WHERE parcel_id = ?', (parcel_id,)).fetchone()
    if existing:
        cur.execute('''
            UPDATE parcels
            SET status = 'sorting', qr_code = ?, destination = ?, bin_number = ?, updated_at = ?
            WHERE parcel_id = ?
        ''', (qr_token, dest, routing['bin_number'], now_str, parcel_id))
    else:
        cur.execute('''
            INSERT INTO parcels (parcel_id, qr_code, destination, status, bin_number, created_at, updated_at)
            VALUES (?, ?, ?, 'sorting', ?, ?, ?)
        ''', (parcel_id, qr_token, dest, routing['bin_number'], now_str, now_str))

    # Log the scan event
    cur.execute('''
        INSERT INTO sorting_events (parcel_id, event_type, description, device_id, created_at)
        VALUES (?, 'scan', ?, ?, ?)
    ''', (parcel_id, f'QR identified: {parcel_id} routed to {dest} (Lane {routing["lane"]})', device_id, now_str))

    # Update ESP32-CAM device heartbeat to online
    cur.execute('''
        UPDATE devices
        SET status = 'online', last_seen = ?
        WHERE device_id = ? OR device_type = 'esp32' AND name LIKE '%CAM%'
    ''', (now_str, device_id))

    conn.commit()
    conn.close()

    result = {
        'parcel_id': parcel_id,
        'destination': dest,
        'lane': routing['lane'],
        'bin_number': routing['bin_number'],
        'servo_angle': routing['servo_angle'],
        'timestamp': now_str,
        'device_id': device_id
    }

    # If MQTT is connected, publish sorting command to the broker so main ESP32 can actuate servo
    if mqtt_client and mqtt_connected:
        try:
            mqtt_client.publish(MQTT_TOPIC_SORT_CMD, json.dumps(result))
        except Exception as e:
            print(f"[MQTT] Publish sort command error: {e}")

    return result


def on_mqtt_message(client, userdata, msg):
    """Callback for messages arriving on subscribed MQTT topics."""
    try:
        topic = msg.topic
        payload_str = msg.payload.decode('utf-8').strip()
        print(f"[MQTT] Message received on {topic}: {payload_str}")

        if topic == MQTT_TOPIC_SCAN:
            try:
                data = json.loads(payload_str)
                pid = data.get('parcel_id') or data.get('id') or data.get('qr')
                dest = data.get('destination') or data.get('dest')
                dev = data.get('device_id', 'ESP32-SORT-02')
            except Exception:
                pid = payload_str
                dest = None
                dev = 'ESP32-SORT-02'

            if pid:
                process_live_scan(pid, destination=dest, device_id=dev)

        elif topic == MQTT_TOPIC_HEARTBEAT:
            try:
                data = json.loads(payload_str)
                dev_id = data.get('device_id')
                status = data.get('status', 'online')
            except Exception:
                dev_id = payload_str
                status = 'online'

            if dev_id:
                conn = sqlite3.connect(DATABASE)
                now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                conn.execute('UPDATE devices SET status=?, last_seen=? WHERE device_id=?', (status, now_str, dev_id))
                conn.commit()
                conn.close()

        elif topic == MQTT_TOPIC_GPS:
            data = json.loads(payload_str)
            pid = data.get('parcel_id')
            lat = float(data.get('latitude', 0))
            lon = float(data.get('longitude', 0))
            now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if pid and lat and lon:
                conn = sqlite3.connect(DATABASE)
                conn.execute('''
                    INSERT INTO gps_updates (parcel_id, latitude, longitude, timestamp)
                    VALUES (?, ?, ?, ?)
                ''', (pid, lat, lon, now_str))
                conn.execute('''
                    UPDATE parcels SET latitude=?, longitude=?, gps_updated_at=?
                    WHERE parcel_id=?
                ''', (lat, lon, now_str, pid))
                conn.execute('UPDATE devices SET status="online", last_seen=? WHERE device_id="ESP32-SORT-03"', (now_str,))
                conn.commit()
                conn.close()

    except Exception as e:
        print(f"[MQTT] Error processing message: {e}")


def start_mqtt_client():
    """Initializes background MQTT client subscriber connecting to public/local broker."""
    global mqtt_client, mqtt_connected
    if not PAHO_AVAILABLE:
        print("[MQTT] Notice: paho-mqtt not available. Direct HTTP API mode active.")
        return

    try:
        # Use CallbackAPIVersion.VERSION2 for paho-mqtt 2.x compatibility
        try:
            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"ParcelPulse_Server_{uuid.uuid4().hex[:6]}"
            )
        except AttributeError:
            client = mqtt.Client(client_id=f"ParcelPulse_Server_{uuid.uuid4().hex[:6]}")

        def on_connect(c, userdata, flags, rc, properties=None):
            global mqtt_connected
            if rc == 0 or (hasattr(rc, 'value') and rc.value == 0):
                mqtt_connected = True
                print(f"[MQTT] Connected successfully to broker {MQTT_BROKER}:{MQTT_PORT}")
                c.subscribe([
                    (MQTT_TOPIC_SCAN, 0),
                    (MQTT_TOPIC_HEARTBEAT, 0),
                    (MQTT_TOPIC_GPS, 0)
                ])
                print(f"[MQTT] Subscribed to {MQTT_TOPIC_SCAN}, {MQTT_TOPIC_HEARTBEAT}, {MQTT_TOPIC_GPS}")
            else:
                mqtt_connected = False
                print(f"[MQTT] Connection failed with code {rc}")

        def on_disconnect(c, userdata, flags, rc=None, properties=None):
            global mqtt_connected
            mqtt_connected = False
            print("[MQTT] Disconnected from broker.")

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = on_mqtt_message

        client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()
        mqtt_client = client
        print(f"[MQTT] Background client started connecting to {MQTT_BROKER}...")
    except Exception as e:
        print(f"[MQTT] Notice: Could not connect to MQTT broker: {e}")


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
    
    # Count full bins (bins with >= 15 parcels sorted into them)
    full_bins = db.execute(
        "SELECT COUNT(DISTINCT bin_number) FROM parcels WHERE bin_number IS NOT NULL AND status='sorted' GROUP BY bin_number HAVING COUNT(*) >= 15"
    ).fetchall()
    full_bins_count = len(full_bins)
    
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
    
    dest_rows = db.execute(
        'SELECT destination, COUNT(*) as count, SUM(CASE WHEN status="sorted" THEN 1 ELSE 0 END) as sorted_count FROM parcels GROUP BY destination'
    ).fetchall()
    dest_dict = {r['destination']: r for r in dest_rows}
    dest_stats = []
    for d in ['Ahmedabad', 'Surat', 'Rajkot']:
        if d in dest_dict:
            dest_stats.append(dest_dict[d])
        else:
            dest_stats.append({'destination': d, 'count': 0, 'sorted_count': 0})

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
        esp_gps=esp_gps,
        mqtt_connected=mqtt_connected
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

    # Destination lanes detail (Ahmedabad, Surat, Rajkot) - 100% dynamic
    lanes_data = [
        {
            'lane': 1,
            'bin_number': 1,
            'destination': 'Ahmedabad',
            'angle': '45° Left',
            'capacity_max': 15,
            'color': '#00d4ff',
        },
        {
            'lane': 2,
            'bin_number': 2,
            'destination': 'Surat',
            'angle': '90° Straight',
            'capacity_max': 15,
            'color': '#f59e0b',
        },
        {
            'lane': 3,
            'bin_number': 3,
            'destination': 'Rajkot',
            'angle': '135° Right',
            'capacity_max': 15,
            'color': '#10b981',
        }
    ]

    active_bin_alert = None
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
        lane['capacity_current'] = sorted_cnt
        lane['is_full'] = sorted_cnt >= lane['capacity_max']
        lane['status'] = 'Bin Full' if lane['is_full'] else ('Empty' if sorted_cnt == 0 else 'Active')
        
        last_ev = db.execute(
            "SELECT description FROM sorting_events WHERE description LIKE ? ORDER BY created_at DESC LIMIT 1",
            (f"%{lane['destination']}%",)
        ).fetchone()
        lane['last_event'] = last_ev['description'] if last_ev else f"Awaiting sorting to {lane['destination']}"
        
        if lane['is_full']:
            active_bin_alert = {
                'destination': lane['destination'],
                'bin_number': lane['bin_number'],
                'lane': lane['lane'],
                'capacity': f"{sorted_cnt}/{lane['capacity_max']}"
            }

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
        active_bin_alert=active_bin_alert,
        device_events=device_events,
        mqtt_connected=mqtt_connected
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
@app.route('/api/scan', methods=['POST'])
def api_scan():
    """Real-time QR Scan ingestion endpoint for ESP32-CAM via direct HTTP POST."""
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    parcel_id = data.get('parcel_id') or data.get('qr_code') or data.get('id') or data.get('qr')
    if not parcel_id:
        return jsonify({'error': 'parcel_id or qr_code is required'}), 400

    destination = data.get('destination') or data.get('dest')
    device_id = data.get('device_id', 'ESP32-SORT-02')
    qr_code = data.get('qr_code', f"QR-{parcel_id}")

    res = process_live_scan(parcel_id, destination=destination, qr_code=qr_code, device_id=device_id)
    return jsonify({
        'success': True,
        'message': 'QR code scanned and routing assigned',
        'data': res
    }), 200


@app.route('/api/live-status', methods=['GET'])
def api_live_status():
    """Lightweight polling endpoint for live dashboard updates without page reloads."""
    db = get_db()
    total = db.execute('SELECT COUNT(*) FROM parcels').fetchone()[0]
    pending = db.execute("SELECT COUNT(*) FROM parcels WHERE status='pending'").fetchone()[0]
    sorting = db.execute("SELECT COUNT(*) FROM parcels WHERE status='sorting'").fetchone()[0]
    sorted_count = db.execute("SELECT COUNT(*) FROM parcels WHERE status='sorted'").fetchone()[0]
    full_bins = db.execute(
        "SELECT COUNT(DISTINCT bin_number) FROM parcels WHERE bin_number IS NOT NULL AND status='sorted' GROUP BY bin_number HAVING COUNT(*) >= 15"
    ).fetchall()

    last_scan = db.execute(
        "SELECT s.*, p.destination FROM sorting_events s LEFT JOIN parcels p ON s.parcel_id=p.parcel_id WHERE s.event_type IN ('scan', 'error') ORDER BY s.created_at DESC LIMIT 1"
    ).fetchone()

    last_event = db.execute('SELECT * FROM sorting_events ORDER BY created_at DESC LIMIT 1').fetchone()
    recent_events = db.execute('SELECT * FROM sorting_events ORDER BY created_at DESC LIMIT 8').fetchall()
    recent_alerts = db.execute(
        "SELECT * FROM sorting_events WHERE event_type IN ('bin_full', 'error') ORDER BY created_at DESC LIMIT 5"
    ).fetchall()

    esp_main = db.execute("SELECT * FROM devices WHERE device_id='ESP32-SORT-01'").fetchone()
    esp_cam = db.execute("SELECT * FROM devices WHERE device_id='ESP32-SORT-02'").fetchone()
    esp_gps = db.execute("SELECT * FROM devices WHERE device_id='ESP32-SORT-03'").fetchone()

    # Destination lane counts
    lanes = {}
    for d in ['Ahmedabad', 'Surat', 'Rajkot']:
        s_cnt = db.execute("SELECT COUNT(*) FROM parcels WHERE destination=? AND status='sorted'", (d,)).fetchone()[0]
        t_cnt = db.execute("SELECT COUNT(*) FROM parcels WHERE destination=?", (d,)).fetchone()[0]
        lanes[d] = {'sorted': s_cnt, 'total': t_cnt, 'is_full': s_cnt >= 15}

    return jsonify({
        'stats': {
            'total_parcels': total,
            'pending': pending + sorting,
            'sorted': sorted_count,
            'full_bins': len(full_bins),
            'devices_online': db.execute("SELECT COUNT(*) FROM devices WHERE status='online'").fetchone()[0]
        },
        'devices': {
            'esp_main': dict(esp_main) if esp_main else None,
            'esp_cam': dict(esp_cam) if esp_cam else None,
            'esp_gps': dict(esp_gps) if esp_gps else None
        },
        'last_scan': dict(last_scan) if last_scan else None,
        'last_event': dict(last_event) if last_event else None,
        'recent_events': [dict(e) for e in recent_events],
        'recent_alerts': [dict(a) for a in recent_alerts],
        'lanes': lanes,
        'mqtt_connected': mqtt_connected
    })


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
    # Launch background MQTT listener for live ESP32-CAM and sensor telemetry
    start_mqtt_client()
    app.run(host='0.0.0.0', port=5000, debug=True)
