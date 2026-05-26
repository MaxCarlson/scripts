<!-- version: 0.3.3 -->
# Web Docs Processor

Build retrieval-friendly Markdown, JSON, and PDF source packs from documentation
websites, GitHub wikis, and docs sidebars.

The normal install path is intentionally full-featured:

```powershell
python -m pip install -e modules/web_docs_processor
```

The editable install installs Python dependencies and attempts to install
Playwright's Chromium browser runtime. Set `WDP_SKIP_PLAYWRIGHT_INSTALL=1` only
when you explicitly need to skip browser setup in a constrained environment.

PDF export uses ReportLab so the default install stays pip-installable on
Windows, WSL2, and Termux without native GTK/Pango setup.

Useful commands:

```powershell
wdp --help
wdp doctor
wdp setup-browsers
wdp discover -u "https://developers.openai.com/codex/skills" -o ".\out\codex-skills-candidates.txt"
wdp build -u "https://developers.openai.com/codex/skills" -f markdown -o ".\out\codex-skills.md" -t "OpenAI Codex Skills Documentation"
```
