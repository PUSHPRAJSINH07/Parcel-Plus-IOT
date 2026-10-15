// ==========================================================================
// ParcelPulse IoT — Client Application Logic
// ==========================================================================

// --- Mobile Navigation Drawer Toggle ---
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    if (sidebar) sidebar.classList.toggle('open');
    if (overlay) overlay.classList.toggle('open');
}

// --- Parcel Registration Modal Lifecycle ---
function openModal() {
    const modal = document.getElementById('register-modal');
    if (modal) modal.classList.add('show');
}

function closeModal() {
    const modal = document.getElementById('register-modal');
    const errEl = document.getElementById('form-error');
    if (modal) modal.classList.remove('show');
    if (errEl) {
        errEl.classList.remove('show');
        errEl.textContent = '';
    }
}

async function registerParcel(event) {
    event.preventDefault();
    const form = event.target;
    
    // NOTE: Weight is completely removed due to load-cell unavailability
    const data = {
        parcel_id: form.parcel_id.value.trim(),
        qr_code: form.qr_code.value.trim() || undefined,
        destination: form.destination.value
    };

    if (!data.parcel_id || !data.destination) {
        showFormError('Parcel ID and Destination are required fields.');
        return;
    }

    try {
        const res = await fetch('/api/parcels', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await res.json();
        if (res.ok) {
            closeModal();
            window.location.reload();
        } else {
            showFormError(result.error || 'Failed to register parcel. Check inputs.');
        }
    } catch (err) {
        showFormError('Network communication error with backend server.');
    }
}

function showFormError(msg) {
    const el = document.getElementById('form-error');
    if (el) {
        el.textContent = msg;
        el.classList.add('show');
    }
}

// --- Client-Side Table Filtering Helper ---
function filterTable(tableId, filters) {
    const table = document.getElementById(tableId);
    if (!table) return;
    const rows = table.querySelectorAll('tbody tr');
    rows.forEach(row => {
        let show = true;
        for (const [colIndex, value] of Object.entries(filters)) {
            if (value && value !== 'all') {
                const cell = row.children[parseInt(colIndex)];
                if (cell) {
                    const cellText = cell.textContent.toLowerCase();
                    if (!cellText.includes(value.toLowerCase())) {
                        show = false;
                        break;
                    }
                }
            }
        }
        row.style.display = show ? '' : 'none';
    });
}

// --- Document Lifecycle Listeners ---
document.addEventListener('DOMContentLoaded', function() {
    // Close sidebar on mobile when navigating
    document.querySelectorAll('.nav-links a').forEach(link => {
        link.addEventListener('click', () => {
            const sidebar = document.getElementById('sidebar');
            const overlay = document.getElementById('sidebar-overlay');
            if (sidebar) sidebar.classList.remove('open');
            if (overlay) overlay.classList.remove('open');
        });
    });
    
    // Close modal when clicking on overlay background
    const overlay = document.getElementById('register-modal');
    if (overlay) {
        overlay.addEventListener('click', function(e) {
            if (e.target === this) closeModal();
        });
    }

    // Escape key to close modal
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') closeModal();
    });
});
