# Orchestrator Web Viewer

Web-based monitoring interface for AI Orchestrator, Knowledge Manager, and TermDash UIs

## Features

- **Dashboard** - Real-time stats and activity feed
- **Orchestrator Monitor** - Worker tracking, task queue visualization, live logs
- **Knowledge Manager** - Project and task management interface
- **TermDash Attachment** - View any TermDash terminal UI in the browser
- **Real-time Updates** - WebSocket-based live updates
- **LAN Access** - Accessible from any device on your network

## Installation

```bash
cd ~/scripts
pip install -e modules/orchestrator_web_viewer/

# With TermDash support
pip install -e modules/orchestrator_web_viewer/[termdash]
```

## Usage

### Start the web server

```bash
# Basic usage (uses default config from environment)
koweb

# Stop any running servers
koweb -s
# or
koweb --stop

# Custom port (short form)
koweb -p 3000

# Custom PostgreSQL connection
koweb -g localhost -P 5432 -d knowledge_manager

# With HTTP Basic Authentication (recommended for LAN access)
koweb -u admin -w your_secure_password

# Development mode (auto-reload)
koweb -r

# Verbose logging
koweb -v

# Full example with all options (short forms)
koweb -p 3000 -u admin -w mypassword -g localhost -v

# Or use long forms for clarity
koweb --port 3000 --auth-user admin --auth-password mypassword --postgres-host localhost --verbose
```

### Access the UI

- **Local:** http://localhost:3000
- **LAN:** http://<your-ip>:3000 (e.g., http://192.168.1.100:3000)
- **Mobile/Tablet:** Same LAN URL

### Environment Variables

```bash
# PostgreSQL connection
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_USER=km_user
export POSTGRES_PASSWORD=your_password
export POSTGRES_DB=knowledge_manager

# Task queue path
export TASK_QUEUE_PATH=~/projects/ai-orchestrator/task_queue

# Authentication (optional - enables HTTP Basic Auth)
export WEB_AUTH_USER=admin
export WEB_AUTH_PASSWORD=your_secure_password
```

**Note**: Authentication is disabled by default. Enable it by:
- Setting `WEB_AUTH_USER` and `WEB_AUTH_PASSWORD` environment variables, OR
- Using `--auth-user` and `--auth-password` CLI arguments

## API Endpoints

### Orchestrator

- `GET /api/orchestrator/stats` - System statistics
- `GET /api/orchestrator/workers` - Active workers
- `GET /api/orchestrator/tasks` - Task queue
- `GET /api/orchestrator/logs/:task_id` - Task logs

### Knowledge Manager

- `GET /api/projects` - List projects
- `GET /api/tasks` - List tasks
- `GET /api/tasks/:id` - Task details
- `POST /api/tasks/:id/assign` - Assign to AI

### TermDash Attachment

- `GET /api/termdash/dashboards` - List attached dashboards
- `GET /api/termdash/dashboards/:id` - Get dashboard state
- `WS /api/termdash/dashboards/:id/stream` - Stream dashboard updates
- `GET /termdash` - TermDash web viewer UI

### Results

- `GET /api/results/:task_id` - Task results
- `GET /api/results/:task_id/logs` - Task logs
- `GET /api/results/:task_id/artifacts` - List artifacts
- `GET /api/results/:task_id/artifacts/:path` - Download artifact

### WebSocket

- `ws://localhost:3000/ws` - Real-time updates

## Development

```bash
# Install in editable mode
pip install -e modules/orchestrator_web_viewer/[termdash]

# Run with auto-reload and verbose logging
koweb -r -v

# Run tests
pytest modules/orchestrator_web_viewer/tests/
```

## TermDash Attachment Mode

The web viewer can attach to any running TermDash terminal UI and mirror it in the browser.

### Attaching from Python Code

```python
from termdash import TermDash, Stat, Line
from orchestrator_web_viewer.api.termdash import register_dashboard

# Create your dashboard
dashboard = TermDash()
line = Line("workers", stats=[
    Stat("active", 0, prefix="Active: "),
    Stat("completed", 0, prefix="Done: "),
])
dashboard.add_line("workers", line)

# Register it for web viewing
register_dashboard("my_workers", dashboard)

# Start the dashboard
with dashboard:
    # Your code that updates stats
    dashboard.update_stat("workers", "active", 5)
    ...
```

### Viewing in Browser

1. Start the web server: `koweb`
2. Navigate to `http://localhost:3000/termdash`
3. Select your dashboard from the list
4. View real-time updates

### Use Cases

- Monitor `ytaedl` download workers
- View async task progress
- Debug terminal UIs remotely
- Share dashboard state across devices on LAN

## Architecture

```
orchestrator_web_viewer/
├── orchestrator_web_viewer/
│   ├── main.py              # FastAPI app + CLI
│   ├── api/
│   │   ├── orchestrator.py  # Orchestrator endpoints
│   │   ├── knowledge.py     # KM endpoints
│   │   └── results.py       # Results endpoints
│   ├── websocket/
│   │   └── manager.py       # WebSocket connections
│   └── static/
│       ├── index.html       # Main UI
│       ├── style.css        # Styling
│       └── app.js           # Frontend logic
└── pyproject.toml
```

## License

MIT
