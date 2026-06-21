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
    # OpenAI / ChatGPT
    "127.0.0.1 chatgpt.com $Marker",
    "127.0.0.1 openai.com $Marker",
    "127.0.0.1 api.openai.com $Marker",
    "127.0.0.1 api2.openai.com $Marker",
    "127.0.0.1 cdn.oaistatic.com $Marker",
    "127.0.0.1 oaistatic.com $Marker",
    "127.0.0.1 cdn.chatgpt.com $Marker",
    "127.0.0.1 ab.chatgpt.com $Marker",
    "127.0.0.1 auth0.openai.com $Marker",
    "127.0.0.1 oaisidekickupdates.blob.core.windows.net $Marker",
    # GitHub
    "127.0.0.1 github.com $Marker",
    "127.0.0.1 api.github.com $Marker",
    "127.0.0.1 codeload.github.com $Marker",
    "127.0.0.1 github.githubassets.com $Marker",
    "127.0.0.1 raw.githubusercontent.com $Marker",
    "127.0.0.1 objects.githubusercontent.com $Marker",
    "127.0.0.1 objects-origin.githubusercontent.com $Marker",
    "127.0.0.1 release-assets.githubusercontent.com $Marker",
    "127.0.0.1 registry.npmjs.org $Marker",
    # Tabbit
    "127.0.0.1 tabbitbrowser.com $Marker",
    "127.0.0.1 web.tabbitbrowser.com $Marker",
    "127.0.0.1 cdn.tabbitbrowser.com $Marker",
    # Anthropic / Claude
    "127.0.0.1 anthropic.com $Marker",
    "127.0.0.1 platform.claude.com $Marker",
    "127.0.0.1 downloads.claude.ai $Marker",
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
    # Typeless
    "127.0.0.1 api.typeless.com $Marker",
    "127.0.0.1 typeless-static.com $Marker",
    # Kiro
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
    "127.0.0.1 prod.tools.shortbread.aws.dev $Marker",
    # Qianwen / Tongyi
    "127.0.0.1 qianwen.com $Marker",
    "127.0.0.1 www.qianwen.com $Marker",
    "127.0.0.1 api.qianwen.com $Marker",
    "127.0.0.1 aide.qianwen.com $Marker",
    "127.0.0.1 chat2-api.qianwen.com $Marker",
    "127.0.0.1 chat2.qianwen.com $Marker",
    "127.0.0.1 chat-side.qianwen.com $Marker",
    "127.0.0.1 cms-sdk-server.qianwen.com $Marker",
    "127.0.0.1 zd.qianwen.com $Marker",
    "127.0.0.1 speech-asr.qianwen.com $Marker",
    "127.0.0.1 userver.upaas.qianwen.com $Marker",
    "127.0.0.1 voice-command.qianwen.com $Marker",
    "127.0.0.1 tongyi.aliyun.com $Marker",
    "127.0.0.1 qianwen.aliyun.com $Marker",
    "127.0.0.1 dashscope.aliyuncs.com $Marker",
    "127.0.0.1 nls-gateway.aliyuncs.com $Marker",
    "127.0.0.1 nls-gateway-cn-shanghai.aliyuncs.com $Marker",
    "127.0.0.1 nlsapi.aliyun.com $Marker",
    # Alibaba CDN (Qianwen app JS/CSS)
    "127.0.0.1 g.alicdn.com $Marker",
    "127.0.0.1 gw.alicdn.com $Marker",
    "127.0.0.1 img.alicdn.com $Marker",
    "127.0.0.1 assets.alicdn.com $Marker",
    # Huawei Cloud ModelArts MaaS
    "127.0.0.1 api-ap-southeast-1.modelarts-maas.com $Marker",
    # OpenRouter
    "127.0.0.1 openrouter.ai $Marker"
)

$content = Get-Content $HostsFile -Raw -Encoding UTF8
$lines = $content -split "`r?`n" | Where-Object { $_ -notmatch [regex]::Escape($Marker) }
$allLines = $lines + $Entries
# Write each line separately to avoid the single-line bug with -join + -NoNewline
Set-Content -Path $HostsFile -Value $allLines -Encoding UTF8
ipconfig /flushdns | Out-Null
Write-Host "Added $($Entries.Count) hosts entries and flushed DNS." -ForegroundColor Green

# Stop existing sni_proxy
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*sni_proxy.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Remove-Item $LogOut, $LogErr -ErrorAction SilentlyContinue

$Python = if (Test-Path "D:\anaconda\python.exe") { "D:\anaconda\python.exe" } else { "python.exe" }
Start-Process -FilePath $Python -ArgumentList "`"$ProxyScript`"" -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $LogOut -RedirectStandardError $LogErr

# Wait up to 120s for the proxy to start (self-check can be slow over VPN)
$deadline = (Get-Date).AddSeconds(120)
do {
    Start-Sleep -Milliseconds 500
    $up = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 443 -State Listen -ErrorAction SilentlyContinue
} while (-not $up -and (Get-Date) -lt $deadline)

if ($up) { Write-Host "SNI proxy listening on 127.0.0.1:443." -ForegroundColor Green }
else { Write-Host "SNI proxy did NOT start listening within 120s." -ForegroundColor Red }

# Start SSH tunnel for Qianwen voice (speech-asr.qianwen.com WebSocket)
# The tunnel is needed because Netentsec blocks WebSocket Upgrade inside CONNECT tunnels.
$TunnelScript = Join-Path $Root "qianwen-voice-tunnel.sh"
$GitBash = "D:\Program Files\Git\usr\bin\bash.exe"
$TunnelPort = 7443

$tunnelUp = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $TunnelPort -State Listen -ErrorAction SilentlyContinue
if ($tunnelUp) {
    Write-Host "SSH tunnel already listening on 127.0.0.1:$TunnelPort." -ForegroundColor Green
} elseif (Test-Path $TunnelScript) {
    # Convert Windows path to MSYS path for bash
    $msysPath = "/" + $TunnelScript.Substring(0,1).ToLower() + $TunnelScript.Substring(2).Replace("\", "/")
    Start-Process -FilePath $GitBash -ArgumentList "-lc", $msysPath -WindowStyle Hidden
    $tunnelDeadline = (Get-Date).AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 500
        $tunnelUp = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $TunnelPort -State Listen -ErrorAction SilentlyContinue
    } while (-not $tunnelUp -and (Get-Date) -lt $tunnelDeadline)
    if ($tunnelUp) { Write-Host "SSH tunnel listening on 127.0.0.1:$TunnelPort." -ForegroundColor Green }
    else { Write-Host "SSH tunnel did NOT start within 20s." -ForegroundColor Yellow }
} else {
    Write-Host "No qianwen-voice-tunnel.sh found; skipping SSH tunnel." -ForegroundColor Yellow
}
