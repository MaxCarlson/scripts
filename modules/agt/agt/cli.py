# agt/cli.py
from __future__ import annotations
import argparse, os, sys, json, time, logging
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import EnforcedArgumentParser with fallback
try:
    from argparse_enforcer import EnforcedArgumentParser
    ENFORCER_AVAILABLE = True
except ImportError:
    EnforcedArgumentParser = argparse.ArgumentParser
    ENFORCER_AVAILABLE = False

from .client import WebAIClient, DEFAULT_URL
from .ingest import materialize_at_refs, render_attachments_block
from .sessions import load_session, append_session

LOG = logging.getLogger("agt")

def setup_logging(level: int=logging.INFO, logfile: Optional[str]=None):
    handlers = [logging.StreamHandler(sys.stderr)]
    if logfile:
        Path(logfile).expanduser().parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(logfile, encoding="utf-8"))
    logging.basicConfig(level=level, format="%(asctime)s | %(levelname)s | %(name)s: %(message)s", handlers=handlers)

def read_prompt_arg(val: str) -> str:
    p = Path(val)
    if p.exists() and p.is_file():
        return p.read_text(encoding="utf-8", errors="replace")
    return val

def build_messages(user_text: str, *, cwd: Path, attach_root_hint: Optional[str], model: str,
                   session_msgs: Optional[List[Dict[str,Any]]] = None) -> List[Dict[str,Any]]:
    clean, files = materialize_at_refs(user_text, cwd=cwd)
    preface = render_attachments_block(files, root_hint=str(cwd) if attach_root_hint is None else attach_root_hint)
    msgs: List[Dict[str,Any]] = []
    if session_msgs:
        msgs.extend(session_msgs)
    if preface.strip():
        msgs.append({"role":"system","content":preface})
    msgs.append({"role":"user","content":clean})
    return msgs

def spinner(label="thinking"):
    frames = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
    i = 0
    while True:
        yield f"{frames[i%len(frames)]} {label}..."
        i += 1

# ---------- one-shot (used by tests)

def one_shot(client: WebAIClient, *, text: str, model: str, session: Optional[str],
             stream: bool, verbose: bool, cwd: Path, attach_root_hint: Optional[str], log_events: bool) -> int:
    sess_msgs = load_session(session) if session else None
    messages = build_messages(text, cwd=cwd, attach_root_hint=attach_root_hint, model=model, session_msgs=sess_msgs)

    if log_events:
        LOG.info("POST /v1/chat/completions model=%s", model)

    if stream:
        spin = spinner()
        sys.stderr.write(next(spin))
        sys.stderr.flush()
        for ev in client.chat_stream_events(messages, model=model):
            if ev.get("event") == "content":
                sys.stderr.write("\r" + " " * 80 + "\r"); sys.stderr.flush()
                sys.stdout.write(ev.get("text","")); sys.stdout.flush()
            elif ev.get("event") == "done":
                sys.stdout.write("\n"); break
            else:
                sys.stderr.write("\r" + next(spin)); sys.stderr.flush()
        reply_text = ""
    else:
        obj = client.chat_once(messages, model=model, stream=False)
        ch = obj.get("choices", [{}])[0]
        reply_text = ch.get("message", {}).get("content", "") or ""
        print(reply_text)

    if session:
        append_session(session, {"role":"user","content":text})
        append_session(session, {"role":"assistant","content":reply_text})

    return 0

# ---------- REPL/TUI

def repl(client: WebAIClient, *, model: str, session: Optional[str],
         cwd: Path, attach_root_hint: Optional[str], log_events: bool):
    os.system("cls" if os.name == "nt" else "clear")
    print(f"agt — Gemini client  (server: {client.base_url}, model: {model})")
    print("Type @path / @glob / @folder to attach files. Ctrl+C to exit.\n")

    sess_msgs = load_session(session) if session else None
    while True:
        try:
            user = input("> ").rstrip("\n")
        except KeyboardInterrupt:
            print(); break
        if not user.strip():
            continue
        if user.strip() in {"/quit","/exit"}:
            break

        messages = build_messages(user, cwd=cwd, attach_root_hint=attach_root_hint, model=model, session_msgs=sess_msgs)

        if log_events:
            LOG.info("POST /v1/chat/completions model=%s", model)

        spin = spinner()
        sys.stderr.write(next(spin)); sys.stderr.flush()
        obj = client.chat_once(messages, model=model, stream=False)
        sys.stderr.write("\r" + " " * 80 + "\r"); sys.stderr.flush()
        ch = obj.get("choices", [{}])[0]
        reply = ch.get("message",{}).get("content","") or ""
        print(reply)

        if session:
            append_session(session, {"role":"user","content":user})
            append_session(session, {"role":"assistant","content":reply})
            if sess_msgs is None: sess_msgs = []
            sess_msgs.append({"role":"user","content":user})
            sess_msgs.append({"role":"assistant","content":reply})

def build_parser() -> argparse.ArgumentParser:
    p = EnforcedArgumentParser(prog="agt", description="AI tools.")
    sub = p.add_subparsers(dest="sub", required=True)

    g = sub.add_parser("gemini", help="Interact with a WebAI-to-API server (Gemini).")
    g.add_argument("-u", "--url", default=DEFAULT_URL, help=f"Server base URL (default: {DEFAULT_URL})")
    g.add_argument("-m", "--model", default=os.environ.get("AGT_MODEL","gemini-2.0-flash"),
                   help="Model name (default: env AGT_MODEL or gemini-2.0-flash)")
    g.add_argument("-p", "--prompt", help="Prompt text OR path to a file containing the prompt.")
    g.add_argument("-s", "--stream", action="store_true", help="Stream assistant output.")
    g.add_argument("-S", "--session", help="Resume/save conversation under this name.")
    g.add_argument("-n", "--new-session", action="store_true", help="Start fresh even if session exists.")
    g.add_argument("-a", "--attach-root-hint", default=None, help="Shown in the ReadManyFiles header. Default: CWD.")
    g.add_argument("-i", "--ui", choices=["tui","repl"], default="tui", help="Choose interface (default: tui).")
    g.add_argument("-v", "--verbose", action="store_true", help="Verbose logging to stderr.")
    g.add_argument("-l", "--log", default=str((Path.home()/".config/agt/agt.log") if os.name!="nt" else (Path.home()/"AppData/Roaming/agt/agt.log")),
                   help="Log file path (default: ~/.config/agt/agt.log)")
    g.add_argument("message", nargs="*", help="Prompt text (if -p not used).")

    return p

def main(argv: Optional[List[str]]=None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(logging.DEBUG if args.verbose else logging.INFO, logfile=args.log)

    if args.sub == "gemini":
        client = WebAIClient(args.url)

        if args.new_session and args.session:
            from .sessions import session_path
            sp = session_path(args.session); sp.parent.mkdir(parents=True, exist_ok=True)
            if sp.exists(): sp.unlink()

        if args.prompt:
            prompt_text = read_prompt_arg(args.prompt)
        else:
            prompt_text = " ".join(args.message).strip()

        if args.ui == "tui" and not prompt_text:
            # full TUI (Gemini-like)
            from .tui import TUI
            TUI(client, model=args.model, provider=None, stream=True, thinking=True, verbose=args.verbose).run()
            return 0

        cwd = Path.cwd()
        if prompt_text:
            return one_shot(
                client, text=prompt_text, model=args.model, session=args.session,
                stream=args.stream, verbose=args.verbose, cwd=cwd,
                attach_root_hint=args.attach_root_hint, log_events=True
            )
        else:
            repl(client, model=args.model, session=args.session,
                 cwd=cwd, attach_root_hint=args.attach_root_hint, log_events=True)
            return 0

    print("No subcommand. Try: agt gemini -h", file=sys.stderr)
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
