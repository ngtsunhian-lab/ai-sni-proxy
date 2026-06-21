"""
Sanitized SNI proxy template for AI clients behind an HTTP corporate proxy.

Configure with environment variables:
  AI_SNI_PROXY_HOST=proxy.huawei.com
  AI_SNI_PROXY_PORT=8080
  AI_SNI_PROXY_USER=<user>
  AI_SNI_PROXY_PASS=<password-or-token>
  AI_SNI_PROXY_TUNNELS=host=port,host2=port2   (optional; route these SNIs through a
                                                local SSH tunnel instead of the proxy)

This template intentionally does not contain real credentials.
"""

import asyncio
import base64
import logging
import os
import socket
import ssl
import struct
import sys

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sni_proxy")

# Recommended: proxybr.huawei.com (other edges like proxy/proxyjp/proxysg are blocked
# by Cloudflare 1010 for Anthropic/OpenAI domains). The SNI proxy's raw TCP relay
# through proxybr bypasses CF's fingerprinting.
PROXY_HOST = os.environ.get("AI_SNI_PROXY_HOST", "proxy.huawei.com")
PROXY_PORT = int(os.environ.get("AI_SNI_PROXY_PORT", "8080"))
PROXY_USER = os.environ["AI_SNI_PROXY_USER"]
PROXY_PASS = os.environ["AI_SNI_PROXY_PASS"]
PROXY_AUTH = base64.b64encode(f"{PROXY_USER}:{PROXY_PASS}".encode()).decode()

# Domains to proxy through corporate proxy
PROXIED_DOMAINS = {
    # OpenAI / ChatGPT
    "chatgpt.com",
    "openai.com",
    "api.openai.com",
    "api2.openai.com",
    "cdn.oaistatic.com",
    "oaistatic.com",
    "oaisidekickupdates.blob.core.windows.net",
    "cdn.chatgpt.com",
    "ab.chatgpt.com",
    "auth0.openai.com",
    "auth.openai.com",
    "chat.openai.com",
    "cdn.auth0.com",
    # GitHub
    "github.com",
    "api.github.com",
    "codeload.github.com",
    "github.githubassets.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "objects-origin.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "registry.npmjs.org",
    # Tabbit
    "tabbitbrowser.com",
    "cdn.tabbitbrowser.com",
    # Anthropic / Claude
    "anthropic.com",
    "platform.claude.com",
    "downloads.claude.ai",
    "api.anthropic.com",
    "a-api.anthropic.com",
    "claude.ai",
    "claude.com",
    "a.claude.ai",
    "assets.claude.ai",
    "assets-proxy.anthropic.com",
    "a-cdn.anthropic.com",
    "s-cdn.anthropic.com",
    "statsig.anthropic.com",
    "console.anthropic.com",
    "challenges.cloudflare.com",
    # Typeless
    "api.typeless.com",
    "typeless-static.com",
    # Kiro
    "kiro.dev",
    "app.kiro.dev",
    "prod.download.desktop.kiro.dev",
    "prod.us-east-1.auth.desktop.kiro.dev",
    "prod.us-east-1.telemetry.desktop.kiro.dev",
    "gamma.us-east-1.telemetry.desktop.kiro.dev",
    "beta.us-east-1.telemetry.kiro.aws.dev",
    "q.us-east-1.amazonaws.com",
    "q.eu-central-1.amazonaws.com",
    "amzn.awsapps.com",
    "view.awsapps.com",
    "signin.aws.amazon.com",
    "sts.amazonaws.com",
    "assets.app.kiro.dev",
    "kaa-assets.app.kiro.dev",
    "prod.assets.shortbread.aws.dev",
    "prod.log.shortbread.aws.dev",
    "prod.tools.shortbread.aws.dev",
    # Qianwen / Tongyi (wildcard via parent-domain matching)
    "aliyun.com",
    "aliyuncs.com",
    "qianwen.com",
    # Alibaba CDN (needed for Qianwen app JS/CSS)
    "alicdn.com",
    # Huawei Cloud ModelArts MaaS (Anthropic-compatible endpoint for opencode)
    "modelarts-maas.com",
    # OpenRouter (Anthropic-compatible endpoint for claude-openrouter)
    "openrouter.ai",
    # Qianwen speech/ASR (WebSocket — needs SSH tunnel; add to hosts so SNI proxy
    # can route it when AI_SNI_PROXY_TUNNELS is set)
    "speech-asr.qianwen.com",
}

# Hosts file entries to add
HOSTS_ENTRIES = [
    ("chatgpt.com", "127.0.0.1"),
    ("openai.com", "127.0.0.1"),
    ("api.openai.com", "127.0.0.1"),
    ("api2.openai.com", "127.0.0.1"),
    ("cdn.oaistatic.com", "127.0.0.1"),
    ("oaistatic.com", "127.0.0.1"),
    ("cdn.chatgpt.com", "127.0.0.1"),
    ("ab.chatgpt.com", "127.0.0.1"),
    ("auth0.openai.com", "127.0.0.1"),
    ("auth.openai.com", "127.0.0.1"),
    ("chat.openai.com", "127.0.0.1"),
    ("cdn.auth0.com", "127.0.0.1"),
    ("oaisidekickupdates.blob.core.windows.net", "127.0.0.1"),
    ("github.com", "127.0.0.1"),
    ("api.github.com", "127.0.0.1"),
    ("codeload.github.com", "127.0.0.1"),
    ("github.githubassets.com", "127.0.0.1"),
    ("raw.githubusercontent.com", "127.0.0.1"),
    ("objects.githubusercontent.com", "127.0.0.1"),
    ("objects-origin.githubusercontent.com", "127.0.0.1"),
    ("release-assets.githubusercontent.com", "127.0.0.1"),
    ("registry.npmjs.org", "127.0.0.1"),
    ("tabbitbrowser.com", "127.0.0.1"),
    ("web.tabbitbrowser.com", "127.0.0.1"),
    ("cdn.tabbitbrowser.com", "127.0.0.1"),
    ("anthropic.com", "127.0.0.1"),
    ("platform.claude.com", "127.0.0.1"),
    ("downloads.claude.ai", "127.0.0.1"),
    ("api.anthropic.com", "127.0.0.1"),
    ("a-api.anthropic.com", "127.0.0.1"),
    ("claude.ai", "127.0.0.1"),
    ("claude.com", "127.0.0.1"),
    ("a.claude.ai", "127.0.0.1"),
    ("assets.claude.ai", "127.0.0.1"),
    ("assets-proxy.anthropic.com", "127.0.0.1"),
    ("a-cdn.anthropic.com", "127.0.0.1"),
    ("s-cdn.anthropic.com", "127.0.0.1"),
    ("statsig.anthropic.com", "127.0.0.1"),
    ("console.anthropic.com", "127.0.0.1"),
    ("challenges.cloudflare.com", "127.0.0.1"),
    ("api.typeless.com", "127.0.0.1"),
    ("typeless-static.com", "127.0.0.1"),
    ("kiro.dev", "127.0.0.1"),
    ("app.kiro.dev", "127.0.0.1"),
    ("prod.download.desktop.kiro.dev", "127.0.0.1"),
    ("prod.us-east-1.auth.desktop.kiro.dev", "127.0.0.1"),
    ("prod.us-east-1.telemetry.desktop.kiro.dev", "127.0.0.1"),
    ("gamma.us-east-1.telemetry.desktop.kiro.dev", "127.0.0.1"),
    ("beta.us-east-1.telemetry.kiro.aws.dev", "127.0.0.1"),
    ("q.us-east-1.amazonaws.com", "127.0.0.1"),
    ("q.eu-central-1.amazonaws.com", "127.0.0.1"),
    ("amzn.awsapps.com", "127.0.0.1"),
    ("view.awsapps.com", "127.0.0.1"),
    ("signin.aws.amazon.com", "127.0.0.1"),
    ("sts.amazonaws.com", "127.0.0.1"),
    ("assets.app.kiro.dev", "127.0.0.1"),
    ("kaa-assets.app.kiro.dev", "127.0.0.1"),
    ("prod.assets.shortbread.aws.dev", "127.0.0.1"),
    ("prod.log.shortbread.aws.dev", "127.0.0.1"),
    ("prod.tools.shortbread.aws.dev", "127.0.0.1"),
    ("api-ap-southeast-1.modelarts-maas.com", "127.0.0.1"),
    ("openrouter.ai", "127.0.0.1"),
    ("speech-asr.qianwen.com", "127.0.0.1"),
]

HOSTS_FILE = r"C:\Windows\System32\drivers\etc\hosts"
HOSTS_MARKER = "# SNI-PROXY-AUTO"

# Domains routed through a local SSH tunnel instead of the corporate CONNECT path.
# Configure via AI_SNI_PROXY_TUNNELS="host=port,host2=port2" (maps SNI -> local port).
def _parse_tunnels(spec: str) -> dict[str, int]:
    tunnels = {}
    for item in spec.split(","):
        host, _, port = item.strip().partition("=")
        if host and port.isdigit():
            tunnels[host.strip().lower()] = int(port)
    return tunnels

TUNNELED_DOMAINS = _parse_tunnels(os.environ.get("AI_SNI_PROXY_TUNNELS", ""))


def should_proxy(sni: str) -> bool:
    """Check if a domain should be proxied through corporate proxy."""
    sni_lower = sni.lower()
    for domain in PROXIED_DOMAINS:
        if sni_lower == domain or sni_lower.endswith("." + domain):
            return True
    return False


def extract_sni(data: bytes) -> str | None:
    """Extract SNI from TLS ClientHello."""
    try:
        if len(data) < 5:
            return None
        if data[0] != 0x16:
            return None
        record_len = struct.unpack("!H", data[3:5])[0]

        hs_offset = 5
        if data[hs_offset] != 0x01:
            return None

        ch_offset = hs_offset + 4
        ch_offset += 2 + 32
        if ch_offset >= len(data):
            return None
        session_id_len = data[ch_offset]
        ch_offset += 1 + session_id_len

        if ch_offset + 2 > len(data):
            return None
        cipher_len = struct.unpack("!H", data[ch_offset : ch_offset + 2])[0]
        ch_offset += 2 + cipher_len

        if ch_offset + 1 > len(data):
            return None
        comp_len = data[ch_offset]
        ch_offset += 1 + comp_len

        if ch_offset + 2 > len(data):
            return None
        ext_total_len = struct.unpack("!H", data[ch_offset : ch_offset + 2])[0]
        ch_offset += 2

        ext_end = ch_offset + ext_total_len
        while ch_offset + 4 <= min(ext_end, len(data)):
            ext_type = struct.unpack("!H", data[ch_offset : ch_offset + 2])[0]
            ext_len = struct.unpack("!H", data[ch_offset + 2 : ch_offset + 4])[0]
            ch_offset += 4

            if ext_type == 0x0000:
                if ch_offset + 2 > len(data):
                    return None
                sni_list_len = struct.unpack("!H", data[ch_offset : ch_offset + 2])[0]
                sni_offset = ch_offset + 2
                while sni_offset + 3 <= min(ch_offset + ext_len, len(data)):
                    sni_type = data[sni_offset]
                    sni_len = struct.unpack("!H", data[sni_offset + 1 : sni_offset + 3])[0]
                    sni_offset += 3
                    if sni_type == 0:
                        if sni_offset + sni_len <= len(data):
                            return data[sni_offset : sni_offset + sni_len].decode("ascii")
                    sni_offset += sni_len
                return None

            ch_offset += ext_len

        return None
    except Exception:
        return None


def _enable_keepalive(sock: socket.socket, idle: int = 10, interval: int = 5, count: int = 6) -> None:
    """Enable TCP keepalive on a socket to prevent corporate proxy idle-timeout drops."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if sys.platform == "win32":
            sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, idle * 1000, interval * 1000))
        else:
            if hasattr(socket, "TCP_KEEPIDLE"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, idle)
            if hasattr(socket, "TCP_KEEPINTVL"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, interval)
            if hasattr(socket, "TCP_KEEPCNT"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, count)
    except (OSError, AttributeError):
        pass


async def _try_connect(hostname: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, str]:
    """Single CONNECT attempt. Returns (reader, writer, status_line)."""
    reader, writer = await asyncio.open_connection(PROXY_HOST, PROXY_PORT)

    sock = writer.get_extra_info("socket")
    if sock:
        _enable_keepalive(sock)

    connect_req = (
        f"CONNECT {hostname}:{port} HTTP/1.1\r\n"
        f"Host: {hostname}:{port}\r\n"
        f"Proxy-Authorization: Basic {PROXY_AUTH}\r\n"
        f"Proxy-Connection: Keep-Alive\r\n"
        f"\r\n"
    )
    writer.write(connect_req.encode())
    await writer.drain()

    response = await reader.readline()
    if not response:
        writer.close()
        raise ConnectionError("Proxy closed connection during CONNECT")

    status_line = response.decode("latin-1").strip()

    while True:
        line = await reader.readline()
        if not line or line == b"\r\n":
            break

    return reader, writer, status_line


async def connect_via_proxy(hostname: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connect to hostname:port through the corporate HTTP proxy using CONNECT.

    If the proxy returns a warning redirect (non-200), re-acknowledges the warning
    and retries once so long-running sessions recover automatically.
    """
    reader, writer, status_line = await _try_connect(hostname, port)

    if "200" in status_line:
        log.debug(f"CONNECT {hostname}:{port} → {status_line}")
        return reader, writer

    log.warning(f"CONNECT {hostname}:{port} rejected ({status_line}) — re-acknowledging proxy warning and retrying")
    try:
        writer.close()
    except (OSError, AttributeError):
        pass

    await acknowledge_proxy_warning()

    reader, writer, status_line = await _try_connect(hostname, port)
    if "200" not in status_line:
        try:
            writer.close()
        except OSError:
            pass
        raise ConnectionError(f"Proxy rejected CONNECT after re-ack: {status_line}")

    log.info(f"CONNECT {hostname}:{port} succeeded after warning re-acknowledgment")
    return reader, writer


async def relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, name: str):
    """Relay data between two connections."""
    bytes_transferred = 0
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                log.info(f"relay {name}: EOF after {bytes_transferred} bytes")
                break
            bytes_transferred += len(data)
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError) as e:
        log.info(f"relay {name}: {type(e).__name__}: {e} (after {bytes_transferred} bytes)")
    except asyncio.CancelledError:
        log.debug(f"relay {name}: cancelled after {bytes_transferred} bytes")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except OSError:
            pass


async def handle_client(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter):
    """Handle an incoming TLS connection."""
    peer = client_writer.get_extra_info("peername")
    client_sock = client_writer.get_extra_info("socket")
    if client_sock:
        _enable_keepalive(client_sock)
    try:
        initial_data = b""
        while len(initial_data) < 5:
            chunk = await client_reader.read(4096)
            if not chunk:
                client_writer.close()
                return
            initial_data += chunk

        if initial_data[0] != 0x16:
            log.warning(f"Non-TLS connection from {peer}, closing")
            client_writer.close()
            return

        record_len = struct.unpack("!H", initial_data[3:5])[0]
        needed = 5 + record_len
        while len(initial_data) < needed and len(initial_data) < 2048:
            chunk = await client_reader.read(4096)
            if not chunk:
                break
            initial_data += chunk

        sni = extract_sni(initial_data)
        if not sni:
            log.warning(f"No SNI found in ClientHello from {peer}, closing")
            client_writer.close()
            return

        if not should_proxy(sni):
            log.info(f"SNI {sni} not in proxy list, closing")
            client_writer.close()
            return

        tunnel_port = TUNNELED_DOMAINS.get(sni.lower())
        if tunnel_port is not None:
            log.info(f"Routing {sni}:443 through SSH tunnel 127.0.0.1:{tunnel_port} for {peer}")
            proxy_reader, proxy_writer = await asyncio.open_connection("127.0.0.1", tunnel_port)
        else:
            log.info(f"Proxying {sni}:443 through corporate proxy for {peer}")
            proxy_reader, proxy_writer = await connect_via_proxy(sni, 443)

        proxy_writer.write(initial_data)
        await proxy_writer.drain()

        task1 = asyncio.create_task(relay(client_reader, proxy_writer, f"client->{sni}"))
        task2 = asyncio.create_task(relay(proxy_reader, client_writer, f"{sni}->client"))
        await asyncio.gather(task1, task2, return_exceptions=True)
        log.info(f"Connection to {sni}:443 closed")

    except ConnectionError as e:
        log.error(f"Connection error for {peer}: {e}")
    except Exception as e:
        log.error(f"Error handling {peer}: {e}")
    finally:
        try:
            client_writer.close()
            await client_writer.wait_closed()
        except OSError:
            pass


def setup_hosts():
    """Add entries to hosts file for proxied domains."""
    try:
        with open(HOSTS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        lines = [l for l in content.splitlines() if HOSTS_MARKER not in l]
        for domain, ip in HOSTS_ENTRIES:
            lines.append(f"{ip} {domain} {HOSTS_MARKER}")
        with open(HOSTS_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        log.info(f"Added {len(HOSTS_ENTRIES)} entries to hosts file")
        os.system("ipconfig /flushdns >nul 2>&1")
    except PermissionError:
        log.error("Need admin privileges to modify hosts file!")
        sys.exit(1)


def cleanup_hosts():
    """Remove auto-added entries from hosts file."""
    try:
        with open(HOSTS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        lines = [l for l in content.splitlines() if HOSTS_MARKER not in l]
        with open(HOSTS_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        log.info("Removed hosts file entries")
        os.system("ipconfig /flushdns >nul 2>&1")
    except Exception as e:
        log.error(f"Error cleaning hosts file: {e}")


async def acknowledge_proxy_warning():
    """Proactively acknowledge the corporate proxy AI warning for proxied domains.

    The proxy shows a warning page for AI domains (chatgpt.com, openai.com).
    We visit each domain, get the warning page, extract the session ID,
    and call the continue endpoint to register acknowledgment.
    """
    import re
    import urllib.parse
    domains_to_ack = [
        "chatgpt.com",
        "openai.com",
        "api.openai.com",
        "web.tabbitbrowser.com",
        "cdn.tabbitbrowser.com",
        "anthropic.com",
        "api.anthropic.com",
        "claude.ai",
        "api.typeless.com",
        "typeless-static.com",
        "app.kiro.dev",
        "prod.download.desktop.kiro.dev",
        "prod.us-east-1.auth.desktop.kiro.dev",
        "prod.us-east-1.telemetry.desktop.kiro.dev",
        "q.us-east-1.amazonaws.com",
        "www.qianwen.com",
        "tongyi.aliyun.com",
        "dashscope.aliyuncs.com",
        "nls-gateway.aliyuncs.com",
        "nls-gateway-cn-shanghai.aliyuncs.com",
        "speech-asr.qianwen.com",
        "voice-command.qianwen.com",
        "userver.upaas.qianwen.com",
        "openrouter.ai",
    ]
    ack_url_pattern = re.compile(r"sessionid=(\w+).*?pid=(\d+).*?uid=(\d+)")
    hidden_input_pattern = re.compile(
        r'id="(sessionid|pid|uid)"[^>]*value="([^"]*)"', re.IGNORECASE
    )

    async def fetch_warning_page(location: str) -> str:
        page_reader, page_writer = await asyncio.wait_for(
            asyncio.open_connection(PROXY_HOST, PROXY_PORT), timeout=10
        )
        page_req = (
            f"GET {location} HTTP/1.1\r\n"
            f"Host: 114.114.114.114:9421\r\n"
            f"Proxy-Authorization: Basic {PROXY_AUTH}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        page_writer.write(page_req.encode())
        await page_writer.drain()
        page_data = await asyncio.wait_for(page_reader.read(65536), timeout=10)
        page_writer.close()
        try:
            await page_writer.wait_closed()
        except OSError:
            pass
        _, _, body = page_data.partition(b"\r\n\r\n")
        return body.decode("utf-8", errors="replace")

    async def continue_warning(sid: str, pid: str, uid: str, domain: str):
        cont_url = f"http://114.114.114.114:9421/proxycontrolwarn/continue?sessionid={sid}&pid={pid}&uid={uid}"
        cont_reader, cont_writer = await asyncio.wait_for(
            asyncio.open_connection(PROXY_HOST, PROXY_PORT), timeout=10
        )
        cont_req = (
            f"GET {cont_url} HTTP/1.1\r\n"
            f"Host: 114.114.114.114:9421\r\n"
            f"Proxy-Authorization: Basic {PROXY_AUTH}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        cont_writer.write(cont_req.encode())
        await cont_writer.drain()
        cont_resp = await asyncio.wait_for(cont_reader.readline(), timeout=10)
        cont_writer.close()
        if "200" in cont_resp.decode("latin-1", errors="replace"):
            log.info(f"Acknowledged proxy warning for {domain}")
        else:
            log.warning(f"Continue request failed for {domain}")

    def hotfix19_token(payload: str) -> str:
        """Encode proxy warning_hotfix19.js check token."""
        def mc(value: int) -> str:
            chars = "0123456789ABCDEF"
            if value == ord(" "):
                return "+"
            if (
                (value < ord("0") and value not in (ord("-"), ord(".")))
                or (ord("9") < value < ord("A"))
                or (ord("Z") < value < ord("a") and value != ord("_"))
                or value > ord("z")
            ):
                return "%" + chars[value >> 4] + chars[value & 15]
            return chr(value)

        def mirror_bits(value: int) -> int:
            return (
                ((1 & value) << 7)
                | ((2 & value) << 5)
                | ((4 & value) << 3)
                | ((8 & value) << 1)
                | ((16 & value) >> 1)
                | ((32 & value) >> 3)
                | ((64 & value) >> 5)
                | ((128 & value) >> 7)
            )

        encoded = base64.b64encode(payload.encode()).decode()
        transformed = "".join(mc(53 ^ mirror_bits(ord(ch)) ^ (255 & index)) for index, ch in enumerate(encoded))
        return base64.b64encode(transformed.encode()).decode()

    async def check_warning(sid: str, pid: str, uid: str, ori_url: str, domain: str):
        payload = f"ori_url={ori_url}&sessionid={sid}&pid={pid}&uid={uid}"
        check_url = f"http://114.114.114.114:9421/proxycontrolwarn/check?{hotfix19_token(payload)}"
        check_reader, check_writer = await asyncio.wait_for(
            asyncio.open_connection(PROXY_HOST, PROXY_PORT), timeout=10
        )
        check_req = (
            f"GET {check_url} HTTP/1.1\r\n"
            f"Host: 114.114.114.114:9421\r\n"
            f"Proxy-Authorization: Basic {PROXY_AUTH}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        check_writer.write(check_req.encode())
        await check_writer.drain()
        check_resp = await asyncio.wait_for(check_reader.readline(), timeout=10)
        check_writer.close()
        if "200" in check_resp.decode("latin-1", errors="replace"):
            log.info(f"Checked proxy warning for {domain}")
        else:
            log.warning(f"Check request failed for {domain}")

    def get_warning_location(domain: str) -> str | None:
        """Make a real HTTPS request through proxy and return warning Location."""
        with socket.create_connection((PROXY_HOST, PROXY_PORT), timeout=10) as raw_sock:
            raw_sock.settimeout(10)
            connect_req = (
                f"CONNECT {domain}:443 HTTP/1.1\r\n"
                f"Host: {domain}:443\r\n"
                f"Proxy-Authorization: Basic {PROXY_AUTH}\r\n"
                f"Proxy-Connection: Keep-Alive\r\n"
                f"\r\n"
            )
            raw_sock.sendall(connect_req.encode())

            proxy_response = b""
            while b"\r\n\r\n" not in proxy_response:
                chunk = raw_sock.recv(4096)
                if not chunk:
                    break
                proxy_response += chunk

            proxy_status = proxy_response.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
            if "200" not in proxy_status:
                log.warning(f"Proxy rejected CONNECT to {domain}: {proxy_status}")
                return None

            context = ssl._create_unverified_context()
            with context.wrap_socket(raw_sock, server_hostname=domain) as tls_sock:
                tls_sock.settimeout(10)
                if domain == "api.anthropic.com":
                    path = "/v1/models"
                elif domain == "web.tabbitbrowser.com":
                    path = "/sidebar"
                elif domain == "cdn.tabbitbrowser.com":
                    path = "/web-prod/_next/static/media/569ce4b8f30dc480-s.p.woff2"
                else:
                    path = "/"
                request = (
                    f"GET {path} HTTP/1.1\r\n"
                    f"Host: {domain}\r\n"
                    f"User-Agent: sni-proxy-ack/1.0\r\n"
                    f"Accept: */*\r\n"
                    f"Connection: close\r\n"
                    f"\r\n"
                )
                tls_sock.sendall(request.encode())

                response = b""
                while len(response) < 65536:
                    try:
                        chunk = tls_sock.recv(4096)
                    except socket.timeout:
                        break
                    if not chunk:
                        break
                    response += chunk
                    if b"\r\n\r\n" in response and b"proxycontrolwarn" in response:
                        break

            headers = response.split(b"\r\n\r\n", 1)[0].decode("latin-1", errors="replace")
            status = headers.splitlines()[0] if headers else ""
            if "302" not in status:
                log.info(f"{domain}: no proxy warning (got {status[:60]})")
                return None

            for header in headers.splitlines()[1:]:
                if header.lower().startswith("location:"):
                    location = header.split(":", 1)[1].strip()
                    if "proxycontrolwarn" in location:
                        return location
            return None

    for domain in domains_to_ack:
        try:
            location = await asyncio.to_thread(get_warning_location, domain)
            if not location:
                continue

            match = ack_url_pattern.search(location)
            if match:
                sid, pid, uid = match.group(1), match.group(2), match.group(3)
                await continue_warning(sid, pid, uid, domain)
                continue

            warning_html = await fetch_warning_page(location)
            fields = dict(hidden_input_pattern.findall(warning_html))
            sid = fields.get("sessionid")
            pid = fields.get("pid")
            uid = fields.get("uid")
            if sid and pid and uid:
                ori_url = urllib.parse.parse_qs(urllib.parse.urlparse(location).query).get("ori_url", [None])[0]
                if ori_url:
                    await check_warning(sid, pid, uid, ori_url, domain)
                await continue_warning(sid, pid, uid, domain)
            else:
                log.warning(f"Could not parse warning page for {domain}")

        except Exception as e:
            log.warning(f"Error checking proxy warning for {domain}: {e}")


async def periodic_ack(interval_seconds: int = 300):
    """Re-acknowledge proxy warnings every interval_seconds to prevent session expiry."""
    while True:
        await asyncio.sleep(interval_seconds)
        log.info("Periodic proxy warning re-acknowledgment...")
        try:
            await acknowledge_proxy_warning()
        except Exception as e:
            log.warning(f"Periodic ack failed: {e}")


async def main():
    log.info("Acknowledging proxy AI warnings...")
    await acknowledge_proxy_warning()

    server = await asyncio.start_server(
        handle_client, "127.0.0.1", 443, reuse_address=True
    )

    log.info("SNI proxy listening on 127.0.0.1:443")
    log.info(f"Proxying through {PROXY_HOST}:{PROXY_PORT}")
    log.info(f"Domains: {', '.join(sorted(PROXIED_DOMAINS))}")

    asyncio.create_task(periodic_ack(300))

    try:
        await server.serve_forever()
    finally:
        log.info("Shutting down...")
        cleanup_hosts()
        log.info("Done")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
