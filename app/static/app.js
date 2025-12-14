// Tab management
function showTab(tabId) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    document.querySelectorAll('.nav-tab').forEach(btn => {
        btn.classList.remove('active');
    });

    // Show selected tab
    document.getElementById(tabId).classList.add('active');
    document.querySelector(`[data-tab="${tabId}"]`).classList.add('active');

    // Load tab data
    loadTabData(tabId);
}

// Load data for specific tab
async function loadTabData(tabId) {
    switch (tabId) {
        case 'dashboard-tab':
            await loadDashboard();
            break;
        case 'instances-tab':
            await loadInstances();
            break;
        case 'pairs-tab':
            await loadProjectPairs();
            break;
        case 'mappings-tab':
            await loadUserMappings();
            break;
        case 'logs-tab':
            await loadSyncLogs();
            break;
        case 'conflicts-tab':
            await loadConflicts();
            break;
    }
}

// Dashboard
async function loadDashboard() {
    try {
        const response = await fetch('/api/dashboard/stats');
        const data = await response.json();

        // Update stats
        document.getElementById('total-pairs').textContent = data.total_pairs;
        document.getElementById('active-pairs').textContent = data.active_pairs;
        document.getElementById('synced-issues').textContent = data.total_synced_issues;
        document.getElementById('unresolved-conflicts').textContent = data.unresolved_conflicts;

        // Update project pairs table
        const tbody = document.getElementById('pairs-status-tbody');
        tbody.innerHTML = '';

        data.pair_stats.forEach(pair => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${pair.name}</td>
                <td>
                    <span class="badge ${pair.sync_enabled ? 'badge-success' : 'badge-secondary'}">
                        ${pair.sync_enabled ? 'Enabled' : 'Disabled'}
                    </span>
                </td>
                <td>
                    <span class="badge ${pair.bidirectional ? 'badge-info' : 'badge-secondary'}">
                        ${pair.bidirectional ? 'Bi-directional' : 'One-way'}
                    </span>
                </td>
                <td>${pair.synced_issues}</td>
                <td>${pair.unresolved_conflicts}</td>
                <td>${pair.last_sync_at ? new Date(pair.last_sync_at).toLocaleString() : 'Never'}</td>
                <td>
                    ${pair.last_status ? `<span class="badge badge-${pair.last_status === 'success' ? 'success' : 'danger'}">${pair.last_status}</span>` : '-'}
                </td>
                <td>
                    <button class="btn btn-primary btn-sm" onclick="triggerSync(${pair.id})">Sync Now</button>
                </td>
            `;
            tbody.appendChild(row);
        });

        // Load recent activity
        const activityResponse = await fetch('/api/dashboard/activity?limit=20');
        const activity = await activityResponse.json();

        const activityDiv = document.getElementById('recent-activity');
        activityDiv.innerHTML = '';

        activity.forEach(log => {
            const item = document.createElement('div');
            item.className = `activity-item ${log.status}`;
            item.innerHTML = `
                <div class="activity-time">${new Date(log.created_at).toLocaleString()}</div>
                <div><strong>Status:</strong> <span class="badge badge-${log.status === 'success' ? 'success' : 'danger'}">${log.status}</span></div>
                ${log.message ? `<div>${log.message}</div>` : ''}
                ${log.direction ? `<div><strong>Direction:</strong> ${log.direction}</div>` : ''}
            `;
            activityDiv.appendChild(item);
        });

    } catch (error) {
        console.error('Failed to load dashboard:', error);
        showAlert('Failed to load dashboard data', 'error');
    }
}

// GitLab Instances
async function loadInstances() {
    try {
        const response = await fetch('/api/instances/');
        const instances = await response.json();

        const tbody = document.getElementById('instances-tbody');
        tbody.innerHTML = '';

        instances.forEach(instance => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${instance.name}</td>
                <td>${instance.url}</td>
                <td>${instance.description || '-'}</td>
                <td>${new Date(instance.created_at).toLocaleDateString()}</td>
                <td>
                    <button class="btn btn-danger btn-sm" onclick="deleteInstance(${instance.id})">Delete</button>
                </td>
            `;
            tbody.appendChild(row);
        });
    } catch (error) {
        console.error('Failed to load instances:', error);
        showAlert('Failed to load instances', 'error');
    }
}

async function createInstance(event) {
    event.preventDefault();
    const formData = new FormData(event.target);

    const data = {
        name: formData.get('name'),
        url: formData.get('url'),
        access_token: formData.get('access_token'),
        description: formData.get('description')
    };

    try {
        const response = await fetch('/api/instances/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (response.ok) {
            showAlert('Instance created successfully', 'success');
            event.target.reset();
            await loadInstances();
        } else {
            const error = await response.json();
            showAlert(error.detail || 'Failed to create instance', 'error');
        }
    } catch (error) {
        console.error('Failed to create instance:', error);
        showAlert('Failed to create instance', 'error');
    }
}

async function deleteInstance(instanceId) {
    if (!confirm('Are you sure you want to delete this instance?')) return;

    try {
        const response = await fetch(`/api/instances/${instanceId}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            showAlert('Instance deleted successfully', 'success');
            await loadInstances();
        } else {
            showAlert('Failed to delete instance', 'error');
        }
    } catch (error) {
        console.error('Failed to delete instance:', error);
        showAlert('Failed to delete instance', 'error');
    }
}

// Project Pairs
async function loadProjectPairs() {
    try {
        const [pairsResponse, instancesResponse] = await Promise.all([
            fetch('/api/project-pairs/'),
            fetch('/api/instances/')
        ]);

        const pairs = await pairsResponse.json();
        const instances = await instancesResponse.json();

        // Update form dropdowns
        const sourceSelect = document.getElementById('source-instance');
        const targetSelect = document.getElementById('target-instance');

        [sourceSelect, targetSelect].forEach(select => {
            select.innerHTML = '<option value="">Select instance...</option>';
            instances.forEach(instance => {
                const option = document.createElement('option');
                option.value = instance.id;
                option.textContent = instance.name;
                select.appendChild(option);
            });
        });

        // Update table
        const tbody = document.getElementById('pairs-tbody');
        tbody.innerHTML = '';

        pairs.forEach(pair => {
            const row = document.createElement('tr');
            const sourceInst = instances.find(i => i.id === pair.source_instance_id);
            const targetInst = instances.find(i => i.id === pair.target_instance_id);

            row.innerHTML = `
                <td>${pair.name}</td>
                <td>${sourceInst ? sourceInst.name : 'Unknown'} / ${pair.source_project_id}</td>
                <td>${targetInst ? targetInst.name : 'Unknown'} / ${pair.target_project_id}</td>
                <td>
                    <span class="badge ${pair.bidirectional ? 'badge-info' : 'badge-secondary'}">
                        ${pair.bidirectional ? 'Bi-directional' : 'One-way'}
                    </span>
                </td>
                <td>
                    <span class="badge ${pair.sync_enabled ? 'badge-success' : 'badge-secondary'}">
                        ${pair.sync_enabled ? 'Enabled' : 'Disabled'}
                    </span>
                </td>
                <td>${pair.sync_interval_minutes} min</td>
                <td>
                    <button class="btn btn-warning btn-sm" onclick="togglePairSync(${pair.id})">Toggle</button>
                    <button class="btn btn-primary btn-sm" onclick="triggerSync(${pair.id})">Sync</button>
                    <button class="btn btn-danger btn-sm" onclick="deletePair(${pair.id})">Delete</button>
                </td>
            `;
            tbody.appendChild(row);
        });
    } catch (error) {
        console.error('Failed to load project pairs:', error);
        showAlert('Failed to load project pairs', 'error');
    }
}

async function createProjectPair(event) {
    event.preventDefault();
    const formData = new FormData(event.target);

    const data = {
        name: formData.get('name'),
        source_instance_id: parseInt(formData.get('source_instance_id')),
        source_project_id: formData.get('source_project_id'),
        target_instance_id: parseInt(formData.get('target_instance_id')),
        target_project_id: formData.get('target_project_id'),
        bidirectional: formData.get('bidirectional') === 'on',
        sync_enabled: formData.get('sync_enabled') === 'on',
        sync_interval_minutes: parseInt(formData.get('sync_interval_minutes'))
    };

    try {
        const response = await fetch('/api/project-pairs/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (response.ok) {
            showAlert('Project pair created successfully', 'success');
            event.target.reset();
            await loadProjectPairs();
        } else {
            const error = await response.json();
            showAlert(error.detail || 'Failed to create project pair', 'error');
        }
    } catch (error) {
        console.error('Failed to create project pair:', error);
        showAlert('Failed to create project pair', 'error');
    }
}

async function togglePairSync(pairId) {
    try {
        const response = await fetch(`/api/project-pairs/${pairId}/toggle`, {
            method: 'POST'
        });

        if (response.ok) {
            showAlert('Sync status toggled successfully', 'success');
            await loadProjectPairs();
        } else {
            showAlert('Failed to toggle sync status', 'error');
        }
    } catch (error) {
        console.error('Failed to toggle sync:', error);
        showAlert('Failed to toggle sync status', 'error');
    }
}

async function deletePair(pairId) {
    if (!confirm('Are you sure you want to delete this project pair?')) return;

    try {
        const response = await fetch(`/api/project-pairs/${pairId}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            showAlert('Project pair deleted successfully', 'success');
            await loadProjectPairs();
        } else {
            showAlert('Failed to delete project pair', 'error');
        }
    } catch (error) {
        console.error('Failed to delete pair:', error);
        showAlert('Failed to delete project pair', 'error');
    }
}

async function triggerSync(pairId) {
    try {
        showAlert('Triggering sync...', 'info');
        const response = await fetch(`/api/sync/${pairId}/trigger`, {
            method: 'POST'
        });

        if (response.ok) {
            const result = await response.json();
            showAlert(`Sync completed: ${JSON.stringify(result.stats)}`, 'success');
            await loadDashboard();
        } else {
            const error = await response.json();
            showAlert(error.detail || 'Sync failed', 'error');
        }
    } catch (error) {
        console.error('Failed to trigger sync:', error);
        showAlert('Failed to trigger sync', 'error');
    }
}

// User Mappings
async function loadUserMappings() {
    try {
        const [mappingsResponse, instancesResponse] = await Promise.all([
            fetch('/api/user-mappings/'),
            fetch('/api/instances/')
        ]);

        const mappings = await mappingsResponse.json();
        const instances = await instancesResponse.json();

        // Update form dropdowns
        const sourceMappingSelect = document.getElementById('source-mapping-instance');
        const targetMappingSelect = document.getElementById('target-mapping-instance');

        [sourceMappingSelect, targetMappingSelect].forEach(select => {
            select.innerHTML = '<option value="">Select instance...</option>';
            instances.forEach(instance => {
                const option = document.createElement('option');
                option.value = instance.id;
                option.textContent = instance.name;
                select.appendChild(option);
            });
        });

        // Update table
        const tbody = document.getElementById('mappings-tbody');
        tbody.innerHTML = '';

        mappings.forEach(mapping => {
            const row = document.createElement('tr');
            const sourceInst = instances.find(i => i.id === mapping.source_instance_id);
            const targetInst = instances.find(i => i.id === mapping.target_instance_id);

            row.innerHTML = `
                <td>${sourceInst ? sourceInst.name : 'Unknown'}</td>
                <td>${mapping.source_username}</td>
                <td>${targetInst ? targetInst.name : 'Unknown'}</td>
                <td>${mapping.target_username}</td>
                <td>
                    <button class="btn btn-danger btn-sm" onclick="deleteMapping(${mapping.id})">Delete</button>
                </td>
            `;
            tbody.appendChild(row);
        });
    } catch (error) {
        console.error('Failed to load user mappings:', error);
        showAlert('Failed to load user mappings', 'error');
    }
}

async function createUserMapping(event) {
    event.preventDefault();
    const formData = new FormData(event.target);

    const data = {
        source_instance_id: parseInt(formData.get('source_instance_id')),
        source_username: formData.get('source_username'),
        target_instance_id: parseInt(formData.get('target_instance_id')),
        target_username: formData.get('target_username')
    };

    try {
        const response = await fetch('/api/user-mappings/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (response.ok) {
            showAlert('User mapping created successfully', 'success');
            event.target.reset();
            await loadUserMappings();
        } else {
            const error = await response.json();
            showAlert(error.detail || 'Failed to create user mapping', 'error');
        }
    } catch (error) {
        console.error('Failed to create user mapping:', error);
        showAlert('Failed to create user mapping', 'error');
    }
}

async function deleteMapping(mappingId) {
    if (!confirm('Are you sure you want to delete this user mapping?')) return;

    try {
        const response = await fetch(`/api/user-mappings/${mappingId}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            showAlert('User mapping deleted successfully', 'success');
            await loadUserMappings();
        } else {
            showAlert('Failed to delete user mapping', 'error');
        }
    } catch (error) {
        console.error('Failed to delete mapping:', error);
        showAlert('Failed to delete user mapping', 'error');
    }
}

// Sync Logs
async function loadSyncLogs() {
    try {
        const response = await fetch('/api/sync/logs?limit=100');
        const logs = await response.json();

        const tbody = document.getElementById('logs-tbody');
        tbody.innerHTML = '';

        logs.forEach(log => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${new Date(log.created_at).toLocaleString()}</td>
                <td>Pair ${log.project_pair_id}</td>
                <td>
                    <span class="badge badge-${log.status === 'success' ? 'success' : log.status === 'failed' ? 'danger' : 'warning'}">
                        ${log.status}
                    </span>
                </td>
                <td>${log.direction || '-'}</td>
                <td>${log.source_issue_iid || '-'}</td>
                <td>${log.target_issue_iid || '-'}</td>
                <td>${log.message || '-'}</td>
            `;
            tbody.appendChild(row);
        });
    } catch (error) {
        console.error('Failed to load sync logs:', error);
        showAlert('Failed to load sync logs', 'error');
    }
}

// Conflicts
async function loadConflicts() {
    try {
        const response = await fetch('/api/sync/conflicts');
        const conflicts = await response.json();

        const tbody = document.getElementById('conflicts-tbody');
        tbody.innerHTML = '';

        if (conflicts.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No conflicts found</td></tr>';
            return;
        }

        conflicts.forEach(conflict => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${new Date(conflict.created_at).toLocaleString()}</td>
                <td>Pair ${conflict.project_pair_id}</td>
                <td>${conflict.source_issue_iid}</td>
                <td>${conflict.target_issue_iid || '-'}</td>
                <td>${conflict.conflict_type}</td>
                <td>
                    <span class="badge ${conflict.resolved ? 'badge-success' : 'badge-danger'}">
                        ${conflict.resolved ? 'Resolved' : 'Unresolved'}
                    </span>
                </td>
                <td>
                    ${!conflict.resolved ? `<button class="btn btn-success btn-sm" onclick="resolveConflict(${conflict.id})">Resolve</button>` : '-'}
                </td>
            `;
            tbody.appendChild(row);
        });
    } catch (error) {
        console.error('Failed to load conflicts:', error);
        showAlert('Failed to load conflicts', 'error');
    }
}

async function resolveConflict(conflictId) {
    const notes = prompt('Enter resolution notes (optional):');

    try {
        const response = await fetch(`/api/sync/conflicts/${conflictId}/resolve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ resolution_notes: notes })
        });

        if (response.ok) {
            showAlert('Conflict marked as resolved', 'success');
            await loadConflicts();
        } else {
            showAlert('Failed to resolve conflict', 'error');
        }
    } catch (error) {
        console.error('Failed to resolve conflict:', error);
        showAlert('Failed to resolve conflict', 'error');
    }
}

// Utility functions
function showAlert(message, type) {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type}`;
    alertDiv.textContent = message;

    const container = document.querySelector('.container');
    container.insertBefore(alertDiv, container.firstChild);

    setTimeout(() => {
        alertDiv.remove();
    }, 5000);
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    showTab('dashboard-tab');

    // Set up form handlers
    document.getElementById('instance-form').addEventListener('submit', createInstance);
    document.getElementById('pair-form').addEventListener('submit', createProjectPair);
    document.getElementById('mapping-form').addEventListener('submit', createUserMapping);

    // Refresh dashboard every 30 seconds
    setInterval(() => {
        const activeTab = document.querySelector('.tab-content.active');
        if (activeTab && activeTab.id === 'dashboard-tab') {
            loadDashboard();
        }
    }, 30000);
});
