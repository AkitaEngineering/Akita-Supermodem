document.addEventListener('DOMContentLoaded', () => {
    const navItems = document.querySelectorAll('.nav-item');
    const tabContents = document.querySelectorAll('.tab-content');
    const settingsForm = document.getElementById('settings-form');
    const transferForm = document.getElementById('transfer-form');
    const meshDot = document.getElementById('mesh-dot');
    const meshStatus = document.getElementById('mesh-status');

    function activateTab(targetId) {
        navItems.forEach(nav => nav.classList.toggle('active', nav.getAttribute('data-tab') === targetId));
        tabContents.forEach(tab => tab.classList.toggle('active', tab.id === `tab-${targetId}`));
    }

    function formatBytes(bytes) {
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        let value = Number(bytes || 0);
        let unit = 0;
        while (value >= 1024 && unit < units.length - 1) {
            value /= 1024;
            unit += 1;
        }
        return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
    }

    function escapeHtml(value) {
        return String(value || '').replace(/[&<>"']/g, character => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[character]));
    }

    async function api(path, options = {}) {
        const response = await fetch(path, options);
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Request failed.');
        }
        return data;
    }

    async function loadConfig() {
        try {
            const data = await api('/api/config');
            document.getElementById('default_mesh_node').value = data.default_mesh_node || '';
            document.getElementById('default_profile').value = data.default_profile || 'meshtastic';
            document.getElementById('ui_port').value = data.ui_port || 8080;
            document.getElementById('transfer_recipient').value = data.default_mesh_node || '';
        } catch (error) {
            showToast(error.message, true);
        }
    }

    function transferProgress(transfer) {
        const total = transfer.num_pieces || 0;
        if (transfer.direction === 'send') {
            return `${transfer.acknowledged_pieces || 0}/${total} acknowledged`;
        }
        return `${transfer.received_pieces || 0}/${total} received`;
    }

    function completedBytes(transfer, key) {
        const pieces = transfer[key] || 0;
        const pieceSize = transfer.piece_size || 0;
        if (transfer.complete) {
            return transfer.total_size || 0;
        }
        return Math.min(transfer.total_size || 0, pieces * pieceSize);
    }

    function renderTransfers(transfers) {
        const activityList = document.getElementById('activity-list');
        const transferList = document.getElementById('transfer-list');
        const activityEmpty = document.getElementById('activity-empty');
        const transferEmpty = document.getElementById('transfer-empty');
        const rows = transfers.map(transfer => {
            const filename = escapeHtml(transfer.filename || 'Unnamed transfer');
            const direction = escapeHtml(transfer.direction);
            const peer = escapeHtml(transfer.peer || 'unknown peer');
            return `
            <div class="transfer-row">
                <div>
                    <div class="transfer-name">${filename}</div>
                    <div class="transfer-meta">${direction} with ${peer}</div>
                </div>
                <div class="transfer-meta">${formatBytes(transfer.total_size)}</div>
                <div class="transfer-progress">${transfer.complete ? 'Complete' : transferProgress(transfer)}</div>
            </div>
        `;
        }).join('');

        activityList.innerHTML = rows;
        transferList.innerHTML = rows;
        activityEmpty.style.display = transfers.length ? 'none' : 'block';
        transferEmpty.style.display = transfers.length ? 'none' : 'block';
    }

    async function refreshStatus() {
        try {
            const data = await api('/api/status');
            const transfers = data.transfers || [];
            const connected = data.mesh && data.mesh.connected;
            meshDot.classList.toggle('online', connected);
            meshDot.classList.toggle('pulse-red', !connected);
            meshStatus.textContent = connected ? `Mesh Online (${data.mesh.device || 'auto'})` : 'Mesh Offline';

            document.getElementById('stat-active-transfers').textContent = transfers.filter(t => !t.complete).length;
            document.getElementById('stat-bytes-sent').textContent = formatBytes(
                transfers.filter(t => t.direction === 'send').reduce((sum, t) => sum + completedBytes(t, 'sent_pieces'), 0)
            );
            document.getElementById('stat-bytes-received').textContent = formatBytes(
                transfers.filter(t => t.direction === 'receive').reduce((sum, t) => sum + completedBytes(t, 'received_pieces'), 0)
            );
            renderTransfers(transfers);
        } catch (error) {
            showToast(error.message, true);
        }
    }

    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            activateTab(item.getAttribute('data-tab'));
        });
    });

    document.getElementById('btn-new-transfer').addEventListener('click', () => {
        activateTab('transfers');
        document.getElementById('transfer_filepath').focus();
    });

    document.getElementById('btn-connect').addEventListener('click', async () => {
        try {
            await api('/api/mesh/connect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });
            showToast('Mesh connected.');
            refreshStatus();
        } catch (error) {
            showToast(error.message, true);
        }
    });

    document.getElementById('btn-disconnect').addEventListener('click', async () => {
        try {
            await api('/api/mesh/disconnect', { method: 'POST' });
            showToast('Mesh disconnected.');
            refreshStatus();
        } catch (error) {
            showToast(error.message, true);
        }
    });

    settingsForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const inputs = ['default_mesh_node', 'default_profile', 'ui_port'];
        try {
            await Promise.all(inputs.map(id => {
                const value = document.getElementById(id).value;
                return api('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key: id, value })
                });
            }));
            showToast('Settings saved successfully.');
            loadConfig();
        } catch (error) {
            showToast(error.message, true);
        }
    });

    transferForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const pieceSize = document.getElementById('transfer_piece_size').value;
        try {
            await api('/api/transfers/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    recipient_id: document.getElementById('transfer_recipient').value,
                    filepath: document.getElementById('transfer_filepath').value,
                    piece_size: pieceSize ? Number(pieceSize) : null
                })
            });
            showToast('Transfer started.');
            refreshStatus();
        } catch (error) {
            showToast(error.message, true);
        }
    });

    function showToast(message, isError=false) {
        const toast = document.getElementById('toast');
        toast.textContent = message;
        if(isError) toast.style.backgroundColor = 'var(--color-red)';
        else toast.style.backgroundColor = 'var(--color-white)';
        
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 3000);
    }

    loadConfig();
    refreshStatus();
    setInterval(refreshStatus, 5000);
});
