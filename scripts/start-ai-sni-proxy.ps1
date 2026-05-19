param([switch]$SkipKimiAck)

$ErrorActionPreference = "Stop"
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    if ($SkipKimiAck) { $args += "-SkipKimiAck" }
    Start-Process powershell.exe -ArgumentList $args -Verb RunAs
    exit
}

$Root = Split-Path -Parent $PSCommandPath
$ProxyScript = Join-Path $Root "sni_proxy.py"
$HostsFile = "$env:SystemRoot\System32\drivers\etc\hosts"
$Marker = "# SNI-PROXY-AUTO"
$LogOut = Join-Path $Root "sni_proxy.out.log"
$LogErr = Join-Path $Root "sni_proxy.err.log"

$Entries = @(
    "127.0.0.1 chatgpt.com $Marker",
    "127.0.0.1 openai.com $Marker",
    "127.0.0.1 api.openai.com $Marker",
    "127.0.0.1 cdn.oaistatic.com $Marker",
    "127.0.0.1 oaistatic.com $Marker",
    "127.0.0.1 cdn.chatgpt.com $Marker",
    "127.0.0.1 ab.chatgpt.com $Marker",
    "127.0.0.1 auth0.openai.com $Marker",
    "127.0.0.1 oaisidekickupdates.blob.core.windows.net $Marker",
    "127.0.0.1 tabbitbrowser.com $Marker",
    "127.0.0.1 web.tabbitbrowser.com $Marker",
    "127.0.0.1 cdn.tabbitbrowser.com $Marker",
    "127.0.0.1 anthropic.com $Marker",
    "127.0.0.1 platform.claude.com $Marker",
    "127.0.0.1 api.anthropic.com $Marker",
    "127.0.0.1 a-api.anthropic.com $Marker",
    "127.0.0.1 claude.ai $Marker",
    "127.0.0.1 claude.com $Marker",
    "127.0.0.1 a.claude.ai $Marker",
    "127.0.0.1 assets.claude.ai $Marker",
    "127.0.0.1 assets-proxy.anthropic.com $Marker",
    "127.0.0.1 a-cdn.anthropic.com $Marker",
    "127.0.0.1 s-cdn.anthropic.com $Marker",
    "127.0.0.1 statsig.anthropic.com $Marker",
    "127.0.0.1 console.anthropic.com $Marker",
    "127.0.0.1 challenges.cloudflare.com $Marker",
    "127.0.0.1 api.typeless.com $Marker",
    "127.0.0.1 typeless-static.com $Marker",
    "127.0.0.1 kiro.dev $Marker",
    "127.0.0.1 app.kiro.dev $Marker",
    "127.0.0.1 prod.download.desktop.kiro.dev $Marker",
    "127.0.0.1 prod.us-east-1.auth.desktop.kiro.dev $Marker",
    "127.0.0.1 prod.us-east-1.telemetry.desktop.kiro.dev $Marker",
    "127.0.0.1 gamma.us-east-1.telemetry.desktop.kiro.dev $Marker",
    "127.0.0.1 beta.us-east-1.telemetry.kiro.aws.dev $Marker",
    "127.0.0.1 q.us-east-1.amazonaws.com $Marker",
    "127.0.0.1 q.eu-central-1.amazonaws.com $Marker",
    "127.0.0.1 amzn.awsapps.com $Marker",
    "127.0.0.1 view.awsapps.com $Marker",
    "127.0.0.1 signin.aws.amazon.com $Marker",
    "127.0.0.1 sts.amazonaws.com $Marker",
    "127.0.0.1 assets.app.kiro.dev $Marker",
    "127.0.0.1 kaa-assets.app.kiro.dev $Marker",
    "127.0.0.1 prod.assets.shortbread.aws.dev $Marker",
    "127.0.0.1 prod.log.shortbread.aws.dev $Marker",
    "127.0.0.1 prod.tools.shortbread.aws.dev $Marker"
)

$content = Get-Content $HostsFile -Raw -Encoding UTF8
$lines = $content -split "`n" | Where-Object { $_ -notmatch [regex]::Escape($Marker) }
Set-Content -Path $HostsFile -Value (($lines + $Entries) -join "`n") -Encoding UTF8 -NoNewline
ipconfig /flushdns | Out-Null

Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*sni_proxy.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Remove-Item $LogOut, $LogErr -ErrorAction SilentlyContinue
$Python = if (Test-Path "D:\anaconda\python.exe") { "D:\anaconda\python.exe" } else { "python.exe" }
Start-Process -FilePath $Python -ArgumentList "`"$ProxyScript`"" -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $LogOut -RedirectStandardError $LogErr
Write-Host "SNI proxy start requested. Check status with ai-sni-proxy status."
