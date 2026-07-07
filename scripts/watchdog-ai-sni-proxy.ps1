# Watchdog: restart sni_proxy if it dies, with a generous startup wait (120s)
# for slow VPN links where proxy warning self-check takes a long time.
$root        = Split-Path -Parent $PSCommandPath
$proxyScript = Join-Path $root "sni_proxy.py"
$python      = "D:\anaconda\python.exe"
if (-not (Test-Path $python)) { $python = "python.exe" }
$stdoutLog   = Join-Path $root "sni_proxy.out.log"
$stderrLog   = Join-Path $root "sni_proxy.err.log"
$watchdogLog = Join-Path $root "sni_proxy.watchdog.log"
$gitBash             = "D:\Program Files\Git\usr\bin\bash.exe"
$chatgptTunnelScript = Join-Path $root "chatgpt-tunnel.sh"
$qianwenTunnelScript = Join-Path $root "qianwen-voice-tunnel.sh"

function wlog($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    $line | Add-Content -LiteralPath $watchdogLog
    Write-Host $line
}

function restart-proxy {
    $dead = Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*sni_proxy.py*" }
    foreach ($p in $dead) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($dead) { Start-Sleep -Seconds 1 }

    Remove-Item -LiteralPath $stdoutLog, $stderrLog -ErrorAction SilentlyContinue

    Start-Process -FilePath $python `
        -ArgumentList "`"$proxyScript`"" `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog

    # 120s grace: proxy warning self-check can be slow over VPN
    $deadline = (Get-Date).AddSeconds(120)
    do {
        Start-Sleep -Milliseconds 500
        $up = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 443 -State Listen -ErrorAction SilentlyContinue
    } while (-not $up -and (Get-Date) -lt $deadline)

    if ($up) { wlog "sni_proxy restarted OK" }
    else      { wlog "WARNING: sni_proxy failed to come up after restart" }
}

# Relaunch an SSH-tunnel supervisor if its bash while-loop process has been killed.
# Watch the supervisor PROCESS, not the listen port: the loop self-restarts its ssh
# within 3 s of a drop, so the port is briefly down every ~60 s when the corporate
# gateway reaps the long-lived tunnel — that is normal and must not trigger a relaunch.
# NOTE: run this watchdog ELEVATED (the start script launches it via RunAs). A
# non-elevated watchdog cannot read the CommandLine of elevated tunnel processes
# (reads as null), so it would never match them and would spawn endless duplicates.
function ensure-tunnel($scriptPath, $matchPattern, $label) {
    if (-not (Test-Path $gitBash) -or -not (Test-Path $scriptPath)) { return }
    $sup = Get-CimInstance Win32_Process |
        Where-Object { $_.Name -eq "bash.exe" -and $_.CommandLine -and $_.CommandLine -like $matchPattern }
    if ($sup) { return }
    wlog "$label tunnel supervisor down — relaunching"
    $msys = "/" + $scriptPath.Substring(0, 1).ToLower() + ($scriptPath.Substring(2) -replace "\\", "/")
    Start-Process -FilePath $gitBash -ArgumentList "-lc", $msys -WindowStyle Hidden
}

wlog "Watchdog started (checking every 30 s)"

while ($true) {
    $proc = Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*sni_proxy.py*" }
    $port = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 443 -State Listen -ErrorAction SilentlyContinue

    if (-not $proc -or -not $port) {
        wlog "sni_proxy down (proc=$($null -ne $proc) port443=$($null -ne $port)) — restarting"
        restart-proxy
    }

    ensure-tunnel $chatgptTunnelScript "*chatgpt-tunnel*" "ChatGPT"
    ensure-tunnel $qianwenTunnelScript "*qianwen-voice-tunnel*" "Qianwen voice"

    Start-Sleep -Seconds 30
}
