$ErrorActionPreference = "Stop"
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    Start-Process powershell.exe -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"") -Verb RunAs
    exit
}

$HostsFile = "$env:SystemRoot\System32\drivers\etc\hosts"
$Marker = "# SNI-PROXY-AUTO"

Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*sni_proxy.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$content = Get-Content $HostsFile -Raw -Encoding UTF8
$lines = $content -split "`n" | Where-Object { $_ -notmatch [regex]::Escape($Marker) }
Set-Content -Path $HostsFile -Value ($lines -join "`n") -Encoding UTF8 -NoNewline
ipconfig /flushdns | Out-Null
Write-Host "Stopped local SNI proxy route and removed hosts entries."
