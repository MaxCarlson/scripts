"""Read-only Task Scheduler Operational Event Log collector and XML parser."""

from __future__ import annotations

import logging
import threading
import xml.etree.ElementTree as ET

from procwatch.collectors.sysmon_evt import (
    ChannelCheckResult,
    _classify_evt_error,
    _find_attr,
    _find_text,
    _safe_int,
)
from procwatch.models import (
    EdgeRelation,
    EvidenceEdge,
    IngestGap,
    RawEventRecord,
    TaskTriggerInfo,
    utc_now_iso,
)
from procwatch.redactor import Redactor
from procwatch.storage import FlightRecorderStorage

logger = logging.getLogger(__name__)

TASK_SCHEDULER_CHANNEL = "Microsoft-Windows-TaskScheduler/Operational"
_EVENT_NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
_TRACKED_TASK_EVENT_IDS = (100, 129, 200, 201)


def parse_task_event_xml(xml_str: str) -> TaskTriggerInfo | None:
    """Parse Task Scheduler Event ID 100/129/200/201 XML into TaskTriggerInfo."""
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return None

    event_id = _safe_int(_find_text(root, "./e:System/e:EventID"))
    if event_id not in _TRACKED_TASK_EVENT_IDS:
        return None

    record_id = _find_text(root, "./e:System/e:EventRecordID")
    event_ts = _find_attr(root, "./e:System/e:TimeCreated", "SystemTime") or utc_now_iso()

    data_map: dict[str, str] = {}
    for elem in root.findall("./e:EventData/e:Data", _EVENT_NS) or root.findall("./EventData/Data"):
        name = elem.attrib.get("Name")
        if name:
            data_map[name] = (elem.text or "").strip()

    task_name = data_map.get("TaskName") or data_map.get("Name") or ""
    if not task_name:
        return None

    action_exe = data_map.get("Path") or data_map.get("ActionName") or None
    return TaskTriggerInfo(
        task_path=task_name,
        event_id=event_id,
        instance_guid=data_map.get("InstanceId") or None,
        action_exe=action_exe,
        action_args=data_map.get("Arguments") or None,
        process_id=_safe_int(data_map.get("ProcessID") or data_map.get("ProcessId")),
        engine_pid=_safe_int(data_map.get("EnginePID") or data_map.get("TaskEngineProcessID")),
        result_code=_safe_int(data_map.get("ResultCode")),
        ts_utc=event_ts,
        source_record_id=record_id,
    )


def check_task_scheduler_channel(channel: str = TASK_SCHEDULER_CHANNEL) -> ChannelCheckResult:
    """Read-only check whether the Task Scheduler Operational channel is readable."""
    try:
        import win32evtlog  # type: ignore[import-untyped]
    except ImportError:
        return ChannelCheckResult(
            channel=channel,
            available=False,
            status="unavailable",
            coverage_state="unavailable",
            detail="pywin32 win32evtlog not installed",
        )

    try:
        handle = win32evtlog.EvtQuery(
            channel,
            win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryReverseDirection,
            "*[System[(EventID=100 or EventID=129 or EventID=200 or EventID=201)]]",
        )
        del handle
        return ChannelCheckResult(
            channel=channel,
            available=True,
            status="active",
            coverage_state="live",
            detail="Task Scheduler Operational channel readable",
        )
    except Exception as exc:
        status, coverage, detail = _classify_evt_error(exc)
        return ChannelCheckResult(
            channel=channel,
            available=False,
            status=status,
            coverage_state=coverage,
            detail=detail,
        )


class TaskSchedulerCollector:
    """Incremental, bookmark-checkpointed Task Scheduler Operational Event Log collector."""

    source_name = "task_events"

    def __init__(
        self,
        storage: FlightRecorderStorage,
        *,
        boot_id: str,
        channel: str = TASK_SCHEDULER_CHANNEL,
        redactor: Redactor | None = None,
        poll_interval_sec: float = 3.0,
    ) -> None:
        self._storage = storage
        self._boot_id = boot_id
        self._channel = channel
        self._redactor = redactor or Redactor()
        self._poll_interval_sec = poll_interval_sec
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start background polling for Task Scheduler Operational events."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="procwatch-task-events",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_sec: float = 3.0) -> None:
        """Stop background polling."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_sec)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.poll_once()
            self._stop_event.wait(self._poll_interval_sec)

    def poll_once(self, max_events: int = 200) -> int:
        """Read available Task Scheduler events incrementally and persist edges/raw logs."""
        try:
            import win32evtlog  # type: ignore[import-untyped]
        except ImportError:
            self._storage.update_collector_state(
                source=self.source_name,
                status="unavailable",
                coverage_state="unavailable",
                last_error="pywin32 win32evtlog not installed",
            )
            return 0

        state_rows = self._storage.get_collector_state(self.source_name)
        bookmark_xml = state_rows[0]["evt_bookmark_xml"] if state_rows else None
        bookmark_handle = None
        if bookmark_xml:
            try:
                bookmark_handle = win32evtlog.EvtCreateBookmark(bookmark_xml)
            except Exception as exc:
                self._storage.record_ingest_gap(
                    IngestGap(
                        source=self.source_name,
                        reason=f"invalid_bookmark: {exc}",
                    )
                )
                bookmark_handle = None

        query_flags = win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryForwardDirection
        xpath = "*[System[(EventID=100 or EventID=129 or EventID=200 or EventID=201)]]"
        try:
            query_handle = win32evtlog.EvtQuery(self._channel, query_flags, xpath)
            if bookmark_handle is not None:
                try:
                    win32evtlog.EvtSeek(
                        query_handle,
                        1,
                        bookmark_handle,
                        0,
                        win32evtlog.EvtSeekRelativeToBookmark,
                    )
                except Exception as exc:
                    self._storage.record_ingest_gap(
                        IngestGap(
                            source=self.source_name,
                            reason=f"stale_bookmark_or_cleared_log: {exc}",
                        )
                    )
                    bookmark_handle = win32evtlog.EvtCreateBookmark(None)
                    query_handle = win32evtlog.EvtQuery(self._channel, query_flags, xpath)
            else:
                bookmark_handle = win32evtlog.EvtCreateBookmark(None)
        except Exception as exc:
            status, coverage, detail = _classify_evt_error(exc)
            self._storage.update_collector_state(
                source=self.source_name,
                status=status,
                coverage_state=coverage,
                last_error=detail,
            )
            return 0

        raw_records: list[RawEventRecord] = []
        parsed_events: list[TaskTriggerInfo] = []
        try:
            while len(raw_records) < max_events:
                batch = win32evtlog.EvtNext(query_handle, min(50, max_events - len(raw_records)), 0)
                if not batch:
                    break
                for evt in batch:
                    xml_str = win32evtlog.EvtRender(evt, win32evtlog.EvtRenderEventXml)
                    parsed = parse_task_event_xml(xml_str)
                    if parsed is not None:
                        parsed_events.append(parsed)
                        raw_records.append(
                            RawEventRecord(
                                boot_id=self._boot_id,
                                source=self.source_name,
                                provider_event_id=parsed.event_id,
                                source_record_id=parsed.source_record_id,
                                event_ts_utc=parsed.ts_utc,
                                payload_redacted=self._redactor.redact_text(xml_str).text,
                            )
                        )
                    win32evtlog.EvtUpdateBookmark(bookmark_handle, evt)
            new_bookmark = win32evtlog.EvtRender(bookmark_handle, win32evtlog.EvtRenderBookmark)
        except Exception as exc:
            status, coverage, detail = _classify_evt_error(exc)
            self._storage.update_collector_state(
                source=self.source_name,
                status=status,
                coverage_state=coverage,
                last_error=detail,
            )
            return 0

        if raw_records:
            _, raw_ids = self._storage.ingest_event_batch(
                source=self.source_name,
                events=raw_records,
                new_bookmark_xml=new_bookmark,
                status="active",
                coverage_state="live",
                last_error=None,
            )
            for idx, parsed in enumerate(parsed_events):
                raw_id = raw_ids[idx] if idx < len(raw_ids) else None
                self._persist_task_edge(parsed, raw_id=raw_id)
        else:
            self._storage.update_collector_state(
                source=self.source_name,
                status="active",
                coverage_state="live",
                last_error=None,
            )
        return len(raw_records)

    def _persist_task_edge(self, info: TaskTriggerInfo, *, raw_id: int | None = None) -> None:
        if info.process_id is None:
            return
        proc_row = self._storage.get_process_by_pid(info.process_id)
        target_node = proc_row["proc_key"] if proc_row else f"pid:{self._boot_id}:{info.process_id}"
        self._storage.insert_edge(
            EvidenceEdge(
                from_node_id=target_node,
                to_node_id=f"task:{info.task_path}",
                relation=EdgeRelation.TRIGGERED_BY,
                source=self.source_name,
                method=f"task_event_{info.event_id}",
                confidence=0.92,
                supporting_raw_ids=[raw_id] if raw_id is not None else [],
                notes=info.action_exe or "",
            )
        )
