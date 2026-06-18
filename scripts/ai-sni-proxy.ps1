param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "ensure", "status", "test", "logs", "claude", "claude-desktop", "codex", "codex-desktop", "typeless", "tabbit", "kiro", "clear-proxy", "help")]
    [string]$Command = "help",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"

$proxyRoot = Join-Path $env:USERPROFILE "clash-tun"
$startScript = Join-Path $proxyRoot "start-ai-sni-proxy.ps1"
$stopScript = Join-Path $proxyRoot "stop-ai-sni-proxy.ps1"
$stderrLog = Join-Path $proxyRoot "sni_proxy.err.log"
$marker = "# SNI-PROXY-AUTO"
$hostsFile = "$env:SystemRoot\System32\drivers\etc\hosts"

function Show-Help {
    Write-Host "Usage:" -ForegroundColor Cyan
    Write-Host "  ai-sni-proxy start [-SkipKimiAck]    # health-check first; repair only if needed"
    Write-Host "  ai-sni-proxy stop"
    Write-Host "  ai-sni-proxy restart [-SkipKimiAck]  # force stop/start"
    Write-Host "  ai-sni-proxy ensure [-SkipKimiAck]"
    Write-Host "  ai-sni-proxy status"
    Write-Host "  ai-sni-proxy test"
    Write-Host "  ai-sni-proxy logs"
    Write-Host "  ai-sni-proxy claude [claude args...]"
    Write-Host "  ai-sni-proxy claude-desktop"
    Write-Host "  ai-sni-proxy codex [codex args...]"
    Write-Host "  ai-sni-proxy codex-desktop"
    Write-Host "  ai-sni-proxy typeless"
    Write-Host "  ai-sni-proxy tabbit"
    Write-Host "  ai-sni-proxy kiro"
    Write-Host "  ai-sni-proxy clear-proxy"
}

function Show-Status {
    Write-Host "SNI proxy status" -ForegroundColor Cyan

    $listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 443 -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        $pids = $listener | Select-Object -ExpandProperty OwningProcess -Unique
        Write-Host "  Listener: 127.0.0.1:443 up (PID: $($pids -join ', '))" -ForegroundColor Green
    } else {
        Write-Host "  Listener: 127.0.0.1:443 not running" -ForegroundColor Yellow
    }

    $hostEntries = Get-Content $hostsFile -ErrorAction SilentlyContinue | Select-String ([regex]::Escape($marker))
    Write-Host "  Hosts entries: $($hostEntries.Count)"

    $anthropicDns = Resolve-DnsName api.anthropic.com -Type A -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty IPAddress
    Write-Host "  api.anthropic.com resolves to: $anthropicDns"

    $claudePlatformDns = Resolve-DnsName platform.claude.com -Type A -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty IPAddress
    Write-Host "  platform.claude.com resolves to: $claudePlatformDns"

    $proc = Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*sni_proxy.py*" } |
        Select-Object -First 1
    if ($proc) {
        Write-Host "  Process: $($proc.ProcessId) $($proc.CommandLine)"
    }

    $httpsProxy = [Environment]::GetEnvironmentVariable("HTTPS_PROXY")
    $httpProxy = [Environment]::GetEnvironmentVariable("HTTP_PROXY")
    if ($httpsProxy -or $httpProxy) {
        Write-Host "  Current shell proxy: HTTP_PROXY/HTTPS_PROXY set" -ForegroundColor Yellow
        Write-Host "    HTTP_PROXY=$httpProxy"
        Write-Host "    HTTPS_PROXY=$httpsProxy"
    } else {
        Write-Host "  Current shell proxy: HTTP_PROXY/HTTPS_PROXY not set"
    }

    $internetSettings = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" -ErrorAction SilentlyContinue
    if ($internetSettings -and $internetSettings.ProxyEnable -eq 1) {
        Write-Host "  Windows user proxy: enabled ($($internetSettings.ProxyServer))" -ForegroundColor Yellow
    } else {
        Write-Host "  Windows user proxy: disabled"
    }

    $winHttpProxy = netsh winhttp show proxy 2>$null
    $winHttpProxyText = ($winHttpProxy -join " ")
    if ($winHttpProxyText -match "Direct access") {
        Write-Host "  WinHTTP proxy: direct"
    } elseif ($winHttpProxyText -match "Proxy Server") {
        Write-Host "  WinHTTP proxy: configured" -ForegroundColor Yellow
    }
}

function Invoke-Tests {
    Write-Host "Testing Anthropic through local SNI proxy..." -ForegroundColor Cyan
    curl.exe -sk --noproxy "*" -D - --connect-timeout 20 https://api.anthropic.com/v1/models -o NUL

    Write-Host ""
    Write-Host "Testing Claude OAuth through local SNI proxy..." -ForegroundColor Cyan
    curl.exe -sk --noproxy "*" -D - --connect-timeout 20 -X POST https://platform.claude.com/v1/oauth/token -o NUL

    Write-Host ""
    Write-Host "Testing ChatGPT through local SNI proxy..." -ForegroundColor Cyan
    curl.exe -sk --noproxy "*" -D - --connect-timeout 20 https://chatgpt.com/ -o NUL
}

function Test-SniProxyHealth {
    param([switch]$Quiet)

    $healthy = $true
    $listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 443 -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        if (-not $Quiet) { Write-Host "  Listener: up" -ForegroundColor Green }
    } else {
        if (-not $Quiet) { Write-Host "  Listener: not running" -ForegroundColor Red }
        $healthy = $false
    }

    $anthropicDns = Resolve-DnsName api.anthropic.com -Type A -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty IPAddress
    if ($anthropicDns -eq "127.0.0.1") {
        if (-not $Quiet) { Write-Host "  api.anthropic.com DNS: 127.0.0.1" -ForegroundColor Green }
    } else {
        if (-not $Quiet) { Write-Host "  api.anthropic.com DNS: $anthropicDns" -ForegroundColor Red }
        $healthy = $false
    }

    $claudePlatformDns = Resolve-DnsName platform.claude.com -Type A -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty IPAddress
    if ($claudePlatformDns -eq "127.0.0.1") {
        if (-not $Quiet) { Write-Host "  platform.claude.com DNS: 127.0.0.1" -ForegroundColor Green }
    } else {
        if (-not $Quiet) { Write-Host "  platform.claude.com DNS: $claudePlatformDns" -ForegroundColor Red }
        $healthy = $false
    }

    if ($listener -and $anthropicDns -eq "127.0.0.1") {
        $headers = & curl.exe -sk --noproxy "*" -D - --connect-timeout 10 --max-time 25 https://api.anthropic.com/v1/models -o NUL 2>&1
        $curlExit = $LASTEXITCODE
        $statusLine = ($headers | Select-String -Pattern "^HTTP/" | Select-Object -Last 1).Line
        if ($curlExit -eq 0 -and $statusLine -match " 401 ") {
            if (-not $Quiet) { Write-Host "  Anthropic probe: $statusLine" -ForegroundColor Green }
        } else {
            if (-not $Quiet) {
                Write-Host "  Anthropic probe failed: curl exit $curlExit, status '$statusLine'" -ForegroundColor Red
            }
            $healthy = $false
        }
    }

    return $healthy
}

function Ensure-SniProxy {
    Write-Host "Checking local SNI proxy health..." -ForegroundColor Cyan
    if (Test-SniProxyHealth) {
        Write-Host "SNI proxy is healthy. No restart needed." -ForegroundColor Green
        return
    }

    Write-Host "SNI proxy health check failed. Restarting route..." -ForegroundColor Yellow
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopScript
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript @Rest

    Start-Sleep -Seconds 3
    Write-Host "Rechecking local SNI proxy health..." -ForegroundColor Cyan
    if (Test-SniProxyHealth) {
        Write-Host "SNI proxy recovered." -ForegroundColor Green
    } else {
        Write-Host "SNI proxy still looks unhealthy. Run 'ai-sni-proxy logs' for details." -ForegroundColor Red
        exit 1
    }
}

function Start-ClaudeThroughSni {
    $env:HTTP_PROXY = ""
    $env:HTTPS_PROXY = ""
    $env:http_proxy = ""
    $env:https_proxy = ""
    $env:NO_PROXY = "*"
    $env:no_proxy = "*"

    Write-Host "Starting Claude Code through the local SNI route only..." -ForegroundColor Cyan
    Write-Host "HTTP_PROXY/HTTPS_PROXY will be cleared for this Claude process." -ForegroundColor Cyan
    & claude @Rest
}

function Start-CodexThroughSni {
    $env:HTTP_PROXY = ""
    $env:HTTPS_PROXY = ""
    $env:http_proxy = ""
    $env:https_proxy = ""
    $env:NO_PROXY = "*"
    $env:no_proxy = "*"

    Write-Host "Starting Codex CLI through the local SNI route only..." -ForegroundColor Cyan
    Write-Host "HTTP_PROXY/HTTPS_PROXY will be cleared for this Codex process." -ForegroundColor Cyan
    & codex @Rest
}

function Start-ClaudeDesktopThroughSni {
    $env:HTTP_PROXY = ""
    $env:HTTPS_PROXY = ""
    $env:http_proxy = ""
    $env:https_proxy = ""
    $env:NO_PROXY = "*"
    $env:no_proxy = "*"
    $env:NODE_TLS_REJECT_UNAUTHORIZED = "0"
    $chromiumArgs = @(
        "--no-proxy-server",
        "--disable-quic",
        "--disable-http3",
        "--disable-features=UseDnsHttpsSvcbAlpn"
    )

    $candidates = @(
        "$env:LOCALAPPDATA\AnthropicClaude\claude.exe",
        "$env:LOCALAPPDATA\Programs\claude\claude.exe",
        "$env:LOCALAPPDATA\Programs\anthropic-claude\claude.exe",
        "$env:PROGRAMFILES\Anthropic\Claude\claude.exe",
        "${env:PROGRAMFILES(X86)}\Anthropic\Claude\claude.exe"
    )
    $claudeDesktop = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

    $appx = Get-AppxPackage -Name "Claude" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $appx) {
        $appx = Get-AppxPackage -Name "*AnthropicClaude*" -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if (-not $claudeDesktop -and $appx -and $appx.InstallLocation) {
        $candidate = Join-Path $appx.InstallLocation "app\Claude.exe"
        if (Test-Path -LiteralPath $candidate) {
            $claudeDesktop = $candidate
        }
    }

    if (-not $claudeDesktop) {
        if ($appx) {
            $appId = "$($appx.PackageFamilyName)!App"
            Write-Host "Could not resolve Claude.exe directly. Falling back to AppID: $appId" -ForegroundColor Yellow
            Write-Host "Warning: AppID fallback cannot pass Chromium flags." -ForegroundColor Yellow
            Start-Process -FilePath "explorer.exe" -ArgumentList "shell:AppsFolder\$appId"
        } else {
            Write-Host "Claude Desktop not found. Download from https://claude.ai/download" -ForegroundColor Red
            Write-Host "Searched:" -ForegroundColor Yellow
            $candidates | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
        }
        return
    }

    Write-Host "Starting Claude Desktop through the local SNI route only..." -ForegroundColor Cyan
    Write-Host "HTTP_PROXY/HTTPS_PROXY will be cleared for this Claude Desktop process." -ForegroundColor Cyan
    Write-Host "Chromium system proxy and QUIC/HTTP3 will be disabled." -ForegroundColor Cyan
    Start-Process -FilePath $claudeDesktop -ArgumentList $chromiumArgs
}

function Start-CodexDesktopThroughSni {
    $env:HTTP_PROXY = ""
    $env:HTTPS_PROXY = ""
    $env:http_proxy = ""
    $env:https_proxy = ""
    $env:NO_PROXY = "*"
    $env:no_proxy = "*"

    $codexDesktop = $null

    $appx = Get-AppxPackage OpenAI.Codex -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($appx -and $appx.InstallLocation) {
        $candidate = Join-Path $appx.InstallLocation "app\Codex.exe"
        if (Test-Path -LiteralPath $candidate) {
            $codexDesktop = $candidate
        }
    }

    if (-not $codexDesktop) {
        $running = Get-CimInstance Win32_Process |
            Where-Object { $_.Name -eq "Codex.exe" -and $_.ExecutablePath -like "*\app\Codex.exe" } |
            Select-Object -First 1
        if ($running -and $running.ExecutablePath -and (Test-Path -LiteralPath $running.ExecutablePath)) {
            $codexDesktop = $running.ExecutablePath
        }
    }

    if (-not $codexDesktop) {
        Write-Host "Could not resolve Codex.exe directly. Falling back to Start menu AppID." -ForegroundColor Yellow
        Start-Process -FilePath "explorer.exe" -ArgumentList "shell:AppsFolder\OpenAI.Codex_2p2nqsd0c76g0!App"
        return
    }

    # --no-sandbox: AppX exe launched directly lacks AppContainer token → sandbox init fails.
    # This suppresses the "无法设置管理员沙盒" warning. Safe for a desktop app.
    # host-resolver-rules: force Chromium renderer to use hosts file DNS instead of HTTPDNS/DoH.
    # Without this, the renderer bypasses hosts and resolves to real IPs → ConnectionRefused.
    $argString = '--no-sandbox --no-proxy-server --disable-quic --disable-http3 --disable-features=UseDnsHttpsSvcbAlpn,DnsOverHttpsUpgrade,BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessSendPreflights,PrivateNetworkAccessRespectPreflightResults,LocalNetworkAccessChecks "--host-resolver-rules=MAP chatgpt.com 127.0.0.1, MAP openai.com 127.0.0.1, MAP api.openai.com 127.0.0.1, MAP api2.openai.com 127.0.0.1, MAP cdn.oaistatic.com 127.0.0.1, MAP oaistatic.com 127.0.0.1, MAP cdn.chatgpt.com 127.0.0.1, MAP ab.chatgpt.com 127.0.0.1, MAP auth0.openai.com 127.0.0.1, MAP oaisidekickupdates.blob.core.windows.net 127.0.0.1, MAP github.com 127.0.0.1, MAP api.github.com 127.0.0.1, MAP codeload.github.com 127.0.0.1, MAP github.githubassets.com 127.0.0.1, MAP raw.githubusercontent.com 127.0.0.1, MAP objects.githubusercontent.com 127.0.0.1, MAP objects-origin.githubusercontent.com 127.0.0.1, MAP release-assets.githubusercontent.com 127.0.0.1, MAP registry.npmjs.org 127.0.0.1"'

    Write-Host "Starting Codex desktop through the local SNI route only..." -ForegroundColor Cyan
    Write-Host "HTTP_PROXY/HTTPS_PROXY will be cleared for this Codex desktop process." -ForegroundColor Cyan
    Write-Host "Using --no-proxy-server + --host-resolver-rules for the local SNI route." -ForegroundColor Cyan
    Start-Process -FilePath $codexDesktop -ArgumentList $argString
}

function Start-TypelessThroughSni {
    $env:HTTP_PROXY = ""
    $env:HTTPS_PROXY = ""
    $env:http_proxy = ""
    $env:https_proxy = ""
    $env:NO_PROXY = "*"
    $env:no_proxy = "*"

    $chromiumArgs = @(
        "--no-proxy-server",
        "--disable-quic",
        "--disable-http3",
        "--disable-features=UseDnsHttpsSvcbAlpn"
    )

    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Typeless\Typeless.exe",
        "$env:LOCALAPPDATA\Typeless\Typeless.exe",
        "$env:PROGRAMFILES\Typeless\Typeless.exe",
        "${env:PROGRAMFILES(X86)}\Typeless\Typeless.exe"
    )

    $typeless = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $typeless) {
        Write-Host "Typeless Desktop not found." -ForegroundColor Red
        Write-Host "Searched:" -ForegroundColor Yellow
        $candidates | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
        return
    }

    Write-Host "Starting Typeless Desktop through the local SNI route only..." -ForegroundColor Cyan
    Write-Host "HTTP_PROXY/HTTPS_PROXY will be cleared for this Typeless process." -ForegroundColor Cyan
    Write-Host "Chromium system proxy and QUIC/HTTP3 will be disabled." -ForegroundColor Cyan
    Start-Process -FilePath $typeless -ArgumentList $chromiumArgs
}

function Start-TabbitThroughSni {
    $env:HTTP_PROXY = ""
    $env:HTTPS_PROXY = ""
    $env:http_proxy = ""
    $env:https_proxy = ""
    $env:NO_PROXY = "*"
    $env:no_proxy = "*"

    $chromiumArgs = @(
        "--no-proxy-server",
        "--disable-quic",
        "--disable-http3",
        "--disable-features=UseDnsHttpsSvcbAlpn"
    )

    $candidates = @(
        "$env:LOCALAPPDATA\Tabbit\Application\Tabbit.exe",
        "$env:LOCALAPPDATA\Programs\Tabbit\Tabbit.exe",
        "$env:PROGRAMFILES\Tabbit\Tabbit.exe",
        "${env:PROGRAMFILES(X86)}\Tabbit\Tabbit.exe"
    )
    $tabbit = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $tabbit) {
        Write-Host "Tabbit Browser not found." -ForegroundColor Red
        Write-Host "Searched:" -ForegroundColor Yellow
        $candidates | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
        return
    }

    Write-Host "Starting Tabbit Browser through the local SNI route only..." -ForegroundColor Cyan
    Write-Host "HTTP_PROXY/HTTPS_PROXY will be cleared for this Tabbit process." -ForegroundColor Cyan
    Write-Host "Chromium system proxy and QUIC/HTTP3 will be disabled." -ForegroundColor Cyan
    Start-Process -FilePath $tabbit -ArgumentList $chromiumArgs
}

function Start-KiroThroughSni {
    $env:HTTP_PROXY = ""
    $env:HTTPS_PROXY = ""
    $env:http_proxy = ""
    $env:https_proxy = ""
    $env:NO_PROXY = "*"
    $env:no_proxy = "*"
    $env:NODE_TLS_REJECT_UNAUTHORIZED = "0"

    $chromiumArgs = @(
        "--no-proxy-server",
        "--disable-quic",
        "--disable-http3",
        "--disable-features=UseDnsHttpsSvcbAlpn"
    )

    $candidates = @(
        "D:\Program Files\Kiro\Kiro.exe",
        "$env:LOCALAPPDATA\Programs\Kiro\Kiro.exe",
        "$env:LOCALAPPDATA\Kiro\Kiro.exe",
        "$env:PROGRAMFILES\Kiro\Kiro.exe",
        "${env:PROGRAMFILES(X86)}\Kiro\Kiro.exe"
    )
    $kiro = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $kiro) {
        Write-Host "Kiro Desktop not found." -ForegroundColor Red
        Write-Host "Searched:" -ForegroundColor Yellow
        $candidates | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
        return
    }

    Write-Host "Starting Kiro Desktop through the local SNI route only..." -ForegroundColor Cyan
    Write-Host "HTTP_PROXY/HTTPS_PROXY will be cleared for this Kiro process." -ForegroundColor Cyan
    Write-Host "Chromium system proxy and QUIC/HTTP3 will be disabled." -ForegroundColor Cyan
    Start-Process -FilePath $kiro -ArgumentList $chromiumArgs
}

function Clear-CurrentShellProxy {
    Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue
    Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
    Remove-Item Env:http_proxy -ErrorAction SilentlyContinue
    Remove-Item Env:https_proxy -ErrorAction SilentlyContinue
    $env:NO_PROXY = "*"
    $env:no_proxy = "*"
    Write-Host "Cleared HTTP_PROXY/HTTPS_PROXY in this process." -ForegroundColor Green
    Write-Host "In PowerShell, prefer the profile function version so the parent shell is modified too." -ForegroundColor Yellow
}

switch ($Command) {
    "start" {
        Ensure-SniProxy
    }
    "stop" {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopScript
    }
    "restart" {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopScript
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript @Rest
    }
    "ensure" {
        Ensure-SniProxy
    }
    "status" {
        Show-Status
    }
    "test" {
        Invoke-Tests
    }
    "logs" {
        if (Test-Path $stderrLog) {
            Get-Content -Path $stderrLog -Tail 120
        } else {
            Write-Host "No log file yet: $stderrLog" -ForegroundColor Yellow
        }
    }
    "claude" {
        Start-ClaudeThroughSni
    }
    "claude-desktop" {
        Start-ClaudeDesktopThroughSni
    }
    "codex" {
        Start-CodexThroughSni
    }
    "codex-desktop" {
        Start-CodexDesktopThroughSni
    }
    "typeless" {
        Start-TypelessThroughSni
    }
    "tabbit" {
        Start-TabbitThroughSni
    }
    "kiro" {
        Start-KiroThroughSni
    }
    "clear-proxy" {
        Clear-CurrentShellProxy
    }
    default {
        Show-Help
    }
}
