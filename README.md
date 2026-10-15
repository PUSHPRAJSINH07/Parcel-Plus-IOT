# ParcelPulse IoT — Smart Parcel Sorting & Live Tracking System

A complete Flask + SQLite web application for IoT-based parcel sorting with live GPS tracking, device monitoring, and full REST API.

---

## Quick Start

### Prerequisites
- Python 3.10+
- pip

### Install & Run

```bash
cd "Parcel Plus IOT"
pip install -r requirements.txt
python app.py
```

Open **http://localhost:5000** in your browser.

The application creates `parcelpulse.db` automatically on first run and seeds it with 12 demo parcels, 8 IoT devices, and 15+ sorting events.

---

## Pages

| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/` | Live stats: total parcels, pending, sorted, full bins, device status |
| Live Tracking | `/tracking` | Interactive Leaflet/OpenStreetMap with GPS markers |
| Parcels | `/parcels` | Register, search, filter parcels with modal form |
| Sorting & Devices | `/devices` | ESP32 nodes, conveyor, motor, servo, IR sensor status |
| History & Alerts | `/history` | Sorting events, bin-full alerts, errors log |

---

## REST API Reference

### Public Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/dashboard` | Dashboard statistics |
| `GET` | `/api/parcels` | List all parcels |
| `POST` | `/api/parcels` | Register a new parcel |
| `GET` | `/api/parcels/<parcel_id>` | Get single parcel |
| `GET` | `/api/gps/<parcel_id>` | Get GPS coordinates |
| `GET` | `/api/sorting-events` | List sorting events |
| `GET` | `/api/devices` | List all devices |

### Protected Endpoints (require `X-API-Key` header)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/gps` | Update GPS coordinates |
| `POST` | `/api/sorting-events` | Log a sorting event |
| `POST` | `/api/devices` | Update device status |

**API Key:** `parcelpulse-device-key-2026`
**Header:** `X-API-Key: parcelpulse-device-key-2026`

### Example API Calls

#### Register a parcel
```bash
curl -X POST http://localhost:5000/api/parcels \
  -H "Content-Type: application/json" \
  -d '{"parcel_id": "PKG-1001", "destination": "Ahmedabad"}'
```

#### Update GPS coordinates (authenticated)
```bash
curl -X POST http://localhost:5000/api/gps \
  -H "Content-Type: application/json" \
  -H "X-API-Key: parcelpulse-device-key-2026" \
  -d '{"parcel_id": "PKG-1001", "latitude": 23.0225, "longitude": 72.5714}'
```

#### Log a sorting event (authenticated)
```bash
curl -X POST http://localhost:5000/api/sorting-events \
  -H "Content-Type: application/json" \
  -H "X-API-Key: parcelpulse-device-key-2026" \
  -d '{"parcel_id": "PKG-1001", "event_type": "sorted", "description": "Sorted to Bin 1", "device_id": "ESP32-SORT-01"}'
```

### Valid Destinations
- `Ahmedabad`
- `Surat`
- `Rajkot`

### Event Types
- `scan` — Parcel scanned at entry
- `sorted` — Parcel sorted into a bin
- `bin_full` — Destination bin is full
- `error` — Scan or sorting error
- `parcel_registered` — New parcel registered

---

## Database

SQLite database (`parcelpulse.db`) with 4 tables:

- **parcels** — Parcel records with GPS coordinates
- **sorting_events** — Sorting/scan event history log
- **devices** — IoT device registry and status
- **gps_updates** — GPS coordinate history

Data persists across restarts. Delete `parcelpulse.db` to reset and re-seed demo data.

---

## Deployment

### Local Network Access
The server binds to `0.0.0.0:5000`, so any device on your local network can access it via your IP address (e.g., `http://192.168.1.x:5000`).

### Public URL via ngrok
```bash
# Install ngrok: https://ngrok.com/download
ngrok http 5000
```
This gives you a public URL like `https://xxxx.ngrok-free.app` that your ESP32 devices can reach.

### Production Deployment
For production, use a WSGI server:
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

---

## Connecting Real Hardware

1. Replace demo GPS coordinates by sending `POST /api/gps` from your ESP32 with real sensor data.
2. Update device heartbeats via `POST /api/devices` to keep statuses current.
3. Log sorting events in real-time via `POST /api/sorting-events`.
4. The live tracking map auto-refreshes every 5 seconds — no code changes needed.

---

## Tech Stack

- **Backend:** Python 3, Flask 3.x, SQLite3
- **Frontend:** Jinja2 templates, vanilla JavaScript
- **Map:** Leaflet.js + OpenStreetMap
- **Icons:** Font Awesome 6
- **Styling:** Custom CSS (responsive, mobile-first)

---

## Project Structure

```
Parcel Plus IOT/
├── app.py              # Flask app (routes, APIs, database, seed data)
├── requirements.txt    # Python dependencies
├── parcelpulse.db      # SQLite database (auto-created)
├── templates/
│   ├── base.html       # Base layout with sidebar
│   ├── dashboard.html  # Dashboard page
│   ├── tracking.html   # Live GPS tracking page
│   ├── parcels.html    # Parcel management page
│   ├── devices.html    # Sorting & devices page
│   └── history.html    # History & alerts page
├── static/
│   ├── css/
│   │   └── style.css   # Complete responsive stylesheet
│   └── js/
│       ├── app.js      # General app JavaScript
│       └── map.js      # Leaflet map integration
└── README.md
```
