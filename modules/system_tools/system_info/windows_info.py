from standard_ui import log_info, log_warning, section

def run_powershell_command(sys_utils, ps_command: str, require_admin: bool = False) -> str:
    """Run a PowerShell command via pwsh."""
    command = f"pwsh -Command \"{ps_command}\""
    return sys_utils.run_command(command, sudo=require_admin)

def get_windows_info(sections: dict, sys_utils, admin_mode: bool):
    if not admin_mode:
        log_warning("Running in non-admin mode; some information may not be accessible.")

    # OS Information
    if sections.get("os", True):
        with section("Operating System Information"):
            cmd = 'Get-ComputerInfo -Property OsName,OsVersion,OsManufacturer,OsConfiguration,OsBuildNumber | Format-List'
            output = run_powershell_command(sys_utils, cmd, require_admin=admin_mode)
            log_info(f"\n{output}")

    # BIOS Information
    if sections.get("bios", True):
        with section("BIOS Information"):
            cmd = 'Get-WmiObject -Class Win32_BIOS | Format-List'
            output = run_powershell_command(sys_utils, cmd, require_admin=admin_mode)
            log_info(f"\n{output}")

    # CPU Information
    if sections.get("cpu", True):
        with section("CPU Information"):
            cmd = 'Get-WmiObject -Class Win32_Processor | Format-List'
            output = run_powershell_command(sys_utils, cmd, require_admin=admin_mode)
            log_info(f"\n{output}")

    # Memory Information
    if sections.get("memory", True):
        with section("Memory Information"):
            cmd = 'Get-WmiObject -Class Win32_PhysicalMemory | Format-List'
            output = run_powershell_command(sys_utils, cmd, require_admin=admin_mode)
            log_info(f"\n{output}")

    # GPU Information
    if sections.get("gpu", True):
        with section("GPU Information"):
            cmd = 'Get-WmiObject -Class Win32_VideoController | Format-List'
            output = run_powershell_command(sys_utils, cmd, require_admin=admin_mode)
            log_info(f"\n{output}")

    # Drives Information
    if sections.get("drives", True):
        with section("Hard Drives Information"):
            cmd = 'Get-WmiObject -Class Win32_DiskDrive | Format-List'
            output = run_powershell_command(sys_utils, cmd, require_admin=admin_mode)
            log_info(f"\n{output}")

    # Network Information
    if sections.get("network", True):
        with section("Network Information"):
            cmd = 'Get-WmiObject -Class Win32_NetworkAdapterConfiguration | Format-List'
            output = run_powershell_command(sys_utils, cmd, require_admin=admin_mode)
            log_info(f"\n{output}")
