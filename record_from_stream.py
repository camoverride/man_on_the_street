import subprocess
import threading
import time
import signal
import yaml
from pathlib import Path
from datetime import datetime



CHUNK_SECONDS = 30
WATCHDOG_TIMEOUT = 90
RESTART_DELAY = 30


class State:
    def __init__(self):
        self.proc = None
        self.last_write = time.time()
        self.running = True
        self.seen_files = set()


def start_ffmpeg(stream_url, out_dir):
    Path(out_dir).mkdir(exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pattern = str(Path(out_dir) / f"{ts}_%03d.mp4")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",

        "-i", stream_url,

        "-f", "segment",
        "-segment_time", str(CHUNK_SECONDS),
        "-reset_timestamps", "1",
        "-c", "copy",

        pattern
    ]

    return subprocess.Popen(cmd)


def file_watcher(out_dir, state: State):
    """
    THIS is your REAL debug layer.
    """
    out_path = Path(out_dir)

    while state.running:
        time.sleep(1)

        current = set(out_path.glob("*.mp4"))
        new_files = current - state.seen_files

        for f in sorted(new_files):
            print(f"[SAVED] {f.name}")
            state.last_write = time.time()

        state.seen_files = current


def ffmpeg_worker(stream_url, out_dir, state: State):
    while state.running:
        print(f"[FFMPEG] session → {datetime.now().strftime('%H:%M:%S')}")

        state.seen_files = set(Path(out_dir).glob("*.mp4"))

        proc = start_ffmpeg(stream_url, out_dir)
        state.proc = proc

        try:
            while state.running:
                time.sleep(2)

                if proc.poll() is not None:
                    print("[FFMPEG] exited")
                    break

        finally:
            try:
                proc.kill()
            except:
                pass

        if state.running:
            print(f"[RECOVERY] sleeping {RESTART_DELAY}s")
            time.sleep(RESTART_DELAY)


def watchdog(state: State):
    while state.running:
        time.sleep(5)

        if time.time() - state.last_write > WATCHDOG_TIMEOUT:
            print("[WATCHDOG] no new files → restarting ffmpeg")

            if state.proc:
                try:
                    state.proc.kill()
                except:
                    pass

            state.last_write = time.time()


def run(stream_url, out_dir):
    state = State()

    def shutdown(sig, frame):
        print("\n[SHUTDOWN]")
        state.running = False
        if state.proc:
            try:
                state.proc.kill()
            except:
                pass

    signal.signal(signal.SIGINT, shutdown)

    t1 = threading.Thread(target=ffmpeg_worker, args=(stream_url, out_dir, state))
    t2 = threading.Thread(target=file_watcher, args=(out_dir, state))
    t3 = threading.Thread(target=watchdog, args=(state,))

    t1.start()
    t2.start()
    t3.start()

    t1.join()
    t2.join()
    t3.join()


if __name__ == "__main__":
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    run(config["traffic_cam_url"], config["video_chunk_save_dir"])