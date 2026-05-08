#!/usr/bin/env python3
"""
Firefly WLED Controller — Flask backend
Supports multiple named WLED controllers, persisted to disk.
"""
import time, math, random, threading, requests, json, os
from flask import Flask, jsonify, request, render_template

app = Flask(__name__)

DATA_FILE = "/data/controllers.json"

# ── Simulation state ──────────────────────────────────────────
state = {
    "running": False,
    "active_controller": None,   # id of currently active controller
    "wled_ip": "",
    "n_leds": 60,
    "n_flies": 8,
    "flash_dur": 0.30,
    "interval": 5.5,
    "jitter": 1.2,
    "gamma": 4.0,
    "coupling": 0.10,
    "hue": 65,
    "species": "pyralis",
    "last_error": "",
}

SPECIES = {
    "pyralis":     {"n_flies":8,  "flash_dur":0.30,"interval":5.5, "jitter":1.2,"gamma":4.0,"coupling":0.10,"hue":65},
    "carolinus":   {"n_flies":16, "flash_dur":0.50,"interval":0.5, "jitter":0.3,"gamma":6.0,"coupling":0.85,"hue":55},
    "marginellus": {"n_flies":6,  "flash_dur":0.20,"interval":3.0, "jitter":0.8,"gamma":5.0,"coupling":0.15,"hue":75},
}

sim_thread = None
stop_event = threading.Event()

# ── Persistent controller storage ─────────────────────────────

def load_controllers():
    try:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_controllers(controllers):
    try:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, "w") as f:
            json.dump(controllers, f, indent=2)
    except Exception as e:
        print(f"Failed to save controllers: {e}")

controllers = load_controllers()

# ── Physics ───────────────────────────────────────────────────

def hsl_to_rgb(h, s, l):
    s /= 100; l /= 100
    c = (1 - abs(2*l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    if   h < 60:  r, g, b = c, x, 0
    elif h < 120: r, g, b = x, c, 0
    elif h < 180: r, g, b = 0, c, x
    elif h < 240: r, g, b = 0, x, c
    elif h < 300: r, g, b = x, 0, c
    else:         r, g, b = c, 0, x
    return int((r+m)*255), int((g+m)*255), int((b+m)*255)


def flash_intensity(t, dur, gamma):
    dt = t / dur
    if dt < 0:
        return 0.0
    elif dt < 0.15:
        return 1.0 / (1.0 + math.exp(-gamma * (dt / 0.15 - 0.85)))
    else:
        return math.exp(-((dt - 0.15) * gamma * 0.5) ** 2)


class Firefly:
    def __init__(self, led_pos, interval, jitter):
        self.led = led_pos
        self.next_flash = time.time() + random.uniform(0, interval + jitter)
        self.flash_start = None

    def intensity(self, now, flash_dur, gamma):
        if self.flash_start is None:
            return 0.0
        t = now - self.flash_start
        v = flash_intensity(t, flash_dur, gamma)
        if t > flash_dur * 3:
            self.flash_start = None
        return max(0.0, v)

    def tick(self, now, others, interval, jitter, coupling, n_leds):
        if self.flash_start is None and now >= self.next_flash:
            self.flash_start = now
            for o in others:
                if o is self or o.flash_start is not None:
                    continue
                dist = abs(self.led - o.led) / max(n_leds, 1)
                influence = coupling * max(0.0, 1.0 - dist * 4)
                if influence > 0:
                    o.next_flash -= influence * interval * 0.3
            self.next_flash = now + interval + random.uniform(-jitter, jitter)


# ── Simulation loop ───────────────────────────────────────────

def run_simulation():
    ip        = state["wled_ip"]
    n_leds    = state["n_leds"]
    n_flies   = state["n_flies"]
    flash_dur = state["flash_dur"]
    interval  = state["interval"]
    jitter    = state["jitter"]
    gamma     = state["gamma"]
    coupling  = state["coupling"]
    hue       = state["hue"]

    flies = [Firefly(int(i / n_flies * n_leds), interval, jitter) for i in range(n_flies)]
    url   = f"http://{ip}/json/state"
    frame = 0.05

    while not stop_event.is_set():
        t0  = time.time()
        now = t0

        for f in flies:
            f.tick(now, flies, interval, jitter, coupling, n_leds)

        colors = [[0, 0, 0]] * n_leds
        for f in flies:
            b = f.intensity(now, flash_dur, gamma)
            if b > 0.01:
                r, g, bl = hsl_to_rgb(hue, 85, int(20 + b * 55))
                r  = int(r  * b)
                g  = int(g  * b)
                bl = int(bl * b)
                for offset in range(-2, 3):
                    idx = f.led + offset
                    if 0 <= idx < n_leds:
                        fade = max(0.0, 1.0 - abs(offset) * 0.4)
                        colors[idx] = [
                            min(255, colors[idx][0] + int(r  * fade)),
                            min(255, colors[idx][1] + int(g  * fade)),
                            min(255, colors[idx][2] + int(bl * fade)),
                        ]

        payload = {
            "on":  True,
            "bri": 255,
            "seg": [{"id": 0, "i": [v for c in colors for v in c]}]
        }

        try:
            requests.post(url, json=payload, timeout=0.3)
            state["last_error"] = ""
        except Exception as e:
            state["last_error"] = str(e)

        elapsed = time.time() - t0
        time.sleep(max(0.0, frame - elapsed))

    try:
        requests.post(url, json={"on": False}, timeout=1)
    except Exception:
        pass


# ── Helpers ───────────────────────────────────────────────────

def stop_sim():
    global sim_thread
    stop_event.set()
    state["running"] = False
    if sim_thread:
        sim_thread.join(timeout=2)
    sim_thread = None

def start_sim():
    global sim_thread
    stop_event.clear()
    state["running"] = True
    sim_thread = threading.Thread(target=run_simulation, daemon=True)
    sim_thread.start()


# ── API routes ────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    return jsonify({
        "state": "on" if state["running"] else "off",
        "running": state["running"],
        "active_controller": state["active_controller"],
        "wled_ip": state["wled_ip"],
        "species": state["species"],
        "last_error": state["last_error"],
        "params": {k: state[k] for k in ["n_leds","n_flies","flash_dur","interval","jitter","gamma","coupling","hue"]},
    })


# ── Controller CRUD ───────────────────────────────────────────

@app.route("/api/controllers", methods=["GET"])
def api_list_controllers():
    return jsonify(controllers)


@app.route("/api/controllers", methods=["POST"])
def api_add_controller():
    data = request.json or {}
    name = data.get("name", "").strip()
    ip   = data.get("ip", "").strip()
    leds = int(data.get("n_leds", 60))
    if not name or not ip:
        return jsonify({"ok": False, "error": "name and ip are required"}), 400
    cid = str(int(time.time() * 1000))
    controllers[cid] = {"id": cid, "name": name, "ip": ip, "n_leds": leds}
    save_controllers(controllers)
    return jsonify({"ok": True, "id": cid, "controller": controllers[cid]})


@app.route("/api/controllers/<cid>", methods=["PUT"])
def api_update_controller(cid):
    if cid not in controllers:
        return jsonify({"ok": False, "error": "not found"}), 404
    data = request.json or {}
    if "name"   in data: controllers[cid]["name"]   = data["name"].strip()
    if "ip"     in data: controllers[cid]["ip"]     = data["ip"].strip()
    if "n_leds" in data: controllers[cid]["n_leds"] = int(data["n_leds"])
    save_controllers(controllers)
    return jsonify({"ok": True, "controller": controllers[cid]})


@app.route("/api/controllers/<cid>", methods=["DELETE"])
def api_delete_controller(cid):
    if cid not in controllers:
        return jsonify({"ok": False, "error": "not found"}), 404
    # Stop simulation if this controller is active
    if state["active_controller"] == cid and state["running"]:
        stop_sim()
        state["active_controller"] = None
    del controllers[cid]
    save_controllers(controllers)
    return jsonify({"ok": True})


@app.route("/api/controllers/<cid>/ping", methods=["POST"])
def api_ping_controller(cid):
    if cid not in controllers:
        return jsonify({"ok": False, "error": "not found"}), 404
    ip = controllers[cid]["ip"]
    try:
        r = requests.get(f"http://{ip}/json/info", timeout=2)
        d = r.json()
        return jsonify({"ok": True, "name": d.get("name","WLED"), "version": d.get("ver","?")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── Start / Stop ──────────────────────────────────────────────

@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.json or {}

    # Can start by controller id or by raw ip
    cid = data.get("controller_id")
    if cid:
        if cid not in controllers:
            return jsonify({"ok": False, "error": "Controller not found"}), 404
        c = controllers[cid]
        state["wled_ip"]           = c["ip"]
        state["n_leds"]            = c["n_leds"]
        state["active_controller"] = cid
    else:
        ip = data.get("wled_ip", "").strip()
        if not ip:
            return jsonify({"ok": False, "error": "No controller_id or wled_ip provided"}), 400
        state["wled_ip"]           = ip
        state["n_leds"]            = int(data.get("n_leds", state["n_leds"]))
        state["active_controller"] = None

    sp = data.get("species", state["species"])
    if sp in SPECIES:
        state["species"] = sp
        for k, v in SPECIES[sp].items():
            state[k] = v

    for k in ["n_flies","flash_dur","interval","jitter","gamma","coupling","hue"]:
        if k in data:
            state[k] = float(data[k]) if k != "n_flies" else int(data[k])

    if state["running"]:
        stop_sim()

    start_sim()
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    stop_sim()
    state["active_controller"] = None
    return jsonify({"ok": True})


@app.route("/api/test", methods=["POST"])
def api_test():
    ip = (request.json or {}).get("wled_ip", "")
    if not ip:
        return jsonify({"ok": False, "error": "No IP"})
    try:
        r = requests.get(f"http://{ip}/json/info", timeout=2)
        d = r.json()
        return jsonify({"ok": True, "name": d.get("name","WLED"), "version": d.get("ver","?")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/species")
def api_species():
    return jsonify(SPECIES)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
