from cross_platform.standard_ui import log_info, log_warning, section

def get_mac_info(sections: dict, sys_utils, admin_mode: bool):
    # OS Information
    if sections.get("os", True):
        with section("Operating System Information"):
            cmd = "sw_vers"
            output = sys_utils.run_command(cmd, sudo=False)
            log_info(f"\n{output}")

    # Hardware Information (includes firmware/BIOS details)
    if sections.get("bios", True) or sections.get("cpu", True) or sections.get("memory", True):
        with section("Hardware Information"):
            cmd = "system_profiler SPHardwareDataType"
            output = sys_utils.run_command(cmd, sudo=False)
            log_info(f"\n{output}")

    # Memory Information (detailed)
    if sections.get("memory", True):
        with section("Memory Information"):
            cmd = "system_profiler SPMemoryDataType"
            output = sys_utils.run_command(cmd, sudo=False)
            log_info(f"\n{output}")

    # GPU Information
    if sections.get("gpu", True):
        with section("GPU Information"):
            cmd = "system_profiler SPDisplaysDataType"
            output = sys_utils.run_command(cmd, sudo=False)
            log_info(f"\n{output}")

    # Drives/Storage Information
    if sections.get("drives", True):
        with section("Storage Information"):
            cmd = "system_profiler SPStorageDataType"
            output = sys_utils.run_command(cmd, sudo=False)
            log_info(f"\n{output}")

    # Network Information
    if sections.get("network", True):
        with section("Network Information"):
            cmd = "system_profiler SPNetworkDataType"
            output = sys_utils.run_command(cmd, sudo=False)
            log_info(f"\n{output}")
