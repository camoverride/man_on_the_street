# Man on the Street

Tracking, analyzing, repeating.


## Setup

- `python3.11 -m venv .venv`
- `source .venv/bin/activate`
- `pip install -r requirements.txt`


## Tests

View the CCTV streams online: [link](https://web.seattle.gov/Travelers/).

Test that the stream works in VLC: 
- `vlc "https://61e0c5d388c2e.streamlock.net/live/4_Olive_NS.stream/chunklist_w941135728.m3u8"`

Check that downloading works in VLC:
    ```
    /opt/homebrew/bin/vlc -I dummy \
    "https://61e0c5d388c2e.streamlock.net/live/4_Olive_NS.stream/chunklist_w941135728.m3u8" \
    --no-video-title-show \
    --sout "#standard{access=file,mux=ts,dst=madison_capture.ts}" \
    --sout-keep \
    --run-time=10 \
    vlc://quit
    ```

Make sure that video chunks are available from the HLS (HTTP Live Streaming) url:
- `curl -s "https://61e0c5d388c2e.streamlock.net/live/4_Olive_NS.stream/chunklist_w941135728.m3u8"`

Download some videos to `./videos` (set in `config.yaml`):
- `python record_from_stream.py`
