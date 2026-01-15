"""CLI entry point for translations module."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from .catalog import TranslationCatalog
from .config import PipelineConfig, TranscriberConfig, TranslatorConfig
from .pipeline import run_pipeline, translate_segments
from .transcribers import available_transcribers, get_transcriber
from .translators import available_translators, TranslationUnit, get_translator
from .utils import write_json

app = typer.Typer(add_completion=False, help="Media transcription + translation toolkit")
catalog_app = typer.Typer(add_completion=False, help="Inspect translation catalogs")
app.add_typer(catalog_app, name="catalog")
console = Console()


@app.command()
def info() -> None:
    """List available engines."""
    table = Table(title="Registered engines", box=box.ROUNDED)
    table.add_column("Kind", style="cyan")
    table.add_column("Name", style="magenta")
    table.add_row("Transcribers", ", ".join(sorted(available_transcribers())))
    table.add_row("Translators", ", ".join(sorted(available_translators())))
    console.print(table)


@app.command()
def transcribe(
    source: Path = typer.Argument(..., exists=True, readable=True, help="Video/audio path"),
    model: str = typer.Option("faster-whisper", "--model", "-m", help="Transcriber backend"),
    model_size: str = typer.Option("large-v3", help="Model size"),
    language: Optional[str] = typer.Option(None, "--language", "-l", help="Force source language"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Write JSON result"),
) -> None:
    cfg = TranscriberConfig(name=model, model_size=model_size, language=language)
    transcriber = get_transcriber(cfg)
    result = transcriber.transcribe(source)
    table = Table(title=f"Transcription for {source.name}", box=box.SIMPLE_HEAD)
    table.add_column("Lang")
    table.add_column("Confidence")
    table.add_column("Preview")
    preview = " ".join(seg.text for seg in result.segments[:3])
    table.add_row(result.language, f"{result.confidence:.2%}", preview[:140])
    console.print(table)
    if output:
        payload = {
            "source": str(source),
            "language": result.language,
            "confidence": result.confidence,
            "segments": [seg.__dict__ for seg in result.segments],
        }
        write_json(output, payload)
        console.print(f"[green]Saved transcription -> {output}")


@app.command()
def translate(
    transcript: Path = typer.Argument(..., exists=True, readable=True, help="JSON transcript"),
    translator_name: str = typer.Option("deepl", "--translator", "-t"),
    target_lang: List[str] = typer.Option(["en"], "--target", "-T"),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
) -> None:
    data = json.loads(transcript.read_text(encoding="utf-8"))
    units = [TranslationUnit(text=seg["text"], source_language=data["language"]) for seg in data["segments"]]
    cfg = TranslatorConfig(name=translator_name, target_languages=target_lang)
    translations = {}
    for lang in target_lang:
        cfg_lang = TranslatorConfig(**{**cfg.__dict__, "target_languages": [lang]})
        translator = get_translator(cfg_lang)
        translations[lang] = translator.translate(units)
    for lang, res in translations.items():
        console.rule(f"{lang} translation")
        console.print("\n".join(res.lines[:10]))
    if output:
        payload = {lang: res.lines for lang, res in translations.items()}
        write_json(output, payload)
        console.print(f"[green]Saved translations -> {output}")


@app.command()
def pipeline(
    sources: List[Path] = typer.Argument(..., help="Media files or directories"),
    tmp_dir: Path = typer.Option(Path("./.translations_tmp"), "--tmp-dir"),
    catalog_path: Optional[Path] = typer.Option(None, "--catalog"),
    translator_name: str = typer.Option("deepl", "--translator"),
    translator_targets: List[str] = typer.Option(["en"], "--target"),
    transcriber_name: str = typer.Option("faster-whisper", "--transcriber"),
    transcriber_model: str = typer.Option("large-v3", "--transcriber-model"),
    export_json: bool = typer.Option(True, help="Write translation.json outputs"),
) -> None:
    cfg = PipelineConfig(
        sources=[Path(p) for p in sources],
        tmp_dir=tmp_dir,
        catalog_path=catalog_path,
        transcriber=TranscriberConfig(name=transcriber_name, model_size=transcriber_model),
        translator=TranslatorConfig(name=translator_name, target_languages=translator_targets),
        export_json=export_json,
    )
    artifacts = run_pipeline(cfg)
    console.print(f"[green]Processed {len(artifacts)} file(s)")


@catalog_app.command("stats")
def catalog_stats(path: Path = typer.Argument(..., exists=True, readable=True)) -> None:
    catalog = TranslationCatalog(path)
    by_lang: Dict[str, int] = {}
    for entry in catalog.entries:
        by_lang[entry.target_language] = by_lang.get(entry.target_language, 0) + 1
    table = Table(title=f"Catalog: {path}", box=box.SIMPLE_HEAD)
    table.add_column("Language")
    table.add_column("Entries")
    for lang, count in sorted(by_lang.items()):
        table.add_row(lang, str(count))
    console.print(table)


@catalog_app.command("search")
def catalog_search(
    path: Path = typer.Argument(..., exists=True, readable=True),
    snippet: str = typer.Argument(..., help="Snippet to match"),
    target_language: str = typer.Option("en", "--target"),
) -> None:
    catalog = TranslationCatalog(path)
    entry = catalog.find_similar(snippet, target_language)
    if not entry:
        console.print("[yellow]No match found")
        raise typer.Exit(code=1)
    console.print(json.dumps(entry.__dict__, ensure_ascii=False, indent=2))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
