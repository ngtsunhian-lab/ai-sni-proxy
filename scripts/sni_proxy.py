"""
Sanitized SNI proxy template for AI clients behind an HTTP corporate proxy.

Configure with environment variables:
  AI_SNI_PROXY_HOST=proxy.huawei.com
  AI_SNI_PROXY_PORT=8080
  AI_SNI_PROXY_USER=<user>
  AI_SNI_PROXY_PASS=<password-or-token>

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ai-sni-proxy")

PROXY_HOST = os.environ.get("AI_SNI_PROXY_HOST", "proxy.huawei.com")
PROXY_PORT = int(os.environ.get("AI_SNI_PROXY_PORT", "8080"))
PROXY_USER = os.environ["AI_SNI_PROXY_USER"]
PROXY_PASS = os.environ["AI_SNI_PROXY_PASS"]
PROXY_AUTH = base64.b64encode(f"{PROXY_USER}:{PROXY_PASS}".encode()).decode()

PROXIED_DOMAINS = {
    "chatgpt.com",
    "openai.com",
    "api.openai.com",
    "cdn.oaistatic.com",
    "oaistatic.com",
    "cdn.chatgpt.com",
    "ab.chatgpt.com",
    "auth0.openai.com",
    "oaisidekickupdates.blob.core.windows.net",
    "anthropic.com",
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
}


def should_proxy(sni: str) -> bool:
    sni = sni.lower()
    return any(sni == domain or sni.endswith("." + domain) for domain in PROXIED_DOMAINS)


def extract_sni(data: bytes) -> str | None:
    try:
        if len(data) < 5 or data[0] != 0x16:
            return None
        hs_offset = 5
        if data[hs_offset] != 0x01:
            return None
        offset = hs_offset + 4 + 2 + 32
        session_len = data[offset]
        offset += 1 + session_len
        cipher_len = struct.unpack("!H", data[offset : offset + 2])[0]
        offset += 2 + cipher_len
        comp_len = data[offset]
        offset += 1 + comp_len
        ext_len = struct.unpack("!H", data[offset : offset + 2])[0]
        offset += 2
        end = offset + ext_len
        while offset + 4 <= min(end, len(data)):
            ext_type = struct.unpack("!H", data[offset : offset + 2])[0]
            item_len = struct.unpack("!H", data[offset + 2 : offset + 4])[0]
            offset += 4
            if ext_type == 0:
                sni_offset = offset + 2
                while sni_offset + 3 <= min(offset + item_len, len(data)):
                    name_type = data[sni_offset]
                    name_len = struct.unpack("!H", data[sni_offset + 1 : sni_offset + 3])[0]
                    sni_offset += 3
                    if name_type == 0 and sni_offset + name_len <= len(data):
                        return data[sni_offset : sni_offset + name_len].decode("ascii")
                    sni_offset += name_len
                return None
            offset += item_len
    except Exception:
        return None
    return None


async def connect_via_proxy(hostname: str, port: int):
    reader, writer = await asyncio.open_connection(PROXY_HOST, PROXY_PORT)
    req = (
        f"CONNECT {hostname}:{port} HTTP/1.1\r\n"
        f"Host: {hostname}:{port}\r\n"
        f"Proxy-Authorization: Basic {PROXY_AUTH}\r\n"
        f"Proxy-Connection: Keep-Alive\r\n\r\n"
    )
    writer.write(req.encode())
    await writer.drain()
    status = (await reader.readline()).decode("latin-1", errors="replace").strip()
    if "200" not in status:
        writer.close()
        raise ConnectionError(f"Proxy rejected CONNECT: {status}")
    while True:
        line = await reader.readline()
        if not line or line == b"\r\n":
            break
    return reader, writer


async def relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError, asyncio.CancelledError):
        pass
    finally:
        writer.close()


async def handle_client(client_reader, client_writer):
    peer = client_writer.get_extra_info("peername")
    try:
        initial = b""
        while len(initial) < 5:
            initial += await client_reader.read(4096)
        record_len = struct.unpack("!H", initial[3:5])[0]
        while len(initial) < 5 + record_len and len(initial) < 8192:
            initial += await client_reader.read(4096)
        sni = extract_sni(initial)
        if not sni or not should_proxy(sni):
            log.warning("Rejected connection from %s with SNI %r", peer, sni)
            client_writer.close()
            return
        log.info("Proxying %s:443 for %s", sni, peer)
        proxy_reader, proxy_writer = await connect_via_proxy(sni, 443)
        proxy_writer.write(initial)
        await proxy_writer.drain()
        await asyncio.gather(
            relay(client_reader, proxy_writer),
            relay(proxy_reader, client_writer),
            return_exceptions=True,
        )
    finally:
        client_writer.close()


def acknowledge_warning_once(domain: str, path: str = "/") -> None:
    """Optional helper pattern: trigger Huawei warning in a real TLS request.

    Production deployments may expand this to parse proxycontrolwarn pages and call
    the observed continue endpoint, or may use a real browser via Kimi WebBridge.
    """
    with socket.create_connection((PROXY_HOST, PROXY_PORT), timeout=10) as raw:
        raw.sendall(
            (
                f"CONNECT {domain}:443 HTTP/1.1\r\n"
                f"Host: {domain}:443\r\n"
                f"Proxy-Authorization: Basic {PROXY_AUTH}\r\n\r\n"
            ).encode()
        )
        data = b""
        while b"\r\n\r\n" not in data:
            data += raw.recv(4096)
        if b"200" not in data.split(b"\r\n", 1)[0]:
            return
        context = ssl._create_unverified_context()
        with context.wrap_socket(raw, server_hostname=domain) as tls:
            tls.sendall(
                (
                    f"GET {path} HTTP/1.1\r\n"
                    f"Host: {domain}\r\n"
                    f"User-Agent: ai-sni-proxy-ack/1.0\r\n"
                    f"Connection: close\r\n\r\n"
                ).encode()
            )
            tls.recv(8192)


async def main():
    server = await asyncio.start_server(handle_client, "127.0.0.1", 443, reuse_address=True)
    log.info("SNI proxy listening on 127.0.0.1:443 via %s:%s", PROXY_HOST, PROXY_PORT)
    await server.serve_forever()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
