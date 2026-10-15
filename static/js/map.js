// ==========================================================================
// ParcelPulse IoT — Leaflet Map & GPS Live Tracking Integration
// ==========================================================================

let map;
let markers = {};
let selectedParcelId = null;
let refreshInterval = null;

// Clean regional destination colors
const destColors = {
    'Ahmedabad': '#00d4ff',
    'Surat': '#f59e0b',
    'Rajkot': '#10b981'
};

function initMap(parcelsData) {
    // Center view on Gujarat logistics triangle with calibrated zoom sensitivity
    map = L.map('map', {
        zoomSnap: 0.5,             // Smooth half-step zoom intervals instead of jarring jumps
        zoomDelta: 0.5,            // 0.5 step per zoom command
        wheelPxPerZoomLevel: 160,  // Calibrated threshold to prevent 2x/3x skipping on touchpads and wheels
        wheelDebounceTime: 80,     // Debounce rapid wheel/touchpad gesture bursts
        touchZoom: true,           // Responsive smooth pinch-to-zoom on touch screens
        bounceAtZoomLimits: false  // Eliminate rubber-band bounce
    }).setView([22.3, 71.8], 7.5);
    
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19
    }).addTo(map);
    
    // Add custom styled circular markers
    parcelsData.forEach(p => {
        if (p.latitude && p.longitude) {
            const color = destColors[p.destination] || '#00d4ff';
            
            const marker = L.circleMarker([p.latitude, p.longitude], {
                radius: 9,
                fillColor: color,
                color: '#ffffff',
                weight: 2.5,
                opacity: 1,
                fillOpacity: 0.9
            }).addTo(map);
            
            const popupContent = `
                <div style="font-family: system-ui, sans-serif; font-size: 0.85rem; line-height: 1.4; padding: 2px;">
                    <div style="font-weight: 700; color: #0f172a; font-size: 0.95rem; margin-bottom: 2px;">${p.parcel_id}</div>
                    <div style="color: #475569;">Destination: <strong>${p.destination}</strong></div>
                    <div style="color: #475569;">Status: <span style="text-transform: capitalize; font-weight: 600;">${p.status}</span></div>
                    <div style="margin-top: 4px; font-size: 0.72rem; color: #64748b; font-style: italic;">Demonstration coordinates</div>
                </div>
            `;
            marker.bindPopup(popupContent);
            
            marker.on('click', () => selectParcel(p.parcel_id));
            markers[p.parcel_id] = { marker, data: p };
        }
    });
}

function selectParcel(parcelId) {
    selectedParcelId = parcelId;
    
    // Update dropdown in panel
    const sel = document.getElementById('parcel-select');
    if (sel && sel.value !== parcelId) sel.value = parcelId;
    
    // Update panel metrics
    updateParcelDetail(parcelId);
    
    // Pan smoothly to marker and open popup
    if (markers[parcelId]) {
        const m = markers[parcelId];
        map.setView([m.data.latitude, m.data.longitude], 10, { animate: true });
        m.marker.openPopup();
    }
    
    // Start or reset 5-second automatic coordinate polling
    if (refreshInterval) clearInterval(refreshInterval);
    refreshInterval = setInterval(() => refreshParcelGPS(parcelId), 5000);
}

async function refreshParcelGPS(parcelId) {
    try {
        const res = await fetch(`/api/gps/${parcelId}`);
        if (!res.ok) return;
        const data = await res.json();
        
        if (data.latitude && data.longitude && markers[parcelId]) {
            markers[parcelId].marker.setLatLng([data.latitude, data.longitude]);
            markers[parcelId].data.latitude = data.latitude;
            markers[parcelId].data.longitude = data.longitude;
            markers[parcelId].data.gps_updated_at = data.gps_updated_at;
        }
        
        updateParcelDetailFromData(data);
    } catch (err) {
        console.warn('GPS refresh polling network notice:', err);
    }
}

function updateParcelDetail(parcelId) {
    if (markers[parcelId]) {
        const d = markers[parcelId].data;
        updateParcelDetailFromData(d);
    }
}

function updateParcelDetailFromData(data) {
    setDetail('detail-parcel-id', data.parcel_id || selectedParcelId);
    setDetail('detail-destination', data.destination || '-');
    setDetail('detail-status', data.status ? data.status.toUpperCase() : '-');
    setDetail('detail-lat', data.latitude ? data.latitude.toFixed(6) : '-');
    setDetail('detail-lng', data.longitude ? data.longitude.toFixed(6) : '-');
    setDetail('detail-updated', data.gps_updated_at || 'Just now');
}

function setDetail(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

// Handlers called from template
function onParcelSelectChange(parcelId) {
    if (parcelId) selectParcel(parcelId);
}
