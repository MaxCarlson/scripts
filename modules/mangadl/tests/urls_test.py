from pathlib import Path

import pytest

from mangadl.cli import build_parser, main


def test_urls_command_is_registered() -> None:
    args = build_parser(["urls"]).parse_args(["urls", "-p", "urls*.txt"])

    assert args.command == "urls"
    assert args.output == Path("all-url-files.txt")
    assert args.apply is False
    assert args.keep_duplicates is False


def test_urls_dry_run_lists_matched_files_without_writing(
    tmp_path: Path, capsys
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    first = source / "urls1.txt"
    second = source / "urls2.txt"
    other = source / "notes.txt"
    first.write_text("https://example.com/one\n", encoding="utf-8")
    second.write_text("https://example.com/two\n", encoding="utf-8")
    other.write_text("https://example.com/other\n", encoding="utf-8")
    output = source / "all-url-files.txt"

    result = main(["urls", "-d", str(source), "-p", "urls*.txt"])

    assert result == 0
    assert not output.exists()
    rendered = capsys.readouterr().out
    assert str(first) in rendered
    assert str(second) in rendered
    assert str(other) not in rendered
    assert str(output) in rendered


def test_urls_apply_writes_stable_unique_urls_in_input_folder(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "urls1.txt").write_text(
        " https://example.com/one \n\nhttps://example.com/two\n", encoding="utf-8"
    )
    (source / "urls2.txt").write_text(
        "https://example.com/one\nhttps://example.com/three\n", encoding="utf-8"
    )

    result = main(
        ["urls", "-d", str(source), "-p", "urls*.txt", "-o", "combined.txt", "-f"]
    )

    assert result == 0
    assert (source / "combined.txt").read_text(encoding="utf-8") == (
        "https://example.com/one\nhttps://example.com/two\nhttps://example.com/three\n"
    )


def test_urls_explicit_relative_output_path_uses_working_directory(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "urls1.txt").write_text("https://example.com/one\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = main(
        ["urls", "-d", str(source), "-p", "urls*.txt", "-o", "out/combined.txt", "-f"]
    )

    assert result == 0
    assert (tmp_path / "out" / "combined.txt").read_text(
        encoding="utf-8"
    ) == "https://example.com/one\n"


def test_urls_repeated_patterns_write_to_absolute_output_path(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "urls1.txt").write_text("https://example.com/one\n", encoding="utf-8")
    (source / "extra.txt").write_text("https://example.com/two\n", encoding="utf-8")
    output = tmp_path / "merged" / "combined.txt"

    result = main(
        [
            "urls",
            "-d",
            str(source),
            "-p",
            "urls*.txt",
            "-p",
            "extra.txt",
            "-o",
            str(output),
            "-f",
        ]
    )

    assert result == 0
    assert output.read_text(encoding="utf-8") == (
        "https://example.com/one\nhttps://example.com/two\n"
    )


def test_urls_refuses_output_that_matches_an_input_file(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    first = source / "urls1.txt"
    second = source / "urls2.txt"
    first.write_text("https://example.com/one\n", encoding="utf-8")
    second.write_text("https://example.com/two\n", encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        main(["urls", "-d", str(source), "-p", "*.txt", "-o", "urls1.txt", "-f"])

    assert error.value.code == 2
    assert first.read_text(encoding="utf-8") == "https://example.com/one\n"


def test_urls_keep_duplicates_when_requested(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "urls1.txt").write_text(
        "https://example.com/one\nhttps://example.com/one\n", encoding="utf-8"
    )

    result = main(
        ["urls", "-d", str(source), "-p", "urls*.txt", "-o", "combined.txt", "-K", "-f"]
    )

    assert result == 0
    assert (source / "combined.txt").read_text(encoding="utf-8") == (
        "https://example.com/one\nhttps://example.com/one\n"
    )


def test_urls_no_matching_files_returns_cli_error(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(SystemExit) as error:
        main(["urls", "-d", str(source), "-p", "urls*.txt"])

    assert error.value.code == 2


def test_urls_updates_existing_default_all_url_files_with_new_urls(
    tmp_path: Path, capsys
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    output = source / "all-url-files.txt"
    output.write_text(
        "https://example.com/existing\nhttps://example.com/one\n", encoding="utf-8"
    )
    (source / "urls1.txt").write_text(
        "https://example.com/one\nhttps://example.com/two\n", encoding="utf-8"
    )
    (source / "urls2.txt").write_text(
        "https://example.com/two\nhttps://example.com/three\n", encoding="utf-8"
    )

    # Dry-run previews the update without modifying the existing file
    assert main(["urls", "-d", str(source), "-p", "urls*.txt"]) == 0
    dry_out = capsys.readouterr().out
    assert "Existing URLs in output: 2" in dry_out
    assert "New URLs to add: 2" in dry_out
    assert output.read_text(encoding="utf-8") == (
        "https://example.com/existing\nhttps://example.com/one\n"
    )

    # Apply updates the existing file with new unique URLs
    assert main(["urls", "-d", str(source), "-p", "urls*.txt", "-f"]) == 0
    assert output.read_text(encoding="utf-8") == (
        "https://example.com/existing\n"
        "https://example.com/one\n"
        "https://example.com/two\n"
        "https://example.com/three\n"
    )


def test_urls_updates_existing_explicit_output_with_keep_duplicates(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "custom.txt"
    output.write_text("https://example.com/one\n", encoding="utf-8")
    (source / "urls1.txt").write_text(
        "https://example.com/one\nhttps://example.com/two\nhttps://example.com/two\n",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "urls",
                "-d",
                str(source),
                "-p",
                "urls*.txt",
                "-o",
                str(output),
                "-K",
                "-f",
            ]
        )
        == 0
    )
    assert output.read_text(encoding="utf-8") == (
        "https://example.com/one\nhttps://example.com/two\nhttps://example.com/two\n"
    )
