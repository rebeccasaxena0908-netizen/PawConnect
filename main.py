"""
PawConnect launcher.

    python main.py --all         → REST API (port 5000) + web app – the full setup
    python main.py --api         → only the Flask REST API  (docs at http://127.0.0.1:5000/docs)
    python main.py               → only the web app (uses the API if it's running, else runs it in-process)
    python main.py --desktop     → PyQt6 admin console
    python main.py --reset-data  → empty the database and load the demo data again
    python main.py --test        → run the unit tests
"""
import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _port_answers(host: str, port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _is_pawconnect(url: str) -> bool:
    from api.client import api_is_up
    return api_is_up(url, timeout=1.5)


def choose_api_port(host: str, preferred: int) -> tuple[int, bool]:
    """
    (port, already_running). On macOS port 5000 is often taken by the AirPlay
    Receiver, so if something that isn't PawConnect answers there we move on.
    """
    for port in range(preferred, preferred + 20):
        if not _port_answers(host, port):
            return port, False
        if _is_pawconnect(f"http://{host}:{port}"):
            return port, True
        print(f"Port {port} is used by another program"
              + (" (on a Mac that is usually AirPlay Receiver)" if port == 5000 else "") + " – trying the next one.",
              flush=True)
    raise SystemExit("No free port found for the API.")


def run_api(host: str, port: int) -> int:
    from api import create_app
    app = create_app()
    print(f"🐾 PawConnect API on http://{host}:{port}   ·   docs: http://{host}:{port}/docs")
    app.run(host=host, port=port, debug=False, threaded=True)
    return 0


def run_web(port: int, env: dict | None = None) -> int:
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(ROOT / "ui" / "web_app.py"),
                            "--server.port", str(port)], cwd=ROOT, env=env)


def run_all(host: str, api_port: int, web_port: int) -> int:
    port, running = choose_api_port(host, api_port)
    url = f"http://{host}:{port}"
    # Both processes need to agree on the addresses: the web app on where the API is,
    # the API on which browser origin CORS should allow.
    env = {**os.environ, "PAWCONNECT_MODE": "api", "PAWCONNECT_API_URL": url,
           "PAWCONNECT_WEB_ORIGIN": f"http://localhost:{web_port}"}
    api = None
    if running:
        print(f"Using the PawConnect API that is already running at {url}")
    else:
        api = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--api", "--api-port", str(port)],
                               cwd=ROOT, env=env)
        for _ in range(60):                       # wait up to 30 s for /health
            if _is_pawconnect(url):
                break
            if api.poll() is not None:
                raise SystemExit("The API stopped while starting – see the error above.")
            time.sleep(0.5)
        else:
            api.terminate()
            raise SystemExit("The API didn't start in 30 seconds.")
    try:
        return run_web(web_port, env)
    finally:
        if api is not None:
            api.terminate()
            api.wait(timeout=10)


def main() -> int:
    import config
    parser = argparse.ArgumentParser(description="PawConnect – stray animal rescue network")
    parser.add_argument("--all", action="store_true", help="start the REST API, then the web app")
    parser.add_argument("--api", action="store_true", help="run only the Flask REST API")
    parser.add_argument("--desktop", action="store_true", help="open the PyQt6 admin console")
    parser.add_argument("--reset-data", action="store_true", help="reset the database to the demo data")
    parser.add_argument("--test", action="store_true", help="run the unit tests")
    parser.add_argument("--port", type=int, default=8501, help="web app port (default 8501)")
    parser.add_argument("--api-port", type=int, default=config.API_PORT, help="API port (default 5000)")
    args = parser.parse_args()

    if args.reset_data:
        from analytics.sample_data import seed
        seed(reset=True)
        return 0
    if args.test:
        return subprocess.call([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT)
    if args.api:
        return run_api(config.API_HOST, args.api_port)
    if args.all:
        return run_all(config.API_HOST, args.api_port, args.port)
    if args.desktop:
        return subprocess.call([sys.executable, str(ROOT / "ui" / "desktop_gui.py")], cwd=ROOT)
    return run_web(args.port)


if __name__ == "__main__":
    sys.exit(main())
