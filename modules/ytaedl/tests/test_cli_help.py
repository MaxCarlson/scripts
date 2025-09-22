import io
import sys

import ytaedl.dlscript as dls
import ytaedl.dlmanager as dlm


def _capture_help(fn):
    buf = io.StringIO()
    old = sys.stdout
    try:
        sys.stdout = buf
        p = fn()
        p.print_help()
    finally:
        sys.stdout = old
    out = buf.getvalue()
    assert "usage:" in out.lower()


def test_dlscript_help():
    _capture_help(dls.make_parser)


def test_dlmanager_help():
    _capture_help(dlm.make_parser)

