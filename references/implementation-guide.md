# AI SNI Proxy Implementation Guide

## Purpose

This guide documents a local SNI/TLS proxy route used to make AI clients such as Codex Desktop, Codex CLI, Claude Code, OpenAI API clients, and Anthropic API clients work behind Huawei corporate proxy controls.

The route is useful when direct client proxy configuration is insufficient because the corporate proxy injects an AI warning/acknowledgement page or because a desktop client does not reliably respect standard proxy variables.

## Architecture

```text
AI client
  |
  | resolves api.openai.com / api.anthropic.com / chatgpt.com to 127.0.0.1
  v
127.0.0.1:443 local SNI proxy
  |
  | reads TLS ClientHello SNI without terminating TLS
  | CONNECT <sni>:443 HTTP/1.1
  v
Huawei corporate proxy
  |
  | optional AI warning / acknowledgement
  v
Real upstream AI service
```

The local proxy does not decrypt AI traffic. It only peeks at the TLS ClientHello to learn the SNI hostname, opens a CONNECT tunnel through Huawei proxy, then relays raw bytes.

## Files Used On This Machine

Current working deployment paths:

```text
%USERPROFILE%\clash-tun\sni_proxy.py
%USERPROFILE%\clash-tun\start-ai-sni-proxy.ps1
%USERPROFILE%\clash-tun\stop-ai-sni-proxy.ps1
%USERPROFILE%\.local\bin\ai-sni-proxy.ps1
%USERPROFILE%\.local\bin\ai-sni-proxy.cmd
%USERPROFILE%\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1
```

The skill bundles sanitized templates under `scripts/`; do not store corporate credentials in the skill.

## Domain Mapping

Hosts entries are marked with:

```text
# SNI-PROXY-AUTO
```

Typical mapped domains:

```text
chatgpt.com
openai.com
api.openai.com
cdn.oaistatic.com
oaistatic.com
cdn.chatgpt.com
ab.chatgpt.com
auth0.openai.com
oaisidekickupdates.blob.core.windows.net
anthropic.com
api.anthropic.com
a-api.anthropic.com
claude.ai
claude.com
a.claude.ai
assets.claude.ai
assets-proxy.anthropic.com
a-cdn.anthropic.com
s-cdn.anthropic.com
statsig.anthropic.com
console.anthropic.com
challenges.cloudflare.com
```

After writing hosts entries, always flush DNS:

```powershell
ipconfig /flushdns
```

## Corporate Proxy Configuration

Use environment variables for credentials in reusable scripts:

```powershell
$env:AI_SNI_PROXY_HOST = "proxy.huawei.com"
$env:AI_SNI_PROXY_PORT = "8080"
$env:AI_SNI_PROXY_USER = "<corporate-id>"
$env:AI_SNI_PROXY_PASS = "<corporate-password-or-token>"
```

Avoid hardcoding passwords in skill files or committed scripts.

## SNI Proxy Behavior

The Python proxy:

1. Listens on `127.0.0.1:443`.
2. Reads the first TLS record from the client.
3. Parses SNI from the ClientHello.
4. Rejects traffic whose SNI is not in the allowlist.
5. Opens `CONNECT <sni>:443` through Huawei proxy with `Proxy-Authorization`.
6. Writes the buffered ClientHello into the tunnel.
7. Relays both directions until either side closes.

## Huawei AI Warning Acknowledgement

Huawei may return:

```text
HTTP/1.1 302 Found
Location: http://114.114.114.114:9421/proxycontrolwarn/httpwarning_3355.html?ori_url=...&uid=0
```

The warning page contains hidden fields:

```html
<input id="sessionid" value="..." />
<input id="pid" value="3355" />
<input id="uid" value="0" />
```

The acknowledgement endpoint observed in this environment:

```text
http://114.114.114.114:9421/proxycontrolwarn/continue?sessionid=<sid>&pid=<pid>&uid=<uid>
```

In practice, acknowledgement may be session-specific. If automated `/continue` returns `200` but later API calls still receive a warning `302`, open the URL once through the real browser and click the Huawei "continue" button. Kimi WebBridge can automate this when its browser extension is connected.

## Global Command Wrapper

The global command is:

```powershell
ai-sni-proxy <command>
```

Subcommands:

```text
start             Start local route, update hosts, start 127.0.0.1:443 proxy.
stop              Stop SNI proxy and remove hosts entries.
restart           Stop then start.
status            Show listener, hosts, DNS, shell proxy, Windows user proxy, WinHTTP proxy.
test              Probe Anthropic/OpenAI through local route.
logs              Show recent proxy logs.
claude            Start Claude Code with HTTP_PROXY/HTTPS_PROXY cleared.
claude-desktop    Start Claude Desktop with HTTP_PROXY/HTTPS_PROXY cleared, --no-proxy-server, and QUIC/HTTP3 disabled.
codex             Start Codex CLI with HTTP_PROXY/HTTPS_PROXY cleared.
codex-desktop     Start Codex Desktop with HTTP_PROXY/HTTPS_PROXY cleared and --no-proxy-server.
clear-proxy       Clear HTTP_PROXY/HTTPS_PROXY in the current PowerShell session.
```

PowerShell profile registration provides tab completion for subcommands and common client flags.

## Why `stop` May Not Block Access

`ai-sni-proxy stop` only disables the local route:

```text
127.0.0.1:443 listener
hosts mappings tagged # SNI-PROXY-AUTO
```

AI clients may still work through other routes:

1. Current shell has `HTTP_PROXY` or `HTTPS_PROXY`.
2. Windows user proxy is enabled under Internet Settings.
3. WinHTTP proxy is configured.
4. Codex Desktop is already running and still has an existing network process.
5. Client has cached sessions or open connections.

Check all routes:

```powershell
ai-sni-proxy status
Get-ChildItem Env: | Where-Object { $_.Name -match 'proxy|ANTHROPIC|OPENAI' }
netsh winhttp show proxy
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' |
  Select-Object ProxyEnable,ProxyServer,AutoConfigURL
```

## Codex Desktop Notes

Codex Desktop is an Electron/Chromium app. It may use Windows system proxy even when shell environment variables are empty.

To force it onto the local SNI route:

1. Start route:
   ```powershell
   ai-sni-proxy start
   ```
2. Fully quit existing Codex processes.
3. Start desktop through wrapper:
   ```powershell
   ai-sni-proxy codex-desktop
   ```

The wrapper starts Codex Desktop with:

```text
--no-proxy-server
```

This prevents Chromium from using Windows system proxy, so the hosts redirection to `127.0.0.1:443` becomes the decisive route.

## Claude Code Notes

Claude Code supports standard proxy variables. If `HTTPS_PROXY` is set, plain `claude` may work even when the SNI route is stopped.

To force Claude Code onto the local SNI route:

```powershell
ai-sni-proxy start
ai-sni-proxy claude
```

To test that plain `claude` is not using shell proxy:

```powershell
ai-sni-proxy clear-proxy
claude
```

## Claude Desktop Notes

Claude Desktop is also an Electron/Chromium app, but it has two extra requirements beyond Claude Code:

1. It loads Claude web, API, static asset, analytics/config, and Cloudflare Turnstile challenge domains.
2. Chromium may try QUIC/HTTP3, which bypasses a TCP-only local SNI proxy route.

Make sure these domains are included in both the SNI proxy allowlist and hosts entries:

```text
claude.ai
claude.com
a.claude.ai
assets.claude.ai
api.anthropic.com
a-api.anthropic.com
assets-proxy.anthropic.com
a-cdn.anthropic.com
s-cdn.anthropic.com
statsig.anthropic.com
console.anthropic.com
challenges.cloudflare.com
```

Start it through the wrapper:

```powershell
ai-sni-proxy start
Get-Process claude -ErrorAction SilentlyContinue | Stop-Process -Force
ai-sni-proxy claude-desktop
```

For MSIX/AppX installs, do not launch only through `shell:AppsFolder\<AppId>` unless direct executable resolution fails. Resolve the installed package first and prefer:

```powershell
$appx = Get-AppxPackage -Name Claude
Start-Process (Join-Path $appx.InstallLocation "app\Claude.exe") -ArgumentList @(
  "--no-proxy-server",
  "--disable-quic",
  "--disable-http3",
  "--disable-features=UseDnsHttpsSvcbAlpn"
)
```

Launching through the AppId fallback starts Claude, but Electron/Chromium does not receive the flags, which can leave desktop-only features routed through Windows proxy or HTTP3.

The wrapper should pass:

```text
--no-proxy-server
--disable-quic
--disable-http3
--disable-features=UseDnsHttpsSvcbAlpn
```

Successful startup signs in `main.log` include:

```text
claude.ai account active and logged in
LocalSessionManager Initialization succeeded
LocalAgentModeSessionManager Initialization succeeded
```

If logs show `SNI challenges.cloudflare.com not in proxy list, closing`, update and restart the SNI proxy allowlist. If auxiliary endpoints such as GrowthBook or Skills return Cloudflare `403`, the core login/model route may still be usable as long as account/session initialization succeeds.

## Expected Validation

With local SNI route running:

```powershell
ai-sni-proxy status
```

Expected:

```text
Listener: 127.0.0.1:443 up
Hosts entries: 12
api.anthropic.com resolves to: 127.0.0.1
```

Probe Anthropic:

```powershell
curl.exe -sk --noproxy '*' -D - https://api.anthropic.com/v1/models -o NUL
```

Expected:

```text
HTTP/1.1 401 Unauthorized
x-api-key header is required
```

Probe OpenAI:

```powershell
curl.exe -sk --noproxy '*' -D - https://api.openai.com/v1/models -o NUL
```

Expected:

```text
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer realm="OpenAI API"
```

If Anthropic/OpenAI returns a Huawei `302` warning URL, refresh acknowledgement through Kimi WebBridge or browser.

## Common Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `127.0.0.1:443 not running` | Proxy process not started or failed | `ai-sni-proxy logs`, then `ai-sni-proxy start` |
| Hosts entries are 0 | Route is stopped | `ai-sni-proxy start` |
| `api.anthropic.com` resolves to public IP | Hosts not active | Run start as admin; flush DNS |
| Client works after `stop` | It is using shell or Windows proxy | Check `ai-sni-proxy status`; run `clear-proxy`; check Windows proxy |
| `codex-desktop` works after `stop` | Existing process or Windows system proxy | Quit all `Codex.exe`; launch with `ai-sni-proxy codex-desktop` |
| API returns Huawei `302` | Warning not acknowledged | Use Kimi WebBridge/browser acknowledgement |
| API returns `401` | Network path is working | Add real API credentials if needed |

## Safe Shutdown

Use:

```powershell
ai-sni-proxy stop
ai-sni-proxy clear-proxy
```

For desktop clients, also fully quit existing app processes if you need a clean negative test.
