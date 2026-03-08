"""Utility launcher for ClackClack prototype."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"


def run_backend() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"],
        cwd=str(ROOT),
    )



def run_frontend() -> subprocess.Popen:
    npm_cmd = "npm.cmd" if sys.platform.startswith("win") else "npm"
    return subprocess.Popen([npm_cmd, "run", "dev"], cwd=str(FRONTEND_DIR))



def main() -> int:
    parser = argparse.ArgumentParser(description="ClackClack launcher")
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    args = parser.parse_args()

    procs: list[subprocess.Popen] = []

    if args.frontend_only:
        procs.append(run_frontend())
    elif args.backend_only:
        procs.append(run_backend())
    else:
        procs.append(run_backend())
        procs.append(run_frontend())

    try:
        for proc in procs:
            proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
