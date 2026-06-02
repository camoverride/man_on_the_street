from datetime import datetime
import time
import requests
import subprocess
import yaml
from pathlib import Path
from urllib.parse import urljoin



def record_stream(
    stream_url: str,
    video_chunk_save_dir: str) -> None:
    """
    Continuously writes video chunks from the security camera feed to
    the desired directory.

    Parameters
    ----------
    stream_url : str
        The HLS (HTTP Live Streaming) URL of the stream
        View more info on the stream with `curl -s URL`
    video_chunk_save_dir : str
        Where the incremental video chunks are saved.

    Returns
    -------
    None
        Video chunks are saved.
    """
    # Create the video chunk directory if it doesn't already exist.
    Path(video_chunk_save_dir).mkdir(exist_ok=True)

    # Track previously downloaded video chunks from the stream.
    seen = set()

    # Main event loop.
    while True:
        try:
            # Get the traffic cam URL.
            playlist = requests.get(stream_url, timeout=10).text

            # This feed contains multiple short videos (approx 10s).
            for line in playlist.splitlines():
                line = line.strip()

                if not line.endswith(".ts"):
                    continue

                # Example: media_w941135728_28.ts
                segment_name = line

                # Skip previously seen videos.
                if segment_name in seen:
                    continue
                seen.add(segment_name)

                # Grab the specific video segment.
                segment_url = urljoin(stream_url, segment_name)

                # Name it.
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                ts_path = Path(video_chunk_save_dir) / f"{timestamp}.ts"
                mp4_path = Path(video_chunk_save_dir) / f"{timestamp}.mp4"

                # Download the chunk.
                print(f"Downloading {segment_name}")
                r = requests.get(segment_url, timeout=30)
                r.raise_for_status()

                with open(ts_path, "wb") as f:
                    f.write(r.content)

                print(f"Converting -> {mp4_path.name}")

                # Convert to mp4.
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        str(ts_path),
                        "-c",
                        "copy",
                        str(mp4_path),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                # Delete .ts file after successful conversion.
                ts_path.unlink()

                print(f"Saved {mp4_path.name}")

        except Exception as e:
            print(f"Error: {e}")

        # Video chunks are about 10s long, so there is no need to continuously
        # hit the URL.
        time.sleep(2)



if __name__ == "__main__":

    # Load config.
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    # Test the function
    record_stream(
        stream_url=config["traffic_cam_url"],
        video_chunk_save_dir=config["video_chunk_save_dir"])
