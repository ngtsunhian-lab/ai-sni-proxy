"""
SSH ProxyCommand helper: tunnel SSH through an HTTP corporate proxy.

Usage (in ~/.ssh/config or on the command line):
  ssh -o ProxyCommand="python ssh_http_connect.py %h %p" user@vps

Or with explicit proxy host/port:
  ssh -o ProxyCommand="python ssh_http_connect.py %h %p proxybr.example.com 8080" user@vps

Credentials come from the same env vars as sni_proxy.py:
  AI_SNI_PROXY_HOST   (fallback: proxy.huawei.com)
  AI_SNI_PROXY_PORT   (fallback: 8080)
  AI_SNI_PROXY_USER
  AI_SNI_PROXY_PASS

This template intentionally does not contain real credentials.
"""

import base64
import os
import socket
import sys
import threading


def relay_socket_to_fd(src, dst_fd, closer):
    try:
        while True:
            data = src.recv(32768)
            if not data:
                break
            os.write(dst_fd, data)
    except Exception:
        pass
    finally:
        try:
            closer.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            closer.close()
        except Exception:
            pass


def relay_fd_to_socket(src_fd, dst, closer):
    try:
        while True:
            data = os.read(src_fd, 32768)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try:
            closer.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            closer.close()
        except Exception:
            pass


def main():
    if len(sys.argv) < 3:
        print("usage: ssh_http_connect.py host port [proxy_host] [proxy_port]", file=sys.stderr)
        return 2

    host = sys.argv[1]
    port = int(sys.argv[2])

    # Proxy config: CLI args > env vars > defaults
    proxy_host = (
        sys.argv[3] if len(sys.argv) > 3
        else os.environ.get("AI_SNI_PROXY_HOST", "proxy.huawei.com")
    )
    proxy_port = (
        int(sys.argv[4]) if len(sys.argv) > 4
        else int(os.environ.get("AI_SNI_PROXY_PORT", "8080"))
    )
    proxy_user = os.environ.get("AI_SNI_PROXY_USER", "")
    proxy_pass = os.environ.get("AI_SNI_PROXY_PASS", "")

    sock = socket.create_connection((proxy_host, proxy_port), timeout=15)

    # Build CONNECT request with optional auth
    headers = [
        f"CONNECT {host}:{port} HTTP/1.1",
        f"Host: {host}:{port}",
    ]
    if proxy_user and proxy_pass:
        proxy_auth = base64.b64encode(f"{proxy_user}:{proxy_pass}".encode()).decode()
        headers.append(f"Proxy-Authorization: Basic {proxy_auth}")
    headers.append("Proxy-Connection: Keep-Alive")
    req = ("\r\n".join(headers) + "\r\n\r\n").encode("ascii")
    sock.sendall(req)

    header = b""
    while b"\r\n\r\n" not in header:
        chunk = sock.recv(1)
        if not chunk:
            print("proxy closed before CONNECT response", file=sys.stderr)
            return 1
        header += chunk
    if not header.startswith(b"HTTP/1.1 200") and not header.startswith(b"HTTP/1.0 200"):
        print(header.decode("latin1", errors="replace"), file=sys.stderr)
        return 1

    t1 = threading.Thread(
        target=relay_fd_to_socket, args=(sys.stdin.fileno(), sock, sock), daemon=True
    )
    t2 = threading.Thread(
        target=relay_socket_to_fd, args=(sock, sys.stdout.fileno(), sock), daemon=True
    )
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
