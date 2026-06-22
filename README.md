# ai-sni-proxy

[![Repo](https://img.shields.io/badge/GitHub-ngtsunhian--lab%2Fai--sni--proxy-181717?logo=github)](https://github.com/ngtsunhian-lab/ai-sni-proxy)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A local SNI/TLS proxy that lets desktop AI clients (Codex, Claude, ChatGPT, Typeless,
Tabbit, Kiro, Qianwen, ...) reach their APIs from behind an HTTP corporate proxy that
MITMs or gates direct access to AI domains.

## How it works

1. Map the target AI domains to `127.0.0.1` in the Windows hosts file.
2. Run a local SNI proxy on `127.0.0.1:443` (`sni_proxy.py`).
3. The proxy reads the TLS ClientHello SNI, then issues `CONNECT <sni>:443` through the
   corporate HTTP proxy.
4. It relays raw TLS bytes both ways, so the client still believes it is talking directly
   to the real domain. End-to-end TLS terminates at the real server — the proxy never
   decrypts anything.

These are **sanitized templates**: no credentials are committed. Configure your own proxy
host/user/pass via environment variables (see below).

## Proxy selection

**Which corporate proxy edge to use matters.** Cloudflare protects `platform.claude.com`
and `api.anthropic.com` and blocks connections from known proxy/VPN exit IPs with
error 1010 ("Access denied").

In the Huawei corporate network, all proxy edges (proxy, proxybr, proxyjp, proxysg,
proxyca, proxyuk, proxyde) have their exit IPs blocked by Cloudflare. **Direct
connections** (Node.js or Python with `HTTPS_PROXY` set) through **any** edge get
HTTP 403.

The SNI proxy's **raw TCP relay** through `proxybr` bypasses Cloudflare's detection.
This is the key insight: the SNI proxy does a plain `CONNECT` through the corporate
proxy and then relays raw bytes without interpreting them, which apparently avoids
the fingerprinting that CF uses to detect proxy exit traffic.

**Recommended config:**

```powershell
$env:AI_SNI_PROXY_HOST = "proxybr.huawei.com"   # or your equivalent
```

## ⚠️ Do NOT set HTTPS_PROXY

When `HTTPS_PROXY` is set (in shell env, PowerShell profile, or Windows system proxy),
Node.js-based clients (Claude Code, Codex CLI) connect **directly** to the proxy,
bypassing the hosts file entirely. This gets Cloudflare 403 because the direct
connection carries CF-detectable fingerprints.

The SNI proxy route works differently:

```
hosts file → 127.0.0.1 → SNI proxy → CONNECT through proxybr → real server
```

Use the `ai-sni-proxy` wrapper to launch clients — it automatically clears
`HTTP_PROXY`/`HTTPS_PROXY` for the child process:

```powershell
ai-sni-proxy claude          # clears proxy env vars, then runs claude
ai-sni-proxy clear-proxy     # just clears proxy env vars in current shell
```

If you have `HTTPS_PROXY` set in your PowerShell profile, remove it or guard it
so it doesn't apply when using the SNI proxy route.

## Netentsec SSL deep inspection

Some corporate gateways (e.g. Netentsec) perform **SSL deep inspection** inside
`CONNECT` tunnels. After the proxy acknowledges the CONNECT, the gateway reads the
inner TLS ClientHello SNI and blocks AI domains with a 302 redirect to a warning
page — even inside tunnels to a VPS IP.

This means **VPS routing** (where the SNI proxy issues `CONNECT <vps-ip>:443`
instead of `CONNECT <domain>:443`) does **not** work: the gateway inspects the
inner TLS and blocks it anyway. `VPS_ROUTED_DOMAINS` has been removed from the
proxy; all domains now route through direct proxybr CONNECT.

The only way to bypass the SSL inspection for WebSocket-blocked domains is an
SSH tunnel (see below), because the gateway only sees an opaque SSH stream and
cannot inspect the inner traffic.

## Contents

```
scripts/
  sni_proxy.py              # the proxy core (Python): SNI parsing + CONNECT tunneling
  ssh_http_connect.py       # SSH ProxyCommand: tunnel SSH through corporate proxy
  ai-sni-proxy.ps1          # command wrapper: start/stop/status/test + per-client launchers
  start-ai-sni-proxy.ps1    # writes hosts entries (admin) and starts sni_proxy.py
  stop-ai-sni-proxy.ps1     # stops the proxy and removes hosts entries
  watchdog-ai-sni-proxy.ps1 # auto-restarts sni_proxy if it dies (120s startup grace)
  fix-after-travel.py       # one-shot travel self-healing script
  set-codex-dns-policy.py   # set Chromium DNS policies for Codex desktop (run once as admin)
```

## Requirements

- Windows (PowerShell 5.1+)
- Python 3.10+ on `PATH` (the start script prefers a local interpreter, otherwise
  falls back to `python.exe` — adjust the path at the top of `start-ai-sni-proxy.ps1`)
- Administrator rights to edit the hosts file (the start script self-elevates)

## Setup

1. Copy the contents of `scripts/` into `%USERPROFILE%\clash-tun\` (the wrapper looks for
   the start/stop scripts and `sni_proxy.py` there), and put `ai-sni-proxy.ps1` on your
   `PATH`.
2. Set the corporate proxy details as environment variables (the proxy reads these):

   ```powershell
   $env:AI_SNI_PROXY_HOST = "proxybr.huawei.com"   # recommended (see Proxy selection)
   $env:AI_SNI_PROXY_PORT = "8080"
   $env:AI_SNI_PROXY_USER = "<user>"
   $env:AI_SNI_PROXY_PASS = "<password-or-token>"
   ```
3. Edit the domain list in `sni_proxy.py` (`PROXIED_DOMAINS`) and `start-ai-sni-proxy.ps1`
   (`$Entries`) to match the clients you use.

## Usage

```powershell
ai-sni-proxy start          # health-check first; repair the route only if needed
ai-sni-proxy restart        # force stop/start
ai-sni-proxy stop
ai-sni-proxy status
ai-sni-proxy test
ai-sni-proxy logs

# launch a client through the local route only (clears HTTP_PROXY/HTTPS_PROXY):
ai-sni-proxy claude         # Claude Code CLI
ai-sni-proxy claude-desktop
ai-sni-proxy codex          # Codex CLI
ai-sni-proxy codex-desktop
ai-sni-proxy typeless
ai-sni-proxy tabbit
ai-sni-proxy kiro
ai-sni-proxy clear-proxy
```

Through the local route, an unauthenticated probe should return the product's own auth
error rather than a corporate warning page, e.g.:

```text
https://api.anthropic.com/v1/models -> HTTP/1.1 401 Unauthorized (x-api-key required)
https://api.openai.com/v1/models    -> HTTP/1.1 401 Unauthorized (Bearer realm="OpenAI API")
```

## WebSocket-blocked domains (SSH tunnel)

Some gateways MITM the `CONNECT 443` tunnel and reject the WebSocket upgrade (HTTP `403`
on `Upgrade: websocket`), which breaks streaming speech/ASR even though plain HTTPS on the
same domain works. The CONNECT path cannot recover from this — the gateway sees the
`Upgrade` header inside the decrypted tunnel.

Bypass: carry those connections inside an SSH stream to an outside VPS instead of the
corporate CONNECT path. The SSH stream itself goes through the corporate proxy using
`ssh_http_connect.py` as a ProxyCommand.

### Example: Qianwen speech/ASR

```bash
# Start the SSH tunnel (ProxyCommand tunnels SSH through corporate proxy)
# ServerAliveInterval keeps the tunnel alive through idle proxy timeouts.
ssh -L 127.0.0.1:7443:speech-asr.qianwen.com:443 \
    -o ProxyCommand="python ssh_http_connect.py %h %p" \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -p 4444 user@vps
```

Also set `ClientAliveInterval 30` in the VPS `/etc/ssh/sshd_config` so both
ends send keepalive probes. Without this, corporate proxy idle timeouts
silently drop the SSH stream, causing repeated tunnel disconnects.

Then tell the SNI proxy to route that SNI to the local tunnel port:

```powershell
$env:AI_SNI_PROXY_TUNNELS = "speech-asr.qianwen.com=7443"
```

`sni_proxy.py` reads `AI_SNI_PROXY_TUNNELS` (`host=port,host2=port2`) and, for a matching
SNI, connects to `127.0.0.1:<port>` instead of issuing `CONNECT`. The gateway only sees an
opaque SSH stream to the VPS, so it cannot inspect or block the upgrade. End-to-end TLS
still terminates at the real server; the VPS only does dumb TCP forwarding (no certificate
or MITM needed).

`ssh_http_connect.py` reads the same `AI_SNI_PROXY_HOST/USER/PASS` env vars as
`sni_proxy.py`, so no extra configuration is needed.

## Travel self-healing

When you travel and your network changes, three things can break:

1. **Corporate proxy exit IP changes** → VPS security group blocks the new IP → SSH tunnel 504
2. **Hosts file entries missing** → clients connect directly to real IPs → ConnectionRefused
3. **sni_proxy / watchdog / SSH tunnel down** → no proxy running at all

Run `fix-after-travel.py` once to fix all three:

```powershell
python fix-after-travel.py
```

For security group updates, also set:

```powershell
$env:AI_SNI_PROXY_SG_ID = "<security-group-id>"
$env:AI_SNI_PROXY_SG_REGION = "la-north-2"
$env:HW_ACCESS_KEY_ID = "<huawei-cloud-ak>"
$env:HW_SECRET_ACCESS_KEY = "<huawei-cloud-sk>"
```

If those are not set, the security group step is skipped (the other steps still run).

## Proxy warning acknowledgment

Many corporate proxies show an AI warning/consent page before allowing access to AI domains.
`sni_proxy.py` automatically acknowledges these warnings at startup by visiting each
domain through the proxy, parsing the warning page, and calling the continue endpoint.
It also re-acknowledges every 5 minutes in the background to prevent session expiry.

If a `CONNECT` attempt returns a warning redirect mid-session, the proxy automatically
re-acknowledges and retries once.

## Codex desktop DNS policy

Codex desktop is an AppX-packaged Electron app. Launching it with
`--host-resolver-rules` (to force DNS via the hosts file) requires starting the
exe directly, which breaks the AppX sandbox ("无法设置管理员沙盒").

Instead, set Chromium enterprise policies that force the app to use the OS DNS
resolver (which respects the hosts file) and disable DNS-over-HTTPS:

```powershell
python set-codex-dns-policy.py   # run once as admin (UAC prompt)
```

This writes to `HKLM\SOFTWARE\Policies\OpenAI\Codex` and
`HKCU\SOFTWARE\Policies\OpenAI\Codex`:

| Policy | Value | Effect |
|--------|-------|--------|
| `BuiltInDnsClientEnabled` | `0` | Use OS DNS resolver → respects hosts file |
| `DnsOverHttpsMode` | `off` | Disable DNS-over-HTTPS |

These are persistent registry settings — no need to re-run after reboot or
Codex update. After setting the policies, `ai-sni-proxy codex-desktop` launches
Codex via normal AppX activation (sandbox works) and traffic flows through the
SNI proxy.

## Watchdog

`watchdog-ai-sni-proxy.ps1` monitors sni_proxy and restarts it if it dies. It waits
120 seconds for startup (generous for slow VPN links where the warning self-check takes
longer). The start script launches the watchdog automatically.

## License

[MIT](LICENSE)
