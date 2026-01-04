// AI Orchestrator Web Viewer - Frontend Application

// State
let ws = null;
let currentView = 'dashboard';
const storedProjectId = window.localStorage.getItem('selectedProjectId');
let selectedProject = storedProjectId || null;
let selectedTask = null;
let memorySearchTerm = '';
let projectTracking = {};
let availableModels = [];
let projectsCache = [];
let selectedTaskDetails = null;
let trackingErrorMessage = '';
let lastTrackingErrorAt = 0;
const TRACKING_ERROR_COOLDOWN_MS = 15000;
const TASK_STATUSES = [
    { value: 'todo', label: 'Todo' },
    { value: 'in_progress', label: 'In Progress' },
    { value: 'blocked', label: 'Blocked' },
    { value: 'done', label: 'Done' },
    { value: 'archived', label: 'Archived' },
];
const DEFAULT_ACTIVE_STATUSES = ['todo', 'in_progress', 'blocked'];
let activeTaskStatuses = new Set(DEFAULT_ACTIVE_STATUSES);
const logViewerSettings = {
    minLevel: 'INFO',
    includeAccess: false,
    autoRefresh: true,
};
const UI_EVENT_ENDPOINT = '/api/telemetry/ui-event';

function logUiEvent(eventType, details = {}) {
    const payload = {
        event: eventType,
        details,
        view: currentView,
        timestamp: new Date().toISOString(),
    };
    fetch(UI_EVENT_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        keepalive: true,
    }).catch((error) => {
        console.warn('Failed to log UI event', eventType, error);
    });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    initializeNavigation();
    initializeWebSocket();
    loadDashboard();
    setupModelControls();
    setupManualTaskForm();
    setupMemoryControls();
    setupProjectCreation();
    initializeTrackingControls();
    initializeLogViewerControls();
    initializeTrackingForm();
    initializeTaskDetailForm();
    initializeTaskToolbar();
    initializeStatusFilters();

    // Refresh data every 5 seconds
    setInterval(refreshCurrentView, 5000);
});

// Navigation
function initializeNavigation() {
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const view = e.target.dataset.view;
            logUiEvent('nav_click', { view });
            switchView(view, 'user');
        });
    });
}

function switchView(view, reason = 'user') {
    if (currentView === view) {
        return;
    }
    const previousView = currentView;

    // Update nav buttons
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.view === view);
    });

    // Update views
    document.querySelectorAll('.view').forEach(v => {
        v.classList.toggle('active', v.id === `${view}-view`);
    });

    currentView = view;
    logUiEvent('view_switch', { from: previousView, to: view, reason });

    // Load view data
    switch(view) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'orchestrator':
            loadOrchestrator();
            break;
        case 'tasks':
            loadTasks();
            break;
        case 'memory':
            loadMemoryView();
            break;
        case 'logs':
            loadLogsView();
            break;
    }
}

function refreshCurrentView() {
    switch (currentView) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'orchestrator':
            loadOrchestrator();
            break;
        case 'tasks':
            if (selectedProject) {
                loadProjects()
                    .then(() => loadTasksList(selectedProject))
                    .catch((error) => console.error('Error refreshing tasks view:', error));
            } else {
                loadTasks();
            }
            break;
        case 'memory':
            loadMemoryView();
            break;
        case 'logs':
            if (logViewerSettings.autoRefresh) {
                loadLogEntries();
            }
            break;
        default:
            break;
    }
}

// WebSocket Connection
function initializeWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('WebSocket connected');
        updateConnectionStatus(true);
    };

    ws.onclose = () => {
        console.log('WebSocket disconnected');
        updateConnectionStatus(false);
        // Reconnect after 5 seconds
        setTimeout(initializeWebSocket, 5000);
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        updateConnectionStatus(false);
    };

    ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        handleWebSocketMessage(message);
    };
}

function updateConnectionStatus(connected) {
    const statusEl = document.getElementById('connection-status');
    const dotEl = document.querySelector('.status-dot');

    if (connected) {
        statusEl.textContent = 'Connected';
        dotEl.style.background = 'var(--success)';
    } else {
        statusEl.textContent = 'Disconnected';
        dotEl.style.background = 'var(--error)';
    }
}

function handleWebSocketMessage(message) {
    console.log('WebSocket message:', message);

    switch(message.type) {
        case 'worker_status':
            updateWorkerStatus(message.data);
            break;
        case 'task_update':
            updateTaskStatus(message.data);
            break;
        case 'log':
            addLogLine(message.data);
            break;
        case 'task_complete':
            handleTaskComplete(message.data);
            break;
    }
}

// Dashboard
async function loadDashboard() {
    try {
        const stats = await fetch('/api/orchestrator/stats').then(r => r.json());

        document.getElementById('stat-workers').textContent = stats.active_workers || 0;
        document.getElementById('stat-queued').textContent = stats.queued || 0;
        document.getElementById('stat-completed').textContent = stats.completed || 0;
        document.getElementById('stat-failed').textContent = stats.failed || 0;
    } catch (error) {
        console.error('Error loading dashboard:', error);
    }
}

// Orchestrator View
async function loadOrchestrator() {
    await loadWorkers();
    await loadTaskQueue();
    await loadModelControls();
}

function setupModelControls() {
    const saveBtn = document.getElementById('model-save-btn');
    if (saveBtn) {
        saveBtn.addEventListener('click', saveModelSelection);
    }
}

function setupManualTaskForm() {
    const form = document.getElementById('manual-task-form');
    if (form) {
        form.addEventListener('submit', submitManualTask);
    }
}

function setupMemoryControls() {
    const refreshBtn = document.getElementById('memory-refresh-btn');
    const searchInput = document.getElementById('memory-search');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            memorySearchTerm = searchInput ? searchInput.value.trim() : '';
            logUiEvent('memory_refresh', { query: memorySearchTerm });
            loadMemoryView();
        });
    }
    if (searchInput) {
        searchInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                memorySearchTerm = event.target.value.trim();
                logUiEvent('memory_search', { query: memorySearchTerm });
                loadMemoryItems();
            }
        });
    }
}

function initializeTrackingControls() {
    const configureBtn = document.getElementById('project-track-btn');
    const embedBtn = document.getElementById('project-embed-btn');
    const untrackBtn = document.getElementById('project-untrack-btn');
    const deleteBtn = document.getElementById('project-delete-btn');

    if (configureBtn) {
        configureBtn.addEventListener('click', showTrackingConfigPanel);
    }
    if (embedBtn) {
        embedBtn.addEventListener('click', startEmbeddingRun);
    }
    if (untrackBtn) {
        untrackBtn.addEventListener('click', stopProjectTracking);
    }
    if (deleteBtn) {
        deleteBtn.addEventListener('click', handleProjectDelete);
    }
}

function setupProjectCreation() {
    const newProjectBtn = document.getElementById('new-project-btn');
    if (newProjectBtn) {
        newProjectBtn.addEventListener('click', createNewProject);
    }
}

function initializeLogViewerControls() {
    const levelFilter = document.getElementById('logs-level-filter');
    if (levelFilter) {
        levelFilter.addEventListener('change', (event) => {
            logViewerSettings.minLevel = event.target.value;
            logUiEvent('logs_filter_level', { level: logViewerSettings.minLevel });
            loadLogEntries();
        });
    }

    const includeAccess = document.getElementById('logs-include-access');
    if (includeAccess) {
        includeAccess.addEventListener('change', (event) => {
            logViewerSettings.includeAccess = event.target.checked;
            logUiEvent('logs_include_access_toggle', { enabled: logViewerSettings.includeAccess });
            loadLogEntries();
        });
    }

    const autoToggle = document.getElementById('logs-auto-refresh');
    if (autoToggle) {
        autoToggle.addEventListener('change', (event) => {
            logViewerSettings.autoRefresh = event.target.checked;
            logUiEvent('logs_auto_refresh_toggle', { enabled: logViewerSettings.autoRefresh });
        });
    }

    const refreshBtn = document.getElementById('logs-refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            logUiEvent('logs_manual_refresh');
            loadLogEntries();
        });
    }

    const applyBtn = document.getElementById('apply-log-level-btn');
    if (applyBtn) {
        applyBtn.addEventListener('click', applyServerLogLevel);
    }
}

async function loadModelControls() {
    const select = document.getElementById('model-select');
    if (!select) return;
    try {
        const config = await fetch('/api/control/models').then(r => r.json());
        availableModels = config.models || [];
        select.innerHTML = config.models.map(model => `
            <option value="${model.id}">${model.label}</option>
        `).join('');
        if (config.current_model) {
            select.value = config.current_model;
        }
        populateTrackingModelSelect(
            document.getElementById('tracking-preferred-model'),
            undefined
        );
    } catch (error) {
        console.error('Error loading models:', error);
    }
}

async function saveModelSelection() {
    const select = document.getElementById('model-select');
    const status = document.getElementById('model-status');
    if (!select) return;

    logUiEvent('model_select', { model_id: select.value });
    try {
        await fetch('/api/control/models/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_id: select.value })
        });
        if (status) {
            status.textContent = 'Model updated successfully';
        }
    } catch (error) {
        console.error('Error updating model:', error);
        if (status) {
            status.textContent = 'Failed to update model';
        }
    }
}

async function submitManualTask(event) {
    event.preventDefault();
    const form = event.target;
    const status = document.getElementById('manual-task-status');
    const formData = new FormData(form);
    const payload = Object.fromEntries(formData.entries());
    payload.priority = Number(payload.priority);
    if (!payload.working_dir) {
        delete payload.working_dir;
    }

    logUiEvent('manual_task_submit', {
        project_id: payload.project_id,
        cli: payload.cli_preference,
        priority: payload.priority,
    });

    try {
        const response = await fetch('/api/control/tasks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Failed to queue task');
        }
        form.reset();
        if (status) {
            status.textContent = `Queued task ${result.task_id}`;
        }
        loadTaskQueue();
    } catch (error) {
        console.error('Error queuing manual task:', error);
        if (status) {
            status.textContent = `Error: ${error.message}`;
        }
    }
}

async function loadWorkers() {
    try {
        const workers = await fetch('/api/orchestrator/workers').then(r => r.json());
        const grid = document.getElementById('workers-grid');

        if (workers.length === 0) {
            grid.innerHTML = '<div class="empty-state">No active workers</div>';
            return;
        }

        grid.innerHTML = workers.map(worker => `
            <div class="worker-card">
                <h4>${worker.worker_id}</h4>
                <div class="task-title">${worker.task_title}</div>
                <div class="meta">
                    PID: ${worker.worker_pid || 'N/A'} |
                    CLI: ${worker.cli_preference}
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Error loading workers:', error);
    }
}

async function loadTaskQueue() {
    try {
        const tasks = await fetch('/api/orchestrator/tasks').then(r => r.json());

        updateQueueColumn('queued', tasks.queued || []);
        updateQueueColumn('progress', tasks.in_progress || []);
        updateQueueColumn('completed', tasks.completed || []);
        updateQueueColumn('failed', tasks.failed || []);
    } catch (error) {
        console.error('Error loading task queue:', error);
    }
}

function updateQueueColumn(status, tasks) {
    const list = document.getElementById(`queue-${status}`);
    const count = document.getElementById(`queue-${status}-count`);

    count.textContent = tasks.length;

    if (tasks.length === 0) {
        list.innerHTML = '<div class="empty-state">No tasks</div>';
        return;
    }

    list.innerHTML = tasks.map(task => `
        <div class="task-card" onclick="viewTaskLogs('${task.task_id}')">
            <div class="title">${task.task_title}</div>
            <div class="meta">${task.task_id.substring(0, 8)}...</div>
        </div>
    `).join('');
}

async function viewTaskLogs(taskId) {
    logUiEvent('task_logs_view', { task_id: taskId });
    try {
        const logs = await fetch(`/api/orchestrator/logs/${taskId}`).then(r => r.json());
        const logsContainer = document.getElementById('live-logs');

        logsContainer.innerHTML = `
            <div class="log-section">
                <h4>Task: ${taskId}</h4>
                <pre>${logs.stdout || 'No output yet'}</pre>
                ${logs.stderr ? `<h4>Errors:</h4><pre>${logs.stderr}</pre>` : ''}
            </div>
        `;
    } catch (error) {
        console.error('Error loading task logs:', error);
    }
}

function clearLogs() {
    document.getElementById('live-logs').innerHTML = '';
    logUiEvent('logs_clear');
}

function addLogLine(logData) {
    const logsContainer = document.getElementById('live-logs');
    const autoScroll = document.getElementById('auto-scroll').checked;

    const logLine = document.createElement('div');
    logLine.className = 'log-line';
    logLine.innerHTML = `
        <span class="timestamp">[${new Date(logData.timestamp).toLocaleTimeString()}]</span>
        <span class="level-${logData.level}">${logData.message}</span>
    `;

    logsContainer.appendChild(logLine);

    if (autoScroll) {
        logsContainer.scrollTop = logsContainer.scrollHeight;
    }
}

// Tasks View
async function loadTasks() {
    await loadProjects();
    // Preserve selected project filter when refreshing
    await loadTasksList(selectedProject);
    renderProjectTrackingBanner();
}

async function loadProjects() {
    try {
        const projects = await fetch('/api/projects').then(r => r.json());
        projectsCache = projects;
        refreshTaskProjectOptions();
        let trackingStatuses = [];
        try {
            const trackingResponse = await fetch('/api/project-tracking');
            if (!trackingResponse.ok) {
                throw new Error(`status ${trackingResponse.status}`);
            }
            trackingStatuses = await trackingResponse.json();
            clearTrackingError();
        } catch (trackingError) {
            console.warn('Failed to load tracking metadata:', trackingError);
            handleTrackingFetchError(trackingError.message || 'unknown');
        }
        projectTracking = {};
        (trackingStatuses || []).forEach(entry => {
            projectTracking[entry.project_id] = entry;
        });
        const list = document.getElementById('projects-list');

        if (projects.length === 0) {
            list.innerHTML = '<div class="empty-state">No projects</div>';
            return;
        }

        list.innerHTML = projects.map(project => `
            <div class="project-item ${selectedProject === project.id ? 'active' : ''} ${projectStatusClass(project.id)}"
                 onclick="selectProject('${project.id}')">
                ${project.name}
            </div>
        `).join('');
        renderProjectTrackingBanner();
    } catch (error) {
        console.error('Error loading projects:', error);
        document.getElementById('projects-list').innerHTML =
            '<div class="error">Failed to load projects</div>';
    }
}

async function loadTasksList(projectId = null) {
    const effectiveProjectId = projectId || selectedProject;
    if (!projectId && effectiveProjectId) {
        logUiEvent('tasks_filter_restore', { project_id: effectiveProjectId });
    } else if (!effectiveProjectId && selectedProject) {
        logUiEvent('tasks_filter_reset', { previously_selected: selectedProject });
    }
    try {
        let url = '/api/tasks?limit=100';
        if (effectiveProjectId) {
            url += `&project_id=${effectiveProjectId}`;
        }

        const tasks = await fetch(url).then(r => r.json());
        const filteredTasks = filterTasksByStatus(tasks);
        const grid = document.getElementById('tasks-grid');

        if (filteredTasks.length === 0) {
            grid.innerHTML = '<div class="empty-state">No tasks for selected filters</div>';
            resetTaskDetailPanel();
            return;
        }

        grid.innerHTML = filteredTasks.map(task => `
            <div class="task-card" onclick="selectTask('${task.id}')">
                <div class="title">${task.title}</div>
                <div class="meta">
                    Status: ${task.status} |
                    Priority: ${task.priority || 'None'}
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Error loading tasks:', error);
    }
}

function selectProject(projectId) {
    selectedProject = projectId;
    window.localStorage.setItem('selectedProjectId', projectId);
    loadProjects();
    loadTasksList(projectId);
    renderProjectTrackingBanner();
    hideTrackingConfigPanel();
    logUiEvent('project_select', { project_id: projectId });
}

async function selectTask(taskId) {
    selectedTask = taskId;
    logUiEvent('task_select', { task_id: taskId });

    try {
        const task = await fetch(`/api/tasks/${taskId}`).then(r => r.json());
        populateTaskDetailForm(task);
    } catch (error) {
        console.error('Error loading task details:', error);
    }
}

async function assignTaskToAI(taskId) {
    logUiEvent('task_assign_to_ai', { task_id: taskId });
    try {
        await fetch(`/api/tasks/${taskId}/assign`, { method: 'POST' });
        alert('Task assigned to AI queue');
        // Switch to orchestrator view
        switchView('orchestrator', 'system');
    } catch (error) {
        console.error('Error assigning task:', error);
        alert('Failed to assign task: ' + error.message);
    }
}

function initializeTaskToolbar() {
    const newTaskBtn = document.getElementById('new-task-btn');
    const cancelBtn = document.getElementById('task-create-cancel');
    const closeBtn = document.getElementById('task-create-close');
    const form = document.getElementById('task-create-form');
    if (newTaskBtn) {
        newTaskBtn.addEventListener('click', () => showTaskCreatePanel({ mode: 'create' }));
    }
    if (cancelBtn) {
        cancelBtn.addEventListener('click', hideTaskCreatePanel);
    }
    if (closeBtn) {
        closeBtn.addEventListener('click', hideTaskCreatePanel);
    }
    if (form) {
        form.addEventListener('submit', handleTaskCreateSubmit);
    }
}

function initializeStatusFilters() {
    const checkboxes = document.querySelectorAll('.status-filter');
    checkboxes.forEach(cb => {
        cb.addEventListener('change', () => {
            const status = cb.dataset.status;
            if (cb.checked) {
                activeTaskStatuses.add(status);
            } else {
                activeTaskStatuses.delete(status);
            }
            if (activeTaskStatuses.size === 0) {
                activeTaskStatuses = new Set(DEFAULT_ACTIVE_STATUSES);
                syncStatusCheckboxes();
            }
            if (currentView === 'tasks') {
                loadTasksList(selectedProject);
            }
        });
    });
    const activeBtn = document.getElementById('status-select-active');
    const allBtn = document.getElementById('status-select-all');
    if (activeBtn) {
        activeBtn.addEventListener('click', () => {
            activeTaskStatuses = new Set(DEFAULT_ACTIVE_STATUSES);
            syncStatusCheckboxes();
            if (currentView === 'tasks') {
                loadTasksList(selectedProject);
            }
        });
    }
    if (allBtn) {
        allBtn.addEventListener('click', () => {
            activeTaskStatuses = new Set(TASK_STATUSES.map(status => status.value));
            syncStatusCheckboxes();
            if (currentView === 'tasks') {
                loadTasksList(selectedProject);
            }
        });
    }
    syncStatusCheckboxes();
}

function syncStatusCheckboxes() {
    document.querySelectorAll('.status-filter').forEach(cb => {
        const status = cb.dataset.status;
        cb.checked = activeTaskStatuses.has(status);
    });
}

function initializeTaskDetailForm() {
    const form = document.getElementById('task-detail-form');
    const deleteBtn = document.getElementById('task-detail-delete');
    const subtaskBtn = document.getElementById('task-detail-add-subtask');
    const assignBtn = document.getElementById('task-detail-assign');

    if (form) {
        form.addEventListener('submit', handleTaskUpdateSubmit);
    }
    if (deleteBtn) {
        deleteBtn.addEventListener('click', handleTaskDelete);
    }
    if (subtaskBtn) {
        subtaskBtn.addEventListener('click', handleAddSubtask);
    }
    if (assignBtn) {
        assignBtn.addEventListener('click', () => {
            if (selectedTask) {
                assignTaskToAI(selectedTask);
            }
        });
    }
}

function showTaskCreatePanel(options = {}) {
    const panel = document.getElementById('task-create-panel');
    const heading = document.getElementById('task-create-title');
    const titleInput = document.getElementById('task-create-title-input');
    const statusSelect = document.getElementById('task-create-status');
    const priorityInput = document.getElementById('task-create-priority');
    const projectSelect = document.getElementById('task-create-project');
    const parentInput = document.getElementById('task-create-parent-id');
    const statusText = document.getElementById('task-create-status-text');

    if (!panel || !titleInput || !statusSelect || !projectSelect || !priorityInput) {
        return;
    }

    const mode = options.mode || 'create';
    if (heading) {
        heading.textContent = mode === 'subtask' ? 'New Subtask' : 'New Task';
    }
    titleInput.value = options.title || '';
    renderStatusOptions(statusSelect, options.status || 'todo');
    priorityInput.value = options.priority || 5;
    populateProjectSelect(projectSelect, options.projectId || selectedProject || '');
    parentInput.value = options.parentTaskId || '';
    if (statusText) {
        statusText.textContent = '';
    }
    panel.dataset.mode = mode;
    panel.classList.remove('hidden');
    titleInput.focus();
}

function hideTaskCreatePanel() {
    const panel = document.getElementById('task-create-panel');
    const form = document.getElementById('task-create-form');
    const statusText = document.getElementById('task-create-status-text');
    if (panel) {
        panel.classList.add('hidden');
    }
    if (form) {
        form.reset();
    }
    if (statusText) {
        statusText.textContent = '';
    }
}

async function handleTaskCreateSubmit(event) {
    event.preventDefault();
    const titleInput = document.getElementById('task-create-title-input');
    const statusSelect = document.getElementById('task-create-status');
    const priorityInput = document.getElementById('task-create-priority');
    const projectSelect = document.getElementById('task-create-project');
    const parentInput = document.getElementById('task-create-parent-id');
    const statusText = document.getElementById('task-create-status-text');
    if (!titleInput || !statusSelect || !priorityInput) {
        return;
    }

    const payload = {
        title: titleInput.value.trim(),
        status: statusSelect.value,
        priority: Number(priorityInput.value) || 5,
        project_id: projectSelect && projectSelect.value ? projectSelect.value : undefined,
        parent_task_id: parentInput && parentInput.value ? parentInput.value : undefined,
    };

    if (!payload.title) {
        if (statusText) statusText.textContent = 'Title is required';
        return;
    }

    logUiEvent('task_create', {
        project_id: payload.project_id || null,
        parent_task_id: payload.parent_task_id || null,
    });

    try {
        const response = await fetch('/api/tasks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const task = await response.json();
        if (!response.ok) {
            throw new Error(task.detail || 'Failed to create task');
        }
        hideTaskCreatePanel();
        selectedProject = task.project_id || selectedProject;
        if (selectedProject) {
            window.localStorage.setItem('selectedProjectId', selectedProject);
        }
        await loadProjects();
        await loadTasksList(selectedProject);
        selectedTask = task.id;
        populateTaskDetailForm(task);
    } catch (error) {
        console.error('Error creating task:', error);
        if (statusText) {
            statusText.textContent = error.message;
        }
    }
}

function renderStatusOptions(select, selectedValue = 'todo') {
    if (!select) return;
    select.innerHTML = TASK_STATUSES.map(status => `
        <option value="${status.value}">${status.label}</option>
    `).join('');
    select.value = selectedValue || 'todo';
}

function populateProjectSelect(select, selectedId = '') {
    if (!select) return;
    const options = projectsCache.map(project => `
        <option value="${project.id}">${project.name}</option>
    `).join('');
    select.innerHTML = `<option value="">Unassigned</option>${options}`;
    select.value = selectedId || '';
}

function refreshTaskProjectOptions() {
    populateProjectSelect(document.getElementById('task-create-project'), selectedProject || '');
}

function getProjectName(projectId) {
    if (!projectId) {
        return '—';
    }
    const project = projectsCache.find(p => p.id === projectId);
    return project ? project.name : projectId;
}

function filterTasksByStatus(tasks = []) {
    if (!activeTaskStatuses || activeTaskStatuses.size === 0) {
        return tasks;
    }
    return tasks.filter(task => activeTaskStatuses.has(task.status));
}

function populateTaskDetailForm(task) {
    selectedTaskDetails = task;
    const form = document.getElementById('task-detail-form');
    const emptyState = document.getElementById('task-empty-state');
    const titleInput = document.getElementById('task-detail-title');
    const statusSelect = document.getElementById('task-detail-status');
    const priorityInput = document.getElementById('task-detail-priority');
    const metaEl = document.getElementById('task-detail-meta');
    const statusText = document.getElementById('task-detail-status-text');

    if (!form || !titleInput || !statusSelect || !priorityInput) {
        return;
    }

    titleInput.value = task.title || '';
    renderStatusOptions(statusSelect, task.status || 'todo');
    priorityInput.value = task.priority || 5;
    if (metaEl) {
        metaEl.innerHTML = `
            <div><strong>Project:</strong> ${getProjectName(task.project_id)}</div>
            <div><strong>Created:</strong> ${formatDate(task.created_at)}</div>
            <div><strong>Updated:</strong> ${formatDate(task.modified_at)}</div>
        `;
    }
    if (statusText) {
        statusText.textContent = '';
    }
    form.classList.remove('hidden');
    if (emptyState) {
        emptyState.classList.add('hidden');
    }
}

function resetTaskDetailPanel() {
    selectedTask = null;
    selectedTaskDetails = null;
    const form = document.getElementById('task-detail-form');
    const emptyState = document.getElementById('task-empty-state');
    if (form) {
        form.classList.add('hidden');
    }
    if (emptyState) {
        emptyState.classList.remove('hidden');
    }
}

async function handleTaskUpdateSubmit(event) {
    event.preventDefault();
    if (!selectedTask) {
        return;
    }
    const titleInput = document.getElementById('task-detail-title');
    const statusSelect = document.getElementById('task-detail-status');
    const priorityInput = document.getElementById('task-detail-priority');
    const statusText = document.getElementById('task-detail-status-text');

    const payload = {
        title: titleInput.value.trim(),
        status: statusSelect.value,
        priority: Number(priorityInput.value) || 5,
    };

    logUiEvent('task_update', { task_id: selectedTask, status: payload.status });

    try {
        const response = await fetch(`/api/tasks/${selectedTask}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const task = await response.json();
        if (!response.ok) {
            throw new Error(task.detail || 'Failed to update task');
        }
        populateTaskDetailForm(task);
        await loadTasksList(selectedProject);
    } catch (error) {
        console.error('Error updating task:', error);
        if (statusText) {
            statusText.textContent = error.message;
        }
    }
}

async function handleTaskDelete() {
    if (!selectedTask) {
        return;
    }
    if (!confirm('Delete this task?')) {
        return;
    }
    logUiEvent('task_delete', { task_id: selectedTask });
    try {
        const response = await fetch(`/api/tasks/${selectedTask}`, { method: 'DELETE' });
        if (!response.ok) {
            const result = await response.json().catch(() => ({}));
            throw new Error(result.detail || 'Failed to delete task');
        }
        resetTaskDetailPanel();
        await loadTasksList(selectedProject);
    } catch (error) {
        console.error('Error deleting task:', error);
        alert('Failed to delete task: ' + error.message);
    }
}

function handleAddSubtask() {
    if (!selectedTask || !selectedTaskDetails) {
        alert('Select a task first.');
        return;
    }
    logUiEvent('task_subtask_modal_open', { task_id: selectedTask });
    showTaskCreatePanel({
        mode: 'subtask',
        parentTaskId: selectedTask,
        projectId: selectedTaskDetails.project_id || selectedProject || '',
        priority: selectedTaskDetails.priority || 5,
        status: 'todo',
    });
}

function formatDate(value) {
    if (!value) return '—';
    try {
        return new Date(value).toLocaleString();
    } catch (error) {
        return value;
    }
}

function handleTrackingFetchError(message) {
    const now = Date.now();
    if (now - lastTrackingErrorAt > TRACKING_ERROR_COOLDOWN_MS) {
        logUiEvent('project_tracking_fetch_error', { message });
        lastTrackingErrorAt = now;
    }
    setTrackingError('Orchestrator unreachable. Please ensure the orchestrator service is running.');
}

function setTrackingError(message) {
    trackingErrorMessage = message || '';
    const errorEl = document.getElementById('project-tracking-error');
    if (errorEl) {
        if (trackingErrorMessage) {
            errorEl.textContent = trackingErrorMessage;
            errorEl.classList.remove('hidden');
        } else {
            errorEl.textContent = '';
            errorEl.classList.add('hidden');
        }
    }
    const configureBtn = document.getElementById('project-track-btn');
    const embedBtn = document.getElementById('project-embed-btn');
    const untrackBtn = document.getElementById('project-untrack-btn');
    [configureBtn, embedBtn, untrackBtn].forEach(btn => {
        if (btn) {
            btn.disabled = !!trackingErrorMessage;
        }
    });
    renderProjectTrackingBanner();
}

function clearTrackingError() {
    if (!trackingErrorMessage) {
        return;
    }
    trackingErrorMessage = '';
    const errorEl = document.getElementById('project-tracking-error');
    if (errorEl) {
        errorEl.textContent = '';
        errorEl.classList.add('hidden');
    }
    const configureBtn = document.getElementById('project-track-btn');
    const embedBtn = document.getElementById('project-embed-btn');
    const untrackBtn = document.getElementById('project-untrack-btn');
    [configureBtn, embedBtn, untrackBtn].forEach(btn => {
        if (btn) {
            btn.disabled = false;
        }
    });
    renderProjectTrackingBanner();
}

async function handleProjectDelete() {
    if (!selectedProject) {
        alert('Select a project first.');
        return;
    }
    const project = projectsCache.find(p => p.id === selectedProject);
    const requiredName = project ? project.name : 'this project';
    const confirmation = prompt(`Type "${requiredName}" to confirm deletion:`);
    if (!confirmation || confirmation.trim() !== requiredName) {
        alert('Project name did not match. Aborting delete.');
        return;
    }
    logUiEvent('project_delete', { project_id: selectedProject });
    try {
        const response = await fetch(`/api/projects/${selectedProject}`, { method: 'DELETE' });
        if (!response.ok) {
            const result = await response.json().catch(() => ({}));
            throw new Error(result.detail || 'Failed to delete project');
        }
        selectedProject = null;
        selectedTask = null;
        window.localStorage.removeItem('selectedProjectId');
        hideTrackingConfigPanel();
        await loadProjects();
        await loadTasksList(null);
        resetTaskDetailPanel();
    } catch (error) {
        console.error('Error deleting project:', error);
        alert('Failed to delete project: ' + error.message);
    }
}

function projectStatusClass(projectId) {
    const info = projectTracking[projectId];
    if (!info || !info.is_tracked) {
        return 'project-untracked';
    }
    const status = info.embedding_status || 'pending';
    if (status === 'ready') {
        return 'project-tracked';
    }
    if (status === 'indexing' || status === 'pending') {
        return 'project-pending';
    }
    if (status === 'error') {
        return 'project-error';
    }
    return 'project-untracked';
}

function renderProjectTrackingBanner() {
    const banner = document.getElementById('project-tracking-banner');
    if (!banner) return;

    const statusText = document.getElementById('project-tracking-status');
    const detailEl = document.getElementById('project-tracking-details');
    const untrackBtn = document.getElementById('project-untrack-btn');
    const embedBtn = document.getElementById('project-embed-btn');
    const configureBtn = document.getElementById('project-track-btn');
    const deleteBtn = document.getElementById('project-delete-btn');
    const errorEl = document.getElementById('project-tracking-error');

    if (!selectedProject) {
        banner.classList.add('hidden');
        return;
    }

    const info = projectTracking[selectedProject];
    if (!info || !info.is_tracked) {
        banner.classList.remove('tracked', 'pending');
        banner.classList.add('untracked');
        statusText.textContent = 'Project not tracked';
        detailEl.textContent = 'Click "Configure Tracking" to assign a repo path and embedding model.';
        banner.classList.remove('hidden');
        if (untrackBtn) {
            untrackBtn.classList.add('hidden');
        }
        if (embedBtn) {
            embedBtn.disabled = true;
        }
        if (configureBtn) {
            configureBtn.disabled = !!trackingErrorMessage;
        }
        if (deleteBtn) {
            deleteBtn.disabled = false;
        }
        if (errorEl) {
            if (trackingErrorMessage) {
                errorEl.textContent = trackingErrorMessage;
                errorEl.classList.remove('hidden');
            } else {
                errorEl.textContent = '';
                errorEl.classList.add('hidden');
            }
        }
        return;
    }

    const paths = Array.isArray(info.repo_paths) ? info.repo_paths : [];
    const repo = paths.length === 0
        ? (info.repo_path || 'Not set')
        : paths.length === 1
            ? paths[0]
            : `${paths[0]} (+${paths.length - 1} more)`;
    const statusLabel = info.embedding_status ? info.embedding_status.toUpperCase() : 'PENDING';
    const lastIndexed = info.embedding_last_indexed
        ? new Date(info.embedding_last_indexed).toLocaleString()
        : 'Never';
    const modelLabel = info.embedding_model_id || info.preferred_model_id || 'Default';
    const gpuLabel = info.gpu_enabled ? `GPU (${info.gpu_device || 'local'})` : 'CPU';

    if (info.embedding_status === 'ready') {
        banner.classList.add('tracked');
        banner.classList.remove('pending', 'untracked');
    } else if (info.embedding_status === 'indexing' || info.embedding_status === 'pending') {
        banner.classList.add('pending');
        banner.classList.remove('tracked', 'untracked');
    } else {
        banner.classList.remove('tracked', 'pending');
        banner.classList.add('untracked');
    }

    statusText.textContent = `${statusLabel} – Repo: ${repo}`;
    detailEl.innerHTML = `
        Last indexed: ${lastIndexed} · Model: ${modelLabel} · ${gpuLabel}
    `;
    banner.classList.remove('hidden');
    if (untrackBtn) {
        untrackBtn.classList.toggle('hidden', !info.is_tracked);
    }
    if (embedBtn) {
        embedBtn.disabled = false;
    }
    if (configureBtn) {
        configureBtn.disabled = false;
    }
    if (deleteBtn) {
        deleteBtn.disabled = false;
    }
    if (errorEl) {
        if (trackingErrorMessage) {
            errorEl.textContent = trackingErrorMessage;
            errorEl.classList.remove('hidden');
        } else {
            errorEl.textContent = '';
            errorEl.classList.add('hidden');
        }
    }

    const disabledDueToError = !!trackingErrorMessage;
    [configureBtn, embedBtn, untrackBtn].forEach(btn => {
        if (btn) {
            btn.disabled = disabledDueToError;
        }
    });
}

function initializeTrackingForm() {
    const form = document.getElementById('tracking-config-form');
    const gpuToggle = document.getElementById('tracking-gpu-enabled');
    const closeBtn = document.getElementById('tracking-config-close');
    const cancelBtn = document.getElementById('tracking-config-cancel');
    if (form) {
        form.addEventListener('submit', handleTrackingFormSubmit);
    }
    if (gpuToggle) {
        gpuToggle.addEventListener('change', (event) => toggleGpuDeviceRow(event.target.checked));
    }
    if (closeBtn) {
        closeBtn.addEventListener('click', hideTrackingConfigPanel);
    }
    if (cancelBtn) {
        cancelBtn.addEventListener('click', hideTrackingConfigPanel);
    }
}

function showTrackingConfigPanel() {
    if (!selectedProject) {
        alert('Select a project first.');
        return;
    }
    if (trackingErrorMessage) {
        alert('Cannot configure tracking while the orchestrator is unreachable.');
        return;
    }
    const panel = document.getElementById('tracking-config-panel');
    const titleEl = document.getElementById('tracking-config-project');
    const repoInput = document.getElementById('tracking-repo-path');
    const modelSelect = document.getElementById('tracking-preferred-model');
    const gpuToggle = document.getElementById('tracking-gpu-enabled');
    const gpuDevice = document.getElementById('tracking-gpu-device');
    const info = projectTracking[selectedProject] || {};
    const project = projectsCache.find(p => p.id === selectedProject);

    if (panel && repoInput && modelSelect && gpuToggle && gpuDevice) {
        if (titleEl && project) {
            titleEl.textContent = project.name;
        }
        const repoPaths = Array.isArray(info.repo_paths) && info.repo_paths.length > 0
            ? info.repo_paths.join('\n')
            : (info.repo_path || '');
        repoInput.value = repoPaths;
        populateTrackingModelSelect(modelSelect, info.preferred_model_id || info.embedding_model_id || '');
        gpuToggle.checked = !!info.gpu_enabled;
        gpuDevice.value = info.gpu_device || '';
        toggleGpuDeviceRow(gpuToggle.checked);
        panel.classList.remove('hidden');
        repoInput.focus();
    }
}

function hideTrackingConfigPanel() {
    const panel = document.getElementById('tracking-config-panel');
    const status = document.getElementById('tracking-config-status');
    if (panel) {
        panel.classList.add('hidden');
    }
    if (status) {
        status.textContent = '';
    }
}

function populateTrackingModelSelect(select, selectedValue = '') {
    if (!select) return;
    const options = availableModels.length
        ? availableModels.map(model => `<option value="${model.id}">${model.label}</option>`).join('')
        : '<option value="">Default (server)</option>';
    select.innerHTML = `<option value="">Auto (server default)</option>${options}`;
    select.value = selectedValue || '';
}

function toggleGpuDeviceRow(show) {
    const row = document.getElementById('tracking-gpu-device-row');
    if (row) {
        row.classList.toggle('hidden', !show);
    }
}

async function handleTrackingFormSubmit(event) {
    event.preventDefault();
    if (!selectedProject) {
        alert('Select a project first.');
        return;
    }
    if (trackingErrorMessage) {
        alert('Cannot update tracking while the orchestrator is unreachable.');
        return;
    }

    const repoInput = document.getElementById('tracking-repo-path');
    const modelSelect = document.getElementById('tracking-preferred-model');
    const gpuToggle = document.getElementById('tracking-gpu-enabled');
    const gpuDevice = document.getElementById('tracking-gpu-device');
    const status = document.getElementById('tracking-config-status');

    if (!repoInput) {
        return;
    }

    const repoPaths = repoInput.value
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean);
    if (repoPaths.length === 0) {
        status.textContent = 'At least one repository path is required.';
        return;
    }
    const repoPath = repoPaths[0];

    const payload = {
        repo_path: repoPath,
        repo_paths: repoPaths,
        is_tracked: true,
        preferred_model_id: modelSelect && modelSelect.value ? modelSelect.value : undefined,
        gpu_enabled: gpuToggle ? gpuToggle.checked : false,
        gpu_device: gpuDevice && gpuDevice.value ? gpuDevice.value.trim() : undefined,
    };

    logUiEvent('project_tracking_configure', {
        project_id: selectedProject,
        repo_path: repoPath,
        preferred_model_id: payload.preferred_model_id || null,
        gpu_enabled: payload.gpu_enabled,
    });

    try {
        const response = await fetch(`/api/project-tracking/${selectedProject}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const result = await response.json().catch(() => ({}));
            throw new Error(result.detail || 'Failed to update tracking');
        }
        if (status) {
            status.textContent = 'Tracking updated';
        }
        await loadProjects();
        await refreshProjectTracking(selectedProject);
        hideTrackingConfigPanel();
    } catch (error) {
        console.error('Error updating tracking:', error);
        if (status) {
            status.textContent = error.message;
        }
        handleTrackingFetchError(error.message || 'unknown');
    }
}

async function stopProjectTracking() {
    if (!selectedProject) return;
    if (trackingErrorMessage) {
        alert('Cannot update tracking while the orchestrator is unreachable.');
        return;
    }
    if (!confirm('Stop tracking this project?')) {
        return;
    }
    logUiEvent('project_tracking_disable', { project_id: selectedProject });
    try {
        await fetch(`/api/project-tracking/${selectedProject}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_tracked: false }),
        });
        await loadProjects();
        await refreshProjectTracking(selectedProject);
    } catch (error) {
        console.error('Error disabling tracking:', error);
        alert('Failed to stop tracking: ' + error.message);
        handleTrackingFetchError(error.message || 'unknown');
    }
}

async function startEmbeddingRun() {
    if (!selectedProject) {
        alert('Select a project first.');
        return;
    }
    if (trackingErrorMessage) {
        alert('Cannot start embeddings while the orchestrator is unreachable.');
        return;
    }
    const info = projectTracking[selectedProject];
    if (!info || !info.is_tracked) {
        alert('Configure tracking before starting an embedding run.');
        return;
    }
    const scopeInput = prompt('Embedding scope? (code / text / both)', 'both') || 'both';
    const allowedScopes = ['code', 'text', 'both'];
    const scope = allowedScopes.includes(scopeInput.toLowerCase()) ? scopeInput.toLowerCase() : 'both';

    logUiEvent('project_embedding_start', { project_id: selectedProject, scope });
    try {
        const response = await fetch(`/api/project-tracking/${selectedProject}/index`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scope }),
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Unable to start embedding');
        }
        await refreshProjectTracking(selectedProject);
        alert(`Embedding job queued: ${result.task_id || 'pending'}`);
    } catch (error) {
        console.error('Error queuing embedding run:', error);
        alert('Failed to start embedding: ' + error.message);
        handleTrackingFetchError(error.message || 'unknown');
    }
}

async function refreshProjectTracking(projectId) {
    try {
        const info = await fetch(`/api/project-tracking/${projectId}`).then(r => r.json());
        projectTracking[projectId] = info;
        clearTrackingError();
        renderProjectTrackingBanner();
    } catch (error) {
        console.error('Error refreshing tracking info:', error);
        handleTrackingFetchError(error.message || 'unknown');
    }
}

async function createNewProject() {
    const nameInput = prompt('Project name? (required)');
    if (nameInput === null) {
        return;
    }
    const name = nameInput.trim();
    if (!name) {
        alert('Project name is required.');
        return;
    }

    const statusInput = prompt('Project status (active/backlog/completed)', 'active') || 'active';
    const status = statusInput.trim() || 'active';

    const track = confirm('Track this project and prepare embeddings?');
    let repoPath = '';
    if (track) {
        const repoPrompt = prompt('Repository path (required for tracking):', '');
        if (repoPrompt === null) {
            return;
        }
        repoPath = (repoPrompt || '').trim();
        if (!repoPath) {
            alert('Repository path is required when tracking.');
            return;
        }
    } else {
        const maybeRepo = prompt('Repository path (optional):', '');
        if (maybeRepo !== null) {
            repoPath = (maybeRepo || '').trim();
        }
    }

    const payload = {
        name,
        status,
        track,
        repo_path: repoPath || undefined,
    };

    logUiEvent('project_create', {
        name,
        status,
        track,
        repo_path: repoPath || null,
    });
    try {
        const response = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const project = await response.json();
        if (!response.ok) {
            throw new Error(project.detail || 'Failed to create project');
        }
        selectedProject = project.id;
        window.localStorage.setItem('selectedProjectId', selectedProject);
        await loadProjects();
        await loadTasksList(selectedProject);
        await refreshProjectTracking(selectedProject);
        renderProjectTrackingBanner();
    } catch (error) {
        console.error('Error creating project:', error);
        alert('Failed to create project: ' + error.message);
    }
}

// Memory View
async function loadMemoryView() {
    await Promise.all([loadMemoryStats(), loadMemoryItems()]);
}

async function loadMemoryStats() {
    try {
        const stats = await fetch('/api/memory/stats').then(r => r.json());
        document.getElementById('memory-total').textContent = stats.total || 0;
        const topCategory = (stats.by_category && stats.by_category[0]) ? stats.by_category[0].category : '—';
        document.getElementById('memory-top-category').textContent = topCategory || '—';
        const latest = stats.latest ? new Date(stats.latest.created_at).toLocaleString() : '—';
        document.getElementById('memory-latest').textContent = latest;
    } catch (error) {
        console.error('Error loading memory stats:', error);
    }
}

async function loadMemoryItems() {
    const params = new URLSearchParams({ limit: 50 });
    if (memorySearchTerm) {
        params.append('search', memorySearchTerm);
    }

    try {
        const items = await fetch(`/api/memory/items?${params.toString()}`).then(r => r.json());
        renderMemoryItems(items);
    } catch (error) {
        console.error('Error loading memory items:', error);
        const container = document.getElementById('memory-list');
        container.innerHTML = '<div class="error">Failed to load memory items</div>';
    }
}

function renderMemoryItems(items) {
    const container = document.getElementById('memory-list');
    if (!items || items.length === 0) {
        container.innerHTML = '<div class="empty-state">No memory entries found</div>';
        return;
    }

    container.innerHTML = items.map(item => `
        <div class="memory-card">
            <div class="memory-content">${renderMemorySnippet(item.content)}</div>
            <div class="memory-meta">
                <span>ID: ${item.memory_id.slice(0, 8)}…</span>
                <span>Project: ${item.project_id || '—'}</span>
                <span>Created: ${new Date(item.created_at).toLocaleString()}</span>
                <span>Feedback: ${item.user_feedback ?? 0}</span>
            </div>
            <div class="memory-tags">
                ${(item.categories || []).map(cat => `<span class="memory-tag">${cat}</span>`).join('')}
            </div>
            <div class="memory-actions">
                <button onclick="handleMemoryFeedback('${item.memory_id}', 1)">👍 Good</button>
                <button onclick="handleMemoryFeedback('${item.memory_id}', -1)">👎 Bad</button>
                <button onclick="handleMemoryDelete('${item.memory_id}')">🗑️ Delete</button>
            </div>
        </div>
    `).join('');
}

async function handleMemoryDelete(memoryId) {
    if (!confirm('Delete this memory entry?')) {
        return;
    }
    logUiEvent('memory_delete', { memory_id: memoryId });
    try {
        const response = await fetch(`/api/memory/items/${memoryId}`, { method: 'DELETE' });
        if (!response.ok) {
            const result = await response.json();
            throw new Error(result.detail || 'Delete failed');
        }
        loadMemoryItems();
        loadMemoryStats();
    } catch (error) {
        console.error('Error deleting memory:', error);
        alert('Failed to delete memory: ' + error.message);
    }
}

async function handleMemoryFeedback(memoryId, delta) {
    logUiEvent('memory_feedback', { memory_id: memoryId, delta });
    try {
        const response = await fetch('/api/memory/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ memory_id: memoryId, feedback: delta })
        });
        if (!response.ok) {
            const result = await response.json();
            throw new Error(result.detail || 'Feedback update failed');
        }
        loadMemoryItems();
    } catch (error) {
        console.error('Error updating feedback:', error);
        alert('Failed to update feedback: ' + error.message);
    }
}

function renderMemorySnippet(content) {
    const value = content || '';
    const snippet = value.slice(0, 400);
    return `${escapeHtml(snippet)}${value.length > 400 ? '…' : ''}`;
}

function escapeHtml(text = '') {
    return text.replace(/[&<>'"]/g, (char) => {
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            "'": '&#39;',
            '"': '&quot;'
        };
        return map[char] || char;
    });
}

// Logs View
async function loadLogsView() {
    logUiEvent('logs_view_load', {
        min_level: logViewerSettings.minLevel,
        include_access: logViewerSettings.includeAccess,
    });
    await Promise.all([loadLogConfig(), loadLogEntries()]);
}

async function loadLogConfig() {
    const targetSelect = document.getElementById('server-log-target');
    const levelSelect = document.getElementById('server-log-level');
    if (!targetSelect || !levelSelect) {
        return;
    }
    try {
        const config = await fetch('/api/logs/levels').then(r => r.json());
        if (Array.isArray(config.available_levels) && config.available_levels.length > 0) {
            levelSelect.innerHTML = config.available_levels.map(level => `
                <option value="${level}">${level.charAt(0)}${level.slice(1).toLowerCase()}</option>
            `).join('');
        }
        if (Array.isArray(config.loggers) && config.loggers.length > 0) {
            const previousTarget = targetSelect.value;
            targetSelect.innerHTML = config.loggers.map(entry => `
                <option value="${entry.name}">${entry.name} (${entry.level})</option>
            `).join('');
            const selectedEntry = config.loggers.find(entry => entry.name === previousTarget) || config.loggers[0];
            if (selectedEntry) {
                targetSelect.value = selectedEntry.name;
                levelSelect.value = selectedEntry.level || logViewerSettings.minLevel;
            }
        }
    } catch (error) {
        console.error('Error loading log level metadata:', error);
    }
}

async function loadLogEntries() {
    const params = new URLSearchParams({
        limit: '500',
        min_level: logViewerSettings.minLevel,
    });
    if (logViewerSettings.includeAccess) {
        params.append('include_access', 'true');
    }
    try {
        const response = await fetch(`/api/logs?${params.toString()}`);
        const data = await response.json();
        renderLogEntries(data.logs || []);
    } catch (error) {
        console.error('Error loading logs:', error);
        const container = document.getElementById('logs-output');
        if (container) {
            container.innerHTML = '<div class="error">Failed to load logs</div>';
        }
    }
}

function renderLogEntries(entries) {
    const container = document.getElementById('logs-output');
    if (!container) {
        return;
    }
    if (!entries || entries.length === 0) {
        container.innerHTML = '<div class="empty-state">No log entries</div>';
        return;
    }
    container.innerHTML = entries.map(entry => {
        const timestamp = entry.timestamp
            ? new Date(entry.timestamp).toLocaleTimeString()
            : new Date().toLocaleTimeString();
        const loggerName = escapeHtml(entry.logger || 'unknown');
        const message = escapeHtml(entry.message || '');
        const level = (entry.level || 'INFO').toUpperCase();
        return `
            <div class="log-entry level-${level}">
                <div class="log-meta">
                    <span>${timestamp}</span>
                    <span>${level}</span>
                    <span class="log-source">${loggerName}</span>
                </div>
                <div class="log-message">${message}</div>
            </div>
        `;
    }).join('');
}

async function applyServerLogLevel() {
    const loggerSelect = document.getElementById('server-log-target');
    const levelSelect = document.getElementById('server-log-level');
    const status = document.getElementById('log-level-status');
    if (!loggerSelect || !levelSelect) {
        return;
    }
    const payload = {
        logger_name: loggerSelect.value || 'root',
        level: levelSelect.value || 'INFO',
    };
    logUiEvent('logs_level_change', payload);
    try {
        const response = await fetch('/api/logs/level', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Failed to update log level');
        }
        if (status) {
            status.textContent = `Set ${result.name} to ${result.level}`;
        }
        await loadLogConfig();
    } catch (error) {
        console.error('Error updating log level:', error);
        if (status) {
            status.textContent = `Error: ${error.message}`;
        }
    }
}

// WebSocket message handlers
function updateWorkerStatus(data) {
    // Refresh workers if on orchestrator view
    if (currentView === 'orchestrator') {
        loadWorkers();
    }
}

function updateTaskStatus(data) {
    // Refresh task queue if on orchestrator view
    if (currentView === 'orchestrator') {
        loadTaskQueue();
    }
}

function handleTaskComplete(data) {
    // Refresh dashboard stats
    loadDashboard();
    // Show notification
    console.log('Task completed:', data.task_id);
}
