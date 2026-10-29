from llm_monitor.cli import build_parser


def test_watch_accepts_session_json_and_interval_options():
    args = build_parser().parse_args(
        ["watch", "--session", "ses-1", "--format", "json", "--interval", "0.5"]
    )

    assert args.command == "watch"
    assert args.session == "ses-1"
    assert args.format == "json"
    assert args.interval == 0.5
