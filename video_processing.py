import json
import time
import subprocess
from datetime import datetime
from pathlib import Path
import yaml



def video_combiner(
    input_dir: Path,
    output_dir: Path,
    group_size: int,
    state_file: str):
    """
    
    """
    # Convert to paths and check that the output dir exists.
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    state_path = Path(state_file)
    output_dir.mkdir(exist_ok=True)

    # Load state (or initialize).
    if state_path.exists():
        state = json.loads(state_path.read_text())
    else:
        state = {"last_processed": ""}
    last_processed = state.get("last_processed", "")

    # Sort the files.
    def get_sorted_files():
        files = sorted(input_dir.glob("*.mp4"))
        if not last_processed:
            return files

        # Only take files strictly after last processed.
        return [f for f in files if f.name > last_processed]

    # Main event loop.
    while True:
        # Sort the files.
        files = get_sorted_files()
        print(f"\nFound {len(files)} new files after '{last_processed}'")

        # Check the group size.
        if len(files) < group_size:
            time.sleep(2)
            continue

        # Take the next chunk.
        chunk = files[:group_size]

        print("Processing chunk:")
        for f in chunk:
            print(" ", f.name)

        # Construct new filename.
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output_file = output_dir / f"combined_{timestamp}.mp4"
        concat_file = output_dir / f"concat_{timestamp}.txt"

        # Write to the state json.
        concat_file.write_text(
            "\n".join(f"file '{f.resolve()}'" for f in chunk)
        )

        # FFMPEG commanf.
        cmd = [
            "ffmpeg",
            "-y",
            "-nostdin",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(output_file),
        ]

        subprocess.run(cmd, check=True)

        print(f"Saved {output_file.name}")

        concat_file.unlink()

        # Update checkpoint using last file in chunk.
        last_processed = chunk[-1].name

        state["last_processed"] = last_processed
        state_path.write_text(json.dumps(state, indent=2))

        print(f"Checkpoint updated: {last_processed}")

        # No need to check constantly.
        time.sleep(2)



if __name__ == "__main__":

    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    video_combiner(
        input_dir=Path(config["video_chunk_save_dir"]),
        output_dir=Path(config["full_video_save_dir"]),
        group_size=config["num_video_chunks_per_full_video"],
        state_file="__video_combiner_state.json",
    )
