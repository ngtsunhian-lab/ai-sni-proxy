# Watchdog: restart sni_proxy if it dies, with a generous startup wait (120s)
# for slow VPN links where proxy warning self-check takes a long time.
$root        = Split-Path -Parent $PSCommandPath
$proxyScript = Join-Path $root "sni_proxy.py"
$python      = "D:\anaconda\python.exe"
if (-not (Test-Path $python)) { $python = "python.exe" }
$stdoutLog   = Join-Path $root "sni_proxy.out.log"
$stderrLog   = Join-Path $root "sni_proxy.err.log"
$watchdogLog = Join-Path $root "sni_proxy.watchdog.log"

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

wlog "Watchdog started (checking every 30 s)"

while ($true) {
    $proc = Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*sni_proxy.py*" }
    $port = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 443 -State Listen -ErrorAction SilentlyContinue

    if (-not $proc -or -not $port) {
        wlog "sni_proxy down (proc=$($null -ne $proc) port443=$($null -ne $port)) — restarting"
        restart-proxy
    }

    Start-Sleep -Seconds 30
}
