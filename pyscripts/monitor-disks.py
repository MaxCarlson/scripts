#!/usr/bin/env python3
import argparse
import time
import sys
import psutil
import collections
import string
import select
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.layout import Layout
from rich.panel import Panel
from rich import box

# --- Non-blocking keyboard input ---
if sys.platform == "win32":
    import msvcrt

    def read_keys():
        keys = []
        while msvcrt.kbhit():
            ch = msvcrt.getch()
            # Check for arrow keys (prefix 0xe0)
            if ch == b'\xe0':
                ch2 = msvcrt.getch()
                if ch2 == b'K':
                    keys.append("left")
                elif ch2 == b'M':
                    keys.append("right")
            else:
                try:
                    keys.append(ch.decode("utf-8", errors="ignore"))
                except Exception:
                    pass
        return keys
else:
    import termios, tty

    class NonBlockingInput:
        def __enter__(self):
            self.fd = sys.stdin.fileno()
            self.old_settings = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
            return self
        def __exit__(self, type, value, traceback):
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)
    def read_keys():
        keys = []
        dr, dw, de = select.select([sys.stdin], [], [], 0)
        if dr:
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                ch2 = sys.stdin.read(2)
                if ch2 == "[D":
                    keys.append("left")
                elif ch2 == "[C":
                    keys.append("right")
            else:
                keys.append(ch)
        return keys

# --- Helper functions ---
def format_speed(bps):
    if bps >= 1e9:
        return f"{bps/1e9:.2f} GB/s"
    elif bps >= 1e6:
        return f"{bps/1e6:.2f} MB/s"
    elif bps >= 1e3:
        return f"{bps/1e3:.2f} KB/s"
    else:
        return f"{bps:.2f} B/s"

def format_percent(val):
    return f"{val:.2f}%"

def get_static_table():
    table = Table(title="Disk Usage", box=box.SIMPLE_HEAVY)
    table.add_column("Mount/Drive", style="cyan")
    table.add_column("File System")
    table.add_column("Total (GB)", justify="right")
    table.add_column("Free (GB)", justify="right")
    table.add_column("Used (%)", justify="right")
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except PermissionError:
            continue
        table.add_row(
            part.mountpoint,
            part.fstype,
            f"{usage.total/1e9:.2f}",
            f"{usage.free/1e9:.2f}",
            f"{usage.percent:.2f}"
        )
    return table

# --- Rolling average helper ---
class RollingAverages:
    def __init__(self, window_ms):
        self.window_sec = window_ms / 1000.0
        self.data = collections.defaultdict(collections.deque)
    def update(self, device, timestamp, read, write, util):
        d = self.data[device]
        d.append((timestamp, read, write, util))
        cutoff = timestamp - self.window_sec
        while d and d[0][0] < cutoff:
            d.popleft()
    def get_avg(self, device):
        d = self.data[device]
        if not d:
            return (0, 0, 0)
        count = len(d)
        sum_read = sum(item[1] for item in d)
        sum_write = sum(item[2] for item in d)
        sum_util = sum(item[3] for item in d)
        return (sum_read/count, sum_write/count, sum_util/count)

# --- Process scanning (without heavy caching) ---
# We'll use a global dictionary to store previous I/O counters per PID.
proc_prev = {}

def scan_processes(target_drive, dt):
    """
    Scan all processes; for those that have at least one open file starting with target_drive,
    compute I/O rates using the global proc_prev dictionary.
    Returns a list of dictionaries with keys: pid, name, open_file, read_rate, write_rate.
    """
    results = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            files = proc.open_files()
        except Exception:
            continue
        match = False
        open_file = ""
        for f in files:
            if f.path.lower().startswith(target_drive.lower()):
                match = True
                open_file = f.path
                break
        if not match:
            continue
        try:
            io = proc.io_counters()
        except Exception:
            continue
        pid = proc.pid
        now = time.time()
        prev = proc_prev.get(pid)
        if prev:
            prev_time, prev_read, prev_write = prev
            delta = now - prev_time
            # If delta is too small, skip (or use dt if available)
            if delta <= 0:
                delta = dt
            read_rate = (io.read_bytes - prev_read) / delta
            write_rate = (io.write_bytes - prev_write) / delta
        else:
            read_rate = 0.0
            write_rate = 0.0
        proc_prev[pid] = (now, io.read_bytes, io.write_bytes)
        results.append({
            'pid': pid,
            'name': proc.info['name'],
            'open_file': open_file,
            'read_rate': read_rate,
            'write_rate': write_rate
        })
    return results

def get_process_table(target_drive, sort_mode, dt):
    """
    Build a single process table for processes that have open files on target_drive.
    sort_mode is either "desc_read" (default) or "desc_write".
    """
    procs = scan_processes(target_drive, dt)
    if sort_mode == "desc_read":
        procs.sort(key=lambda x: x.get('read_rate', 0), reverse=True)
    else:
        procs.sort(key=lambda x: x.get('write_rate', 0), reverse=True)
    table = Table(title=f"Processes accessing '{target_drive}'", box=box.SIMPLE_HEAVY)
    table.add_column("PID", style="red", justify="right")
    table.add_column("Name", style="green")
    table.add_column("Open File", style="cyan")
    table.add_column("Read Speed", justify="right")
    table.add_column("Write Speed", justify="right")
    for p in procs[:30]:
        table.add_row(
            str(p['pid']),
            p['name'] or "",
            p['open_file'] or "",
            format_speed(p.get('read_rate', 0)),
            format_speed(p.get('write_rate', 0))
        )
    return table

# --- Dynamic Table for Disk Performance ---
def get_dynamic_table(avg_data, rolling_avgs):
    table = Table(title="Live Disk Performance", box=box.SIMPLE_HEAVY)
    table.add_column("Drive", style="magenta")
    table.add_column("Read Speed", justify="right")
    table.add_column("Read Avg", justify="right")
    table.add_column("Write Speed", justify="right")
    table.add_column("Write Avg", justify="right")
    table.add_column("Util (%)", justify="right")
    table.add_column("Util Avg", justify="right")
    for device, (inst_read, inst_write, inst_util) in avg_data.items():
        roll_read, roll_write, roll_util = rolling_avgs.get_avg(device)
        table.add_row(
            device,
            format_speed(inst_read),
            format_speed(roll_read),
            format_speed(inst_write),
            format_speed(roll_write),
            format_percent(inst_util),
            format_percent(roll_util)
        )
    return table

# --- Global variable for sort mode ---
# Only two modes: "desc_read" and "desc_write". Default is descending read.
sort_mode = "desc_read"
current_target_drive = ""  # e.g. "C:\\" if in drive-specific mode

# --- Main loop ---
def main(args):
    global sort_mode, current_target_drive
    update_time = args.update_time
    internal_polling = args.internal_polling
    rolling_avg_ms = args.rolling_avg
    # Start in drive-specific mode if -d is provided.
    current_target_drive = args.drive if args.drive else ""

    if update_time < internal_polling:
        print(f"[WARN] --update-time ({update_time}ms) is less than --internal-polling ({internal_polling}ms). Setting internal_polling = update_time.")
        internal_polling = update_time
    if rolling_avg_ms < internal_polling:
        print(f"[WARN] --rolling-avg ({rolling_avg_ms}ms) is less than --internal-polling ({internal_polling}ms). Setting rolling_avg = internal_polling.")
        rolling_avg_ms = internal_polling

    polls_per_update = max(1, update_time // internal_polling)
    rolling_avgs = RollingAverages(rolling_avg_ms)
    prev = psutil.disk_io_counters(perdisk=True)
    accum = {dev: [0.0, 0.0, 0.0] for dev in prev}
    console = Console()
    static_table = get_static_table()
    layout = Layout()
    layout.split_column(
        Layout(name="static", size=9),
        Layout(name="dynamic"),
        Layout(name="footer", size=3)
    )
    layout["static"].update(static_table)
    footer_text = ("Press [bold green]q[/bold green] to quit • "
                   "Press left/right arrow to toggle sort (current: {}). "
                   "Press a letter to toggle drive-specific mode").format(
                       "Descending Read" if sort_mode=="desc_read" else "Descending Write")
    footer_panel = Panel(footer_text, style="dim", box=box.SIMPLE)
    layout["footer"].update(footer_panel)
    live = Live(layout, refresh_per_second=10, console=console, transient=False)
    update_counter = 0
    last_update_time = time.time()

    # For drive-specific mode, try mapping the chosen drive letter.
    def map_drive(target):
        for part in psutil.disk_partitions():
            if part.mountpoint.lower() == target.lower():
                return part.device
        return None

    # If in drive mode, replace the disk performance table's device key if possible.
    def adjust_inst_data(inst_data, target):
        mapped = map_drive(target)
        if mapped:
            new_inst = {}
            for dev, vals in inst_data.items():
                if mapped.lower() in dev.lower():
                    new_inst[target] = vals
                else:
                    new_inst[dev] = vals
            return new_inst
        return inst_data

    nb_context = None
    if sys.platform != "win32":
        nb_context = NonBlockingInput()
        nb_context.__enter__()

    try:
        with live:
            while True:
                time.sleep(internal_polling / 1000.0)
                now = time.time()
                dt = now - last_update_time
                last_update_time = now

                curr = psutil.disk_io_counters(perdisk=True)
                for dev in curr:
                    if dev not in prev:
                        prev[dev] = curr[dev]
                        continue
                    delta_read = curr[dev].read_bytes - prev[dev].read_bytes
                    delta_write = curr[dev].write_bytes - prev[dev].write_bytes
                    delta_io_time = (curr[dev].read_time + curr[dev].write_time) - (prev[dev].read_time + prev[dev].write_time)
                    poll_interval_sec = internal_polling / 1000.0
                    read_speed = delta_read / poll_interval_sec
                    write_speed = delta_write / poll_interval_sec
                    util = min(100.0, (delta_io_time / internal_polling) * 100.0)
                    accum[dev][0] += read_speed
                    accum[dev][1] += write_speed
                    accum[dev][2] += util
                prev = curr
                update_counter += 1

                inst_data = {}
                for dev, totals in accum.items():
                    avg_read = totals[0] / update_counter
                    avg_write = totals[1] / update_counter
                    avg_util = totals[2] / update_counter
                    inst_data[dev] = (avg_read, avg_write, avg_util)
                    rolling_avgs.update(dev, now, avg_read, avg_write, avg_util)
                if update_counter >= polls_per_update:
                    accum = {dev: [0.0, 0.0, 0.0] for dev in prev}
                    update_counter = 0

                display_inst_data = inst_data
                if current_target_drive:
                    display_inst_data = adjust_inst_data(inst_data, current_target_drive)
                dynamic_table = get_dynamic_table(display_inst_data, rolling_avgs)
                if current_target_drive:
                    # In drive-specific mode, build a process table.
                    proc_table = get_process_table(current_target_drive, sort_mode, dt)
                    # If console width is narrow, stack vertically; else, side by side.
                    if console.width < 100:
                        sub_layout = Layout()
                        sub_layout.split_column(
                            Layout(dynamic_table, name="io"),
                            Layout(proc_table, name="proc")
                        )
                    else:
                        sub_layout = Layout()
                        sub_layout.split_row(
                            Layout(dynamic_table, name="io"),
                            Layout(proc_table, name="proc")
                        )
                    layout["dynamic"].update(sub_layout)
                else:
                    layout["dynamic"].update(dynamic_table)

                # Process key events.
                for key in read_keys():
                    lk = key.lower()
                    if lk == "q":
                        return
                    elif lk == "left":
                        # Toggle sort mode.
                        sort_mode = "desc_read" if sort_mode == "desc_write" else "desc_write"
                        footer_text = ("Press [bold green]q[/bold green] to quit • "
                                       "Press left/right arrow to toggle sort (current: {}). "
                                       "Press a letter to toggle drive-specific mode").format(
                                           "Descending Read" if sort_mode=="desc_read" else "Descending Write")
                        layout["footer"].update(Panel(footer_text, style="dim", box=box.SIMPLE))
                    elif lk == "right":
                        sort_mode = "desc_read" if sort_mode == "desc_write" else "desc_write"
                        footer_text = ("Press [bold green]q[/bold green] to quit • "
                                       "Press left/right arrow to toggle sort (current: {}). "
                                       "Press a letter to toggle drive-specific mode").format(
                                           "Descending Read" if sort_mode=="desc_read" else "Descending Write")
                        layout["footer"].update(Panel(footer_text, style="dim", box=box.SIMPLE))
                    elif lk in string.ascii_letters:
                        candidate = lk.upper() + ":\\"  # e.g. "C:\\"
                        if current_target_drive == candidate:
                            current_target_drive = ""
                        else:
                            current_target_drive = candidate
    finally:
        if nb_context:
            nb_context.__exit__(None, None, None)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Real-time cross-platform disk performance monitor")
    parser.add_argument("-u", "--update-time", type=int, default=1000,
                        help="Update display every N milliseconds (default: 1000)")
    parser.add_argument("-i", "--internal-polling", type=int, default=100,
                        help="Poll disk counters every N milliseconds (default: 100; must be <= update time)")
    parser.add_argument("-r", "--rolling-avg", type=int, default=10000,
                        help="Rolling average window in milliseconds (default: 10000; must be >= internal polling)")
    parser.add_argument("-d", "--drive", type=str, default="",
                        help="Specify a drive/mount (e.g. 'C:\\' or '/mnt/data') for process monitoring")
    args = parser.parse_args()
    main(args)
