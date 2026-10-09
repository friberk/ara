"""Exercise developer reload with actual subprocesses and filesystem events."""

import json
import subprocess
import sys
import time


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def wait_for(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for subprocess evidence")


def launch_wrapper(worker, log, source, *, shutdown_seconds=1):
    script = """
import sys
from app.jobs.development_worker import run_worker
raise SystemExit(run_worker([sys.executable, sys.argv[1], sys.argv[2], sys.argv[3]],
                            sys.argv[4], shutdown_seconds=float(sys.argv[5]),
                            debounce_ms=400, step_ms=200))
"""
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(worker),
            str(log),
            str(source),
            str(worker.parent),
            str(shutdown_seconds),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def test_source_edit_burst_restarts_once_after_latest_source_is_written(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("initial")
    log = tmp_path / "worker.jsonl"
    worker = tmp_path / "worker.py"
    worker.write_text("""
import json, os, signal, sys, time
from pathlib import Path
log, source = Path(sys.argv[1]), Path(sys.argv[2])
def record(event):
    with log.open('a') as stream:
        stream.write(json.dumps({'event':event,'pid':os.getpid(),'source':source.read_text()})+'\\n')
def stop(*args):
    record('stopped')
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
record('started')
while True: time.sleep(.02)
""")
    process = launch_wrapper(worker, log, source)
    try:
        wait_for(lambda: len(records(log)) >= 1 or process.poll() is not None)
        assert process.poll() is None, process.communicate()[0]
        time.sleep(0.15)
        for value in ("first", "middle", "last"):
            source.write_text(value)
            time.sleep(0.03)
        wait_for(lambda: len([r for r in records(log) if r["event"] == "started"]) >= 2)
        time.sleep(0.5)
        starts = [r for r in records(log) if r["event"] == "started"]
        assert [r["source"] for r in starts] == ["initial", "last"]
        assert len({r["pid"] for r in starts}) == 2
    finally:
        process.terminate()
        process.communicate(timeout=5)
    assert len([r for r in records(log) if r["event"] == "stopped"]) == 2


def test_shutdown_deadline_terminates_hanging_worker_and_its_child(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("initial")
    log = tmp_path / "worker.jsonl"
    worker = tmp_path / "worker.py"
    worker.write_text('''
import signal, subprocess, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = """
import json, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
while True:
    with open(sys.argv[1], 'a') as stream: stream.write(json.dumps({'event':'tick'})+'\\\\n')
    time.sleep(.03)
"""
subprocess.Popen([sys.executable, '-c', child, sys.argv[1]])
while True: time.sleep(.02)
''')
    process = launch_wrapper(worker, log, source, shutdown_seconds=0.2)
    try:
        wait_for(lambda: len(records(log)) >= 2 or process.poll() is not None)
        assert process.poll() is None, process.communicate()[0]
    finally:
        process.terminate()
        process.communicate(timeout=5)
    before = log.stat().st_size
    time.sleep(0.2)
    assert log.stat().st_size == before
