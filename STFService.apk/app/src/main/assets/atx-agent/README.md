# atx-agent (uiautomator2) binaries

STFService uses **atx-agent** when present so the device speaks the real uiautomator2 HTTP API (no ADB).

## Add binaries

1. Download from [openatx/atx-agent releases](https://github.com/openatx/atx-agent/releases) (e.g. 0.10.0):
   - `atx-agent_*_linux_arm64.tar.gz` → extract `atx-agent` → put as **arm64-v8a/atx-agent**
   - `atx-agent_*_linux_armv7.tar.gz` → extract `atx-agent` → put as **armeabi-v7a/atx-agent**

2. Or run from **STFService.apk** directory:
   ```bash
   ./scripts/fetch-atx-agent.sh
   ```

If these files are missing, STFService falls back to the in-app U2CompatServer (same API, different implementation).
