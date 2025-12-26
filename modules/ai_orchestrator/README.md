# AI Orchestrator

Unified orchestration layer for managing CLI tools, AI models, and knowledge database.

## Features

- **Knowledge Database Interface**: Human-friendly access to projects, tasks, and subtasks
- **CLI Manager**: Automatically selects the best CLI tool for specific jobs
- **Model Manager**: Manages AI models and selects optimal models for tasks (with RTX 5090 support)
- **Rich Terminal UI**: Beautiful command-line interface with tables and colors

## Installation

```bash
cd modules/ai_orchestrator
pip install -e .
```

### Dependencies

The orchestrator requires the `knowledge_manager` module to be installed:

```bash
cd modules/knowledge_manager
pip install -e .
```

## Usage

The orchestrator provides the `aio` command-line tool.

### Database Operations

```bash
# List all projects
aio db list-projects

# Show project with tasks
aio db show-project --name "My Project"

# Create a new project
aio db create-project "New Project" --status active

# Create a task
aio db create-task "Implement feature X" --project "My Project"

# List tasks
aio db list-tasks --project "My Project" --status todo
```

### CLI Tool Management

```bash
# List all available CLI tools
aio cli list

# List only installed tools
aio cli list --installed

# Get best tool for a job type
aio cli best code_generation
aio cli best file_operations --local
```

Available job types:
- `code_generation`
- `code_analysis`
- `text_generation`
- `chat`
- `research`
- `file_operations`
- `system_admin`
- `data_processing`

### AI Model Management

```bash
# List all models
aio model list

# List models with specific capability
aio model list --capability code_generation

# List only local models
aio model list --local

# Get best model for capability
aio model best code_generation --local

# Check GPU status
aio model gpu

# Get model recommendations for a task
aio model recommend "Write a Python script to parse JSON"
```

Available capabilities:
- `code_generation`
- `code_understanding`
- `reasoning`
- `math`
- `chat`
- `function_calling`
- `vision`
- `long_context`

### System Status

```bash
# Show overall system status
aio status
```

## Architecture

### Components

1. **KnowledgeDB** (`db_interface.py`): Wraps the knowledge_manager SQLite database with a simple dictionary-based API
2. **CLIManager** (`cli_manager.py`): Manages CLI tools and selects the best one for specific job types
3. **ModelManager** (`model_manager.py`): Manages AI models, detects GPU, and recommends models for tasks
4. **CLI** (`cli.py`): Rich terminal interface built with Typer and Rich

### Database Schema

The knowledge_manager database includes:
- **Projects**: Top-level organization units with status tracking
- **Tasks**: Actionable items with priority, due dates, and status
- **Subtasks**: Tasks can have parent tasks for hierarchical organization
- **Tags**: Categorization system
- **Notes**: Rich text notes attached to projects/tasks
- **Attachments**: File attachments

### Future Enhancements

- **Vectorization**: Add embedding support for semantic search and AI memory
- **Task Dependencies**: Automatic dependency tracking and scheduling
- **Model Fine-tuning**: Track custom fine-tuned models
- **Cost Tracking**: Monitor API usage and costs
- **Batch Operations**: Process multiple tasks in parallel
- **Integration**: Connect with external tools (Jira, GitHub, etc.)

## Examples

### Create a project and tasks

```bash
# Create project
aio db create-project "Website Redesign" --status active

# Add tasks
aio db create-task "Design mockups" --project "Website Redesign" --priority 4
aio db create-task "Implement frontend" --project "Website Redesign" --priority 3
aio db create-task "Write tests" --project "Website Redesign" --priority 2

# List all tasks for the project
aio db list-tasks --project "Website Redesign"
```

### Find the best tools for a workflow

```bash
# Code generation
aio cli best code_generation

# File operations
aio cli best file_operations

# Research/analysis
aio cli best research
```

### Get model recommendations

```bash
# For coding tasks
aio model recommend "Refactor Python codebase to use async/await"

# For research
aio model recommend "Summarize recent papers on transformer architectures"

# For math
aio model recommend "Solve differential equations"
```

## Python API

You can also use the orchestrator programmatically:

```python
from ai_orchestrator import KnowledgeDB, CLIManager, ModelManager
from ai_orchestrator.cli_manager import JobType
from ai_orchestrator.model_manager import ModelCapability

# Access database
with KnowledgeDB() as db:
    projects = db.list_projects()
    for project in projects:
        print(f"{project['name']}: {project['status']}")

# Get best CLI tool
cli_mgr = CLIManager()
tool = cli_mgr.get_best_tool(JobType.CODE_GENERATION)
print(f"Use {tool.command} for code generation")

# Get best model
model_mgr = ModelManager()
model = model_mgr.get_best_model(ModelCapability.CODE_GENERATION)
print(f"Use {model.name} ({model.model_id})")
```

## Configuration

### Custom Models

You can add custom models by creating a JSON config file:

```json
{
  "models": [
    {
      "name": "Custom Local Model",
      "provider": "local_ollama",
      "model_id": "codellama:13b",
      "capabilities": ["code_generation", "chat"],
      "context_window": 4096,
      "max_output_tokens": 2048,
      "priority": 7,
      "is_local": true,
      "requires_gpu": true,
      "vram_required_gb": 8.0
    }
  ]
}
```

Pass the config path when initializing:

```python
from pathlib import Path
from ai_orchestrator import ModelManager

manager = ModelManager(config_path=Path("~/my_models.json"))
```

## License

Part of the scripts repository.
