#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import io

from procparsers.stream import iter_parsed_events


def test_iter_parsed_events_stops_at_stream_eof():
    stream = io.StringIO('{"event":"complete","file_size":12345}\n')

    events = list(iter_parsed_events("aebndl", stream, heartbeat_secs=0.01))

    assert events == [{"event": "complete", "file_size": 12345}]
