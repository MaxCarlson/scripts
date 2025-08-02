from cross_platform.standard_ui import log_info, log_warning, section

def get_termux_info(sections: dict, sys_utils, admin_mode: bool):
    # Termux/Android OS Information
    if sections.get("os", True):
        with section("Termux/Android OS Information"):
            cmd = "termux-info"
            output = sys_utils.run_command(cmd, sudo=False)
            log_info(f"\n{output}")

    # CPU Information
    if sections.get("cpu", True):
        with section("CPU Information"):
            cmd = "cat /proc/cpuinfo"
            output = sys_utils.run_command(cmd, sudo=False)
            log_info(f"\n{output}")

    # Memory Information
    if sections.get("memory", True):
        with section("Memory Information"):
            cmd = "cat /proc/meminfo"
            output = sys_utils.run_command(cmd, sudo=False)
            log_info(f"\n{output}")

    # Drives/Storage Information
    if sections.get("drives", True):
        with section("Storage Information"):
            cmd = "lsblk -a"
            output = sys_utils.run_command(cmd, sudo=False)
            log_info(f"\n{output}")

    # Network Information
    if sections.get("network", True):
        with section("Network Information"):
            cmd = "ip a"
            output = sys_utils.run_command(cmd, sudo=False)
            log_info(f"\n{output}")
