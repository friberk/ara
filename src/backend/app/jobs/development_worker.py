"""Debounced developer reload with one complete process tree per worker generation."""

import argparse
import logging
import os
import signal
import subprocess
import sys
import threading
from contextlib import suppress

from watchfiles import PythonFilter, watch

logger = logging.getLogger(__name__)


def stop_worker(process, shutdown_seconds):
    if process.poll() is None:
        with suppress(ProcessLookupError):
            process.terminate()
        try:
            process.wait(timeout=shutdown_seconds)
        except subprocess.TimeoutExpired:
            logger.warning(
                "Worker shutdown exceeded deadline; terminating its process group."
            )
    # The subprocess is a session leader. Clean up any surviving children before
    # starting a new generation; killing only the supervisor leaves orphan workers.
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=5)


def run_worker(
    command, watch_path, *, shutdown_seconds=30, debounce_ms=1600, step_ms=500
):
    stopping = threading.Event()
    previous_handlers = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        previous_handlers[signum] = signal.signal(signum, lambda *_: stopping.set())
    process = None
    watcher = watch(
        watch_path,
        watch_filter=PythonFilter(),
        debounce=debounce_ms,
        step=step_ms,
        stop_event=stopping,
        yield_on_timeout=True,
        rust_timeout=500,
        poll_delay_ms=100,
    )
    try:
        # Seed the polling baseline before the child imports application modules.
        # Otherwise edits immediately after child boot can disappear into setup.
        next(watcher, None)
        if stopping.is_set():
            return 0
        process = subprocess.Popen(command, start_new_session=True)
        for changes in watcher:
            if stopping.is_set():
                break
            if changes:
                logger.info("Worker source changed; restarting after debounce.")
                stop_worker(process, shutdown_seconds)
                if stopping.is_set():
                    break
                process = subprocess.Popen(command, start_new_session=True)
            elif process.poll() is not None:
                return process.returncode
        return 0
    finally:
        if process is not None:
            stop_worker(process, shutdown_seconds)
        watcher.close()
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module", choices=("app.jobs.actors", "app.jobs.model_actors"))
    args, worker_args = parser.parse_known_args()
    if "--watch" in worker_args:
        parser.error("Reload is managed here; omit Dramatiq --watch.")
    logging.basicConfig(level=logging.INFO)
    command = [sys.executable, "-m", "dramatiq", args.module, *worker_args]
    raise SystemExit(run_worker(command, "app"))


if __name__ == "__main__":
    main()
