# Firefly WLED Controller

A mathematically accurate firefly bioluminescence simulator for WLED LED strips,
running as a Docker container with a web UI.

## Quick start

```bash
docker compose up --build
```

Then open http://localhost:5000 in your browser.

## Usage

1. Enter your WLED device's IP address in the UI
2. Set the number of LEDs to match your strip
3. Pick a species preset (or tweak parameters manually)
4. Hit **start effect**

## Finding your WLED IP

- Open the WLED app → Config → WiFi Setup → note the IP shown
- Or check your router's connected devices list for a device named "WLED"

## Notes

- `network_mode: host` is set so the container can reach WLED devices on your LAN.
  On macOS/Windows with Docker Desktop, remove that line and ensure your WLED IP
  is reachable from the host machine instead.
- The simulation runs at 20fps (50ms frame interval) via the WLED JSON API.
- Ctrl+C stops the container and sends an "off" command to the WLED device.

## Species presets

| Species | Flash | Interval | Notes |
|---|---|---|---|
| P. pyralis (Big Dipper) | 0.3s | 5.5s | Common backyard firefly |
| P. carolinus (Synchronous) | 0.5s | 0.5s | Kuramoto coupling enabled |
| P. marginellus | 0.2s | 3.0s | Quick flash species |
