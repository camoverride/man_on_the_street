import subprocess
import threading
import time
import signal
import yaml
from pathlib import Path
from datetime import datetime



class State:
    """
    Shared state used by all worker threads.

    Attributes
    ----------
    proc : subprocess.Popen | None
        Active ffmpeg process.
    last_write : float
        Unix timestamp of the most recently detected video segment.
    running : bool
        Global shutdown flag checked by all threads.
    seen_files : set[pathlib.Path]
        Snapshot of segment files already observed by `file_watcher`
    """
    def __init__(self):
        self.proc = None
        self.last_write = time.time()
        self.running = True
        self.seen_files = set()


def start_ffmpeg(
        stream_url: str,
        recording_duration: int,
        out_dir: str | Path
    ) -> subprocess.Popen:
    """
    Start ffmpeg recording and segment the stream into MP4 files.

    Parameters
    ----------
    stream_url : str
        Input stream URL understood by ffmpeg.
    recording_duration : int
        Segment length in seconds.
    out_dir : str | Path
        Directory where MP4 segments will be written.

    Returns
    -------
    subprocess.Popen
        Running ffmpeg process.
    """
    # Create the output directory if it doesn't alredt exist.
    Path(out_dir).mkdir(exist_ok=True)

    # Use a session timestamp to avoid filename collisions across
    # ffmpeg restarts.
    pattern = str(Path(out_dir) / "%Y%m%d_%H%M%S.mp4")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-i", stream_url,
        "-f", "segment",
        "-segment_time", str(recording_duration),
        "-strftime", "1",
        "-reset_timestamps", "1",
        "-c", "copy",
        pattern,
    ]

    return subprocess.Popen(cmd)


def file_watcher(
        out_dir: str | Path,
        state: State
    ) -> None:
    """
    Monitor the output directory for newly created segments.

    Updates `state.last_write` whenever a new MP4 file appears.
    The watchdog uses this timestamp to determine whether recording
    is still making progress.

    Parameters
    ----------
    out_dir : str | Path
        Directory containing recorded video segments.
    state : State
        Shared application state.
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


def ffmpeg_worker(
        stream_url: str,
        recording_duration: int,
        out_dir: str | Path,
        state: State
    ) -> None:
    """
    Manage the ffmpeg process lifecycle.

    If ffmpeg exits unexpectedly, the worker waits briefly
    and then attempts to start a new recording session.

    Parameters
    ----------
    stream_url : str
        Input stream URL.
    recording_duration : int
        Segment length in seconds.
    out_dir : str | Path
        Output directory for recorded segments.
    state : State
        Shared application state.
    """
    restart_delay = 30

    while state.running:
        print(f"[FFMPEG] session -> {datetime.now().strftime('%H:%M:%S')}")

        # Ignore files created by previous recording sessions when
        # determining whether new output is being produced.
        state.seen_files = set(Path(out_dir).glob("*.mp4"))

        proc = start_ffmpeg(
            stream_url,
            recording_duration,
            out_dir)
        state.proc = proc  # type: ignore

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
            print(f"[RECOVERY] sleeping {restart_delay}s")
            time.sleep(restart_delay)


def watchdog(
        state: State
    ) -> None:
    """
    Restart ffmpeg when no new segments are produced.

    The watchdog assumes recording has stalled if no new MP4 files
    have been detected for 90 seconds. Killing the ffmpeg process
    allows `ffmpeg_worker` to restart the recording session.

    Parameters
    ----------
    state : State
        Shared application state.
    """
    while state.running:
        time.sleep(5)

        if time.time() - state.last_write > 90:
            print("[WATCHDOG] no new files → restarting ffmpeg")

            if state.proc:
                try:
                    state.proc.kill()
                except:
                    pass

            state.last_write = time.time()


def run(
        stream_url: str,
        recording_duration: int,
        out_dir: str
    ) -> None:
    """
    Start all worker threads and block until shutdown.

    Parameters
    ----------
    stream_url : str
        Input stream URL.
    recording_duration : int
        Segment length in seconds.
    out_dir : str | Path
        Output directory for recorded segments.
    """
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

    t1 = threading.Thread(
        target=ffmpeg_worker,
        args=(stream_url, recording_duration, out_dir, state))
    t2 = threading.Thread(
        target=file_watcher,
        args=(out_dir, state))
    t3 = threading.Thread(
        target=watchdog,
        args=(state,))

    t1.start()
    t2.start()
    t3.start()

    t1.join()
    t2.join()
    t3.join()


if __name__ == "__main__":
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    run(
        config["traffic_cam_url"],
        recording_duration=30,
        out_dir=config["video_chunk_save_dir"])
