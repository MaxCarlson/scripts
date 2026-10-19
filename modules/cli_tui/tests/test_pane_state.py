import argparse
from cli_tui.schema import introspect_parser
from cli_tui.state import (
    FormState,
    PaneType,
    PaneWorkspace,
    copy_matching_form_values,
)


def test_pane_workspace_lifecycle():
    ws = PaneWorkspace()
    assert len(ws.panes) == 1
    assert ws.active_index == 0
    p1 = ws.active_pane
    assert p1.title == "Main"
    assert p1.pane_type == PaneType.COMMAND

    # Add second pane
    p2 = ws.create_pane(title="compress plan", pane_type=PaneType.COMMAND)
    assert len(ws.panes) == 2
    assert ws.active_index == 1
    assert ws.active_pane == p2

    # Cycling
    ws.cycle_prev()
    assert ws.active_index == 0
    ws.cycle_next()
    assert ws.active_index == 1

    # Deletion
    assert ws.delete_pane(1) is True
    assert len(ws.panes) == 1
    assert ws.active_index == 0


def test_copy_matching_form_values():
    p1 = argparse.ArgumentParser()
    p1.add_argument("-d", "--destination", default="default_dest")
    p1.add_argument("-w", "--workspace", default="./")
    p1.add_argument("-s", "--sample-size", type=int, default=10)
    cmd1 = introspect_parser(p1)
    form1 = FormState(cmd1)
    form1.set_value("destination", "custom_dest")
    form1.set_value("workspace", "/custom/work")
    form1.set_value("sample_size", 50)

    p2 = argparse.ArgumentParser()
    p2.add_argument("-d", "--destination", default="")
    p2.add_argument("-w", "--workspace", default="")
    p2.add_argument("-t", "--threads", type=int, default=4)
    cmd2 = introspect_parser(p2)
    form2 = FormState(cmd2)

    copied = copy_matching_form_values(form1, form2)
    assert copied == 2
    assert form2.get_value("destination") == "custom_dest"
    assert form2.get_value("workspace") == "/custom/work"
    assert form2.get_value("threads") == 4
