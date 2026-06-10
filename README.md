# Man on the Street

Tracking, analyzing, and repeating videos of people from CCTV cameras using HLS streams.


## Setup

Select a stream from `all_cameras.txt` or visit [link](https://web.seattle.gov/Travelers/) and sniff the web traffic to find these url's.

Works best with python3.11.

- `python3 -m venv .venv`
- `source .venv/bin/activate`
- `pip install -r requirements.txt`

NOTE: this is expected to run on Ubuntu with a GPU (tested: 3050). If no GPU is present, some video chunks may not be analyzed.


## Tests

Make sure the CCTV streams are live and that you haven't been blocked. If your IP has been blocked,
ProtonVPN's command line utils work just fine.

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

Test run all parts:

Record videos to `video_chunks`:
- `python record_from_stream.py`

Track and crop people, saving to `person_crops`:
- `python track_and_crop.py`

Display the videos:
- `python grid_display.py`


## Run in Production

Start all services with *systemd*. This will start the program when the computer starts and revive it when it dies. Start all three services in `system_d_services` like below:

- `mkdir -p ~/.config/systemd/user`
- `cat system_d_services/record.service > ~/.config/systemd/user/record.service`

Start the service using the commands below:

- `systemctl --user daemon-reload`
- `systemctl --user enable record.service`
- `systemctl --user start record.service`

Start it on boot: 

- `sudo loginctl enable-linger $(whoami)`

Get the logs: 

- `journalctl --user -u record.service`

TODO:
- [ ] integrate into single loop
- [ ] dont track stationary objects at night
- [ ] raise confidence at night (0.7)
- [ ] print receipts
- [ ] AI enhance images
- [ ] "zoom" functions on videos
