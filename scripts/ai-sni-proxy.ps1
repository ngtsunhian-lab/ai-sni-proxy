param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status", "test", "logs", "claude", "claude-desktop", "codex", "codex-desktop", "clear-proxy", "help")]
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
    Write-Host "  ai-sni-proxy start [-SkipKimiAck]"
    Write-Host "  ai-sni-proxy stop"
    Write-Host "  ai-sni-proxy restart [-SkipKimiAck]"
    Write-Host "  ai-sni-proxy status"
    Write-Host "  ai-sni-proxy test"
    Write-Host "  ai-sni-proxy logs"
    Write-Host "  ai-sni-proxy claude [claude args...]"
    Write-Host "  ai-sni-proxy claude-desktop"
    Write-Host "  ai-sni-proxy codex [codex args...]"
    Write-Host "  ai-sni-proxy codex-desktop"
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

    Write-Host "Starting Codex desktop through the local SNI route only..." -ForegroundColor Cyan
    Write-Host "HTTP_PROXY/HTTPS_PROXY will be cleared for this Codex desktop process." -ForegroundColor Cyan
    Write-Host "Chromium system proxy use will be disabled with --no-proxy-server." -ForegroundColor Cyan
    Start-Process -FilePath $codexDesktop -ArgumentList "--no-proxy-server"
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
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript @Rest
    }
    "stop" {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopScript
    }
    "restart" {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopScript
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript @Rest
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
    "clear-proxy" {
        Clear-CurrentShellProxy
    }
    default {
        Show-Help
    }
}
