#!/usr/bin/env python3
"""
install.py — Install career-ops as a macOS launchd scheduled job.

What this does:
  1. Detects your Python path and career-ops directory
  2. Writes a launchd plist to ~/Library/LaunchAgents/
  3. Loads it so it starts immediately and persists across reboots
  4. Installs a `ops-status` shell alias for quick log checks

Usage:
  python3 install.py           # interactive install
  python3 install.py --uninstall
  python3 install.py --status
"""

import os
import sys
import json
import subprocess
import argparse
from pathlib import Path
from datetime import datetime

PLIST_LABEL = "com.career-ops.daemon"
PLIST_PATH  = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"
LOG_DIR     = Path.home() / ".career-ops" / "logs"
STATE_FILE  = Path.home() / ".career-ops" / "daemon-state.json"

CAREER_OPS_DIR = Path(__file__).parent.resolve()
PYTHON_PATH    = Path(sys.executable).resolve()
DAEMON_SCRIPT  = CAREER_OPS_DIR / "daemon.py"


# ── Colors ────────────────────────────────────────────────────────────────────

def green(s):  return f"\033[92m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def red(s):    return f"\033[91m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"
def dim(s):    return f"\033[2m{s}\033[0m"


# ── Schedule options ──────────────────────────────────────────────────────────

SCHEDULES = {
    "1": {"label": "Every 6 hours",   "interval": 6,  "start_hour": 8},
    "2": {"label": "Every 12 hours",  "interval": 12, "start_hour": 8},
    "3": {"label": "Every 24 hours",  "interval": 24, "start_hour": 8},
    "4": {"label": "Twice a day (8am + 8pm)", "hours": [8, 20]},
    "5": {"label": "Once a day at 6am", "hours": [6]},
}


def build_calendar_intervals(hours: list[int]) -> list[dict]:
    """Build StartCalendarInterval entries for specific hours."""
    return [{"Hour": h, "Minute": 0} for h in hours]


def build_plist(schedule_choice: str, scan_interval_hours: int) -> str:
    """Generate launchd plist XML."""
    log_out = str(LOG_DIR / "launchd-stdout.log")
    log_err = str(LOG_DIR / "launchd-stderr.log")
    sched   = SCHEDULES[schedule_choice]

    if "hours" in sched:
        # Specific hours via StartCalendarInterval
        intervals = build_calendar_intervals(sched["hours"])
        interval_xml = "\n        ".join(
            f"<dict>\n            <key>Hour</key><integer>{i['Hour']}</integer>\n"
            f"            <key>Minute</key><integer>{i['Minute']}</integer>\n        </dict>"
            for i in intervals
        )
        schedule_block = f"""
    <key>StartCalendarInterval</key>
    <array>
        {interval_xml}
    </array>"""
    else:
        # Interval in seconds
        seconds = sched["interval"] * 3600
        schedule_block = f"""
    <key>StartInterval</key>
    <integer>{seconds}</integer>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>

    <!-- Identity -->
    <key>Label</key>
    <string>{PLIST_LABEL}</string>

    <!-- Command to run -->
    <key>ProgramArguments</key>
    <array>
        <string>{PYTHON_PATH}</string>
        <string>{DAEMON_SCRIPT}</string>
    </array>

    <!-- Working directory -->
    <key>WorkingDirectory</key>
    <string>{CAREER_OPS_DIR}</string>

    <!-- Schedule -->
    {schedule_block.strip()}

    <!-- Run after wake from sleep -->
    <key>StartOnMount</key>
    <false/>

    <!-- Restart on crash (not on clean exit) -->
    <key>KeepAlive</key>
    <false/>

    <!-- Logs -->
    <key>StandardOutPath</key>
    <string>{log_out}</string>
    <key>StandardErrorPath</key>
    <string>{log_err}</string>

    <!-- Environment — ensure PATH includes Homebrew and pyenv -->
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:{PYTHON_PATH.parent}</string>
        <key>HOME</key>
        <string>{Path.home()}</string>
        <key>CAREER_OPS_SCAN_INTERVAL_HOURS</key>
        <string>{scan_interval_hours}</string>
    </dict>

    <!-- Don't run if on battery below 20% -->
    <key>LowPriorityIO</key>
    <true/>

</dict>
</plist>
"""


def load_plist():
    """Load the plist into launchd."""
    result = subprocess.run(
        ["launchctl", "load", "-w", str(PLIST_PATH)],
        capture_output=True, text=True
    )
    return result.returncode == 0, result.stderr.strip()


def unload_plist():
    """Unload the plist from launchd."""
    result = subprocess.run(
        ["launchctl", "unload", "-w", str(PLIST_PATH)],
        capture_output=True, text=True
    )
    return result.returncode == 0


def is_loaded() -> bool:
    result = subprocess.run(
        ["launchctl", "list", PLIST_LABEL],
        capture_output=True, text=True
    )
    return result.returncode == 0


def install_shell_alias():
    """Add ops-status alias to ~/.zshrc (or ~/.bashrc)."""
    alias_cmd = (
        f'alias ops-status="python3 {CAREER_OPS_DIR}/ops.py status && '
        f'cat {LOG_DIR}/daemon-$(date +%Y-%m-%d).log 2>/dev/null | tail -30"'
    )
    alias_log = f'alias ops-logs="tail -f {LOG_DIR}/daemon-$(date +%Y-%m-%d).log"'

    shell_rc = Path.home() / (".zshrc" if os.environ.get("SHELL", "").endswith("zsh") else ".bashrc")
    existing = shell_rc.read_text() if shell_rc.exists() else ""

    if "ops-status" not in existing:
        with open(shell_rc, "a") as f:
            f.write(f"\n# career-ops shortcuts\n{alias_cmd}\n{alias_log}\n")
        return True
    return False


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_install():
    print(bold("\n⚡ career-ops — background automation installer\n"))

    # Pre-checks
    if sys.platform != "darwin":
        print(red("✗ launchd is macOS-only."))
        print("  For Linux, see the cron setup below:")
        print(dim("  crontab -e"))
        print(dim(f"  0 */6 * * * cd {CAREER_OPS_DIR} && python3 daemon.py"))
        sys.exit(1)

    if not DAEMON_SCRIPT.exists():
        print(red(f"✗ daemon.py not found at {DAEMON_SCRIPT}"))
        sys.exit(1)

    # Check if already installed
    if PLIST_PATH.exists():
        print(yellow(f"⚠  Already installed. Reinstalling will overwrite the schedule.\n"))

    # Choose schedule
    print(bold("How often should career-ops scan for new jobs?\n"))
    for k, v in SCHEDULES.items():
        print(f"  {k}) {v['label']}")
    print()

    choice = input("Choose [1-5, default: 2]: ").strip() or "2"
    if choice not in SCHEDULES:
        choice = "2"
    print(f"  → {green(SCHEDULES[choice]['label'])}\n")

    # Scan interval (controls dedup — how many hours between re-scanning the same company)
    scan_hours = input("Re-scan interval in hours (default: 12): ").strip() or "12"
    try:
        scan_hours = int(scan_hours)
    except ValueError:
        scan_hours = 12

    # Write plist
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    plist_content = build_plist(choice, scan_hours)
    PLIST_PATH.write_text(plist_content)
    print(f"{green('✓')} Plist written: {PLIST_PATH}")

    # Unload first if it was already loaded
    unload_plist()

    # Load into launchd
    ok, err = load_plist()
    if ok:
        print(f"{green('✓')} Loaded into launchd")
    else:
        print(yellow(f"⚠  launchctl load returned: {err}"))
        print(dim("  Try running: launchctl load -w " + str(PLIST_PATH)))

    # Shell alias
    if install_shell_alias():
        print(f"{green('✓')} Shell aliases added (reload terminal or run: source ~/.zshrc)")
        print(f"   ops-status  — show pipeline status + today's log")
        print(f"   ops-logs    — live-tail today's daemon log")

    # Update profile.yml with daemon config
    _update_profile_daemon_config(scan_hours)

    print(f"""
{bold('Installation complete!')}

{bold('What happens next:')}
  • career-ops will scan portals every {SCHEDULES[choice]['label'].lower()}
  • New job URLs are added to data/pipeline.md
  • The AI evaluates them and updates data/applications.md
  • macOS notifications arrive when evaluations complete
  • Full logs at: {LOG_DIR}/

{bold('To run immediately:')}
  python3 {DAEMON_SCRIPT} --force

{bold('To check status:')}
  python3 install.py --status

{bold('To uninstall:')}
  python3 install.py --uninstall
""")


def cmd_uninstall():
    print(bold("\nUninstalling career-ops daemon...\n"))
    if not PLIST_PATH.exists():
        print(yellow("⚠  Not installed (plist not found)"))
        return

    unload_plist()
    PLIST_PATH.unlink()
    print(f"{green('✓')} Unloaded and removed plist")
    print(dim(f"  Log files remain at: {LOG_DIR}"))
    print(dim("  Remove manually if desired: rm -rf ~/.career-ops"))


def cmd_status():
    print(bold("\n⚡ career-ops daemon status\n"))

    # launchd status
    loaded = is_loaded()
    print(f"  Launchd:  {green('● loaded') if loaded else red('○ not loaded')}")

    # Plist
    if PLIST_PATH.exists():
        print(f"  Plist:    {green('✓')} {PLIST_PATH}")
    else:
        print(f"  Plist:    {red('✗ not installed')}  — run: python3 install.py")

    # Last run state
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        print(f"\n  {bold('Last run:')}")
        for k, v in [
            ("Last run at",    state.get("last_run_at", "never")),
            ("Elapsed",        state.get("last_run_elapsed", "—")),
            ("Last scan at",   state.get("last_scan_at", "never")),
            ("Jobs found",     state.get("last_scan_found", 0)),
            ("Offers evaluated", state.get("last_evaluated", 0)),
            ("Last error",     state.get("last_error", "none")),
        ]:
            print(f"    {k:<20} {v}")
    else:
        print(f"\n  {dim('No run history yet.')}")

    # Recent log tail
    log_files = sorted(LOG_DIR.glob("daemon-*.log"), reverse=True)
    if log_files:
        latest = log_files[0]
        lines = latest.read_text().splitlines()[-15:]
        print(f"\n  {bold('Recent log')} ({latest.name}):\n")
        for line in lines:
            if "ERROR" in line:
                print(f"    {red(line)}")
            elif "WARNING" in line:
                print(f"    {yellow(line)}")
            elif "✓" in line or "complete" in line.lower():
                print(f"    {green(line)}")
            else:
                print(f"    {dim(line)}")
    else:
        print(f"\n  {dim('No log files yet.')}")

    print()


def _update_profile_daemon_config(scan_hours: int):
    """Inject daemon config block into profile.yml."""
    from pathlib import Path
    profile_path = CAREER_OPS_DIR / "config" / "profile.yml"
    if not profile_path.exists():
        return
    content = profile_path.read_text()
    daemon_block = f"""
# Daemon configuration (managed by install.py)
daemon:
  scan_interval_hours: {scan_hours}
  max_evaluations_per_run: 8
  max_new_jobs_per_scan: 20
  parallel_workers: 2
"""
    if "daemon:" not in content:
        profile_path.write_text(content.rstrip() + "\n" + daemon_block)


# ── Cron fallback for Linux ───────────────────────────────────────────────────

def print_cron_instructions():
    print(bold("\nLinux / cron setup:\n"))
    print("  Run: crontab -e")
    print("  Add one of these lines:\n")
    print(f"  # Every 6 hours")
    print(f"  {dim('0 */6 * * * cd ' + str(CAREER_OPS_DIR) + ' && python3 daemon.py >> ~/.career-ops/logs/cron.log 2>&1')}\n")
    print(f"  # Every 12 hours (8am + 8pm)")
    print(f"  {dim('0 8,20 * * * cd ' + str(CAREER_OPS_DIR) + ' && python3 daemon.py >> ~/.career-ops/logs/cron.log 2>&1')}\n")
    print(f"  # Once a day at 6am")
    print(f"  {dim('0 6 * * * cd ' + str(CAREER_OPS_DIR) + ' && python3 daemon.py >> ~/.career-ops/logs/cron.log 2>&1')}\n")
    print("  Note: Make sure Ollama starts on boot.")
    print("  Add to /etc/rc.local or a systemd user service: ollama serve &\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Install/manage career-ops background daemon")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--status",    action="store_true")
    parser.add_argument("--cron",      action="store_true", help="Print cron instructions (Linux)")
    args = parser.parse_args()

    if args.uninstall:
        cmd_uninstall()
    elif args.status:
        cmd_status()
    elif args.cron:
        print_cron_instructions()
    else:
        if sys.platform != "darwin":
            print_cron_instructions()
        else:
            cmd_install()


if __name__ == "__main__":
    main()
