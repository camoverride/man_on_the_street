import cv2
from datetime import datetime
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Union
import yaml
from ultralytics import YOLO
from collections import defaultdict



def clamp(v, vmin, vmax):
    return max(vmin, min(v, vmax))


def id_to_color(track_id: int):
    rng = np.random.default_rng(track_id)
    return tuple(int(x) for x in rng.integers(0, 255, size=3))


def compute_box(
    cx: float,
    cy: float,
    w: float,
    h: float
) -> Tuple[int, int, int, int]:
    """
    Convert a bounding box from center-width-height format
    to corner coordinates.

    Parameters
    ----------
    cx : float
        x-coordinate of the bounding box center.
    cy : float
        y-coordinate of the bounding box center.
    w : float
        Width of the bounding box.
    h : float
        Height of the bounding box.

    Returns
    -------
    Tuple[int, int, int, int]
        Bounding box in corner format as (x1, y1, x2, y2), where:
        - (x1, y1) is the top-left corner
        - (x2, y2) is the bottom-right corner
    """
    # Convert center-based representation to corner coordinates.
    x1 = int(cx - w / 2)
    y1 = int(cy - h / 2)
    x2 = int(cx + w / 2)
    y2 = int(cy + h / 2)

    return x1, y1, x2, y2


def run_tracking(
    input_path: Union[str, Path],
    model,
    classes,
    conf_threshold: float,
    tracker_cfg: Path,
) -> Tuple[Dict[int, List[Tuple[int, float, float, float, float]]], int]:
    """
    Run YOLO object tracking on a video and collect per-track motion data.

    This function processes a video frame-by-frame using a YOLO tracking model
    (ByteTrack via Ultralytics). It extracts detections for class `person`
    only, assigns persistent track IDs, and stores each track's trajectory as
    center-based bounding boxes over time.

    Parameters
    ----------
    input_path : str or Path
        Path to the input video file.
    model : ultralytics.YOLO
        Loaded YOLO model instance with tracking capability.
    conf : float
        Confidence threshold for detections.
    tracker_cfg : str
        Path or name of the tracker configuration (e.g., "bytetrack.yaml").

    Returns
    -------
    tracks : dict[int, list[tuple[int, float, float, float, float]]]
        Dictionary mapping track ID to a list of observations.
        Each observation is:
            (frame_index, cx, cy, width, height)
    frame_count : int
        Total number of frames processed in the video.
    """
    # Load the video.
    cap = cv2.VideoCapture(str(input_path))

    # Store track history: track_id -> list of (frame, cx, cy, w, h)
    tracks = defaultdict(list)
    frame_idx = 0

    # Main event loop..
    while True:
        # Read a frame.
        ret, frame = cap.read()
        if not ret:
            break

        # Run YOLO tracking (person class only).
        results = model.track(
            frame,
            persist=True,
            conf=conf_threshold,
            classes=classes,
            tracker=tracker_cfg,
            verbose=False)[0]

        # Extract detections if available.
        if results.boxes is not None:
            for box in results.boxes:

                # Skip detections without a valid track ID.
                if box.id is None:
                    continue

                # Track ID assigned by ByteTrack / tracker.
                tid = int(box.id[0])

                # Bounding box in x1,y1,x2,y3 format.
                x1, y1, x2, y2 = map(float, box.xyxy[0])

                # Convert to center format for easier interpolation later.
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                w = (x2 - x1)
                h = (y2 - y1)

                # Store observation.
                tracks[tid].append((frame_idx, cx, cy, w, h))

        frame_idx += 1

    cap.release()

    return tracks, frame_idx


def interpolate_tracks(
    tracks: Dict[int, List[Tuple[int, float, float, float, float]]]
) -> Dict[int, List[Tuple[int, float, float, float, float]]]:
    """
    Linearly interpolate missing frame observations in tracked object trajectories.

    This function fills temporal gaps between sparse tracking detections by
    performing linear interpolation over bounding box parameters:
    center coordinates (cx, cy) and size (w, h).

    The interpolation is done per track independently.

    Parameters
    ----------
    tracks : dict[int, list[tuple[int, float, float, float, float]]]
        Dictionary mapping track ID to a list of detections.
        Each detection is a tuple:
            (frame_index, cx, cy, width, height)

    Returns
    -------
    dict[int, list[tuple[int, float, float, float, float]]]
        Same structure as input, but with additional interpolated frames
        inserted between observed detections.

    Notes
    -----
    - Uses simple linear interpolation per dimension.
    - Does NOT smooth noise; it only fills missing frames.
    - Assumes frame indices are integers and monotonic per track.
    """
    full_tracks: Dict[int, List[Tuple[int, float, float, float, float]]] = {}

    for tid, data in tracks.items():
        if not data:
            continue

        # Ensure temporal ordering
        data.sort(key=lambda x: x[0])

        frames: List[Tuple[int, float, float, float, float]] = []

        # Interpolate between consecutive detections.
        for i in range(len(data) - 1):
            f0, cx0, cy0, w0, h0 = data[i]
            f1, cx1, cy1, w1, h1 = data[i + 1]

            # Keep the original observation.
            frames.append((f0, cx0, cy0, w0, h0))

            gap = f1 - f0

            # Fill missing frames between f0 and f1.
            if gap > 1:
                for k in range(1, gap):

                    # Normalized interpolation factor [0,1]
                    t = k / gap

                    cx = cx0 + t * (cx1 - cx0)
                    cy = cy0 + t * (cy1 - cy0)
                    w = w0 + t * (w1 - w0)
                    h = h0 + t * (h1 - h0)

                    frames.append((f0 + k, cx, cy, w, h))

        # Append final observation.
        frames.append(data[-1])

        # Ensure correct ordering after interpolation.
        frames.sort(key=lambda x: x[0])

        full_tracks[tid] = frames

    return full_tracks


def stabilize(
    frames: List[Tuple[int, float, float, float, float]],
    aspect_ratio: Tuple[float, float]
) -> List[Tuple[int, float, float, float, float]]:
    """
    Enforce a fixed aspect ratio on bounding boxes while preserving
    their centers.

    This function adjusts the width and height of each bounding box
    so that it matches a target aspect ratio. The center position
    (cx, cy) is preserved, meaning boxes are resized but not moved.

    Parameters
    ----------
    frames : list of tuple
        List of bounding box observations in the form:
            (frame_index, cx, cy, width, height)
    aspect_ratio : tuple of float
        Desired aspect ratio expressed as (ar_w, ar_h).
        For example:
            (1, 1)   -> square boxes
            (2, 3)   -> portrait boxes
            (16, 9)  -> landscape boxes

    Returns
    -------
    list of tuple
        Updated list of frames with stabilized bounding boxes:
            (frame_index, cx, cy, width, height)

    Notes
    -----
    - This function does NOT smooth position or size over time.
    - It only enforces a consistent shape per frame.
    - If a box is too wide relative to the target ratio, height is increased.
      If it is too tall, width is increased.
    """
    ar_w, ar_h = aspect_ratio
    target_ar = ar_w / ar_h

    out: List[Tuple[int, float, float, float, float]] = []

    for f, cx, cy, w, h in frames:

        # Compute current aspect ratio (guard against division by zero).
        current_ar = w / (h + 1e-6)

        # Adjust dimensions to match target aspect ratio.
        if current_ar > target_ar:
            # If too wide then increase height.
            h = w / target_ar
        else:
            # if too tall, increase width.
            w = h * target_ar

        out.append((f, cx, cy, w, h))

    return out


def export_crops(
    input_path: Path,
    tracks: Dict[int, List[Tuple[int, float, float, float, float]]],
    fps: float,
    out_dir: Path,
    aspect_ratio: tuple[float, float],
    output_width: int,
    margin_x: float,
    margin_y: float,
    min_seconds: int
) -> None:
    """
    Export cropped videos for each tracked object based on stabilized
    trajectories.

    Each track is converted into a separate video by cropping the
    original frames using the provided bounding box trajectory. Tracks
    shorter than `min_seconds` are ignored.

    Parameters
    ----------
    input_path : Path
        Path to the original input video.
    tracks : dict[int, list[tuple[int, float, float, float, float]]]
        Dictionary mapping track IDs to frame-level bounding box data:
            (frame_index, cx, cy, width, height)
    fps : float
        Frame rate of the input video.
    out_dir : Path
        Directory where per-person cropped videos will be saved.
    aspect_ratio : tuple[float, float]
        Desired aspect ratio.
    output_width : int
        The desired output width in pixels. The height is automatically
        scaled, preserving the aspect ratio.
    margin_x : float
        Horizontal margin multiplier applied to bounding box width.
        Example: 0.1 increases width by 10%.
    margin_y : float
        Vertical margin multiplier applied to bounding box height.
        Example: 0.1 increases height by 10%.
    min_seconds : int, optional
        Minimum duration (in seconds) a track must exist to be exported.

    Returns
    -------
    None
        Writes video files to disk.

    Notes
    -----
    - Frames are randomly accessed via cv2.VideoCapture.set, which is simple
      but not optimal for performance on long videos.
    - Bounding boxes are clipped to image boundaries.
    """
    # Read video.
    cap = cv2.VideoCapture(str(input_path))

    # Original video dimensions.
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    out_dir.mkdir(parents=True, exist_ok=True)

    # Minimum track length in frames.
    min_frames = int(min_seconds * fps)

    # Scale the image to the desired width, preserving the aspect ratio.
    ar_w, ar_h = aspect_ratio
    scale = output_width / ar_w
    output_height = int(ar_h * scale)

    for tid, data in tracks.items():

        # Skip short-lived tracks.
        if len(data) < min_frames:
            continue

        frames_out = []

        for f, cx, cy, w, h in data:

            # Apply margins.
            w *= (1 + margin_x)
            h *= (1 + margin_y)

            # Convert center box to corner box.
            x1, y1, x2, y2 = compute_box(cx, cy, w, h)

            # Clamp to image bounds.
            x1 = clamp(x1, 0, W - 1)
            y1 = clamp(y1, 0, H - 1)
            x2 = clamp(x2, 0, W - 1)
            y2 = clamp(y2, 0, H - 1)

            # Seek to correct frame.
            cap.set(cv2.CAP_PROP_POS_FRAMES, f)
            ret, frame = cap.read()
            if not ret:
                continue

            # Crop region of interest.
            crop = frame[y1:y2, x1:x2]

            # Resize.
            crop = cv2.resize(crop, (output_width, output_height))

            frames_out.append(crop)

        # Skip empty outputs.
        if not frames_out:
            continue

        # Write per-person video.
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out_path = out_dir / f"{timestamp}_person_{tid}.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # type: ignore
        writer = cv2.VideoWriter(
            str(out_path),
            fourcc,
            fps,
            (output_width, output_height))

        for fr in frames_out:
            writer.write(fr)

        writer.release()
        print(f"Saved {out_path}")

    cap.release()


def export_debug_video(
    input_path: str | Path,
    tracks: dict[int, list[tuple[int, float, float, float, float]]],
    fps: float,
    out_path: str | Path,
) -> None:
    """
    Export an annotated debug video showing tracked person detections.

    The input video is read frame-by-frame and bounding boxes are drawn for
    all track detections that belong to the current frame. Each detection is
    labeled with its track ID using the format ``person_<track_id>``. The
    resulting frames are written to a new video file.

    Parameters
    ----------
    input_path : str | Path
        Path to the input video.
    tracks : dict[int, list[tuple[int, float, float, float, float]]]
        Mapping from track ID to a list of detections.

        Each detection is represented as::

            (frame_idx, center_x, center_y, width, height)

        where ``frame_idx`` is the zero-based frame index in the video.
    fps : float
        Frame rate of the output video.
    out_path : str | Path
        Path where the annotated video will be written.

    Returns
    -------
    None

    Notes
    -----
    This function assumes that:

    - ``compute_box(cx, cy, w, h)`` returns bounding box coordinates in the
      format ``(x1, y1, x2, y2)``.
    - ``id_to_color(track_id)`` returns a valid OpenCV BGR color tuple.
    """
    # Open the input video.
    cap = cv2.VideoCapture(str(input_path))

    # Get video dimensions for the output writer.
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # type: ignore
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (W, H))

    frame_idx = 0

    # Main event loop.
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Draw all detections associated with the current frame.
        for track_id, data in tracks.items():
            for f, cx, cy, w, h in data:
                if f != frame_idx:
                    continue

                x1, y1, x2, y2 = compute_box(cx, cy, w, h)

                cv2.rectangle(
                    frame,
                    (x1, y1),
                    (x2, y2),
                    id_to_color(track_id),
                    2
                )

                cv2.putText(
                    frame,
                    f"person_{track_id}",
                    (x1, max(20, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    id_to_color(track_id),
                    2
                )

        writer.write(frame)
        frame_idx += 1

    # Release video resources.
    cap.release()
    writer.release()

    print(f"Saved debug video: {out_path}")


def main(
    input_video : Path,
    output_dir: Path,
    yolo_model : str,
    classes: list[int],
    conf_threshold : float,
    crop_aspect_ratio : tuple,
    fps : int,
    margin_x : float,
    margin_y : float,
    output_width,
    min_seconds : int,
    debug_video : bool,
    tracker_config):

    # Load YOLO model.
    model = YOLO(yolo_model)

    # Track objects from the video.
    tracks, total_frames = run_tracking(
        input_path=input_video,
        model=model,
        classes=classes,
        conf_threshold=conf_threshold,
        tracker_cfg=tracker_config
    )

    # Interpolate missing frames.
    tracks = interpolate_tracks(tracks)

    # Stabilize all frames.
    for tid in tracks:
        tracks[tid] = stabilize(tracks[tid], crop_aspect_ratio)

    # Turn the input video into many cropped sub-videos.
    export_crops(
        input_video,
        tracks,
        fps,
        output_dir,
        crop_aspect_ratio,
        output_width,
        margin_x,
        margin_y,
        min_seconds
       )

    # If requested, save the origial video with tracking.
    if debug_video:
        export_debug_video(
            input_video,
            tracks,
            fps,
            out_path=Path("__debug_tracked_video.mp4"))



if __name__ == "__main__":

    # Open config.
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    # Select a test video (first one).
    test_input_video_path = \
        sorted(Path("videos_full").glob("*.mp4"))[0].resolve()

    main(
        input_video=test_input_video_path,
        output_dir=Path("person_crops"),
        yolo_model=config["yolo_model"],
        classes=config["target_classes"],
        conf_threshold=config["conf_threshold"],
        crop_aspect_ratio=config["crop_aspect_ratio"],
        fps=config["fps"],
        margin_x=config["margin_x"],
        margin_y=config["margin_y"],
        output_width=config["output_width"],
        min_seconds=config["min_duration_cropped_videos"],
        debug_video=True,
        tracker_config=config["tracker_config"])