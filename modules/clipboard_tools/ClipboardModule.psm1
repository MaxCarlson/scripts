# pwsh/ClipboardModule.psm1

# Requires your setup to have put bin/ on PATH so the wrappers exist.
# Commands used below: print_clipboard, set_clipboard_text, copy_to_clipboard,
#                      replace_with_clipboard, append_clipboard, output_to_clipboard

function Get-ClipboardContents {
    [CmdletBinding()]
    param()
    # Print the clipboard via Python (consistent stats/formatting)
    print_clipboard --no-stats
}
#Set-Alias -Name gcb -Value Get-ClipboardContents

function Set-ClipboardContent {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$InputData,
        [switch]$Append
    )
    if (Test-Path -LiteralPath $InputData -PathType Leaf) {
        # Copy file contents (raw) to clipboard (or append)
        if ($Append) {
            copy_to_clipboard -r -a -- $InputData
        } else {
            copy_to_clipboard -r -- $InputData
        }
    } else {
        # Treat as literal text; pipe to the helper so huge strings are safe
        if ($Append) {
            $InputData | set_clipboard_text -a
        } else {
            $InputData | set_clipboard_text
        }
    }
}
#Set-Alias -Name scb -Value Set-ClipboardContent
#Set-Alias -Name c2c -Value Set-ClipboardContent  # your older alias

function Set-FileClipboard {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$Path
    )
    # Replace file contents with clipboard (Python handles stats & errors)
    replace_with_clipboard -- $Path
}
#Set-Alias -Name sfc -Value Set-FileClipboard
#Set-Alias -Name rwc -Value Set-FileClipboard  # your older alias

function Add-ClipboardToFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$FilePath
    )
    append_clipboard -- $FilePath
}
#Set-Alias -Name apc -Value Add-ClipboardToFile

function Invoke-CommandToClipboard {
    [CmdletBinding()]
    param(
        [Parameter(ValueFromRemainingArguments=$true)]
        [string[]]$Command,
        [switch]$Wrap,
        [switch]$Append
    )
    # Forward to the Python script (uses shell wrapper logic for aliases/functions)
    $argsList = @()
    if ($Wrap)   { $argsList += "-w" }
    if ($Append) { $argsList += "-a" }
    $argsList += "--"
    $argsList += $Command
    output_to_clipboard @argsList
}
#Set-Alias -Name otc -Value Invoke-CommandToClipboard

Export-ModuleMember `
  -Function Get-ClipboardContents, Set-ClipboardContent, Set-FileClipboard, Add-ClipboardToFile, Invoke-CommandToClipboard `
  # -Alias gcb, scb, c2c, sfc, rwc, apc, otc
  # Removing aliases as they interfere with pythkn clipboard_tools.mldule's idenrical cli
