<#
.SYNOPSIS
  Snapshot what other download managers' installers tend to change, and compare two snapshots.

.DESCRIPTION
  The comparison benchmark (tools/bench/compare.py) installs other download managers for a run
  and removes them after. Their installers may register browser native hosts, push browser
  extensions, take over .torrent / magnet / http associations, add autostart entries, scheduled
  tasks, services or firewall rules. Take a snapshot before installing anything, one after
  each install and uninstall, and compare: MDM's own registration and the user's associations
  must come back byte for byte.

    powershell -File tools/bench/sysstate.ps1 snapshot C:\mdm-bench\state\00-before
    powershell -File tools/bench/sysstate.ps1 compare  C:\mdm-bench\state\00-before C:\mdm-bench\state\09-after

  Read-only: it only exports and lists.
#>
param(
  [Parameter(Mandatory)][ValidateSet('snapshot', 'compare')][string]$Action,
  [Parameter(Mandatory)][string]$A,
  [string]$B
)
$ErrorActionPreference = 'Stop'

# Registry keys exported whole (a missing key is recorded as missing).
$Keys = @()
foreach ($hive in 'HKLM\SOFTWARE', 'HKLM\SOFTWARE\WOW6432Node', 'HKCU\Software') {
  foreach ($vendor in 'Google\Chrome', 'Chromium', 'Microsoft\Edge', 'BraveSoftware\Brave-Browser',
    'Vivaldi', 'Opera Software', 'Mozilla') {
    $Keys += "$hive\$vendor\NativeMessagingHosts"
    $Keys += "$hive\$vendor\Extensions"
  }
  $Keys += "$hive\Mozilla\Firefox\Extensions"
  $Keys += "$hive\Policies\Google\Chrome"
  $Keys += "$hive\Policies\Microsoft\Edge"
  $Keys += "$hive\Policies\Mozilla"
  $Keys += "$hive\Microsoft\Windows\CurrentVersion\Run"
  $Keys += "$hive\Microsoft\Windows\CurrentVersion\RunOnce"
  $Keys += "$hive\Microsoft\Windows\CurrentVersion\Uninstall"
  $Keys += "$hive\RegisteredApplications"
  $Keys += "$hive\Classes\.torrent"
  $Keys += "$hive\Classes\magnet"
  $Keys += "$hive\Classes\ftp"
  $Keys += "$hive\Classes\*\shell"
  $Keys += "$hive\Classes\Directory\shell"
  $Keys += "$hive\Classes\Applications"
}
$Keys += 'HKCU\Software\Microsoft\Windows\Shell\Associations\UrlAssociations'
$Keys += 'HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.torrent'
$Keys += 'HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved'
$Keys += 'HKCU\Software\Microsoft\Internet Explorer\MenuExt'
$Keys += 'HKLM\SOFTWARE\Microsoft\Internet Explorer\MenuExt'

# Folders listed one level deep (names only: what appeared or vanished).
$Folders = @(
  $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramData, $env:APPDATA, $env:LOCALAPPDATA,
  "$env:LOCALAPPDATA\Programs", $env:USERPROFILE,
  "$env:APPDATA\Microsoft\Windows\Start Menu\Programs",
  "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup",
  "$env:ProgramData\Microsoft\Windows\Start Menu\Programs",
  "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Startup",
  "$env:USERPROFILE\Desktop", "$env:PUBLIC\Desktop"
)

function Safe([string]$s) { ($s -replace '[\\/:*?"<>| ]', '_') }

function Snapshot([string]$dir) {
  New-Item -ItemType Directory -Force $dir | Out-Null
  New-Item -ItemType Directory -Force "$dir\reg" | Out-Null
  foreach ($k in $Keys) {
    $file = Join-Path "$dir\reg" ((Safe $k) + '.reg')
    # Through cmd: Windows PowerShell turns a native program's stderr into an error record.
    $null = & cmd.exe /d /c "reg.exe export `"$k`" `"$file`" /y >nul 2>nul"
    if ($LASTEXITCODE -ne 0) { Set-Content -Encoding utf8 $file 'missing' }
  }
  $lines = foreach ($f in $Folders) {
    if (Test-Path -LiteralPath $f) {
      Get-ChildItem -LiteralPath $f -Force -ErrorAction SilentlyContinue | ForEach-Object { "$f`t$($_.Name)" }
    }
  }
  $lines | Sort-Object | Set-Content -Encoding utf8 "$dir\folders.txt"
  Get-ScheduledTask | ForEach-Object { "$($_.TaskPath)$($_.TaskName)`t$($_.State)" } | Sort-Object |
    Set-Content -Encoding utf8 "$dir\tasks.txt"
  Get-Service | ForEach-Object { "$($_.Name)`t$($_.StartType)" } | Sort-Object | Set-Content -Encoding utf8 "$dir\services.txt"
  Get-NetFirewallRule -ErrorAction SilentlyContinue | ForEach-Object { "$($_.Name)`t$($_.DisplayName)`t$($_.Enabled)" } |
    Sort-Object | Set-Content -Encoding utf8 "$dir\firewall.txt"
  # What a browser would launch for MDM's host, and the user's defaults, said plainly.
  $plain = foreach ($k in 'HKLM:\SOFTWARE\Google\Chrome\NativeMessagingHosts\com.misterdownloadmanager.host',
    'HKLM:\SOFTWARE\Mozilla\NativeMessagingHosts\com.misterdownloadmanager.host',
    'HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.misterdownloadmanager.host',
    'HKCU:\Software\Mozilla\NativeMessagingHosts\com.misterdownloadmanager.host') {
    $v = (Get-ItemProperty -LiteralPath $k -ErrorAction SilentlyContinue).'(default)'
    "$k = $v"
  }
  foreach ($p in 'http', 'https', 'ftp', 'magnet') {
    $v = (Get-ItemProperty "HKCU:\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\$p\UserChoice" -ErrorAction SilentlyContinue).ProgId
    $plain += "UserChoice $p = $v"
  }
  $v = (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.torrent\UserChoice' -ErrorAction SilentlyContinue).ProgId
  $plain += "UserChoice .torrent = $v"
  $plain | Set-Content -Encoding utf8 "$dir\summary.txt"
  Write-Output "snapshot: $dir ($($Keys.Count) keys)"
}

function Compare-Snap([string]$a, [string]$b) {
  $diff = 0
  foreach ($f in Get-ChildItem "$a\reg" -File) {
    $other = Join-Path "$b\reg" $f.Name
    $ha = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
    $hb = if (Test-Path -LiteralPath $other) { (Get-FileHash -LiteralPath $other -Algorithm SHA256).Hash } else { 'absent' }
    if ($ha -ne $hb) { $diff++; Write-Output "REG CHANGED  $($f.BaseName)" }
  }
  foreach ($n in 'folders.txt', 'tasks.txt', 'services.txt', 'firewall.txt', 'summary.txt') {
    $la = Get-Content -LiteralPath "$a\$n"
    $lb = Get-Content -LiteralPath "$b\$n"
    $d = Compare-Object @($la) @($lb)
    foreach ($x in $d) {
      $diff++
      $side = if ($x.SideIndicator -eq '=>') { 'added  ' } else { 'removed' }
      Write-Output "$n $side $($x.InputObject)"
    }
  }
  if ($diff -eq 0) { Write-Output 'IDENTICAL' } else { Write-Output "$diff difference(s)" }
}

switch ($Action) {
  'snapshot' { Snapshot $A }
  'compare' { Compare-Snap $A $B }
}
