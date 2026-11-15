"""Read-only Sysmon Operational Event Log collector and XML parser."""

from __future__ import annotations

import logging
import os
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from procwatch.models import (
    CapabilityFlags,
    EdgeRelation,
    EvidenceEdge,
    IngestGap,
    ProcessIdentity,
    ProcessObservation,
    RawEventRecord,
    utc_now_iso,
)
from procwatch.redactor import Redactor
from procwatch.storage import FlightRecorderStorage

logger = logging.getLogger(__name__)

SYSMON_CHANNEL = "Microsoft-Windows-Sysmon/Operational"
_EVENT_NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
_ERR_ACCESS_DENIED = 5
_ERR_EVT_CHANNEL_NOT_FOUND = 15007
_ERR_EVT_INVALID_BOOKMARK = 15008
_ERR_EVT_STALE = 15011


@dataclass(slots=True)
class SysmonEventData:
    """Structured fields parsed from a Sysmon Operational XML event."""

    event_id: int
    record_id: str
    event_ts_utc: str
    computer: str
    process_guid: str | None = None
    pid: int | None = None
    image_path: str | None = None
    command_line: str | None = None
    current_directory: str | None = None
    user: str | None = None
    parent_guid: str | None = None
    ppid: int | None = None
    parent_image: str | None = None
    parent_command_line: str | None = None
    integrity_level: str | None = None
    raw_xml: str = ""


@dataclass(slots=True)
class ChannelCheckResult:
    """Read-only probe status for a Windows Event Log channel."""

    channel: str
    available: bool
    status: str  # active | unavailable | access_denied | error
    coverage_state: str  # live | unavailable | access_denied | unknown
    detail: str = ""


def _safe_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value, 0) if value.lower().startswith("0x") else int(value)
    except ValueError:
        return None


def _find_text(root: ET.Element, path: str) -> str:
    node = root.find(path, _EVENT_NS)
    if node is None:
        # Fallback for XML without namespace declaration in tests.
        plain_path = path.replace("e:", "")
        node = root.find(plain_path)
    return (node.text or "").strip() if node is not None else ""


def _find_attr(root: ET.Element, path: str, attr: str) -> str:
    node = root.find(path, _EVENT_NS)
    if node is None:
        plain_path = path.replace("e:", "")
        node = root.find(plain_path)
    return (node.attrib.get(attr, "") or "").strip() if node is not None else ""


def parse_sysmon_event_xml(xml_str: str) -> SysmonEventData | None:
    """Parse a Sysmon XML event (primarily Event ID 1 and 5) into SysmonEventData."""
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return None

    event_id = _safe_int(_find_text(root, "./e:System/e:EventID"))
    if event_id is None:
        return None
    record_id = _find_text(root, "./e:System/e:EventRecordID")
    event_ts = _find_attr(root, "./e:System/e:TimeCreated", "SystemTime") or utc_now_iso()
    computer = _find_text(root, "./e:System/e:Computer")

    data_map: dict[str, str] = {}
    for elem in root.findall("./e:EventData/e:Data", _EVENT_NS) or root.findall("./EventData/Data"):
        name = elem.attrib.get("Name")
        if name:
            data_map[name] = (elem.text or "").strip()

    image_path = data_map.get("Image") or None
    return SysmonEventData(
        event_id=event_id,
        record_id=record_id,
        event_ts_utc=event_ts,
        computer=computer,
        process_guid=data_map.get("ProcessGuid") or None,
        pid=_safe_int(data_map.get("ProcessId")),
        image_path=image_path,
        command_line=data_map.get("CommandLine") or None,
        current_directory=data_map.get("CurrentDirectory") or None,
        user=data_map.get("User") or None,
        parent_guid=data_map.get("ParentProcessGuid") or None,
        ppid=_safe_int(data_map.get("ParentProcessId")),
        parent_image=data_map.get("ParentImage") or None,
        parent_command_line=data_map.get("ParentCommandLine") or None,
        integrity_level=data_map.get("IntegrityLevel") or None,
        raw_xml=xml_str,
    )


def _classify_evt_error(exc: Exception) -> tuple[str, str, str]:
    winerror = getattr(exc, "winerror", None)
    if winerror is None and exc.args:
        first = exc.args[0]
        if isinstance(first, int):
            winerror = first
    if winerror == _ERR_ACCESS_DENIED:
        return ("degraded", "access_denied", f"access_denied (winerror={winerror})")
    if winerror == _ERR_EVT_CHANNEL_NOT_FOUND:
        return ("unavailable", "unavailable", f"channel_not_found (winerror={winerror})")
    return ("degraded", "unavailable", str(exc))


def check_sysmon_channel(channel: str = SYSMON_CHANNEL) -> ChannelCheckResult:
    """Read-only check whether the Sysmon Operational channel exists and is readable."""
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
            "*[System[(EventID=1 or EventID=5)]]",
        )
        # Close immediately; we only test channel accessibility.
        del handle
        return ChannelCheckResult(
            channel=channel,
            available=True,
            status="active",
            coverage_state="live",
            detail="Sysmon Operational channel readable",
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


class SysmonCollector:
    """Incremental, bookmark-checkpointed Sysmon Operational Event Log collector."""

    source_name = "sysmon_evt"

    def __init__(
        self,
        storage: FlightRecorderStorage,
        *,
        boot_id: str,
        channel: str = SYSMON_CHANNEL,
        redactor: Redactor | None = None,
        poll_interval_sec: float = 2.0,
    ) -> None:
        self._storage = storage
        self._boot_id = boot_id
        self._channel = channel
        self._redactor = redactor or Redactor()
        self._poll_interval_sec = poll_interval_sec
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start background polling for Sysmon Operational events."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="procwatch-sysmon-evt",
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
        """Read available Sysmon events incrementally from saved bookmark and persist them."""
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
        try:
            query_handle = win32evtlog.EvtQuery(
                self._channel,
                query_flags,
                "*[System[(EventID=1 or EventID=5)]]",
            )
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
                    winerr = getattr(exc, "winerror", None)
                    if winerr in (_ERR_EVT_INVALID_BOOKMARK, _ERR_EVT_STALE) or True:
                        self._storage.record_ingest_gap(
                            IngestGap(
                                source=self.source_name,
                                reason=f"stale_bookmark_or_cleared_log: {exc}",
                            )
                        )
                        bookmark_handle = win32evtlog.EvtCreateBookmark(None)
                        query_handle = win32evtlog.EvtQuery(
                            self._channel,
                            query_flags,
                            "*[System[(EventID=1 or EventID=5)]]",
                        )
            elif bookmark_handle is None:
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
        parsed_events: list[SysmonEventData] = []
        try:
            while len(raw_records) < max_events:
                batch = win32evtlog.EvtNext(query_handle, min(50, max_events - len(raw_records)), 0)
                if not batch:
                    break
                for evt in batch:
                    xml_str = win32evtlog.EvtRender(evt, win32evtlog.EvtRenderEventXml)
                    parsed = parse_sysmon_event_xml(xml_str)
                    if parsed is not None:
                        parsed_events.append(parsed)
                        raw_records.append(
                            RawEventRecord(
                                boot_id=self._boot_id,
                                source=self.source_name,
                                provider_event_id=parsed.event_id,
                                source_record_id=parsed.record_id,
                                event_ts_utc=parsed.event_ts_utc,
                                payload_redacted=self._redactor.redact_text(xml_str).text,
                                machine_id=parsed.computer,
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
                self._persist_parsed_event(parsed, raw_id=raw_id)
        else:
            self._storage.update_collector_state(
                source=self.source_name,
                status="active",
                coverage_state="live",
                last_error=None,
            )
        return len(raw_records)

    def _persist_parsed_event(self, evt: SysmonEventData, *, raw_id: int | None = None) -> None:
        if evt.pid is None:
            return
        guid = evt.process_guid or f"rec:{evt.record_id}"
        proc_key = f"sysmon:{self._boot_id}:{evt.pid}:{guid}"
        identity = ProcessIdentity(
            proc_key=proc_key,
            boot_id=self._boot_id,
            pid=evt.pid,
            is_provisional=False,
            sysmon_guid=evt.process_guid,
        )
        image_name = os.path.basename(evt.image_path) if evt.image_path else ""
        redacted_cmd = self._redactor.redact_text(evt.command_line).text if evt.command_line else None
        obs = ProcessObservation(
            identity=identity,
            ppid=evt.ppid,
            image_name=image_name,
            image_path=evt.image_path,
            command_line_redacted=redacted_cmd,
            username=evt.user,
            integrity_level=evt.integrity_level,
            start_ts_utc=evt.event_ts_utc if evt.event_id == 1 else None,
            end_ts_utc=evt.event_ts_utc if evt.event_id == 5 else None,
            source=self.source_name,
            capabilities=CapabilityFlags(
                process_created=(evt.event_id == 1),
                process_terminated=(evt.event_id == 5),
                command_line_captured=bool(redacted_cmd),
            ),
        )
        self._storage.upsert_process(obs, cwd=evt.current_directory)
        if evt.event_id == 1 and evt.ppid is not None:
            parent_node = (
                f"sysmon:{self._boot_id}:{evt.ppid}:{evt.parent_guid}"
                if evt.parent_guid
                else f"pid:{self._boot_id}:{evt.ppid}"
            )
            self._storage.insert_edge(
                EvidenceEdge(
                    from_node_id=parent_node,
                    to_node_id=proc_key,
                    relation=EdgeRelation.PARENT_OF,
                    source=self.source_name,
                    method="sysmon_event_id_1",
                    confidence=0.95,
                    supporting_raw_ids=[raw_id] if raw_id is not None else [],
                    notes=evt.parent_image or "",
                )
            )
