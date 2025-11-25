param(
    [string]$CatalogPath,
    [string]$SelectionPath
)

$defaultCatalog = Join-Path (Resolve-Path "$PSScriptRoot\..\..\..") "W11-powershell\Setup\InstalledPackages\package-catalog.json"
if (-not $CatalogPath) { $CatalogPath = $defaultCatalog }
if (-not $SelectionPath) { $SelectionPath = Join-Path (Split-Path $CatalogPath -Parent) "selected.packages.txt" }

if (-not (Test-Path $CatalogPath)) {
    Write-Error "Catalog not found at $CatalogPath"
    return
}

try { Add-Type -AssemblyName PresentationFramework -ErrorAction Stop } catch { Write-Error $_; return }

$existingSelection = if (Test-Path $SelectionPath) {
    Get-Content $SelectionPath | Where-Object { $_ -match '^\w+:.+' -and $_ -notmatch '^\s*#' }
} else { @() }

$catalog = Get-Content -Path $CatalogPath -Raw | ConvertFrom-Json
$items = New-Object System.Collections.ObjectModel.ObservableCollection[psobject]

foreach ($cat in $catalog.categories) {
    foreach ($pkg in $cat.packages) {
        $id = $pkg.id
        $selected = if ($existingSelection -contains $id) { $true } else { [bool]$pkg.defaultSelected }
        $obj = [pscustomobject]@{
            Selected = $selected
            Category = $cat.name
            Label    = $pkg.label
            Id       = $id
        }
        $items.Add($obj)
    }
}

[xml]$xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Package Selector" Height="520" Width="900"
        WindowStartupLocation="CenterScreen">
    <DockPanel>
        <StackPanel Orientation="Horizontal" DockPanel.Dock="Top" Margin="6">
            <Button Name="SelectAllBtn" Width="90" Margin="0,0,6,0">Select All</Button>
            <Button Name="DeselectAllBtn" Width="100" Margin="0,0,6,0">Deselect All</Button>
            <Button Name="SaveBtn" Width="90" Margin="0,0,6,0">Save</Button>
            <Button Name="CloseBtn" Width="90">Close</Button>
            <TextBlock Name="StatusText" Margin="12,0,0,0" VerticalAlignment="Center"/>
        </StackPanel>
        <DataGrid Name="Grid"
                  AutoGenerateColumns="False"
                  CanUserAddRows="False"
                  SelectionMode="Extended"
                  SelectionUnit="FullRow"
                  Margin="6">
            <DataGrid.Columns>
                <DataGridCheckBoxColumn Binding="{Binding Selected, Mode=TwoWay}" Header="Install" Width="70"/>
                <DataGridTextColumn Binding="{Binding Category}" Header="Category" Width="150"/>
                <DataGridTextColumn Binding="{Binding Label}" Header="Name" Width="*"/>
                <DataGridTextColumn Binding="{Binding Id}" Header="Id" Width="220"/>
            </DataGrid.Columns>
        </DataGrid>
    </DockPanel>
</Window>
"@

$reader = New-Object System.Xml.XmlNodeReader $xaml
$window = [Windows.Markup.XamlReader]::Load($reader)
$grid = $window.FindName("Grid")
$status = $window.FindName("StatusText")
$grid.ItemsSource = $items

function Update-Status {
    $count = ($items | Where-Object { $_.Selected }).Count
    $status.Text = "$count selected"
}

Update-Status

($window.FindName("SelectAllBtn")).Add_Click({
    foreach ($i in $items) { $i.Selected = $true }
    $grid.Items.Refresh()
    Update-Status
})

($window.FindName("DeselectAllBtn")).Add_Click({
    foreach ($i in $items) { $i.Selected = $false }
    $grid.Items.Refresh()
    Update-Status
})

$grid.Add_MouseDoubleClick({
    if ($grid.SelectedItem) {
        $grid.SelectedItem.Selected = -not $grid.SelectedItem.Selected
        $grid.Items.Refresh()
        Update-Status
    }
})

($window.FindName("SaveBtn")).Add_Click({
    $selected = $items | Where-Object { $_.Selected } | ForEach-Object { $_.Id }
    if (-not $selected) { [System.IO.File]::WriteAllText($SelectionPath, "# no selections`n") }
    else { $selected | Set-Content -Path $SelectionPath -Encoding UTF8 }
    $status.Text = "Saved to $SelectionPath"
})

($window.FindName("CloseBtn")).Add_Click({ $window.Close() })

[void]$window.ShowDialog()
