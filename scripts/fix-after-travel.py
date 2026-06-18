"""
fix-after-travel.py — ai-sni-proxy travel self-healing script

When you travel and your network changes, run this once to fix:
1. Corporate proxy exit IP changed → VPS security group not updated → SSH tunnel 504
2. Hosts file empty/incomplete → Claude/Codex connect to real IP → ConnectionRefused
3. sni_proxy / watchdog / SSH tunnel down

Usage (admin):  python fix-after-travel.py

Idempotent: safe to re-run; no duplicate rules or processes.

Environment variables (same as sni_proxy.py):
  AI_SNI_PROXY_HOST, AI_SNI_PROXY_PORT, AI_SNI_PROXY_USER, AI_SNI_PROXY_PASS

Additional (for security group update):
  AI_SNI_PROXY_SG_ID      — Huawei Cloud security group ID (default: amers-sg)
  AI_SNI_PROXY_SG_REGION  — Huawei Cloud region (default: la-north-2)
  HW_ACCESS_KEY_ID        — Huawei Cloud AK
  HW_SECRET_ACCESS_KEY    — Huawei Cloud SK
"""

import base64
import os
import re
import socket
import ssl
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
HOSTS_FILE = r"C:\Windows\System32\drivers\etc\hosts"
HOSTS_MARKER = "# sni-proxy"

# Corporate proxy config (from env, same as sni_proxy.py)
PROXY_HOST = os.environ.get("AI_SNI_PROXY_HOST", "proxy.huawei.com")
PROXY_PORT = int(os.environ.get("AI_SNI_PROXY_PORT", "8080"))
PROXY_USER = os.environ["AI_SNI_PROXY_USER"]
PROXY_PASS = os.environ["AI_SNI_PROXY_PASS"]
PROXY_AUTH = base64.b64encode(f"{PROXY_USER}:{PROXY_PASS}".encode()).decode()

# VPS security group config (from env)
SG_ID = os.environ.get("AI_SNI_PROXY_SG_ID", "")
SG_REGION = os.environ.get("AI_SNI_PROXY_SG_REGION", "la-north-2")
HW_AK = os.environ.get("HW_ACCESS_KEY_ID", "")
HW_SK = os.environ.get("HW_SECRET_ACCESS_KEY", "")
SG_PORTS = [
    (22,   "SSH (proxy exit IP)"),
    (4444, "SSH-alt (proxy exit IP)"),
    (80,   "nginx/dashboard (proxy exit IP)"),
    (8088, "gateway dashboard (proxy exit IP)"),
    (4000, "gateway litellm (proxy exit IP)"),
]

# Domains to write into hosts (sync with start-ai-sni-proxy.ps1)
SNI_PROXY_DOMAINS = [
    "api.anthropic.com", "a-api.anthropic.com", "platform.claude.com",
    "claude.ai", "claude.com", "a.claude.ai", "downloads.claude.ai",
    "assets.claude.ai", "assets-proxy.anthropic.com",
    "a-cdn.anthropic.com", "s-cdn.anthropic.com", "statsig.anthropic.com",
    "console.anthropic.com", "challenges.cloudflare.com",
    "chatgpt.com", "api.openai.com", "openai.com", "auth0.openai.com",
    "cdn.chatgpt.com", "cdn.oaistatic.com", "oaistatic.com",
    "ab.chatgpt.com", "api2.openai.com", "api.github.com",
    "oaisidekickupdates.blob.core.windows.net",
    "github.com", "github.githubassets.com", "objects.githubusercontent.com",
    "objects-origin.githubusercontent.com", "raw.githubusercontent.com",
    "codeload.github.com", "release-assets.githubusercontent.com",
    "registry.npmjs.org",
    "api.typeless.com", "typeless-static.com",
    "kiro.dev", "app.kiro.dev", "prod.download.desktop.kiro.dev",
    "prod.us-east-1.auth.desktop.kiro.dev",
    "prod.us-east-1.telemetry.desktop.kiro.dev",
    "gamma.us-east-1.telemetry.desktop.kiro.dev",
    "assets.app.kiro.dev", "kaa-assets.app.kiro.dev",
    "beta.us-east-1.telemetry.kiro.aws.dev",
    "q.us-east-1.amazonaws.com", "q.eu-central-1.amazonaws.com",
    "amzn.awsapps.com", "view.awsapps.com",
    "signin.aws.amazon.com", "sts.amazonaws.com",
    "prod.assets.shortbread.aws.dev", "prod.log.shortbread.aws.dev",
    "prod.tools.shortbread.aws.dev",
    "qianwen.com", "www.qianwen.com", "api.qianwen.com",
    "aide.qianwen.com", "chat2-api.qianwen.com", "chat2.qianwen.com",
    "chat-side.qianwen.com", "cms-sdk-server.qianwen.com", "zd.qianwen.com",
    "speech-asr.qianwen.com", "userver.upaas.qianwen.com", "voice-command.qianwen.com",
    "tongyi.aliyun.com", "qianwen.aliyun.com", "dashscope.aliyuncs.com",
    "nls-gateway.aliyuncs.com", "nls-gateway-cn-shanghai.aliyuncs.com",
    "nlsapi.aliyun.com",
    "g.alicdn.com", "gw.alicdn.com", "img.alicdn.com", "assets.alicdn.com",
    "api-ap-southeast-1.modelarts-maas.com",
    "openrouter.ai",
    "tabbitbrowser.com", "web.tabbitbrowser.com", "cdn.tabbitbrowser.com",
]

VERIFY_DOMAINS = ["api.anthropic.com", "chatgpt.com"]


def status(ok, msg):
    tag = "OK" if ok else "FAIL"
    print(f"  [{'+'if ok else '!'}] {tag}: {msg}")
    return ok


def proxy_connect(host, port, timeout=10):
    s = socket.create_connection((PROXY_HOST, PROXY_PORT), timeout=timeout)
    s.settimeout(timeout)
    req = (
        f"CONNECT {host}:{port} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Proxy-Authorization: Basic {PROXY_AUTH}\r\n"
        f"Proxy-Connection: Keep-Alive\r\n\r\n"
    )
    s.sendall(req.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = s.recv(4096)
        if not chunk:
            break
        resp += chunk
    if b"200" not in resp.split(b"\r\n")[0]:
        s.close()
        raise ConnectionError(f"Proxy CONNECT {host}:{port} failed")
    return s


def is_port_listening(addr, port):
    try:
        s = socket.create_connection((addr, port), timeout=2)
        s.close()
        return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def run(cmd, **kwargs):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                          timeout=kwargs.pop("timeout", 60), **kwargs)


def detect_proxy_exit_ip():
    print("\n[Step 1] Detect corporate proxy exit IP...")
    try:
        raw = proxy_connect("api.ipify.org", 443)
        ctx = ssl.create_default_context()
        tls = ctx.wrap_socket(raw, server_hostname="api.ipify.org")
        tls.sendall(b"GET / HTTP/1.1\r\nHost: api.ipify.org\r\nConnection: close\r\n\r\n")
        data = b""
        while True:
            chunk = tls.recv(4096)
            if not chunk:
                break
            data += chunk
        tls.close()
        body = data.split(b"\r\n\r\n", 1)[1].decode().strip()
        ip = body.strip().split("\r\n")[-1].strip()
        socket.inet_aton(ip)
        status(True, f"Proxy exit IP = {ip}")
        return ip
    except Exception as e:
        status(False, f"Detection failed: {e}")
        return None


def update_security_group(new_ip):
    print(f"\n[Step 2] Update VPS security group (IP: {new_ip})...")
    if not SG_ID or not HW_AK or not HW_SK:
        return status(False, "Skip: AI_SNI_PROXY_SG_ID / HW_ACCESS_KEY_ID / HW_SECRET_ACCESS_KEY not set")
    try:
        import warnings
        warnings.filterwarnings("ignore")
        from huaweicloudsdkcore.auth.credentials import BasicCredentials
        from huaweicloudsdkcore.region.region import Region
        from huaweicloudsdkcore.http.http_config import HttpConfig
        from huaweicloudsdkvpc.v2 import (VpcClient, ShowSecurityGroupRequest,
            CreateSecurityGroupRuleRequest)
        from huaweicloudsdkvpc.v2.model import (CreateSecurityGroupRuleRequestBody,
            NeutronCreateSecurityGroupRuleOption)
    except ImportError as e:
        return status(False, f"Huawei Cloud SDK not installed: {e}")

    try:
        credentials = BasicCredentials(HW_AK, HW_SK)
        credentials.with_iam_endpoint("https://iam.myhuaweicloud.com")
        http_config = HttpConfig(
            proxy_protocol="http", proxy_host=PROXY_HOST, proxy_port=PROXY_PORT,
            proxy_user=PROXY_USER, proxy_password=PROXY_PASS,
            ignore_ssl_verification=True, timeout=(30, 60))
        vpc = VpcClient.new_builder().with_credentials(credentials).with_region(
            Region(SG_REGION, f"https://vpc.{SG_REGION}.myhuaweicloud.com")
        ).with_http_config(http_config).build()

        cidr = f"{new_ip}/32"
        existing = vpc.show_security_group(
            ShowSecurityGroupRequest(security_group_id=SG_ID)
        ).security_group.security_group_rules

        added, skipped = 0, 0
        for port, desc in SG_PORTS:
            found = any(
                r.direction == "ingress" and r.protocol == "tcp"
                and r.port_range_min == port and r.port_range_max == port
                and r.remote_ip_prefix == cidr
                for r in existing
            )
            if found:
                skipped += 1
                continue
            opt = NeutronCreateSecurityGroupRuleOption(
                security_group_id=SG_ID, direction="ingress", ethertype="IPv4",
                protocol="tcp", port_range_min=port, port_range_max=port,
                remote_ip_prefix=cidr, description=desc)
            vpc.create_security_group_rule(
                CreateSecurityGroupRuleRequest(
                    body=CreateSecurityGroupRuleRequestBody(security_group_rule=opt)))
            added += 1
        status(True, f"SG: added {added}, skipped {skipped} (cidr={cidr})")
        return True
    except Exception as e:
        return status(False, f"SG update failed: {e}")


def ensure_hosts():
    print("\n[Step 3] Check hosts file...")
    try:
        with open(HOSTS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = ""

    existing_domains = set()
    for line in content.splitlines():
        if HOSTS_MARKER in line:
            parts = line.split()
            if len(parts) >= 2:
                existing_domains.add(parts[1])

    missing = [d for d in SNI_PROXY_DOMAINS if d not in existing_domains]
    if not missing:
        status(True, f"Hosts complete ({len(existing_domains)} entries)")
        return True

    print(f"  Missing {len(missing)} domains, writing hosts...")
    lines = [l for l in content.splitlines() if HOSTS_MARKER not in l]
    new_entries = [f"127.0.0.1 {d} {HOSTS_MARKER}" for d in SNI_PROXY_DOMAINS]
    new_content = "\n".join(lines + new_entries) + "\n"

    try:
        with open(HOSTS_FILE, "w", encoding="utf-8") as f:
            f.write(new_content)
    except PermissionError:
        return status(False, "Permission denied writing hosts (run as admin)")

    run("ipconfig /flushdns", timeout=10)
    status(True, f"Hosts updated ({len(SNI_PROXY_DOMAINS)} entries), DNS flushed")
    return True


def restart_sni_proxy():
    print("\n[Step 4] Restart sni_proxy + watchdog...")
    run('wmic process where "commandline like \'%%sni_proxy.py%%\'" call terminate', timeout=10)
    time.sleep(1)
    result = run("netstat -ano | findstr :443 | findstr LISTENING", timeout=5)
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 5:
                try:
                    run(f"taskkill /PID {int(parts[-1])} /F", timeout=5)
                except (ValueError, subprocess.TimeoutExpired):
                    pass
    time.sleep(1)
    run('wmic process where "commandline like \'%%watchdog-ai-sni-proxy%%\'" call terminate', timeout=10)

    python = "D:\\anaconda\\python.exe"
    if not os.path.exists(python):
        python = "python.exe"
    proxy_script = os.path.join(ROOT, "sni_proxy.py")
    stdout_log = os.path.join(ROOT, "sni_proxy.out.log")
    stderr_log = os.path.join(ROOT, "sni_proxy.err.log")

    for f in [stdout_log, stderr_log]:
        try:
            open(f, "w").close()
        except OSError:
            pass

    subprocess.Popen(
        [python, proxy_script], cwd=ROOT,
        stdout=open(stdout_log, "w"), stderr=open(stderr_log, "w"),
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    print("  sni_proxy.py started, waiting for port 443...")

    deadline = time.time() + 120
    while time.time() < deadline:
        if is_port_listening("127.0.0.1", 443):
            status(True, "sni_proxy listening on 127.0.0.1:443")
            break
        time.sleep(2)
    else:
        status(False, "sni_proxy did not listen on 443 within 120s")

    watchdog = os.path.join(ROOT, "watchdog-ai-sni-proxy.ps1")
    if os.path.exists(watchdog):
        run(
            f'powershell -NoProfile -Command "Start-Process powershell '
            f'-ArgumentList \'\'-NoProfile\',\'\'-ExecutionPolicy\',\'\'Bypass\',\'\'-WindowStyle\',\'\'Hidden\',\'\'-File\',\'\'{watchdog}\'\' '
            f'-WindowStyle Hidden"',
            timeout=10,
        )
        status(True, "Watchdog started")


def ensure_ssh_tunnel():
    print("\n[Step 5] Check SSH tunnel (7443)...")
    if is_port_listening("127.0.0.1", 7443):
        status(True, "SSH tunnel already listening on 127.0.0.1:7443")
        return True

    print("  Tunnel not running, starting...")
    tunnel_script = os.path.join(ROOT, "qianwen-voice-tunnel.sh")
    git_bash = "D:\\Program Files\\Git\\usr\\bin\\bash.exe"
    if not os.path.exists(tunnel_script) or not os.path.exists(git_bash):
        status(False, "Tunnel script or git-bash not found")
        return False

    msys_path = "/" + tunnel_script[0].lower() + tunnel_script[2:].replace("\\", "/")
    subprocess.Popen(
        [git_bash, "-lc", msys_path],
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )

    deadline = time.time() + 20
    while time.time() < deadline:
        if is_port_listening("127.0.0.1", 7443):
            status(True, "SSH tunnel up on 127.0.0.1:7443")
            return True
        time.sleep(1)
    status(False, "SSH tunnel did not come up on 7443 within 20s")
    return False


def verify_connectivity():
    print("\n[Step 6] End-to-end verification...")
    all_ok = True
    for domain in VERIFY_DOMAINS:
        try:
            ip = socket.gethostbyname(domain)
            if ip != "127.0.0.1":
                status(False, f"{domain} resolves to {ip} (expected 127.0.0.1)")
                all_ok = False
                continue
            s = socket.create_connection(("127.0.0.1", 443), timeout=10)
            ctx = ssl.create_default_context()
            tls = ctx.wrap_socket(s, server_hostname=domain)
            tls.close()
            status(True, f"{domain} -> 127.0.0.1 -> TLS OK")
        except Exception as e:
            status(False, f"{domain} failed: {e}")
            all_ok = False

    if is_port_listening("127.0.0.1", 7443):
        status(True, "speech-asr.qianwen.com -> SSH tunnel (7443) OK")
    else:
        status(False, "speech-asr.qianwen.com -> SSH tunnel (7443) not listening")
        all_ok = False
    return all_ok


def main():
    print("=" * 60)
    print("ai-sni-proxy travel self-healing script")
    print("=" * 60)

    proxy_ip = detect_proxy_exit_ip()
    if proxy_ip:
        update_security_group(proxy_ip)
    else:
        print("\n[Step 2] Skipped (could not detect proxy exit IP)")

    ensure_hosts()
    restart_sni_proxy()
    ensure_ssh_tunnel()
    ok = verify_connectivity()

    print("\n" + "=" * 60)
    if ok:
        print("All fixed! Claude Code / Codex / Qianwen should work.")
    else:
        print("Some steps failed — check [!] markers above.")
    print("=" * 60)


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            import ctypes
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            is_admin = False
        if not is_admin:
            print("Admin required (hosts file write), elevating...")
            script = os.path.abspath(__file__)
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, f'"{script}"', None, 1)
            sys.exit(0)
    main()
