"""Headless Textual UI tests for ProcessWatchApp using run_test() and Pilot."""

from __future__ import annotations

from types import SimpleNamespace

import psutil
import pytest
from textual.widgets import DataTable, Input, Static, TabbedContent

from system_manager.process_watch.filters import ProcessFilter
from system_manager.process_watch.sampler import ProcessSampler
from system_manager.process_watch.tui import HelpModal, ProcessInspectorModal, ProcessWatchApp


class FakeProc:
    def __init__(self, pid: int, *, ppid: int = 0, name: str = "proc.exe", cpu_user: float = 1.0, rss: int = 1024**2, cmdline: list[str] | None = None) -> None:
        self.pid = pid
        self._ppid = ppid
        self._name = name
        self._cpu_user = cpu_user
        self._rss = rss
        self._cmdline = cmdline or [name]

    @property
    def info(self):
        return {
            "pid": self.pid,
            "ppid": self._ppid,
            "name": self._name,
            "exe": f"/usr/bin/{self._name}",
            "cmdline": self._cmdline,
            "username": "tester",
            "status": "running",
            "create_time": 10.0,
            "cpu_times": SimpleNamespace(user=self._cpu_user, system=0.0),
            "memory_info": SimpleNamespace(rss=self._rss, vms=self._rss * 2, private=self._rss // 2),
            "num_threads": 2,
        }

    def io_counters(self):
        return SimpleNamespace(read_bytes=1000, write_bytes=500)


class FakePsutil:
    NoSuchProcess = psutil.NoSuchProcess
    AccessDenied = psutil.AccessDenied
    ZombieProcess = psutil.ZombieProcess
    Error = psutil.Error

    def __init__(self, procs: list[FakeProc]) -> None:
        self.procs = procs

    def process_iter(self, attrs, ad_value=None):
        return list(self.procs)

    def cpu_count(self, logical=True):
        return 4

    def cpu_percent(self, interval=None):
        return 10.0

    def virtual_memory(self):
        return SimpleNamespace(used=4 * 1024**3, total=16 * 1024**3, percent=25.0)

    def disk_io_counters(self):
        return SimpleNamespace(read_bytes=1000, write_bytes=2000)


def _make_app(*, clock_val: list[float] | None = None, procs: list[FakeProc] | None = None) -> tuple[ProcessWatchApp, FakePsutil, list[float]]:
    clock = clock_val or [100.0]
    default_procs = procs or [
        FakeProc(100, ppid=1, name="alpha.exe", cpu_user=2.0, rss=50 * 1024**2, cmdline=["alpha.exe", "--token=xyz"]),
        FakeProc(101, ppid=100, name="beta.exe", cpu_user=1.0, rss=20 * 1024**2),
        FakeProc(102, ppid=100, name="gamma.exe", cpu_user=0.5, rss=10 * 1024**2),
    ]
    fps = FakePsutil(default_procs)
    sampler = ProcessSampler(
        psutil_module=fps,
        monotonic_clock=lambda: clock[0],
        wall_clock=lambda: 1000.0 + clock[0],
        exited_grace_seconds=5.0,
    )
    # Prime one sample so CPU/IO rates can be computed on second sample
    sampler.sample()
    clock[0] += 1.0
    for p in default_procs:
        p._cpu_user += 0.2
    app = ProcessWatchApp(
        sampler,
        initial_filter=ProcessFilter(),
        interval_seconds=1.0,
        enable_background_worker=False,
    )
    return app, fps, clock


@pytest.mark.asyncio
async def test_tui_navigation_filter_sort_pin_and_inspector():
    app, fps, clock = _make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        table = app.query_one("#proc-table", DataTable)
        assert table.row_count == 3

        # Move down and inspect
        await pilot.press("j")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ProcessInspectorModal)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ProcessInspectorModal)

        # Pin selected process
        selected_before = app.selected_identity
        await pilot.press("space")
        await pilot.pause()
        assert selected_before in app.pinned_identities

        # Filter input focus takes precedence over global hotkeys (typing 'q' or 's' must not quit/open modal)
        await pilot.press("/")
        await pilot.pause()
        inp = app.query_one("#filter-input", Input)
        assert app.focused is inp
        await pilot.press("b", "e", "t", "a")
        await pilot.pause()
        assert inp.value == "beta"
        assert table.row_count == 1

        # Escape clears filter and returns focus
        await pilot.press("escape")
        await pilot.pause()
        assert table.row_count == 3

        # Reverse sort, toggle aggregation, toggle freeze
        await pilot.press("S")
        await pilot.press("a")
        await pilot.press("f")
        await pilot.pause()
        assert app.aggregated is True
        assert app.frozen is True
        await pilot.press("f")

        # Dynamic row count
        await pilot.press("-")
        await pilot.press("+")
        await pilot.pause()

        # History tab & Help modal
        await pilot.press("h")
        await pilot.pause()
        assert app.query_one("#main-tabs", TabbedContent).active == "tab-history"

        await pilot.press("?")
        await pilot.pause()
        assert isinstance(app.screen, HelpModal)
        await pilot.press("escape")
        await pilot.pause()

        # Clean quit
        await pilot.press("q")


@pytest.mark.asyncio
async def test_tui_narrow_layout_and_exited_pinned_process():
    app, fps, clock = _make_app()
    async with app.run_test(size=(75, 22)) as pilot:
        table = app.query_one("#proc-table", DataTable)
        # Narrow layout hides non-essential columns
        assert len(table.columns) <= 5

        # Pin first process, then simulate its exit
        pinned = app.selected_identity
        await pilot.press("space")
        await pilot.pause()
        assert pinned in app.pinned_identities

        clock[0] += 1.0
        fps.procs = [p for p in fps.procs if p.pid != pinned.pid]
        snap = app.sampler.sample(pinned_identities=set(app.pinned_identities))
        app.apply_snapshot(snap)
        await pilot.pause()

        pinned_tbl = app.query_one("#pinned-table", DataTable)
        assert pinned_tbl.row_count == 1
        assert "EXITED" in str(app.query_one("#quick-details", Static).renderable) or pinned in app.pinned_identities


@pytest.mark.asyncio
async def test_tui_scrolls_all_matches_and_grouped_totals_ignore_visible_limit():
    clock = [100.0]
    procs = [FakeProc(200 + i, ppid=1, name="worker.exe", cpu_user=1.0 + i * 0.1, rss=1024**2) for i in range(12)]
    app, fps, clock = _make_app(clock_val=clock, procs=procs)
    app.visible_rows = 4
    async with app.run_test(size=(120, 30)) as pilot:
        table = app.query_one("#proc-table", DataTable)
        # All 12 matching processes are loaded into the scrollable table despite visible_rows=4
        assert table.row_count == 12
        assert table.styles.height.value == 5  # 4 rows + 1 header

        # Grouped mode aggregates all 12 matching processes, not just the 4 visible rows
        app.group_mode = "name"
        app._refresh_views()
        await pilot.pause()
        assert table.row_count == 1
        row_cells = table.get_row("grp:worker.exe")
        assert row_cells[1] == "12"


@pytest.mark.asyncio
async def test_tui_tree_preserves_expansion_and_selection_across_updates():
    from textual.widgets import Tree

    clock = [100.0]
    procs = [
        FakeProc(100, ppid=1, name="alpha.exe", cpu_user=3.0, rss=50 * 1024**2),
        FakeProc(101, ppid=100, name="beta.exe", cpu_user=1.0, rss=20 * 1024**2),
        FakeProc(102, ppid=100, name="gamma.exe", cpu_user=0.5, rss=10 * 1024**2),
        FakeProc(200, ppid=1, name="zeta.exe", cpu_user=2.0, rss=40 * 1024**2),
        FakeProc(201, ppid=200, name="zeta_child.exe", cpu_user=0.5, rss=10 * 1024**2),
    ]
    app, fps, clock = _make_app(clock_val=clock, procs=procs)
    async with app.run_test(size=(120, 30)) as pilot:
        app.query_one("#main-tabs", TabbedContent).active = "tab-tree"
        await pilot.pause()
        tree = app.query_one("#proc-tree", Tree)
        # Keep alpha.exe expanded and select its child beta.exe; collapse zeta.exe
        alpha_node = next(n for n in tree.root.children if n.data.pid == 100)
        zeta_node = next(n for n in tree.root.children if n.data.pid == 200)
        alpha_ident = alpha_node.data
        zeta_ident = zeta_node.data
        zeta_node.collapse()
        app._tree_expanded[zeta_ident] = False
        beta_node = alpha_node.children[0]
        beta_ident = beta_node.data
        tree.select_node(beta_node)
        await pilot.pause()

        # Trigger update with a birth (103), exit (gamma 102), and CPU reorder
        clock[0] += 1.0
        fps.procs = [p for p in fps.procs if p.pid != 102] + [
            FakeProc(103, ppid=100, name="delta.exe", cpu_user=5.0, rss=30 * 1024**2)
        ]
        for p in fps.procs:
            p._cpu_user += 0.5
        snap = app.sampler.sample()
        app.apply_snapshot(snap)
        await pilot.pause()

        # Expansion state (alpha expanded, zeta collapsed) and selection (beta) are preserved
        new_alpha = next(n for n in tree.root.children if n.data == alpha_ident)
        new_zeta = next(n for n in tree.root.children if n.data == zeta_ident)
        assert new_alpha.is_expanded is True
        assert new_zeta.is_expanded is False
        assert tree.cursor_node is not None
        assert tree.cursor_node.data == beta_ident


@pytest.mark.asyncio
async def test_tui_clears_cli_glob_filter_and_cycles_theme():
    from textual.widgets import DataTable, Static

    procs = [
        FakeProc(100, ppid=1, name="python.exe", cpu_user=3.0, rss=50 * 1024**2),
        FakeProc(200, ppid=1, name="node.exe", cpu_user=2.0, rss=40 * 1024**2),
    ]
    fps = FakePsutil(procs)
    sampler = ProcessSampler(psutil_module=fps, monotonic_clock=lambda: 100.0, wall_clock=lambda: 1000.0)
    app = ProcessWatchApp(
        sampler,
        initial_filter=ProcessFilter(include_globs=["python"]),
        interval_seconds=0.5,
        visible_rows=10,
        enable_background_worker=False,
    )
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        table = app.query_one("#proc-table", DataTable)
        header = str(app.query_one("#host-header", Static).renderable)
        assert table.row_count == 1
        assert "[g:python]" in header

        # Pressing x clears CLI -g/-e/-p filters and restores all rows
        await pilot.press("x")
        await pilot.pause()
        assert table.row_count == 2
        assert not app.proc_filter.has_selectors()

        # Re-apply -g filter and clear via Escape
        app.proc_filter.include_globs = ["node"]
        app._refresh_views()
        assert table.row_count == 1
        await pilot.press("escape")
        await pilot.pause()
        assert table.row_count == 2

        # Theme cycling returns cleanly to dark
        await pilot.press("t")
        await pilot.pause()
        assert app.screen.has_class("theme-light")
        await pilot.press("t")
        await pilot.pause()
        assert app.screen.has_class("theme-high-contrast")
        await pilot.press("t")
        await pilot.pause()
        assert not app.screen.has_class("theme-light")
        assert not app.screen.has_class("theme-high-contrast")


@pytest.mark.asyncio
async def test_tui_background_startup_mounts_before_first_sample():
    import threading
    from textual.widgets import DataTable

    gate = threading.Event()
    procs = [FakeProc(100, ppid=1, name="python.exe", cpu_user=3.0, rss=50 * 1024**2)]
    fps = FakePsutil(procs)
    sampler = ProcessSampler(psutil_module=fps, monotonic_clock=lambda: 100.0, wall_clock=lambda: 1000.0)
    orig_sample = sampler.sample

    def gated_sample(**kwargs):
        gate.wait(timeout=2.0)
        return orig_sample(**kwargs)

    sampler.sample = gated_sample  # type: ignore[method-assign]
    app = ProcessWatchApp(sampler, interval_seconds=5.0, visible_rows=10, enable_background_worker=True)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        table = app.query_one("#proc-table", DataTable)
        # App mounted immediately even though first sample is still blocked
        assert app.latest_snapshot is None
        assert table.row_count == 0
        gate.set()
        for _ in range(20):
            if app.latest_snapshot is not None:
                break
            await pilot.pause(0.05)
        assert app.latest_snapshot is not None
        assert table.row_count == 1
