import cv2
import numpy as np
import random
from pathlib import Path

def grid_display(
    video_dir,
    num_vids_horizontal,
    num_vids_vertical,
    full_video_duration,
    output_video_path
):
    videos = sorted(video_dir.glob("*.mp4"))

    grid_size = num_vids_horizontal * num_vids_vertical

    if len(videos) == 0:
        raise ValueError("No videos found")

    videos = random.sample(videos, grid_size)

    caps = [cv2.VideoCapture(str(v)) for v in videos]

    # read first frame for sizing
    ret, frame = caps[0].read()
    if not ret:
        raise ValueError("Cannot read first video")

    h, w = frame.shape[:2]

    grid_w = w * num_vids_horizontal
    grid_h = h * num_vids_vertical

    fps = caps[0].get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 1:
        fps = 30

    total_frames = int(full_video_duration * fps)

    out = cv2.VideoWriter(
        str(output_video_path),
        cv2.VideoWriter_fourcc(*"mp4v"),  # type: ignore
        fps,
        (grid_w, grid_h))

    for _ in range(total_frames):

        grid_frame = np.zeros((grid_h, grid_w, 3), dtype=np.uint8)

        for i, cap in enumerate(caps):

            ret, frame = cap.read()

            # LOOP VIDEO PROPERLY
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()

            if not ret:
                continue  # skip broken stream

            row = i // num_vids_horizontal
            col = i % num_vids_horizontal

            y1, y2 = row * h, (row + 1) * h
            x1, x2 = col * w, (col + 1) * w

            grid_frame[y1:y2, x1:x2] = frame

        out.write(grid_frame)

    for cap in caps:
        cap.release()
    out.release()


if __name__ == "__main__":

    grid_display(
        video_dir=Path("person_crops"),
        num_vids_horizontal=5,
        num_vids_vertical=3,
        full_video_duration=15,
        output_video_path="composite.mp4")
