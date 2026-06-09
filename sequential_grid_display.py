import cv2
import numpy as np
import os
from pathlib import Path
import random
import threading
import time



def load_video_frames(
        path: str | Path,
        max_frames=120
    ) -> list[np.ndarray]:
    """
    Load frames from a video file.

    Parameters
    ----------
    path : str | PathLike[str]
        Path to the video file.
    max_frames : int, default=120
        Maximum number of frames to read.

    Returns
    -------
    list[numpy.ndarray]
        List of BGR frames as returned by OpenCV. The list may contain
        fewer than ``max_frames`` entries if the video ends early.
    """
    cap = cv2.VideoCapture(path)
    frames = []

    while len(frames) < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        frames.append(frame)

    cap.release()
    return frames


def resize(
        frames: list[np.ndarray],
        width: int,
    ) -> tuple[list[np.ndarray], int]:
    """
    Resize frames to a target width while preserving aspect ratio.

    Parameters
    ----------
    frames : list[np.ndarray]
        Frames to resize. Must contain at least one frame.
    width : int
        Target width in pixels.

    Returns
    -------
    tuple[list[np.ndarray], int]
        Resized frames and the resulting frame height.
    """
    h, ow = frames[0].shape[:2]

    scale = width / ow
    nh = int(h * scale)

    return [cv2.resize(f, (width, nh)) for f in frames], nh


def normalize_to_canvas_length(
        frames: list[np.ndarray],
        target_len: int,
    ) -> list[np.ndarray]:
    """
    Normalize a frame sequence to a fixed length.

    Parameters
    ----------
    frames : list[np.ndarray]
        Input frame sequence.
    target_len : int
        Desired sequence length.

    Returns
    -------
    list[np.ndarray]
        Frame sequence with length ``target_len``. Short sequences
        are repeated cyclically and long sequences are truncated.
    """
    n = len(frames)

    if n == 0:
        return frames

    if n >= target_len:
        return frames[:target_len]

    # Repeat frames so every video has the same timeline length.
    return [frames[i % n] for i in range(target_len)]


def injector(
        folder: str | Path,
        grid: list[list[tuple[list[np.ndarray], int, int] | None]],
        grid_w: int,
        grid_h: int,
        cell_w: int,
        num_canvas_frames: int,
    ) -> None:
    """
    Continuously load videos into the grid in creation-time order.

    On startup, fills the grid with the most recent grid_w * grid_h
    videos. After that, only newly-created videos are inserted.
    """
    capacity = grid_w * grid_h

    def get_sorted_videos():
        videos = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.endswith(".mp4")
            and "tmp" not in f
        ]

        videos.sort(key=os.path.getmtime)
        return videos

    videos = get_sorted_videos()

    # Start with the newest videos that fit in the grid.
    initial_videos = videos[-capacity:]

    queue = list(initial_videos)

    # Remember every file we've already processed so we never repeat.
    seen = set(videos)

    x = 0
    y = 0

    while True:
        # Detect newly-created files.
        videos = get_sorted_videos()

        for path in videos:
            if path not in seen:
                seen.add(path)
                queue.append(path)

        if not queue:
            time.sleep(0.1)
            continue

        video_path = queue.pop(0)

        frames = load_video_frames(video_path)

        if not frames:
            continue

        frames, scaled_h = resize(frames, cell_w)
        frames = normalize_to_canvas_length(frames, num_canvas_frames)

        offset = random.randint(0, len(frames) - 1)

        grid[y][x] = (frames, offset, scaled_h)

        x += 1

        if x >= grid_w:
            x = 0
            y += 1

        if y >= grid_h:
            y = 0


def run(
        screen_w: int,
        screen_h: int,
        grid_w: int,
        grid_h: int,
        folder: str | Path,
        num_canvas_frames: int,
    ) -> None:
    """
    Render a fullscreen video mosaic.

    Parameters
    ----------
    screen_w : int
        Output canvas width in pixels.
    screen_h : int
        Output canvas height in pixels.
    grid_w : int
        Number of grid columns.
    grid_h : int
        Number of grid rows.
    folder : str | Path
        Directory containing source videos.
    num_canvas_frames : int
        Target frame count for all loaded videos.
    """
    cv2.namedWindow("vid", cv2.WND_PROP_FULLSCREEN)
    cv2.setWindowProperty(
        "vid",
        cv2.WND_PROP_FULLSCREEN,
        cv2.WINDOW_FULLSCREEN)

    cell_w = screen_w // grid_w

    grid = [[None for _ in range(grid_w)] for _ in range(grid_h)]

    threading.Thread(
        target=injector,
        args=(folder, grid, grid_w, grid_h, cell_w, num_canvas_frames),
        daemon=True).start()

    i = 0

    while True:
        frame = np.zeros((screen_h, screen_w, 3), dtype=np.uint8)

        row_y = 0

        for y in range(grid_h):

            # find tallest video in this row
            row_height = 0

            row_items = []

            for x in range(grid_w):
                item = grid[y][x]

                if item is None:
                    row_items.append(None)
                    continue

                frames, offset, scaled_h = item  # type: ignore

                f = frames[(i + offset) % len(frames)]

                row_items.append(f)

                if scaled_h > row_height:
                    row_height = scaled_h

            if row_height == 0:
                continue

            if row_y >= screen_h:
                break

            for x in range(grid_w):
                f = row_items[x]

                if f is None:
                    continue

                fh, fw = f.shape[:2]

                px = x * cell_w
                py = row_y

                # Clip videos that extend past the screen.
                visible_h = min(fh, screen_h - py)

                if visible_h <= 0:
                    continue

                frame[
                    py:py + visible_h,
                    px:px + fw
                ] = f[:visible_h]

            row_y += row_height

        cv2.imshow("vid", frame)

        key = cv2.waitKey(16)

        if key & 0xFF == 27:
            break

        i += 1

    cv2.destroyAllWindows()



if __name__ == "__main__":


    run(
        screen_w=2560,
        screen_h=1600,
        grid_w=48,
        grid_h=20,
        folder="3_person_crops",
        num_canvas_frames=600)
