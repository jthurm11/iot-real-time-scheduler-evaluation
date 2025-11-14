Short, focused guidance for AI coding agents working on this repo.

Goal
- Help an AI agent be immediately productive: where runtime configs live, how components communicate, and the exact scripts/services to run or modify.

Key architecture (big picture)
- Two-node physical testbed: `alpha/` (actuator/fan) and `beta/` (sensor/controller). See `src/README.md`.
- Central web dashboard: `src/web_app/master_controller.py` (Flask + Flask-SocketIO) that reads/writes runtime JSON configs and emits telemetry via Socket.IO.
- Data flows:
  - Sensor `beta` measures height, runs PID, sends UDP fan commands to `alpha` on FAN_COMMAND_PORT (default 5005).
  - Fan `alpha` listens on FAN_COMMAND_PORT and sends telemetry back to sensor via FAN_DATA_LISTEN_PORT (default 5007).
  - Web dashboard reads/writes setpoint and congestion values via files under `/opt/project/common` (runtime) and receives status via Socket.IO.

Runtime config and where to look
- Runtime JSON files are expected under `/opt/project/common` on the target devices (populated by `src/setup_nodes.sh`):
  - `network_config.json` — core IPs and ports (e.g. WEB_APP_PORT, FAN_COMMAND_PORT, TELEMETRY_PORT). Example: `src/common/network_config.json`.
  - `setpoint_config.json` — persisted PID setpoint (master writes, sensor reads).
  - `congestion_config.json` — master writes `CONGESTION_DELAY` (in ms) and `PACKET_LOSS_RATE`; `network_injector.py` reads it and converts delay to seconds.

Important file examples and patterns to reference
- `src/web_app/master_controller.py` — web server, Socket.IO event names and JSON file writes. It writes `CONGESTION_DELAY` in milliseconds (ms).
- `src/web_app/templates/index.html` — client uses Socket.IO events: `status_update`, `set_setpoint`, `set_congestion`, `start_experiment`, `stop_experiment`.
- `src/beta/*` — controller/sensor PID code reads `SETPOINT_CONFIG_PATH` and sends UDP control packets.
- `src/alpha/fan_PIDcontroller.py` — fan UDP listener and I2C hardware abstraction (tries CircuitPython then smbus). Use this file to understand hardware fallbacks.
- `src/network_injector.py` (or `src/beta/network_injector.py`) — converts `CONGESTION_DELAY` (ms) -> seconds and simulates loss.
- `src/setup_nodes.sh` — authoritative install script. It:
  - copies `src/{common,alpha|beta}` to `/opt/project`
  - substitutes `@@INSTALL_DIR@@` and `@@SERVICE_USER@@` in `.service` files and enables them
  - installs OS packages (pigpiod, i2c-tools) and enables services

Developer workflows (how to run / test locally)
- Quick local web UI run (dev VM or Pi):
  1) Ensure runtime config directory exists and copy the repo config:
     sudo mkdir -p /opt/project/common
     sudo cp src/common/network_config.json /opt/project/common/network_config.json
  2) Install Python deps (minimal):
     pip3 install flask flask-socketio
  3) Run dashboard:
     python3 src/web_app/master_controller.py
- Full device install (recommended for device imaging): run `src/setup_nodes.sh` on the Pi and use the `install_project` step. Example:
  - sudo bash src/setup_nodes.sh -f install_project
  - This will copy files to `/opt/project`, substitute placeholders in systemd unit files and enable them.
- Manage services: systemd units live as templates in the repo (e.g. `src/web_app/web_app.service`) and are installed to `/etc/systemd/system/` by the setup script.

Conventions & gotchas (project-specific)
- Unit conventions: service unit templates in `src/*/*.service` use `@@INSTALL_DIR@@` and `@@SERVICE_USER@@` placeholders; `setup_nodes.sh` replaces them — modify templates only when you understand the replacement flow.
- Port & unit-of-measure mismatch: `master_controller.py` writes `CONGESTION_DELAY` in ms, while `network_injector.py` reads that value and divides by 1000 to get seconds. Treat congestion delays as milliseconds at the master layer.
- JSON-as-IPC: the project uses files in `/opt/project/common` for cross-process config (not a DB). Changes by the master controller are authoritative at runtime.
- Hardware abstraction: `src/alpha/fan_PIDcontroller.py` prefers CircuitPython (busio) but falls back to `smbus`. Tests or CI that run on non-RPi hosts should mock I2C imports or set BUS emulation.

Socket / message conventions (use exact names)
- Socket.IO events used by the UI and master controller (important for any UI/backend change):
  - status_update  (telemetry object)
  - set_setpoint   (payload: { setpoint })
  - set_congestion (payload: { delay_ms, loss_perc })
  - command_ack    (ack from master on set commands)
  - start_experiment / stop_experiment (experiment control)

When changing network config or ports
- Edit `src/common/network_config.json` for defaults, then ensure the file is present on the device at `/opt/project/common/network_config.json` before starting services.
- If you change a port, update `network_config.json` and restart services (or re-run `setup_nodes.sh -f install_project` if you want updated deployed copies).

What to do as an AI-coded change (practical examples)
- Small task example: Add a new telemetry field
  - Update `system_status` shape in `src/web_app/master_controller.py`.
  - Emit the new field in the poller and update `index.html` to display it (Socket.IO event `status_update`).
  - No systemd changes required. Add to top-level `src/common` README if cross-node.

If anything above is unclear or you want guidance for a specific task (e.g., add an endpoint, mock I2C for CI, or add tests), tell me which area to expand and I will iterate.
