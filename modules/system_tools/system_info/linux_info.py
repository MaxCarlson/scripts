from cross_platform.standard_ui import log_info, log_warning, section

def get_linux_info(sections: dict, sys_utils, admin_mode: bool):
    if not admin_mode:
        log_warning("Running in non-admin mode; some information (e.g., BIOS) may be inaccessible.")

    # OS Information
    if sections.get("os", True):
        with section("Operating System Information"):
            cmd = "hostnamectl"
            output = sys_utils.run_command(cmd, sudo=False)
            log_info(f"\n{output}")

    # BIOS Information
    if sections.get("bios", True):
        with section("BIOS Information"):
            cmd = "dmidecode -t bios"
            output = sys_utils.run_command(cmd, sudo=admin_mode)
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

    # GPU Information
    if sections.get("gpu", True):
        with section("GPU Information"):
            cmd = "lspci | grep -i 'vga\\|3d\\|2d'"
            output = sys_utils.run_command(cmd, sudo=False)
            log_info(f"\n{output}")

    # Drives Information
    if sections.get("drives", True):
        with section("Hard Drives Information"):
            cmd = "lsblk -a"
            output = sys_utils.run_command(cmd, sudo=False)
            log_info(f"\n{output}")

    # Network Information
    if sections.get("network", True):
        with section("Network Information"):
            cmd = "ip a"
            output = sys_utils.run_command(cmd, sudo=False)
            log_info(f"\n{output}")
