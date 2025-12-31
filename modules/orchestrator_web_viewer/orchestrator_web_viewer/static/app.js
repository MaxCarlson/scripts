// AI Orchestrator Web Viewer - Frontend Application

// State
let ws = null;
let currentView = 'dashboard';
let selectedProject = null;
let selectedTask = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    initializeNavigation();
    initializeWebSocket();
    loadDashboard();

    // Refresh data every 5 seconds
    setInterval(refreshCurrentView, 5000);
});

// Navigation
function initializeNavigation() {
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const view = e.target.dataset.view;
            switchView(view);
        });
    });
}

function switchView(view) {
    // Update nav buttons
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.view === view);
    });

    // Update views
    document.querySelectorAll('.view').forEach(v => {
        v.classList.toggle('active', v.id === `${view}-view`);
    });

    currentView = view;

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
    }
}

function refreshCurrentView() {
    switchView(currentView);
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
    await loadTasksList();
}

async function loadProjects() {
    try {
        const projects = await fetch('/api/projects').then(r => r.json());
        const list = document.getElementById('projects-list');

        if (projects.length === 0) {
            list.innerHTML = '<div class="empty-state">No projects</div>';
            return;
        }

        list.innerHTML = projects.map(project => `
            <div class="project-item ${selectedProject === project.id ? 'active' : ''}"
                 onclick="selectProject('${project.id}')">
                ${project.name}
            </div>
        `).join('');
    } catch (error) {
        console.error('Error loading projects:', error);
        document.getElementById('projects-list').innerHTML =
            '<div class="error">Failed to load projects</div>';
    }
}

async function loadTasksList(projectId = null) {
    try {
        let url = '/api/tasks?limit=100';
        if (projectId) {
            url += `&project_id=${projectId}`;
        }

        const tasks = await fetch(url).then(r => r.json());
        const grid = document.getElementById('tasks-grid');

        if (tasks.length === 0) {
            grid.innerHTML = '<div class="empty-state">No tasks</div>';
            return;
        }

        grid.innerHTML = tasks.map(task => `
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
    loadProjects();
    loadTasksList(projectId);
}

async function selectTask(taskId) {
    selectedTask = taskId;

    try {
        const task = await fetch(`/api/tasks/${taskId}`).then(r => r.json());
        const panel = document.getElementById('task-detail-panel');

        panel.innerHTML = `
            <h3>${task.title}</h3>
            <div class="meta" style="margin-bottom: 1rem;">
                <strong>Status:</strong> ${task.status}<br>
                <strong>Priority:</strong> ${task.priority || 'None'}<br>
                <strong>Created:</strong> ${new Date(task.created_at).toLocaleString()}
            </div>
            <button onclick="assignTaskToAI('${task.id}')">
                Assign to AI Queue
            </button>
        `;
    } catch (error) {
        console.error('Error loading task details:', error);
    }
}

async function assignTaskToAI(taskId) {
    try {
        await fetch(`/api/tasks/${taskId}/assign`, { method: 'POST' });
        alert('Task assigned to AI queue');
        // Switch to orchestrator view
        switchView('orchestrator');
    } catch (error) {
        console.error('Error assigning task:', error);
        alert('Failed to assign task: ' + error.message);
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
