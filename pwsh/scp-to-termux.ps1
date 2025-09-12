<#
.SYNOPSIS
    Uploads a file to a predefined remote server using SCP, with fallback hosts.

.DESCRIPTION
    This script takes a single file path as an argument and securely copies it
    to a hardcoded remote server destination. It will try a list of hosts in
    order until a successful connection is made.

.PARAMETER Path
    The full or relative path to the file that you want to upload.
    This parameter is mandatory.

.EXAMPLE
    .\scplog.ps1 -Path "C:\Users\YourUser\Documents\log-ytaedl.log"

.EXAMPLE
    .\scplog.ps1 -f .\log-ytaedl.log

.EXAMPLE
    # Since 'Path' is the first positional parameter, you can omit the name.
    .\scplog.ps1 .\log-ytaedl.log

.NOTES
    Ensures that scp.exe is available in your system's PATH.
    Configuration for the remote servers is stored in variables at the top of the script.
#>
[CmdletBinding()]
param (
    [Parameter(Mandatory = $true, Position = 0, HelpMessage = "Path to the file you want to upload.")]
    [Alias('f', 'FilePath')]
    [string]$Path
)

# --- Configuration ---
# You can easily change these values to match your remote server details.
$RemotePort = 8022
$RemoteUser = "u0_a142"
$RemoteHosts = @(
    "192.168.50.101",
    "10.6.0.2"
) # List of hosts to try in order.
$RemoteDestinationFolder = "~/storage/shared/Download/"
# ---------------------

# Validate that the source path points to a file before attempting to copy.
# The '-PathType Leaf' ensures it's a file and not a directory.
if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    Write-Error "Error: File not found at '${Path}'. Please provide a valid path to a file."
    # Exit the script with a non-zero exit code to indicate failure
    exit 1
}

# Resolve the path to get the full, absolute path. This is more reliable for external commands.
$FullSourcePath = (Resolve-Path -LiteralPath $Path).Path
$TransferSuccess = $false

# Loop through each host in the list and attempt the file transfer.
foreach ($RemoteHost in $RemoteHosts) {
    # Construct the full remote destination string for the current host
    $Destination = "${RemoteUser}@${RemoteHost}:${RemoteDestinationFolder}"

    Write-Host "Attempting to transfer to host: ${RemoteHost} on port ${RemotePort}..."
    Write-Host "    Source:      '${FullSourcePath}'"
    Write-Host "    Destination: '${Destination}'"
    Write-Host "" # Add a blank line for readability

    # Execute the scp command with all the defined parameters.
    # The '-o ConnectTimeout=10' option will prevent it from hanging for too long on an unresponsive host.
    scp.exe -P $RemotePort -o ConnectTimeout=10 $FullSourcePath $Destination

    # Check the exit code of the last command run ($?).
    # If the command was successful, the exit code is 0, and $? is $true.
    if ($?) {
        Write-Host "File transfer to ${RemoteHost} completed successfully."
        $TransferSuccess = $true
        break # Exit the loop since the transfer was successful
    }
    else {
        Write-Warning "Failed to transfer to host '${RemoteHost}'. Trying next host..."
        Write-Host ""
    }
}

# After the loop, check if the transfer was ever successful.
if (-not $TransferSuccess) {
    Write-Error "File transfer failed for all specified hosts. Please check your connection and credentials."
    exit 1
}



