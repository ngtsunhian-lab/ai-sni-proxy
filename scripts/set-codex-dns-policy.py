"""
set-codex-dns-policy.py — Set Chromium enterprise policies for Codex desktop

Codex desktop is an AppX-packaged Electron app. Launching it directly with
--host-resolver-rules breaks the AppX sandbox ("无法设置管理员沙盒").
Instead, we set Chromium enterprise policies that force the app to use the
OS DNS resolver (which respects the hosts file) and disable DNS-over-HTTPS.

Policies set:
  BuiltInDnsClientEnabled = 0   (use OS DNS resolver → respects hosts file)
  DnsOverHttpsMode        = off (disable DNS-over-HTTPS)

Run once as admin:
  python set-codex-dns-policy.py

These are persistent registry settings — no need to re-run after reboot or
Codex update.
"""

import ctypes
import os
import sys
import winreg

POLICIES = {
    "BuiltInDnsClientEnabled": 0,    # DWORD: use OS DNS resolver
    "DnsOverHttpsMode": "off",        # SZ: disable DoH
}

REG_PATHS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\OpenAI\Codex"),
    (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Policies\OpenAI\Codex"),
]


def set_policies():
    for hive, path in REG_PATHS:
        try:
            winreg.CreateKey(hive, path)
            key = winreg.OpenKey(hive, path, 0, winreg.KEY_SET_VALUE)
            for name, value in POLICIES.items():
                if isinstance(value, int):
                    winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
                else:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            winreg.CloseKey(key)
            hive_name = "HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "HKCU"
            print(f"  [+] {hive_name}\\{path}")
        except PermissionError:
            hive_name = "HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "HKCU"
            print(f"  [!] {hive_name}\\{path} — permission denied (run as admin)")
        except Exception as e:
            print(f"  [!] {hive_name}\\{path} — {e}")


def main():
    is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    if not is_admin:
        print("Admin required for HKLM policy. Elevating...")
        script = os.path.abspath(__file__)
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{script}"', None, 1
        )
        sys.exit(0)

    print("Setting Codex Chromium DNS policies...")
    set_policies()
    print("Done. Codex will use OS DNS resolver (respects hosts file).")


if __name__ == "__main__":
    main()
