---
name: ai-sni-proxy
description: Configure, operate, document, or troubleshoot a local SNI/TLS proxy route for AI clients behind a Huawei corporate proxy. Use when Codex needs to help with OpenAI/Codex Desktop, Claude Code, Anthropic, ChatGPT, hosts-file redirection, Huawei AI warning acknowledgement, PowerShell command wrappers, proxy bypass testing, or distinguishing local SNI proxy traffic from HTTP_PROXY/Windows system proxy traffic.
---

# AI SNI Proxy

## Core Model

Use this skill for the local route:

1. Map target AI domains to `127.0.0.1` in the Windows hosts file.
2. Run a local SNI proxy on `127.0.0.1:443`.
3. Read the TLS ClientHello SNI, then `CONNECT <sni>:443` through Huawei corporate proxy.
4. Relay raw TLS bytes so the AI client still believes it is talking to the real domain.
5. Acknowledge Huawei AI warning pages when needed.
6. Start AI clients in a proxy-isolated environment so they do not silently use `HTTP_PROXY` or Windows system proxy.

## Workflow

When asked to set up or debug this route:

1. Read [references/implementation-guide.md](references/implementation-guide.md) for the full end-to-end design, commands, and troubleshooting matrix.
2. Inspect the live state:
   ```powershell
   ai-sni-proxy status
   Get-Content C:\Windows\System32\drivers\etc\hosts | Select-String SNI-PROXY-AUTO
   Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 443 -ErrorAction SilentlyContinue
   ```
3. If the command wrapper is missing or stale, use the bundled templates in `scripts/` as the source of truth and adapt them to the local machine.
4. Never assume `stop` means "all AI access is blocked." Check `HTTP_PROXY`, `HTTPS_PROXY`, WinHTTP, and Windows user proxy. Desktop Chromium clients may use Windows system proxy unless launched with `--no-proxy-server`.
5. For Codex Desktop and Claude Desktop, fully quit existing processes before testing a changed proxy launch path. Existing Electron processes keep their original network/proxy state.
6. For Claude Desktop, make sure the route includes Claude API, static asset, and Cloudflare Turnstile domains, and launch with QUIC/HTTP3 disabled.

## Canonical Commands

Start the route:

```powershell
ai-sni-proxy start
```

Start clients through the local route only:

```powershell
ai-sni-proxy codex
ai-sni-proxy codex-desktop
ai-sni-proxy claude
ai-sni-proxy claude-desktop
```

Check or test:

```powershell
ai-sni-proxy status
ai-sni-proxy test
ai-sni-proxy logs
```

Stop and clear shell proxy variables:

```powershell
ai-sni-proxy stop
ai-sni-proxy clear-proxy
```

## Expected Test Results

Through the local SNI route, unauthenticated API probes should return product-origin auth errors, not Huawei warning pages:

```text
https://api.anthropic.com/v1/models -> HTTP/1.1 401 Unauthorized, x-api-key header is required
https://api.openai.com/v1/models    -> HTTP/1.1 401 Unauthorized, Bearer realm="OpenAI API"
```

If the response is `302 Location: http://114.114.114.114:9421/proxycontrolwarn/...`, the Huawei AI warning is not acknowledged for that session/path yet.

## Resources

- `references/implementation-guide.md`: Detailed build/run/debug documentation.
- `scripts/sni_proxy.py`: Sanitized SNI proxy template.
- `scripts/ai-sni-proxy.ps1`: Command wrapper template.
- `scripts/start-ai-sni-proxy.ps1`: Startup template.
- `scripts/stop-ai-sni-proxy.ps1`: Shutdown template.
