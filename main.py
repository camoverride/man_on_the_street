from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os
import random
import json

app = FastAPI()

VIDEO_DIR = os.path.join(os.path.dirname(__file__), "person_crops")

W, H = 24, 8
GRID = W * H

STATE_FILE = "grid_state.json"

state = []
known = set()
cursor = 0


# ---------- PERSISTENCE ----------
def load_cursor():
    global cursor
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                cursor = json.load(f).get("cursor", 0)
        except:
            cursor = 0


def save_cursor():
    with open(STATE_FILE, "w") as f:
        json.dump({"cursor": cursor}, f)


# ---------- SCAN ----------
def scan():
    return sorted([f for f in os.listdir(VIDEO_DIR) if f.endswith(".mp4")])


# ---------- INIT ----------
def init():
    global state, known, cursor

    files = scan()
    known = set(files)

    if not files:
        state = []
        return

    state = random.sample(files, min(GRID, len(files)))


# ---------- UPDATE (CYCLIC OVERWRITE) ----------
def update_state():
    global state, known, cursor

    files = set(scan())
    new_files = list(files - known)
    known = files

    for f in new_files:

        if len(state) < GRID:
            state.append(f)
        else:
            state[cursor] = f
            cursor = (cursor + 1) % GRID
            save_cursor()


# ---------- STARTUP ----------
@app.on_event("startup")
def startup():
    load_cursor()
    init()


# ---------- STATIC ----------
app.mount("/videos", StaticFiles(directory=VIDEO_DIR), name="videos")


# ---------- API ----------
@app.get("/state")
def get_state():
    update_state()
    return JSONResponse(state)


# ---------- UI ----------
@app.get("/")
def home():
    return HTMLResponse(f"""
<html>
<head>
<style>
body {{
    margin: 0;
    background: black;
}}

.grid {{
    display: grid;
    grid-template-columns: repeat({W}, 1fr);
    grid-template-rows: repeat({H}, 1fr);
    width: 100vw;
    height: 100vh;
}}

.cell {{
    position: relative;
    overflow: hidden;
}}

video {{
    width: 100%;
    height: 100%;
    object-fit: cover;
}}

.label {{
    position: absolute;
    bottom: 2px;
    left: 2px;
    font-size: 10px;
    color: white;
    background: rgba(0,0,0,0.5);
    padding: 2px 4px;
    font-family: monospace;
}}
</style>
</head>

<body>
<div class="grid" id="grid"></div>

<script>

const GRID = {GRID};

let current = [];

// ---------- FIXED GRID ----------
function createGrid(files) {{
    const grid = document.getElementById("grid");
    grid.innerHTML = "";

    for (let i = 0; i < GRID; i++) {{

        const cell = document.createElement("div");
        cell.className = "cell";

        const v = document.createElement("video");
        v.id = "v_" + i;
        v.autoplay = true;
        v.muted = true;
        v.loop = true;
        v.playsInline = true;
        v.dataset.file = "";

        const label = document.createElement("div");
        label.className = "label";
        label.id = "label_" + i;

        cell.appendChild(v);
        cell.appendChild(label);
        grid.appendChild(cell);
    }}

    current = files;
}}

// ---------- UPDATE ----------
async function update() {{
    const res = await fetch("/state");
    const files = await res.json();

    if (current.length === 0) {{
        createGrid(files);
    }}

    for (let i = 0; i < files.length && i < GRID; i++) {{
        const f = files[i];

        const v = document.getElementById("v_" + i);
        const label = document.getElementById("label_" + i);

        if (!v) continue;

        if (v.dataset.file !== f) {{
            v.src = "/videos/" + f;
            v.dataset.file = f;
            v.load();
            v.play().catch((e) => console.log("play failed", f, e));
        }}

        if (label) {{
            label.innerText = f;
        }}
    }}

    current = files;
}}

createGrid([]);
setInterval(update, 2000);
update();

</script>
</body>
</html>
""")