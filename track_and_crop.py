import cv2
from dataclasses import dataclass, field
from datetime import datetime
import math
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Union
import yaml
from ultralytics import YOLO
from collections import defaultdict



# Define the Observation data class, as part of Tracks
@dataclass
class Observation:
    frame: int
    cx: float
    cy: float
    width: float
    height: float


# Define the Tracks data class, which is used for all object tracking.
@dataclass
class Tracks:
    data: Dict[int, List[Observation]] = field(
        default_factory=lambda: defaultdict(list))

    def add(
        self,
        track_id: int,
        frame: int,
        cx: float,
        cy: float,
        width: float,
        height: float,
    ) -> None:
        self.data[track_id].append(
            Observation(
                frame=frame,
                cx=cx,
                cy=cy,
                width=width,
                height=height))

    def items(self):
        return self.data.items()

    def __getitem__(self, track_id: int):
        return self.data[track_id]

    def __setitem__(self, track_id: int, value):
        self.data[track_id] = value






# NOTE: this mus be replaced with edge detection so boxes are warped at image edges.
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
    yolo_model_path : str,
    classes,
    conf_threshold: float,
    tracker_cfg: Path,
) -> Tracks:
    """
    Run YOLO object tracking on a video and collect per-track motion data.

    This function processes a video frame-by-frame using a YOLO tracking model
    (ByteTrack via Ultralytics). It extracts detections, assigns persistent
    track IDs, and stores each track's trajectory as center-based bounding
    boxes over time.

    Parameters
    ----------
    input_path : str or Path
        Path to the input video file.
    model : str
        Path to the YOLO model instance with tracking capability.
    conf : float
        Confidence threshold for detections.
    tracker_cfg : str
        Path of the tracker configuration (e.g., "bytetrack.yaml").

    Returns
    -------
    tracks : dict[int, list[tuple[int, float, float, float, float]]]
        Dictionary mapping track ID to a list of observations.
        Each observation is: (frame_index, cx, cy, width, height)
    """
    # Load YOLO model.
    model = YOLO(yolo_model_path)

    # Load the video.
    cap = cv2.VideoCapture(str(input_path))

    # Store track history: track_id -> list of (frame, cx, cy, w, h)
    tracks = Tracks()
    frame_idx = 0

    # Main event loop.
    while True:
        # Read a frame.
        ret, frame = cap.read()
        if not ret:
            break

        # Run YOLO tracking.
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
                tracks.add(
                    track_id=tid,
                    frame=frame_idx,
                    cx=cx,
                    cy=cy,
                    width=w,
                    height=h)

        frame_idx += 1

    cap.release()

    return tracks


def interpolate_tracks(
    tracks: Tracks
) -> Tracks:
    """
    Linearly interpolate missing frame observations in tracked
    object trajectories.

    This function fills temporal gaps between sparse tracking
    detections by performing linear interpolation over bounding
    box parameters: center coordinates (cx, cy) and size (w, h).

    Parameters
    ----------
    tracks : Tracks
        Dictionary mapping track ID to a list of detections.
        Each detection is a tuple:
            (frame_index, cx, cy, width, height)

    Returns
    -------
    Tracks
        Same structure as input, but with additional interpolated frames
        inserted between observed detections.
    """
    # Collect all the tracks here.
    result = Tracks()

    # Iterate over track ID's and observations.
    for track_id, observations in tracks.items():

        # If there is an ID with no observations, skip.
        # NOTE: this is very unlikely to happen.
        if not observations:
            continue

        observations = sorted(
            observations,
            key=lambda obs: obs.frame)

        for i in range(len(observations) - 1):

            start = observations[i]
            end = observations[i + 1]

            # Keep original observation.
            result.add(
                track_id,
                start.frame,
                start.cx,
                start.cy,
                start.width,
                start.height)

            gap = end.frame - start.frame

            # Fill missing frames.
            if gap > 1:

                for k in range(1, gap):

                    t = k / gap

                    result.add(
                        track_id,
                        frame=start.frame + k,
                        cx=start.cx + t * (end.cx - start.cx),
                        cy=start.cy + t * (end.cy - start.cy),
                        width=start.width + t * (end.width - start.width),
                        height=start.height + t * (end.height - start.height))

        # Append final observation.
        last = observations[-1]

        result.add(
            track_id,
            last.frame,
            last.cx,
            last.cy,
            last.width,
            last.height)

    return result


def stabilize_bb_aspect_ratio(
    tracks: Tracks,
    crop_aspect_ratio: Tuple[int, int]
) -> Tracks:
    """
    Force every bounding box to have the same aspect ratio.

    The center of each bounding box is preserved. Width and height
    are adjusted so that width / height = target_aspect_ratio while
    approximately preserving the original box area. This avoids
    arbitrarily treating either the original width or height as the
    "correct" dimension.

    Parameters
    ----------
    tracks : Tracks
        Input tracked observations.

    crop_aspect_ratio : Tuple[int, int]
        Desired output aspect ratio expressed as (width, height)

    Returns
    -------
    Tracks
        Tracks whose observations all share the same aspect ratio.
    """
    # Convert (width, height) tuple into a scalar aspect ratio.
    # Example: (16, 9) -> 1.777..., (9, 16) -> 0.5625
    target_ar = crop_aspect_ratio[0] / crop_aspect_ratio[1]

    # Create a new Tracks object so we do not mutate input data.
    stabilized = Tracks()

    # Process each tracked object independently.
    for track_id, observations in tracks.items():

        # Iterate through all detections for this track.
        for obs in observations:

            # Skip invalid bounding boxes that could break math operations.
            if obs.width <= 0 or obs.height <= 0:
                continue

            # Compute the original bounding box area.
            # This acts as a "size budget" we preserve while changing shape.
            area = obs.width * obs.height

            # Compute new width and height while keeping area constant.
            new_width = math.sqrt(area * target_ar)
            new_height = math.sqrt(area / target_ar)

            # Store transformed observation with:
            # - same frame index
            # - same center position (cx, cy)
            # - adjusted width/height matching target aspect ratio
            stabilized.add(
                track_id=track_id,
                frame=obs.frame,
                cx=obs.cx,
                cy=obs.cy,
                width=new_width,
                height=new_height)

    return stabilized


def smooth_bb_size(
    tracks: Tracks,
    alpha: float,
) -> Tracks:
    """
    Smooth bounding box width/height using an Exponential
    Moving Average (EMA).
    
    Parameters
    ----------
    tracks : Tracks
        Input tracked observations.
    alpha : float
        EMA smoothing factor in [0, 1].
        Larger values = more smoothing.
        Smaller values = more responsive sizing.
    
    Returns
    -------
    Tracks
        Smoothed tracks.
    """

    # Output container (do not mutate input tracks)
    smoothed_tracks = Tracks()

    # Process each object independently (important: no cross-track smoothing)
    for track_id, observations in tracks.items():

        # If no data, skip safely
        if not observations:
            continue

        # Ensure temporal order (EMA assumes sequential time series)
        observations = sorted(observations, key=lambda obs: obs.frame)

        # Initialize EMA state using the first observation
        # This becomes the "previous smoothed value"
        prev_w = observations[0].width
        prev_h = observations[0].height

        # Iterate over time-ordered detections
        for obs in observations:
            w = alpha * prev_w + (1.0 - alpha) * obs.width
            h = alpha * prev_h + (1.0 - alpha) * obs.height

            # Store smoothed observation
            smoothed_tracks.add(
                track_id,
                frame=obs.frame,
                cx=obs.cx,   # NOTE: position is NOT smoothed
                cy=obs.cy,   # keeps crop "locked" to motion
                width=w,
                height=h
            )

            # Update EMA state for next iteration
            # (this is what makes it "memory-based")
            prev_w = w
            prev_h = h

    return smoothed_tracks


def add_margins(
    tracks: Tracks,
    margin: float
) -> Tracks:
    """
    Adds relative margins to each bounding box while preserving
    center location (cx, cy) and aspect ratio of each box.

    The margin is applied as a uniform scaling factor:
    margin = 0.2 -> +20% size in both width and height

    Parameters
    ----------
    tracks : Tracks
        Input tracked observations.
    margin : float
        The margin to be added to the observations.

    Returns
    -------
    Tracks
        Observations with added margins.
    """
    # Output container (do not mutate input)
    expanded_tracks = Tracks()

    # Precompute scale factor once for clarity
    # Example:
    #   margin = 0.2 -> scale = 1.2
    scale = 1.0 + margin

    # Iterate over all tracked objects
    for track_id, observations in tracks.items():

        for obs in observations:
            new_width = obs.width * scale
            new_height = obs.height * scale

            # Store expanded bounding box with same center position
            expanded_tracks.add(
                track_id,
                frame=obs.frame,
                cx=obs.cx,
                cy=obs.cy,
                width=new_width,
                height=new_height)

    return expanded_tracks


def export_crops(
    input_path: Path,
    tracks: Tracks,
    fps: float,
    out_dir: Path,
    aspect_ratio: tuple[float, float],
    output_width: int,
    margin: float,
    min_seconds: int
) -> None:
    """
    Export cropped videos for each tracked object based on trajectories.
    """

    cap = cv2.VideoCapture(str(input_path))

    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    out_dir.mkdir(parents=True, exist_ok=True)

    min_frames = int(min_seconds * fps)

    ar_w, ar_h = aspect_ratio
    scale = output_width / ar_w
    output_height = int(ar_h * scale)

    # Build frame index: frame -> list of (track_id, obs)
    frame_map = defaultdict(list)

    for tid, observations in tracks.items():
        for obs in observations:
            frame_map[obs.frame].append((tid, obs))

    # Prepare video writers lazily per track
    writers = {}
    frame_buffers = defaultdict(list)
    active_tracks = set()

    # Sequential frame processing.
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx in frame_map:

            for tid, obs in frame_map[frame_idx]:

                # skip short tracks early
                if len(tracks[tid]) < min_frames:
                    continue

                cx, cy = obs.cx, obs.cy
                w, h = obs.width, obs.height

                # apply margin ONCE (correct place)
                w *= (1.0 + margin)
                h *= (1.0 + margin)

                # convert to box
                x1, y1, x2, y2 = compute_box(cx, cy, w, h)

                # boundary check
                if x1 < 0 or y1 < 0 or x2 > W or y2 > H:
                    continue
                if x2 <= x1 or y2 <= y1:
                    continue

                crop = frame[y1:y2, x1:x2]

                if crop.size == 0:
                    continue

                crop = cv2.resize(crop, (output_width, output_height))

                # initialize writer lazily
                if tid not in writers:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    out_path = out_dir / f"{timestamp}_person_{tid}.mp4"

                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # type: ignore
                    writers[tid] = cv2.VideoWriter(
                        str(out_path),
                        fourcc,
                        fps,
                        (output_width, output_height)
                    )

                writers[tid].write(crop)

        frame_idx += 1

    # Cleanup.
    cap.release()

    for w in writers.values():
        w.release()

    print(f"Saved {len(writers)} cropped videos to {out_dir}")


def export_debug_video(
    input_path: Path,
    tracks: Tracks,
    fps: float,
    out_path: Path,
) -> None:
    """
    Export an annotated debug video showing tracked detections.

    Parameters
    ----------
    input_path : Path
        Input video path.
    tracks : Tracks
        Track data containing Observation objects.
    fps : float
        Output video frame rate.
    out_path : Path
        Output video path.

    Returns
    -------
    None
    """

    cap = cv2.VideoCapture(str(input_path))

    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # type: ignore
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (W, H))

    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Draw all boxes that belong to this frame
        for track_id, observations in tracks.items():

            for obs in observations:

                if obs.frame != frame_idx:
                    continue

                x1, y1, x2, y2 = compute_box(
                    obs.cx,
                    obs.cy,
                    obs.width,
                    obs.height,
                )

                color = id_to_color(track_id)

                cv2.rectangle(
                    frame,
                    (x1, y1),
                    (x2, y2),
                    color,
                    2,
                )

                cv2.putText(
                    frame,
                    f"person_{track_id}",
                    (x1, max(20, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    color,
                    2,
                )

        writer.write(frame)
        frame_idx += 1

    cap.release()
    writer.release()

    print(f"Saved debug video: {out_path}")


def main(
    input_video : Path,
    output_dir: Path,

    yolo_model_path : str,
    classes: list[int],
    conf_threshold : float,
    crop_aspect_ratio : tuple,

    fps : int,
    margin : float,
    output_video_width,
    min_seconds : int,
    debug_video : bool,
    smoothing_alpha : float,

    tracker_config):
    """
    This function has three major processing steps:
        1) Get bounding boxes with object ID's from YOLO.
        2) Perform iterpolation, location smoothing, and size
           smoothing so bounding boxes look nicer.
        3) Apply these bounding boxes to the videos as "crops,
           creating sub-videos.
    """
    # Track objects from the video.
    # This returns all the tracked objects with unique ID's that are
    # used for video processing downstream.
    # tracks : dict[int, list[tuple[int, float, float, float, float]]]
    #    Dictionary mapping track ID to a list of observations.
    #    Each observation is: (frame_index, cx, cy, width, height)
    tracks = run_tracking(
        input_path=input_video,
        yolo_model_path=yolo_model_path,
        classes=classes,
        conf_threshold=conf_threshold,
        tracker_cfg=tracker_config)

    # Interpolate missing bounding boxes.
    # For instance, if a tracked person appears for 10 frames, vanishes
    # for 5 frames, and re-appears for 20 frames, the "missing" 5 bb's
    # will be interpolated. Theoretically, if the gap is very long, this
    # will lead to low-quality interpolations: but when YOLO produces gaps
    # they are usually quite short anyway.
    tracks = interpolate_tracks(
        tracks=tracks)

    # Stabilize aspect ratio across all bounding boxes.
    # All frames will have the exact same aspect ratio. This is calculated
    # by getting the centroid of the bb, and then multiplying the width by
    # the aspect ratio to get the new height, with the center of this new
    # bb in the same location as the original bb (original width, original
    # centroid, new height).
    tracks = stabilize_bb_aspect_ratio(
        tracks=tracks,
        crop_aspect_ratio=crop_aspect_ratio)

    # Smooth bounding box size changes.
    # The bounding boxes returned by YOLO are jittery, increasing and decreasing
    # in size a lot. This function smooths over those sizes, making sure they
    # are not too jittery.
    tracks = smooth_bb_size(
        tracks,
        alpha=smoothing_alpha)

    # Add margins.
    # Margins are relative. For instance, a 0.2 horizontal margin adds 20%
    # to the width.
    tracks = add_margins(
        tracks=tracks,
        margin=margin)

    # Turn the input video into many cropped sub-videos.
    export_crops(
        input_path=input_video,
        tracks=tracks,
        out_dir=output_dir,
        fps=fps,
        output_width=output_video_width,
        margin=margin,
        aspect_ratio=crop_aspect_ratio,
        min_seconds=min_seconds)

    # If requested, export the origial video with tracking added.
    if debug_video:
        export_debug_video(
            input_path=input_video,
            tracks=tracks,
            fps=fps,
            out_path=Path("__debug_tracked_video.mp4"))



if __name__ == "__main__":

    # Open config.
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    # Iterate over all the full video files.
    videos_dir = Path("videos_full")

    video_files = sorted([
        p for p in videos_dir.iterdir()
        if p.is_file() and p.suffix.lower() \
            in {".mp4", ".avi", ".mov", ".mkv"}])

    for video_path in video_files:
        print(f"Processing: {video_path}")

        main(
            input_video=video_path,
            output_dir=Path("person_crops"),

            yolo_model_path=config["yolo_model"],
            classes=config["target_classes"],
            conf_threshold=config["conf_threshold"],

            crop_aspect_ratio=config["crop_aspect_ratio"],
            fps=config["fps"],
            margin=config["margin"],
            output_video_width=config["output_width"],
            min_seconds=config["min_duration_cropped_videos"],
            debug_video=True,
            smoothing_alpha=config["smoothing_alpha"],

            tracker_config=config["tracker_config"])
