"""Start both local services with one cross-platform command; Ctrl+C stops both."""

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    python = (
        ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    npm = shutil.which("npm")
    if not python.exists() or not npm or not (ROOT / "frontend/node_modules").exists():
        raise SystemExit(
            "Install Python and frontend dependencies first. See README.md, Quick start."
        )
    processes = []
    try:
        for command, directory in [
            (
                [
                    str(python),
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--app-dir",
                    "backend",
                    # Uvicorn's Windows reloader broadcasts Ctrl+C to this shared
                    # console, which also stops npm. Keep the combined runner stable.
                    *([] if os.name == "nt" else ["--reload"]),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ],
                ROOT,
            ),
            ([npm, "run", "dev", "--", "--strictPort"], ROOT / "frontend"),
        ]:
            processes.append(
                subprocess.Popen(
                    command,
                    cwd=directory,
                    # Only npm.cmd requires a shell; execute Python directly.
                    shell=os.name == "nt" and command[0] == npm,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                    if os.name == "nt"
                    else 0,
                    start_new_session=os.name != "nt",
                )
            )
        print(
            "\nFolio: http://127.0.0.1:5173\nAPI: http://127.0.0.1:8000/docs\nCtrl+C stops both services.\n",
            flush=True,
        )
        while all(process.poll() is None for process in processes):
            time.sleep(0.25)
        if any(process.poll() not in (None, 0) for process in processes):
            raise SystemExit(
                "A service stopped. Check its output above (a port may already be in use)."
            )
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is not None:
                continue
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(process.pid, signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    os.killpg(process.pid, signal.SIGKILL)


if __name__ == "__main__":
    main()
