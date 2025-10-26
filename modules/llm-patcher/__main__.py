# Absolute import so `python -m llm-patcher` style invocations work in both modes.
from cli import main

if __name__ == "__main__":
    raise SystemExit(main())
