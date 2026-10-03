from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)


LOOPBACK = "127.0.0.1"
ALLOW_EXTERNAL_ENV = "PROCUREAI_ALLOW_EXTERNAL"


def ui_bind_address(env: dict | None = None) -> str:
    """The UI has no authentication, so it binds to loopback unless the operator explicitly opts in."""
    env = os.environ if env is None else env
    return "0.0.0.0" if env.get(ALLOW_EXTERNAL_ENV) == "1" else LOOPBACK


def streamlit_command(env: dict | None = None) -> list[str]:
    return [sys.executable, "-m", "streamlit", "run", "app.py", "--server.address", ui_bind_address(env), "--server.port", "8501"]


def start(cmd: list[str]) -> subprocess.Popen:
    # On Windows each child gets its own process group so it can receive a
    # CTRL_BREAK event for a graceful shutdown; elsewhere a SIGTERM does it.
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    return subprocess.Popen(cmd, cwd=ROOT, creationflags=flags)


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
        proc.wait(timeout=8)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        proc.kill()
        proc.wait(timeout=5)


def wait_for_api(url: str, proc: subprocess.Popen, timeout_seconds: float = 10.0) -> None:
    """Wait until the mock API is reachable or fail with a useful message."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"Vendor-risk API exited during startup with code {proc.returncode}. "
                "Check the terminal output above (a port conflict is a common cause)."
            )
        try:
            response = requests.get(url, timeout=0.5)
            if response.ok:
                return
        except requests.RequestException:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"Vendor-risk API did not become ready within {timeout_seconds:.0f}s: {url}")


def _handle_termination(signum: int, frame: object) -> None:
    """Route SIGTERM through normal cleanup (useful for IDE/terminal stop actions)."""
    raise KeyboardInterrupt


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_termination)
    procs: list[subprocess.Popen] = []
    try:
        print("Starting vendor-risk API on http://127.0.0.1:8001 ...")
        api_proc = start(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "mock_api.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8001",
            ]
        )
        procs.append(api_proc)
        wait_for_api("http://127.0.0.1:8001/health", api_proc)
        print("Vendor-risk API is ready.")

        try:
            __import__("streamlit")
        except ImportError:
            print("Streamlit is not installed. Run: pip install -r requirements.txt")
            print("The mock API is still running. Press Ctrl+C to stop.")
        else:
            if ui_bind_address() != LOOPBACK:
                print(
                    f"WARNING: {ALLOW_EXTERNAL_ENV}=1 -- the UI is bound to {ui_bind_address()} and has NO authentication. "
                    "Put an authenticating reverse proxy in front of it."
                )
            print(f"Starting starter UI on http://{LOOPBACK}:8501 (bound to {ui_bind_address()}) ...")
            procs.append(start(streamlit_command()))

        while True:
            time.sleep(1)
            for proc in procs:
                if proc.poll() is not None:
                    raise RuntimeError(f"A local process exited with code {proc.returncode}")
    except KeyboardInterrupt:
        print("\nStopping local services ...")
    finally:
        for proc in procs:
            stop(proc)


if __name__ == "__main__":
    main()
