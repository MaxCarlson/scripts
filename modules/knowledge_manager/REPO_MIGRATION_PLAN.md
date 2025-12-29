# Repository Migration Plan

**Current**: `~/src/scripts/modules/knowledge_manager` + `~/src/scripts/modules/ai_orchestrator`
**Target**: New standalone repo for the multi-agent orchestrator system

---

## Why Migrate?

1. **Size**: This is becoming a major project (1000+ lines of code, research docs, Docker setup)
2. **Independence**: It's a complete system, not just a "module"
3. **CI/CD**: Easier to set up GitHub Actions, Docker builds
4. **Collaboration**: Cleaner for potential contributors
5. **Documentation**: Dedicated README, wiki, issues

---

## Proposed Repository Structure

```
ai-orchestrator-system/
├── .github/
│   ├── workflows/
│   │   ├── tests.yml
│   │   └── docker-build.yml
│   └── ISSUE_TEMPLATE/
├── docs/
│   ├── architecture/
│   │   ├── database-schema.md
│   │   ├── agent-orchestration.md
│   │   └── cli-integration.md
│   ├── research/
│   │   ├── Claude-V4-multi-agent-orchestration.md
│   │   └── vectorization.md
│   └── guides/
│       ├── setup.md
│       ├── development.md
│       └── deployment.md
├── knowledge_manager/
│   ├── knowledge_manager/          # Python package
│   │   ├── __init__.py
│   │   ├── db.py
│   │   ├── models.py
│   │   ├── tui/
│   │   └── ...
│   ├── docker/
│   │   ├── docker-compose.yml
│   │   └── ...
│   ├── tests/
│   ├── pyproject.toml
│   └── README.md
├── ai_orchestrator/
│   ├── ai_orchestrator/            # Python package
│   │   ├── __init__.py
│   │   ├── cli_manager.py
│   │   ├── model_manager.py
│   │   └── ...
│   ├── tests/
│   ├── pyproject.toml
│   └── README.md
├── examples/
│   ├── basic_task_assignment.py
│   ├── multi_agent_workflow.py
│   └── local_llm_routing.py
├── docker/
│   ├── docker-compose.full.yml     # All services
│   └── ...
├── .gitignore
├── .dockerignore
├── README.md                        # Main project README
├── LICENSE
└── CONTRIBUTING.md
```

---

## Migration Steps

### Option A: New Repo with History Preservation

```bash
# 1. Create new repo on GitHub
# (Do this via GitHub web UI: https://github.com/new)
# Name: ai-orchestrator-system (or your preference)

# 2. Clone current repo to new location
cd ~/src
git clone ~/src/scripts ai-orchestrator-system
cd ai-orchestrator-system

# 3. Filter to only keep relevant modules
git filter-repo --path modules/knowledge_manager/ --path modules/ai_orchestrator/ --path-rename modules/:

# 4. Restructure (move files)
mkdir -p knowledge_manager ai_orchestrator docs/research
mv knowledge_manager/knowledge_manager knowledge_manager/  # Python package
mv knowledge_manager/research-output/* docs/research/
# ... continue restructuring

# 5. Create main README
cat > README.md << 'EOF'
# AI Orchestrator System

Multi-agent orchestration system for coordinating AI coding CLIs with PostgreSQL task queuing and local LLM routing.

[Full README content here]
EOF

# 6. Add remote and push
git remote add origin https://github.com/YOUR_USERNAME/ai-orchestrator-system.git
git push -u origin main
```

### Option B: Fresh Start (Simpler)

```bash
# 1. Create new repo on GitHub

# 2. Create new directory
cd ~/src
mkdir ai-orchestrator-system
cd ai-orchestrator-system
git init

# 3. Copy files from old repo
cp -r ~/src/scripts/modules/knowledge_manager ./knowledge_manager
cp -r ~/src/scripts/modules/ai_orchestrator ./ai_orchestrator

# 4. Clean up
rm -rf knowledge_manager/__pycache__
rm -rf knowledge_manager/.pytest_cache

# 5. Create structure
mkdir -p docs/research docs/architecture docs/guides

# 6. Move research docs
mv knowledge_manager/research-output/* docs/research/

# 7. Create main README and commit
# ... (create files)

# 8. Push
git remote add origin https://github.com/YOUR_USERNAME/ai-orchestrator-system.git
git add .
git commit -m "Initial commit: AI Orchestrator System"
git push -u origin main
```

---

## Recommended Approach

**Go with Option B (Fresh Start)** because:
- ✅ Cleaner structure from the start
- ✅ No git filter-repo complexity
- ✅ Can reorganize files properly
- ❌ Loses git history (but it's mostly from scripts repo anyway)

---

## Post-Migration Tasks

1. **Update original scripts repo**:
   ```bash
   # Add README pointing to new repo
   echo "# Moved to https://github.com/YOUR_USERNAME/ai-orchestrator-system" > modules/knowledge_manager/MOVED.md
   git rm -r modules/knowledge_manager/docker modules/ai_orchestrator
   git commit -m "Migrate ai-orchestrator-system to standalone repo"
   ```

2. **Set up CI/CD** in new repo:
   - GitHub Actions for pytest
   - Docker image builds
   - Automated testing

3. **Create comprehensive README** with:
   - Architecture diagram
   - Quick start guide
   - Feature roadmap
   - Contributing guidelines

4. **Add Docker multi-service setup**:
   - PostgreSQL + pgAdmin
   - Optional: pgloader service
   - Optional: llama.cpp server

5. **Update cross_platform module** (if still needed):
   - Make it a dependency via pip
   - Or vendor it into the new repo

---

## Timeline

**Do this AFTER PostgreSQL migration is working**:
- Phase 3: ✅ PostgreSQL running + migration complete
- Phase 4: ✅ Python code supports PostgreSQL
- Phase 5: ✅ TUI tested with PostgreSQL
- **THEN**: Migrate to new repo
- Phase 6+: Continue in new repo

This way we don't complicate the current migration with a repo move.

---

## GitHub Repository Settings

**Suggested configuration**:
- **Name**: `ai-orchestrator-system`
- **Description**: "Multi-agent orchestration for AI coding CLIs with PostgreSQL, local LLM routing, and real-time task management"
- **Topics**: `multi-agent`, `orchestration`, `postgresql`, `llm`, `docker`, `knowledge-management`, `rtx-5090`
- **License**: MIT (or your preference)
- **Branch protection**: Enable on `main` after initial setup

---

## Files to Keep in Original Repo

These can stay in `~/src/scripts`:
- `cross_platform/` - Shared utility
- `standard_ui/` - Terminal UI components
- Other unrelated modules

---

**End of Migration Plan**
