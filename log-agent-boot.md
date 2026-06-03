dellusia-u16@dellusia-u16-Inspiron-5379:~/device-farm/agent-boot$ git pull 
remote: Enumerating objects: 22, done.
remote: Counting objects: 100% (22/22), done.
remote: Total 22 (delta 21), reused 22 (delta 21), pack-reused 0 (from 0)
Unpacking objects: 100% (22/22), 5.39 KiB | 306.00 KiB/s, done.
From github.com:HoangLeK2/device-farm
   b87ac583..0bfe5d39  feat/epic-1-11 -> origin/feat/epic-1-11
Updating b87ac583..0bfe5d39
Fast-forward
 agent-boot/relay/extra_data/collector.py            | 110 +++++++++++++++++++++++++++++++++++++++++++-----
 agent-boot/relay/extra_data/ingest.py               |  97 ++++++++++++++++++++++++++++++++++++++++--
 agent-boot/relay/tests/test_extra_data_collector.py | 137 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
 agent-boot/relay/tests/test_extra_data_ingest.py    | 135 +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
 device_farm/api/routes/dashboard_page.py            |   3 +-
 device_farm/api/routes/relay_agents.py              |  14 +++++--
 device_farm/tasks/scenario/steps/extraction.py      |  13 ++++++
 device_farm/tests/test_edge_extra_data.py           |   5 +++
 device_farm/tests/test_scenario_step_contract.py    |   5 ++-
 9 files changed, 500 insertions(+), 19 deletions(-)
dellusia-u16@dellusia-u16-Inspiron-5379:~/device-farm/agent-boot$ uv run main.py
[agent-boot] Bootstrapping 2 device(s): ['ce021602b062850605', 'ce0217122019d82c05']
╭──────── Bootstrap ─────────╮
│ Serial: ce0217122019d82c05 │
│ Model:  SM-G930S           │
│ SDK:    34                 │
╰────────────────────────────╯
─────────────────────────────────────────── Step 1/7  Enable adb tcpip 5555 ────────────────────────────────────────────
╭──────── Bootstrap ─────────╮
│ Serial: ce021602b062850605 │
│ Model:  SM-G935F           │
│ SDK:    34                 │
╰────────────────────────────╯
─────────────────────────────────────────── Step 1/7  Enable adb tcpip 5555 ────────────────────────────────────────────
    ✓ adb tcpip 5555 OK
    ✓ adb tcpip 5555 OK
────────────────────────────── Step 2/7  Enable Wireless Debugging (Android 11+, SDK 34) ───────────────────────────────
────────────────────────────── Step 2/7  Enable Wireless Debugging (Android 11+, SDK 34) ───────────────────────────────
    ✓ Wireless Debugging enabled — zeroconf mDNS will auto-discover this device
───────────────────────────────────────── Step 3/7  Install uiautomator2 APKs ──────────────────────────────────────────
    ✓ Wireless Debugging enabled — zeroconf mDNS will auto-discover this device
───────────────────────────────────────── Step 3/7  Install uiautomator2 APKs ──────────────────────────────────────────
    ✓ com.github.uiautomator already installed — skipping.
    ✓ com.github.uiautomator.test already installed — skipping.
───────────────────────────────────── Step 4/7  Push + start atx-agent (port 7912) ─────────────────────────────────────
    ✓ com.github.uiautomator already installed — skipping.
    ✓ com.github.uiautomator.test already installed — skipping.
───────────────────────────────────── Step 4/7  Push + start atx-agent (port 7912) ─────────────────────────────────────
    → atx-agent detected on :7912 — refreshing process
    → atx-agent detected on :7912 — refreshing process
    ✓ Pushed atx-agent-arm64 → /data/local/tmp/atx-agent
    ✓ Pushed atx-agent-arm64 → /data/local/tmp/atx-agent
    ✓ atx-agent running on :7912
─────────────────────────────────────────── Step 5/7  Install STFService.apk ───────────────────────────────────────────
    ✓ atx-agent running on :7912
─────────────────────────────────────────── Step 5/7  Install STFService.apk ───────────────────────────────────────────
    ✓ jp.co.cyberagent.stf already installed — skipping.
──────────────────────────────────────── Step 6/7  Grant STFService permissions ────────────────────────────────────────
    ✓ jp.co.cyberagent.stf already installed — skipping.
──────────────────────────────────────── Step 6/7  Grant STFService permissions ────────────────────────────────────────
    ⚠ pm grant android.permission.WRITE_SECURE_SETTINGS: Exception occurred while executing 'grant':
java.lang.SecurityException: Package jp.co.cyberagent.stf has not requested permission 
android.permission.WRITE_SECURE_SETTINGS
        at com.android.server.pm.pe
    ⚠ pm grant android.permission.WRITE_SECURE_SETTINGS: Exception occurred while executing 'grant':
java.lang.SecurityException: Package jp.co.cyberagent.stf has not requested permission 
android.permission.WRITE_SECURE_SETTINGS
        at com.android.server.pm.pe
    ⚠ pm grant android.permission.READ_PHONE_STATE: Exception occurred while executing 'grant':
java.lang.SecurityException: Package jp.co.cyberagent.stf has not requested permission 
android.permission.READ_PHONE_STATE
        at com.android.server.pm.permiss
────────────────────────────────────────────── Step 7/7  Open STFService ───────────────────────────────────────────────
    Skipped auto-open (set AUTO_OPEN_STF_APP=1 to enable)
    ⚠ pm grant android.permission.READ_PHONE_STATE: Exception occurred while executing 'grant':
java.lang.SecurityException: Package jp.co.cyberagent.stf has not requested permission 
android.permission.READ_PHONE_STATE
        at com.android.server.pm.permiss
────────────────────────────────────────────── Step 7/7  Open STFService ───────────────────────────────────────────────
    Skipped auto-open (set AUTO_OPEN_STF_APP=1 to enable)
    ✓ stay_on_while_plugged_in=3 (screen stays on while charging)
    ✓ stay_on_while_plugged_in=3 (screen stays on while charging)
    ✓ svc power stayon=true
    ✓ svc power stayon=true
    ✓ screen_off_timeout=max
    ✓ screen_off_timeout=max
    ✓ auto-rotate off
    ✓ auto-rotate off
    ✓ lock portrait
    ✓ lock portrait
    ✓ STF Doze whitelist
    ✓ STF Doze whitelist
    ✓ u2 Doze whitelist
    ✓ u2 Doze whitelist
    ✓ u2-test Doze whitelist
    ✓ u2-test Doze whitelist
    ✓ u2 overlay appop
    ✓ u2 overlay appop
    ✓ STF background appop
    ✓ STF background appop
    ✓ STF any-background appop
    ✓ STF any-background appop

✅  Bootstrap done!

✅  Bootstrap done!
       Bootstrap Results       
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Serial             ┃ Result ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ ce021602b062850605 │ ✅ OK  │
│ ce0217122019d82c05 │ ✅ OK  │
└────────────────────┴────────┘

============================================================
[agent-boot] ✅ All devices bootstrapped successfully
============================================================

[agent-boot] Starting relay daemon (GRPC mode)
  Server : 100.107.128.81:50051
  Relay ID: dellusia-u16-Inspiron-5379-a31653
  Ctrl+C to stop.

[agent-boot] uvloop installed (libuv-backed asyncio loop)
2026-06-03 14:37:46 [INFO] [relay.extra_data] extra-data ingest listening on http://0.0.0.0:8765
2026-06-03 14:37:46 [INFO] [relay.runtime] runtime: executors ready adb=48 u2=48 scrcpy=16 generic=8 cpu=4 json=orjson
2026-06-03 14:37:46 [INFO] [relay.runtime] runtime: semaphores ready extra_data=6 u2_batch=20 u2_flow=20
2026-06-03 14:37:46 [INFO] [relay.agent] u2 batch/flow enabled (U2_BATCH_ENABLED=true)
2026-06-03 14:37:46 [INFO] [relay.agent] runtime: gc.freeze() applied (frozen=41587)
2026-06-03 14:37:46 [INFO] [relay.supervisor] supervisor started tick=15s breaker_max=5 breaker_reset=60s
2026-06-03 14:37:49 [INFO] [relay.agent] gRPC connecting → 100.107.128.81:50051 (relay_id=dellusia-u16-Inspiron-5379-a31653)
2026-06-03 14:37:49 [INFO] [relay.agent] device ce021602b062850605 → online (retries=0)
2026-06-03 14:37:49 [INFO] [relay.agent] registered: registered 2 serials
2026-06-03 14:37:49 [INFO] [relay.control_client] control channel registered: control channel registered 0 serials
2026-06-03 14:37:50 [INFO] [relay.agent] capabilities (pre-heartbeat) ce021602b062850605: wlan_ip=192.168.1.9
2026-06-03 14:37:50 [INFO] [relay.agent] device ce0217122019d82c05 → online (retries=0)
2026-06-03 14:37:52 [INFO] [relay.agent] capabilities (pre-heartbeat) ce0217122019d82c05: wlan_ip=192.168.1.12
2026-06-03 14:38:44 [INFO] [relay.scrcpy] [ce0217122019d82c05] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:38:44 [INFO] [relay.session_mgr] session started: ce0217122019d82c05 (total=1)
2026-06-03 14:38:44 [INFO] [relay.scrcpy] [ce021602b062850605] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:38:44 [INFO] [relay.session_mgr] session started: ce021602b062850605 (total=2)
2026-06-03 14:38:45 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server started, forward tcp:27183 → localabstract:scrcpy
2026-06-03 14:38:45 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server started, forward tcp:27185 → localabstract:scrcpy
2026-06-03 14:38:45 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G930S (Android 14)
2026-06-03 14:38:45 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G935F (Android 14)
2026-06-03 14:38:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 14:38:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 14:38:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 14:38:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:38:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] handshake OK — 304x536
2026-06-03 14:38:46 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 14:38:46 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 14:38:46 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 14:38:46 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:38:46 [INFO] [relay.scrcpy] [ce021602b062850605] handshake OK — 304x536
2026-06-03 14:38:46 [INFO] [relay.runtime] runtime stats: adb_t=1/48 u2_t=1/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.05s scrcpy.sessions=2 devices.online=2 a11y.serials=0 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=1
2026-06-03 14:38:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=2 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:38:48 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:38:48 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:49 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:38:49 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:38:49 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:49 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:38:51 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:38:53 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:38:53 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:53 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:38:53 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:38:53 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:38:53 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:38:55 [INFO] [relay.session_mgr] session stopped: ce021602b062850605 (reason=manual_stop, remaining=1)
2026-06-03 14:38:55 [INFO] [relay.agent] auto-resume skipped ce021602b062850605: desired=false reason=manual_stop
2026-06-03 14:38:55 [INFO] [relay.session_mgr] session stopped: ce0217122019d82c05 (reason=manual_stop, remaining=0)
2026-06-03 14:38:55 [INFO] [relay.agent] auto-resume skipped ce0217122019d82c05: desired=false reason=manual_stop
2026-06-03 14:38:55 [INFO] [relay.scrcpy] [ce0217122019d82c05] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:38:55 [INFO] [relay.session_mgr] session started: ce0217122019d82c05 (total=1)
2026-06-03 14:38:56 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server started, forward tcp:27183 → localabstract:scrcpy
2026-06-03 14:38:56 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G930S (Android 14)
2026-06-03 14:38:56 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 14:38:56 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 14:38:56 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 14:38:57 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:38:57 [INFO] [relay.scrcpy] [ce0217122019d82c05] handshake OK — 304x536
2026-06-03 14:39:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:39:01 [INFO] [relay.scrcpy] [ce021602b062850605] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:39:01 [INFO] [relay.session_mgr] session started: ce021602b062850605 (total=2)
2026-06-03 14:39:02 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server started, forward tcp:27185 → localabstract:scrcpy
2026-06-03 14:39:03 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G935F (Android 14)
2026-06-03 14:39:03 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:03 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 14:39:03 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 14:39:03 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 14:39:03 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:03 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:03 [INFO] [relay.scrcpy] [ce021602b062850605] handshake OK — 304x536
2026-06-03 14:39:03 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:06 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:10 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:10 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:10 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=2 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:39:16 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:16 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:16 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:19 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:19 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:19 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:19 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:19 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:19 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:22 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:22 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:22 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:23 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:23 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:23 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:28 [INFO] [relay.session_mgr] session stopped: ce0217122019d82c05 (reason=manual_stop, remaining=1)
2026-06-03 14:39:28 [INFO] [relay.agent] auto-resume skipped ce0217122019d82c05: desired=false reason=manual_stop
2026-06-03 14:39:28 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:28 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:39:33 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:33 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:33 [INFO] [relay.scrcpy] [ce0217122019d82c05] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:39:33 [INFO] [relay.session_mgr] session started: ce0217122019d82c05 (total=2)
2026-06-03 14:39:33 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:33 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:33 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:33 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:33 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:33 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:33 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:33 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:33 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:33 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server started, forward tcp:27183 → localabstract:scrcpy
2026-06-03 14:39:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G930S (Android 14)
2026-06-03 14:39:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 14:39:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 14:39:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 14:39:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] handshake OK — 304x536
2026-06-03 14:39:38 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:38 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:38 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:41 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:41 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:41 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:44 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:44 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:44 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=1/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=2 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:39:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=2 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:39:47 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:47 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:47 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:48 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:48 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:48 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:53 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:53 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:53 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:55 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:55 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:55 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:57 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:57 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:57 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:58 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:39:58 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:58 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:39:59 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:59 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:59 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:59 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:59 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:39:59 [INFO] [relay.session_mgr] session stopped: ce0217122019d82c05 (reason=manual_stop, remaining=1)
2026-06-03 14:39:59 [INFO] [relay.agent] auto-resume skipped ce0217122019d82c05: desired=false reason=manual_stop
2026-06-03 14:39:59 [INFO] [relay.session_mgr] session stopped: ce021602b062850605 (reason=manual_stop, remaining=0)
2026-06-03 14:39:59 [INFO] [relay.agent] auto-resume skipped ce021602b062850605: desired=false reason=manual_stop
2026-06-03 14:39:59 [INFO] [relay.scrcpy] [ce0217122019d82c05] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:39:59 [INFO] [relay.session_mgr] session started: ce0217122019d82c05 (total=1)
2026-06-03 14:40:00 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server started, forward tcp:27183 → localabstract:scrcpy
2026-06-03 14:40:00 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G930S (Android 14)
2026-06-03 14:40:01 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 14:40:01 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 14:40:01 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 14:40:01 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:01 [INFO] [relay.scrcpy] [ce0217122019d82c05] handshake OK — 304x536
2026-06-03 14:40:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:40:01 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:03 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:03 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:04 [INFO] [relay.scrcpy] [ce021602b062850605] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:40:04 [INFO] [relay.session_mgr] session started: ce021602b062850605 (total=2)
2026-06-03 14:40:05 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server started, forward tcp:27185 → localabstract:scrcpy
2026-06-03 14:40:06 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G935F (Android 14)
2026-06-03 14:40:06 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 14:40:06 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 14:40:06 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 14:40:06 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:06 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:06 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:06 [INFO] [relay.scrcpy] [ce021602b062850605] handshake OK — 304x536
2026-06-03 14:40:06 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:06 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:06 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:07 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:07 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:08 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:08 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:09 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:09 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:11 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:11 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:11 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:11 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:11 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:11 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:11 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:11 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:11 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:15 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:15 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:15 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:16 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:16 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:16 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=2 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:40:18 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:18 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:18 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:18 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:18 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:18 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:21 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:21 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:21 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:23 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:23 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:23 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:23 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:23 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:23 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:26 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:26 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:26 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:29 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:29 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:29 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:29 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:29 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:29 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=2 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:40:32 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:32 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:32 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:33 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:33 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:33 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:36 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:36 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:36 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:39 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:39 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:39 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:41 [INFO] [relay.session_mgr] session stopped: ce021602b062850605 (reason=manual_stop, remaining=1)
2026-06-03 14:40:41 [INFO] [relay.agent] auto-resume skipped ce021602b062850605: desired=false reason=manual_stop
2026-06-03 14:40:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:40:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:40:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:40:44 [INFO] [relay.session_mgr] session stopped: ce0217122019d82c05 (reason=manual_stop, remaining=0)
2026-06-03 14:40:44 [INFO] [relay.agent] auto-resume skipped ce0217122019d82c05: desired=false reason=manual_stop
2026-06-03 14:40:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:40:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:41:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:41:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:41:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:41:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:41:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:42:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:42:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:42:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:42:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:42:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:43:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:43:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:43:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:43:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:43:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:44:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:44:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:44:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:44:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:44:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:45:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:45:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:45:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:45:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:45:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:46:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:46:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:46:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:46:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:46:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:47:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:47:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:47:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:47:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:47:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:48:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:48:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:48:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:48:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:48:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:49:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:49:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:49:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:49:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:49:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:50:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:50:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:50:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:50:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:50:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:51:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:51:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:51:25 [INFO] [relay.scrcpy] [ce0217122019d82c05] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:51:25 [INFO] [relay.session_mgr] session started: ce0217122019d82c05 (total=1)
2026-06-03 14:51:25 [INFO] [relay.scrcpy] [ce021602b062850605] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:51:25 [INFO] [relay.session_mgr] session started: ce021602b062850605 (total=2)
2026-06-03 14:51:25 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server started, forward tcp:27183 → localabstract:scrcpy
2026-06-03 14:51:25 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server started, forward tcp:27185 → localabstract:scrcpy
2026-06-03 14:51:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G930S (Android 14)
2026-06-03 14:51:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 14:51:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 14:51:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 14:51:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] handshake OK — 304x536
2026-06-03 14:51:26 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G935F (Android 14)
2026-06-03 14:51:26 [INFO] [relay.session_mgr] session stopped: ce0217122019d82c05 (reason=manual_stop, remaining=1)
2026-06-03 14:51:26 [INFO] [relay.agent] auto-resume skipped ce0217122019d82c05: desired=false reason=manual_stop
2026-06-03 14:51:27 [INFO] [relay.session_mgr] session stopped: ce021602b062850605 (reason=manual_stop, remaining=0)
2026-06-03 14:51:27 [INFO] [relay.agent] auto-resume skipped ce021602b062850605: desired=false reason=manual_stop
2026-06-03 14:51:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:51:27 [INFO] [relay.session_mgr] session started: ce0217122019d82c05 (total=1)
2026-06-03 14:51:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server started, forward tcp:27183 → localabstract:scrcpy
2026-06-03 14:51:28 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G930S (Android 14)
2026-06-03 14:51:28 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 14:51:28 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 14:51:28 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 14:51:28 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:28 [INFO] [relay.scrcpy] [ce0217122019d82c05] handshake OK — 304x536
2026-06-03 14:51:31 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:51:31 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:31 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:51:33 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:51:33 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:35 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:35 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:35 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:35 [INFO] [relay.scrcpy] [ce021602b062850605] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:51:35 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:35 [INFO] [relay.session_mgr] session started: ce021602b062850605 (total=2)
2026-06-03 14:51:35 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:35 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:36 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server started, forward tcp:27185 → localabstract:scrcpy
2026-06-03 14:51:36 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G935F (Android 14)
2026-06-03 14:51:37 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 14:51:37 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 14:51:37 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 14:51:37 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:37 [INFO] [relay.scrcpy] [ce021602b062850605] handshake OK — 304x536
2026-06-03 14:51:38 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:51:38 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:38 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:39 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:51:39 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:39 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:41 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:51:41 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:41 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:42 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:51:42 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:42 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:44 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:51:44 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:44 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:44 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:44 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:44 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=2 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:51:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=2 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:51:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:51:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:46 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:51:46 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:47 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:47 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:47 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:47 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:47 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:47 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:47 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:47 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:47 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:47 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:47 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:47 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:51:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:51:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:50 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:51 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:51 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:51 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:51 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:51 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:52 [INFO] [relay.session_mgr] session stopped: ce021602b062850605 (reason=manual_stop, remaining=1)
2026-06-03 14:51:52 [INFO] [relay.agent] auto-resume skipped ce021602b062850605: desired=false reason=manual_stop
2026-06-03 14:51:52 [INFO] [relay.session_mgr] session stopped: ce0217122019d82c05 (reason=manual_stop, remaining=0)
2026-06-03 14:51:52 [INFO] [relay.agent] auto-resume skipped ce0217122019d82c05: desired=false reason=manual_stop
2026-06-03 14:51:53 [INFO] [relay.scrcpy] [ce0217122019d82c05] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:51:53 [INFO] [relay.session_mgr] session started: ce0217122019d82c05 (total=1)
2026-06-03 14:51:53 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server started, forward tcp:27183 → localabstract:scrcpy
2026-06-03 14:51:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G930S (Android 14)
2026-06-03 14:51:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 14:51:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 14:51:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 14:51:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] handshake OK — 304x536
2026-06-03 14:51:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:51:58 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:51:58 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:51:59 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:52:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:52:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:52:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:52:04 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:04 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:04 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:04 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:04 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:04 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:04 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:04 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:52:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:52:06 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:06 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:52:06 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:06 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:52:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:52:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:52:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:52:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:52:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:52:25 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:25 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:52:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:52:37 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:37 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:52:45 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:45 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:52:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=1 loop_max_lag=0.00s scrcpy.sessions=1 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:52:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:52:49 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:52:49 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:49 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:52:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:52:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:52 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:52:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:52:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:52:59 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:52:59 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:52:59 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:53:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:03 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:15 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:15 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:15 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:15 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:15 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:15 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:53:19 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:19 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:19 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:22 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:22 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:22 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:25 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:25 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:25 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:29 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:29 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:29 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:53:32 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:32 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:32 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:35 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:42 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:42 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:42 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:45 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:45 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:45 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=1 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:53:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:53:49 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:49 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:49 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:52 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:52 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:52 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:55 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:55 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:55 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:53:59 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:53:59 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:53:59 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:54:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:15 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:15 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:15 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:54:18 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:18 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:19 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:19 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:22 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:22 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:22 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:24 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:24 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:25 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:30 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:30 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:30 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:54:32 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:32 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:32 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:35 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:35 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:35 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:38 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:38 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:38 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:40 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:40 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:40 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=1 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:54:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:54:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:52 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:52 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:52 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:55 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:55 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:55 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:54:58 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:54:58 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:54:58 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:00 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:00 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:55:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:55:03 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:03 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:55:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:10 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:55:10 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:10 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:55:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:15 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:55:15 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:15 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:55:20 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:55:20 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:20 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:21 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:21 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:22 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:22 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:25 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:55:25 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:25 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:30 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:55:30 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:30 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:55:33 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:55:33 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:33 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:35 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:55:35 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:35 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:40 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:55:40 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:40 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:55:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:45 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:55:45 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=1 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:55:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:55:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:55:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:53 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:55:53 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:53 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:55:56 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:55:56 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:55:56 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:56:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:07 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:07 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:10 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:11 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:16 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:16 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:16 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:56:20 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:20 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:20 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:23 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:23 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:23 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:24 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:24 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:24 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:24 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:30 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:30 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:30 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:56:33 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:33 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:33 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:40 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:40 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:41 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=1 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:56:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:56:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:53 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:53 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:53 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:56:56 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:56:56 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:56:56 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:57:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:15 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:57:17 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:17 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:17 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:21 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:21 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:21 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:23 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:23 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:24 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:31 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:31 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:31 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:57:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:42 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:42 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:42 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:44 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:44 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:45 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=1 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:57:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:57:47 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:47 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:47 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:53 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:53 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:53 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:55 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:55 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:56 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:57:58 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:57:58 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:57:58 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:58:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:10 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:11 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:15 [INFO] [relay.scrcpy] [ce021602b062850605] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:58:15 [INFO] [relay.session_mgr] session started: ce021602b062850605 (total=2)
2026-06-03 14:58:16 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server started, forward tcp:27185 → localabstract:scrcpy
2026-06-03 14:58:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=2 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:58:17 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G935F (Android 14)
2026-06-03 14:58:17 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:17 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:17 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:17 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 14:58:17 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 14:58:17 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 14:58:17 [INFO] [relay.scrcpy] [ce021602b062850605] handshake OK — 304x536
2026-06-03 14:58:17 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:17 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:17 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:19 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:19 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:21 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:21 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:21 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:21 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:21 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:24 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:24 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:24 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:25 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:25 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:25 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:25 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:27 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:28 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:28 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:28 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:30 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:30 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:31 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=2 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:58:31 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:31 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:31 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:33 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:33 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:33 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:36 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:36 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:36 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:36 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:36 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:36 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:36 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:36 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:36 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:36 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:39 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:39 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:39 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:42 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:42 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:42 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:58:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:43 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:44 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:44 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:45 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:45 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=3/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.00s scrcpy.sessions=2 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 14:58:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=2 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:58:48 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:48 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:56 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:56 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:58:58 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:58:58 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:00 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:00 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=2 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:59:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:03 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:03 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:05 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:05 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:06 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:06 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:06 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:06 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:06 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:59:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:09 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:59:09 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:09 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:09 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:09 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:10 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:10 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:11 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:11 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:11 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:11 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:59:11 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:12 [INFO] [relay.session_mgr] session stopped: ce021602b062850605 (reason=manual_stop, remaining=1)
2026-06-03 14:59:12 [INFO] [relay.agent] auto-resume skipped ce021602b062850605: desired=false reason=manual_stop
2026-06-03 14:59:12 [INFO] [relay.session_mgr] session stopped: ce0217122019d82c05 (reason=manual_stop, remaining=0)
2026-06-03 14:59:12 [INFO] [relay.agent] auto-resume skipped ce0217122019d82c05: desired=false reason=manual_stop
2026-06-03 14:59:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:59:12 [INFO] [relay.session_mgr] session started: ce0217122019d82c05 (total=1)
2026-06-03 14:59:12 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_posts expand_see_more=True
2026-06-03 14:59:12 [INFO] [relay.u2_session_pool] u2-pool: connected serial=ce021602b062850605
2026-06-03 14:59:12 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_posts expand=True open_post=True
2026-06-03 14:59:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server started, forward tcp:27183 → localabstract:scrcpy
2026-06-03 14:59:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G930S (Android 14)
2026-06-03 14:59:14 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.30s bytes=42659
2026-06-03 14:59:14 [INFO] [relay.extra_data.collector] [ce021602b062850605] open_post_before_extract: no header tap target on feed diag={'reason_code': 'diagnostic', 'screen_size': [1440, 2560], 'is_post_detail': False, 'scan_elements': 1, 'built_with_tap': 0, 'missing_author': 0, 'missing_tap': 0, 'missing_post_nodes': 1, 'filtered_by_band': 0} debug_xml=None
2026-06-03 14:59:14 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more: xml_probe_first (Facebook-friendly)
2026-06-03 14:59:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 14:59:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 14:59:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 14:59:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] handshake OK — 304x536
2026-06-03 14:59:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:14 [INFO] [relay.scrcpy] [ce021602b062850605] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:59:14 [INFO] [relay.session_mgr] session started: ce021602b062850605 (total=2)
2026-06-03 14:59:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:14 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:15 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.18s bytes=42659
2026-06-03 14:59:15 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe: no see-more in hierarchy
2026-06-03 14:59:15 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe_first: no tap (skip selector storm)
2026-06-03 14:59:15 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data reuse expand hierarchy (skip redundant dump)
2026-06-03 14:59:15 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=1 total=2.51s
2026-06-03 14:59:15 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server started, forward tcp:27185 → localabstract:scrcpy
2026-06-03 14:59:15 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G935F (Android 14)
2026-06-03 14:59:16 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 14:59:16 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 14:59:16 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 14:59:16 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:16 [INFO] [relay.scrcpy] [ce021602b062850605] handshake OK — 304x536
2026-06-03 14:59:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=2 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:59:16 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:16 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:17 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:59:17 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:17 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:19 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_target_tap expand_see_more=False
2026-06-03 14:59:19 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect+tap start strategy=fb_comment_target_tap
2026-06-03 14:59:19 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:19 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:20 [INFO] [relay.session_mgr] session stopped: ce021602b062850605 (reason=manual_stop, remaining=1)
2026-06-03 14:59:20 [INFO] [relay.agent] auto-resume skipped ce021602b062850605: desired=false reason=manual_stop
2026-06-03 14:59:20 [INFO] [relay.session_mgr] session stopped: ce0217122019d82c05 (reason=manual_stop, remaining=0)
2026-06-03 14:59:20 [INFO] [relay.agent] auto-resume skipped ce0217122019d82c05: desired=false reason=manual_stop
2026-06-03 14:59:20 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.99s bytes=36278
2026-06-03 14:59:20 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data fb_comment_target_tap: skip tap reason=comment_button_not_found diag={'reason_code': 'diagnostic', 'screen_size': [1440, 2560], 'feed_children': 3, 'comment_token_nodes': 1, 'buttons_in_cards': 1, 'missing_post_pid': 0, 'filtered_by_band': 1, 'band': [0.12, 0.97]}
2026-06-03 14:59:20 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect+tap done snapshots=1 total=1.01s tapped=False verified=False attempts=0 chosen_index=None
2026-06-03 14:59:25 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_posts expand_see_more=True
2026-06-03 14:59:25 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_posts expand=True open_post=True
2026-06-03 14:59:27 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.43s bytes=38255
2026-06-03 14:59:27 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 14:59:27 [INFO] [relay.u2_session_pool] u2-pool: heartbeat evicted dead session serial=ce021602b062850605
2026-06-03 14:59:29 [INFO] [relay.extra_data.collector] [ce021602b062850605] open_post_before_extract tap #0 kind=timestamp route=click_coord label='20 giờ•Chia sẻ với: Nhóm công khai'
2026-06-03 14:59:30 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.09s bytes=38183
2026-06-03 14:59:30 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more: xml_probe_first (Facebook-friendly)
2026-06-03 14:59:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:59:31 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.14s bytes=38183
2026-06-03 14:59:31 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe: no see-more in hierarchy
2026-06-03 14:59:31 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe_first: no tap (skip selector storm)
2026-06-03 14:59:31 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data reuse expand hierarchy (skip redundant dump)
2026-06-03 14:59:31 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=1 total=6.28s
2026-06-03 14:59:33 [INFO] [relay.scrcpy] [ce0217122019d82c05] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:59:33 [INFO] [relay.session_mgr] session started: ce0217122019d82c05 (total=1)
2026-06-03 14:59:33 [INFO] [relay.scrcpy] [ce021602b062850605] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 14:59:33 [INFO] [relay.session_mgr] session started: ce021602b062850605 (total=2)
2026-06-03 14:59:33 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server started, forward tcp:27183 → localabstract:scrcpy
2026-06-03 14:59:33 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server started, forward tcp:27185 → localabstract:scrcpy
2026-06-03 14:59:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G930S (Android 14)
2026-06-03 14:59:34 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G935F (Android 14)
2026-06-03 14:59:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 14:59:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 14:59:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 14:59:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:34 [INFO] [relay.scrcpy] [ce0217122019d82c05] handshake OK — 304x536
2026-06-03 14:59:34 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_target_tap expand_see_more=False
2026-06-03 14:59:34 [INFO] [relay.u2_session_pool] u2-pool: connected serial=ce021602b062850605
2026-06-03 14:59:34 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect+tap start strategy=fb_comment_target_tap
2026-06-03 14:59:34 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 14:59:34 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 14:59:34 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 14:59:34 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:34 [INFO] [relay.scrcpy] [ce021602b062850605] handshake OK — 304x536
2026-06-03 14:59:35 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:35 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:35 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.91s bytes=42516
2026-06-03 14:59:35 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data fb_comment_target_tap: already on comment sheet — skip tap
2026-06-03 14:59:35 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_filter_apply expand_see_more=False
2026-06-03 14:59:35 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply start target=all_comments max_steps=5
2026-06-03 14:59:36 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.09s bytes=42516
2026-06-03 14:59:36 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply done switched=False reason=indicator_not_found total=1.10s steps=1
2026-06-03 14:59:37 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:59:37 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:37 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:38 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comments expand_see_more=False
2026-06-03 14:59:38 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_comments expand=False open_post=False
2026-06-03 14:59:39 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:59:39 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:39 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:39 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.85s bytes=25383
2026-06-03 14:59:41 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:41 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:42 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:42 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:44 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:59:44 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:44 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=4/48 scrcpy_t=1/16 generic_t=0/8 extra_free=5 u2b_free=20 u2f_free=20 tasks=1 loop_max_lag=0.00s scrcpy.sessions=2 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=1 http.hosts=2
2026-06-03 14:59:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=2 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 14:59:47 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.08s bytes=47631
2026-06-03 14:59:47 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:59:47 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:47 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:47 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 14:59:47 [INFO] [relay.u2_session_pool] u2-pool: heartbeat evicted dead session serial=ce021602b062850605
2026-06-03 14:59:52 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:59:52 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:52 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:52 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:52 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:52 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:52 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:55 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 14:59:55 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.36s bytes=47750
2026-06-03 14:59:55 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 14:59:55 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 14:59:57 [INFO] [relay.session_mgr] session stopped: ce0217122019d82c05 (reason=manual_stop, remaining=1)
2026-06-03 14:59:57 [INFO] [relay.agent] auto-resume skipped ce0217122019d82c05: desired=false reason=manual_stop
2026-06-03 14:59:57 [INFO] [relay.session_mgr] session stopped: ce021602b062850605 (reason=manual_stop, remaining=0)
2026-06-03 14:59:57 [INFO] [relay.agent] auto-resume skipped ce021602b062850605: desired=false reason=manual_stop
2026-06-03 15:00:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:00:01 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.94s bytes=36173
2026-06-03 15:00:08 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.29s bytes=48501
2026-06-03 15:00:13 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.07s bytes=51968
2026-06-03 15:00:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:00:19 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.98s bytes=54232
2026-06-03 15:00:25 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.02s bytes=53626
2026-06-03 15:00:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:00:32 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.09s bytes=43679
2026-06-03 15:00:38 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.22s bytes=42558
2026-06-03 15:00:44 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.94s bytes=25269
2026-06-03 15:00:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=4/48 scrcpy_t=1/16 generic_t=0/8 extra_free=5 u2b_free=20 u2f_free=20 tasks=1 loop_max_lag=0.02s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 15:00:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:00:49 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.82s bytes=15749
2026-06-03 15:00:55 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.83s bytes=37255
2026-06-03 15:01:00 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.05s bytes=37255
2026-06-03 15:01:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:01:06 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.87s bytes=37255
2026-06-03 15:01:12 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.13s bytes=37255
2026-06-03 15:01:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:01:18 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.07s bytes=37255
2026-06-03 15:01:18 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment scroll done swipes=48 dumps=14 snapshots=14
2026-06-03 15:01:18 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=14 total=99.65s
2026-06-03 15:01:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:01:34 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_posts expand_see_more=True
2026-06-03 15:01:34 [INFO] [relay.u2_session_pool] u2-pool: connected serial=ce021602b062850605
2026-06-03 15:01:34 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_posts expand=True open_post=True
2026-06-03 15:01:35 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.10s bytes=42023
2026-06-03 15:01:37 [INFO] [relay.extra_data.collector] [ce021602b062850605] open_post_before_extract tap #0 kind=timestamp route=click_coord label='5 giờ•Chia sẻ với: Nhóm công khai'
2026-06-03 15:01:38 [INFO] [relay.scrcpy] [ce0217122019d82c05] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 15:01:38 [INFO] [relay.session_mgr] session started: ce0217122019d82c05 (total=1)
2026-06-03 15:01:38 [INFO] [relay.scrcpy] [ce021602b062850605] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 15:01:38 [INFO] [relay.session_mgr] session started: ce021602b062850605 (total=2)
2026-06-03 15:01:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server started, forward tcp:27183 → localabstract:scrcpy
2026-06-03 15:01:39 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server started, forward tcp:27185 → localabstract:scrcpy
2026-06-03 15:01:39 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G935F (Android 14)
2026-06-03 15:01:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G930S (Android 14)
2026-06-03 15:01:40 [INFO] [relay.session_mgr] session stopped: ce0217122019d82c05 (reason=manual_stop, remaining=1)
2026-06-03 15:01:40 [INFO] [relay.agent] auto-resume skipped ce0217122019d82c05: desired=false reason=manual_stop
2026-06-03 15:01:40 [INFO] [relay.session_mgr] session stopped: ce021602b062850605 (reason=manual_stop, remaining=0)
2026-06-03 15:01:40 [INFO] [relay.agent] auto-resume skipped ce021602b062850605: desired=false reason=manual_stop
2026-06-03 15:01:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.98s bytes=76853
2026-06-03 15:01:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more: xml_probe_first (Facebook-friendly)
2026-06-03 15:01:40 [INFO] [relay.session_mgr] session started: ce0217122019d82c05 (total=1)
2026-06-03 15:01:41 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server started, forward tcp:27183 → localabstract:scrcpy
2026-06-03 15:01:41 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.11s bytes=76853
2026-06-03 15:01:41 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe: no see-more in hierarchy
2026-06-03 15:01:41 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe_first: no tap (skip selector storm)
2026-06-03 15:01:41 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data reuse expand hierarchy (skip redundant dump)
2026-06-03 15:01:41 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=1 total=7.34s
2026-06-03 15:01:41 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G930S (Android 14)
2026-06-03 15:01:41 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 15:01:41 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 15:01:41 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 15:01:41 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:01:44 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_target_tap expand_see_more=False
2026-06-03 15:01:44 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect+tap start strategy=fb_comment_target_tap
2026-06-03 15:01:45 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.33s bytes=97310
2026-06-03 15:01:45 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data fb_comment_target_tap: already on comment sheet — skip tap
2026-06-03 15:01:45 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_filter_apply expand_see_more=False
2026-06-03 15:01:45 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply start target=all_comments max_steps=5
2026-06-03 15:01:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=4/48 scrcpy_t=1/16 generic_t=0/8 extra_free=5 u2b_free=20 u2f_free=20 tasks=3 loop_max_lag=0.02s scrcpy.sessions=1 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=1 http.hosts=2
2026-06-03 15:01:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:01:46 [WARNING] [relay.scrcpy] [ce0217122019d82c05] scrcpy error (attempt 1/10): scrcpy-server not ready on 127.0.0.1:27183 after 5.0s — adb forward EOF — scrcpy not ready yet — retry in 2.0s
2026-06-03 15:01:47 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.37s bytes=97310
2026-06-03 15:01:47 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply done switched=False reason=indicator_not_found total=1.38s steps=1
2026-06-03 15:01:48 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Screen streaming stopped
2026-06-03 15:01:48 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Device message sender stopped
2026-06-03 15:01:48 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Controller stopped
2026-06-03 15:01:48 [INFO] [relay.scrcpy] [ce0217122019d82c05] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 15:01:49 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server started, forward tcp:27183 → localabstract:scrcpy
2026-06-03 15:01:49 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comments expand_see_more=False
2026-06-03 15:01:49 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_comments expand=False open_post=False
2026-06-03 15:01:49 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G930S (Android 14)
2026-06-03 15:01:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 15:01:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 15:01:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 15:01:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:01:50 [INFO] [relay.scrcpy] [ce0217122019d82c05] handshake OK — 304x536
2026-06-03 15:01:50 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.97s bytes=72936
2026-06-03 15:01:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:01:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:01:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:01:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:01:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:01:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:01:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:01:54 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:01:55 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:01:55 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:01:56 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.21s bytes=70521
2026-06-03 15:01:57 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:01:57 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:01:57 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:01:57 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:01:58 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:01:58 [INFO] [relay.u2_session_pool] u2-pool: heartbeat evicted dead session serial=ce021602b062850605
2026-06-03 15:01:58 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:01:58 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:02:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:02:02 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.23s bytes=70521
2026-06-03 15:02:03 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:02:03 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:02:03 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:02:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:02:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:02:05 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:02:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:02:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:02:08 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.92s bytes=70521
2026-06-03 15:02:08 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:02:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:02:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:02:13 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:02:14 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.01s bytes=70521
2026-06-03 15:02:15 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:02:15 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:02:16 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:02:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:02:18 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:02:18 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:02:18 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:02:20 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.97s bytes=70521
2026-06-03 15:02:20 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment no-growth break after 5 dump cycles (15 swipes, 3 unchanged XML dumps, snapshots=3)
2026-06-03 15:02:20 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment scroll done swipes=15 dumps=3 snapshots=3
2026-06-03 15:02:20 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=3 total=30.34s
2026-06-03 15:02:23 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:02:23 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:02:23 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:02:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:02:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:02:26 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:02:28 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:02:28 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:02:28 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:02:29 [INFO] [relay.session_mgr] session stopped: ce0217122019d82c05 (reason=manual_stop, remaining=0)
2026-06-03 15:02:29 [INFO] [relay.agent] auto-resume skipped ce0217122019d82c05: desired=false reason=manual_stop
2026-06-03 15:02:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:02:33 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_posts expand_see_more=True
2026-06-03 15:02:34 [INFO] [relay.u2_session_pool] u2-pool: connected serial=ce021602b062850605
2026-06-03 15:02:34 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_posts expand=True open_post=True
2026-06-03 15:02:35 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.17s bytes=45082
2026-06-03 15:02:37 [INFO] [relay.extra_data.collector] [ce021602b062850605] open_post_before_extract tap #0 kind=timestamp route=click_coord label='5 giờ•Chia sẻ với: Nhóm công khai'
2026-06-03 15:02:39 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.69s bytes=76853
2026-06-03 15:02:39 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more: xml_probe_first (Facebook-friendly)
2026-06-03 15:02:41 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.21s bytes=76853
2026-06-03 15:02:41 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe: no see-more in hierarchy
2026-06-03 15:02:41 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe_first: no tap (skip selector storm)
2026-06-03 15:02:41 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data reuse expand hierarchy (skip redundant dump)
2026-06-03 15:02:41 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=1 total=7.13s
2026-06-03 15:02:43 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_target_tap expand_see_more=False
2026-06-03 15:02:43 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect+tap start strategy=fb_comment_target_tap
2026-06-03 15:02:44 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.18s bytes=97462
2026-06-03 15:02:44 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data fb_comment_target_tap: already on comment sheet — skip tap
2026-06-03 15:02:44 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_filter_apply expand_see_more=False
2026-06-03 15:02:44 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply start target=all_comments max_steps=5
2026-06-03 15:02:46 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.12s bytes=97462
2026-06-03 15:02:46 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply done switched=False reason=indicator_not_found total=1.13s steps=1
2026-06-03 15:02:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=5/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.02s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=1 http.hosts=2
2026-06-03 15:02:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:02:48 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comments expand_see_more=False
2026-06-03 15:02:48 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_comments expand=False open_post=False
2026-06-03 15:02:49 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.99s bytes=72128
2026-06-03 15:02:55 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.23s bytes=70521
2026-06-03 15:02:58 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:02:58 [INFO] [relay.u2_session_pool] u2-pool: heartbeat evicted dead session serial=ce021602b062850605
2026-06-03 15:03:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:03:01 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.16s bytes=70521
2026-06-03 15:03:07 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.99s bytes=70521
2026-06-03 15:03:13 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.17s bytes=70521
2026-06-03 15:03:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:03:19 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.07s bytes=70521
2026-06-03 15:03:19 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment no-growth break after 5 dump cycles (15 swipes, 3 unchanged XML dumps, snapshots=3)
2026-06-03 15:03:19 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment scroll done swipes=15 dumps=3 snapshots=3
2026-06-03 15:03:19 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=3 total=30.62s
2026-06-03 15:03:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:03:33 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_posts expand_see_more=True
2026-06-03 15:03:33 [INFO] [relay.u2_session_pool] u2-pool: connected serial=ce021602b062850605
2026-06-03 15:03:33 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_posts expand=True open_post=True
2026-06-03 15:03:35 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.11s bytes=44166
2026-06-03 15:03:37 [INFO] [relay.extra_data.collector] [ce021602b062850605] open_post_before_extract tap #0 kind=timestamp route=click_coord label='5 giờ•Chia sẻ với: Nhóm công khai'
2026-06-03 15:03:39 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.60s bytes=76853
2026-06-03 15:03:39 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more: xml_probe_first (Facebook-friendly)
2026-06-03 15:03:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.16s bytes=76853
2026-06-03 15:03:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe: no see-more in hierarchy
2026-06-03 15:03:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe_first: no tap (skip selector storm)
2026-06-03 15:03:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data reuse expand hierarchy (skip redundant dump)
2026-06-03 15:03:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=1 total=6.84s
2026-06-03 15:03:43 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_target_tap expand_see_more=False
2026-06-03 15:03:43 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect+tap start strategy=fb_comment_target_tap
2026-06-03 15:03:44 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.12s bytes=92189
2026-06-03 15:03:44 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data fb_comment_target_tap: already on comment sheet — skip tap
2026-06-03 15:03:44 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_filter_apply expand_see_more=False
2026-06-03 15:03:44 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply start target=all_comments max_steps=5
2026-06-03 15:03:45 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.24s bytes=92189
2026-06-03 15:03:45 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply done switched=False reason=indicator_not_found total=1.25s steps=1
2026-06-03 15:03:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=5/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.02s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=1 http.hosts=2
2026-06-03 15:03:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:03:48 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comments expand_see_more=False
2026-06-03 15:03:48 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_comments expand=False open_post=False
2026-06-03 15:03:49 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.16s bytes=69438
2026-06-03 15:03:55 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.27s bytes=70521
2026-06-03 15:04:00 [INFO] [relay.scrcpy] [ce0217122019d82c05] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 15:04:00 [INFO] [relay.session_mgr] session started: ce0217122019d82c05 (total=1)
2026-06-03 15:04:00 [INFO] [relay.scrcpy] [ce021602b062850605] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 15:04:00 [INFO] [relay.session_mgr] session started: ce021602b062850605 (total=2)
2026-06-03 15:04:00 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server started, forward tcp:27183 → localabstract:scrcpy
2026-06-03 15:04:00 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server started, forward tcp:27185 → localabstract:scrcpy
2026-06-03 15:04:01 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G930S (Android 14)
2026-06-03 15:04:01 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G935F (Android 14)
2026-06-03 15:04:01 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 15:04:01 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 15:04:01 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 15:04:01 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:04:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=2 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:04:01 [INFO] [relay.scrcpy] [ce0217122019d82c05] handshake OK — 304x536
2026-06-03 15:04:01 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 15:04:01 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 15:04:01 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 15:04:01 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:04:01 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.94s bytes=70521
2026-06-03 15:04:01 [INFO] [relay.scrcpy] [ce021602b062850605] handshake OK — 304x536
2026-06-03 15:04:01 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:04:02 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:04:04 [INFO] [relay.session_mgr] session stopped: ce0217122019d82c05 (reason=manual_stop, remaining=1)
2026-06-03 15:04:04 [INFO] [relay.agent] auto-resume skipped ce0217122019d82c05: desired=false reason=manual_stop
2026-06-03 15:04:04 [INFO] [relay.session_mgr] session stopped: ce021602b062850605 (reason=manual_stop, remaining=0)
2026-06-03 15:04:04 [INFO] [relay.agent] auto-resume skipped ce021602b062850605: desired=false reason=manual_stop
2026-06-03 15:04:08 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.11s bytes=70521
2026-06-03 15:04:14 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.11s bytes=70521
2026-06-03 15:04:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:04:19 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.85s bytes=70521
2026-06-03 15:04:19 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment no-growth break after 5 dump cycles (15 swipes, 3 unchanged XML dumps, snapshots=3)
2026-06-03 15:04:19 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment scroll done swipes=15 dumps=3 snapshots=3
2026-06-03 15:04:19 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=3 total=31.61s
2026-06-03 15:04:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:04:35 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_posts expand_see_more=True
2026-06-03 15:04:39 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:04:39 [INFO] [relay.u2_session_pool] u2-pool: heartbeat evicted dead session serial=ce021602b062850605
2026-06-03 15:04:45 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:04:45 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_posts expand=True open_post=True
2026-06-03 15:04:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=5/48 scrcpy_t=1/16 generic_t=0/8 extra_free=5 u2b_free=20 u2f_free=20 tasks=1 loop_max_lag=0.02s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 15:04:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:04:46 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.91s bytes=47858
2026-06-03 15:04:48 [INFO] [relay.extra_data.collector] [ce021602b062850605] open_post_before_extract tap #0 kind=timestamp route=click_coord label='5 giờ•Chia sẻ với: Nhóm công khai'
2026-06-03 15:04:51 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.56s bytes=76855
2026-06-03 15:04:51 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more: xml_probe_first (Facebook-friendly)
2026-06-03 15:04:52 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.17s bytes=76855
2026-06-03 15:04:52 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe: no see-more in hierarchy
2026-06-03 15:04:52 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe_first: no tap (skip selector storm)
2026-06-03 15:04:52 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data reuse expand hierarchy (skip redundant dump)
2026-06-03 15:04:52 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=1 total=6.54s
2026-06-03 15:04:54 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_target_tap expand_see_more=False
2026-06-03 15:04:54 [INFO] [relay.u2_session_pool] u2-pool: connected serial=ce021602b062850605
2026-06-03 15:04:54 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect+tap start strategy=fb_comment_target_tap
2026-06-03 15:04:55 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.13s bytes=89811
2026-06-03 15:04:55 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data fb_comment_target_tap: already on comment sheet — skip tap
2026-06-03 15:04:56 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_filter_apply expand_see_more=False
2026-06-03 15:04:56 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply start target=all_comments max_steps=5
2026-06-03 15:04:57 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.23s bytes=89811
2026-06-03 15:04:57 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply done switched=False reason=indicator_not_found total=1.24s steps=1
2026-06-03 15:04:59 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comments expand_see_more=False
2026-06-03 15:04:59 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_comments expand=False open_post=False
2026-06-03 15:05:00 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.09s bytes=68507
2026-06-03 15:05:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:05:07 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.13s bytes=70413
2026-06-03 15:05:09 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:05:09 [INFO] [relay.u2_session_pool] u2-pool: heartbeat evicted dead session serial=ce021602b062850605
2026-06-03 15:05:12 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.90s bytes=70413
2026-06-03 15:05:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:05:18 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.09s bytes=70413
2026-06-03 15:05:25 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.39s bytes=70413
2026-06-03 15:05:25 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment no-growth break after 4 dump cycles (12 swipes, 3 unchanged XML dumps, snapshots=2)
2026-06-03 15:05:25 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment scroll done swipes=12 dumps=2 snapshots=2
2026-06-03 15:05:25 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=2 total=25.24s
2026-06-03 15:05:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:05:39 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_posts expand_see_more=True
2026-06-03 15:05:39 [INFO] [relay.u2_session_pool] u2-pool: connected serial=ce021602b062850605
2026-06-03 15:05:39 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_posts expand=True open_post=True
2026-06-03 15:05:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.17s bytes=48156
2026-06-03 15:05:42 [INFO] [relay.extra_data.collector] [ce021602b062850605] open_post_before_extract tap #0 kind=timestamp route=click_coord label='1 ngày•Chia sẻ với: Nhóm công khai'
2026-06-03 15:05:45 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.68s bytes=54069
2026-06-03 15:05:45 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more: xml_probe_first (Facebook-friendly)
2026-06-03 15:05:46 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.99s bytes=54069
2026-06-03 15:05:46 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe: no see-more in hierarchy
2026-06-03 15:05:46 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe_first: no tap (skip selector storm)
2026-06-03 15:05:46 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data reuse expand hierarchy (skip redundant dump)
2026-06-03 15:05:46 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=1 total=6.69s
2026-06-03 15:05:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=5/48 scrcpy_t=1/16 generic_t=0/8 extra_free=5 u2b_free=20 u2f_free=20 tasks=1 loop_max_lag=0.02s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=1 http.hosts=2
2026-06-03 15:05:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:05:48 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_target_tap expand_see_more=False
2026-06-03 15:05:48 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect+tap start strategy=fb_comment_target_tap
2026-06-03 15:05:49 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.02s bytes=61537
2026-06-03 15:05:49 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data fb_comment_target_tap: already on comment sheet — skip tap
2026-06-03 15:05:49 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_filter_apply expand_see_more=False
2026-06-03 15:05:49 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply start target=all_comments max_steps=5
2026-06-03 15:05:51 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.09s bytes=61537
2026-06-03 15:05:51 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply done switched=False reason=indicator_not_found total=1.10s steps=1
2026-06-03 15:05:53 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comments expand_see_more=False
2026-06-03 15:05:53 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_comments expand=False open_post=False
2026-06-03 15:05:54 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.11s bytes=43474
2026-06-03 15:06:00 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:06:00 [INFO] [relay.u2_session_pool] u2-pool: heartbeat evicted dead session serial=ce021602b062850605
2026-06-03 15:06:00 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.23s bytes=62360
2026-06-03 15:06:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:06:06 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.94s bytes=53058
2026-06-03 15:06:12 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.96s bytes=50138
2026-06-03 15:06:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:06:18 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.96s bytes=48520
2026-06-03 15:06:23 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.99s bytes=38209
2026-06-03 15:06:29 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.19s bytes=38209
2026-06-03 15:06:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:06:35 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.91s bytes=38209
2026-06-03 15:06:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.91s bytes=38209
2026-06-03 15:06:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment no-growth break after 8 dump cycles (24 swipes, 3 unchanged XML dumps, snapshots=6)
2026-06-03 15:06:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment scroll done swipes=24 dumps=6 snapshots=6
2026-06-03 15:06:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=6 total=47.72s
2026-06-03 15:06:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=5/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.02s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 15:06:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:06:57 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_posts expand_see_more=True
2026-06-03 15:06:57 [INFO] [relay.u2_session_pool] u2-pool: connected serial=ce021602b062850605
2026-06-03 15:06:57 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_posts expand=True open_post=True
2026-06-03 15:06:58 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.92s bytes=49974
2026-06-03 15:07:00 [INFO] [relay.extra_data.collector] [ce021602b062850605] open_post_before_extract tap #0 kind=timestamp route=click_coord label='1 ngày•Chia sẻ với: Nhóm công khai'
2026-06-03 15:07:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:07:02 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.90s bytes=54070
2026-06-03 15:07:02 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more: xml_probe_first (Facebook-friendly)
2026-06-03 15:07:03 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.91s bytes=54070
2026-06-03 15:07:03 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe: no see-more in hierarchy
2026-06-03 15:07:03 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe_first: no tap (skip selector storm)
2026-06-03 15:07:03 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data reuse expand hierarchy (skip redundant dump)
2026-06-03 15:07:03 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=1 total=5.57s
2026-06-03 15:07:05 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_target_tap expand_see_more=False
2026-06-03 15:07:05 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect+tap start strategy=fb_comment_target_tap
2026-06-03 15:07:06 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.93s bytes=62092
2026-06-03 15:07:06 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data fb_comment_target_tap: already on comment sheet — skip tap
2026-06-03 15:07:06 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_filter_apply expand_see_more=False
2026-06-03 15:07:06 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply start target=all_comments max_steps=5
2026-06-03 15:07:07 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.11s bytes=62092
2026-06-03 15:07:07 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply done switched=False reason=indicator_not_found total=1.13s steps=1
2026-06-03 15:07:09 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comments expand_see_more=False
2026-06-03 15:07:09 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_comments expand=False open_post=False
2026-06-03 15:07:11 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.12s bytes=44425
2026-06-03 15:07:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:07:17 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.90s bytes=63698
2026-06-03 15:07:23 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.86s bytes=52725
2026-06-03 15:07:28 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.95s bytes=50514
2026-06-03 15:07:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:07:34 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.81s bytes=44535
2026-06-03 15:07:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.91s bytes=38209
2026-06-03 15:07:45 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.02s bytes=38209
2026-06-03 15:07:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=5/48 scrcpy_t=1/16 generic_t=0/8 extra_free=5 u2b_free=20 u2f_free=20 tasks=1 loop_max_lag=0.02s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=1 http.hosts=2
2026-06-03 15:07:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:07:51 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.98s bytes=38209
2026-06-03 15:07:56 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.85s bytes=38209
2026-06-03 15:07:56 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment no-growth break after 8 dump cycles (24 swipes, 3 unchanged XML dumps, snapshots=6)
2026-06-03 15:07:56 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment scroll done swipes=24 dumps=6 snapshots=6
2026-06-03 15:07:56 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=6 total=46.88s
2026-06-03 15:08:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:08:11 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:08:11 [INFO] [relay.u2_session_pool] u2-pool: heartbeat evicted dead session serial=ce021602b062850605
2026-06-03 15:08:13 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_posts expand_see_more=True
2026-06-03 15:08:13 [INFO] [relay.u2_session_pool] u2-pool: connected serial=ce021602b062850605
2026-06-03 15:08:13 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_posts expand=True open_post=True
2026-06-03 15:08:14 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.85s bytes=43222
2026-06-03 15:08:16 [INFO] [relay.extra_data.collector] [ce021602b062850605] open_post_before_extract tap #0 kind=timestamp route=click_coord label='1 ngày•Chia sẻ với: Nhóm công khai'
2026-06-03 15:08:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:08:17 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.05s bytes=71702
2026-06-03 15:08:17 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more: xml_probe_first (Facebook-friendly)
2026-06-03 15:08:18 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.14s bytes=71702
2026-06-03 15:08:18 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe: no see-more in hierarchy
2026-06-03 15:08:18 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe_first: no tap (skip selector storm)
2026-06-03 15:08:18 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data reuse expand hierarchy (skip redundant dump)
2026-06-03 15:08:18 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=1 total=5.72s
2026-06-03 15:08:21 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_target_tap expand_see_more=False
2026-06-03 15:08:21 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect+tap start strategy=fb_comment_target_tap
2026-06-03 15:08:22 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.05s bytes=73532
2026-06-03 15:08:22 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data fb_comment_target_tap: already on comment sheet — skip tap
2026-06-03 15:08:22 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_filter_apply expand_see_more=False
2026-06-03 15:08:22 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply start target=all_comments max_steps=5
2026-06-03 15:08:23 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.98s bytes=73532
2026-06-03 15:08:23 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply done switched=False reason=indicator_not_found total=0.99s steps=1
2026-06-03 15:08:25 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comments expand_see_more=False
2026-06-03 15:08:25 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_comments expand=False open_post=False
2026-06-03 15:08:27 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.04s bytes=55331
2026-06-03 15:08:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:08:31 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:08:31 [INFO] [relay.u2_session_pool] u2-pool: heartbeat evicted dead session serial=ce021602b062850605
2026-06-03 15:08:33 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.16s bytes=49704
2026-06-03 15:08:38 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.93s bytes=56632
2026-06-03 15:08:44 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.85s bytes=46531
2026-06-03 15:08:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=5/48 scrcpy_t=1/16 generic_t=0/8 extra_free=5 u2b_free=20 u2f_free=20 tasks=1 loop_max_lag=0.02s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 15:08:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:08:51 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.36s bytes=51847
2026-06-03 15:08:57 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.89s bytes=43833
2026-06-03 15:09:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:09:03 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.14s bytes=39152
2026-06-03 15:09:09 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.02s bytes=39152
2026-06-03 15:09:15 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.12s bytes=39152
2026-06-03 15:09:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:09:21 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.04s bytes=39152
2026-06-03 15:09:21 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment no-growth break after 9 dump cycles (27 swipes, 3 unchanged XML dumps, snapshots=7)
2026-06-03 15:09:21 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment scroll done swipes=27 dumps=7 snapshots=7
2026-06-03 15:09:21 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=7 total=55.89s
2026-06-03 15:09:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:09:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 15:09:36 [INFO] [relay.session_mgr] session started: ce0217122019d82c05 (total=1)
2026-06-03 15:09:36 [INFO] [relay.scrcpy] [ce021602b062850605] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 15:09:36 [INFO] [relay.session_mgr] session started: ce021602b062850605 (total=2)
2026-06-03 15:09:36 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server started, forward tcp:27183 → localabstract:scrcpy
2026-06-03 15:09:37 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server started, forward tcp:27185 → localabstract:scrcpy
2026-06-03 15:09:37 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G930S (Android 14)
2026-06-03 15:09:37 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_posts expand_see_more=True
2026-06-03 15:09:37 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G935F (Android 14)
2026-06-03 15:09:37 [INFO] [relay.u2_session_pool] u2-pool: connected serial=ce021602b062850605
2026-06-03 15:09:37 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_posts expand=True open_post=True
2026-06-03 15:09:37 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 15:09:37 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 15:09:37 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 15:09:37 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:09:37 [INFO] [relay.scrcpy] [ce0217122019d82c05] handshake OK — 304x536
2026-06-03 15:09:38 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 15:09:38 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 15:09:38 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 15:09:38 [INFO] [relay.scrcpy] [ce021602b062850605] handshake OK — 304x536
2026-06-03 15:09:38 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:09:38 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:09:38 [INFO] [relay.scrcpy] [ce021602b062850605] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:09:38 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.87s bytes=43191
2026-06-03 15:09:38 [INFO] [relay.session_mgr] session stopped: ce0217122019d82c05 (reason=manual_stop, remaining=1)
2026-06-03 15:09:38 [INFO] [relay.agent] auto-resume skipped ce0217122019d82c05: desired=false reason=manual_stop
2026-06-03 15:09:38 [INFO] [relay.session_mgr] session stopped: ce021602b062850605 (reason=manual_stop, remaining=0)
2026-06-03 15:09:38 [INFO] [relay.agent] auto-resume skipped ce021602b062850605: desired=false reason=manual_stop
2026-06-03 15:09:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] pushing scrcpy-server 3.3.4 (device_size='' expected=90980)
2026-06-03 15:09:39 [INFO] [relay.session_mgr] session started: ce0217122019d82c05 (total=1)
2026-06-03 15:09:39 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server started, forward tcp:27183 → localabstract:scrcpy
2026-06-03 15:09:40 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Device: [samsung] samsung SM-G930S (Android 14)
2026-06-03 15:09:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] open_post_before_extract tap #0 kind=timestamp route=click_coord label='1 ngày•Chia sẻ với: Nhóm công khai'
2026-06-03 15:09:40 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Using video encoder: 'OMX.Exynos.AVC.Encoder'
2026-06-03 15:09:40 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: i-frame-interval (Integer) = 1
2026-06-03 15:09:40 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Video codec option set: max-bframes (Integer) = 0
2026-06-03 15:09:40 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:09:40 [INFO] [relay.scrcpy] [ce0217122019d82c05] handshake OK — 304x536
2026-06-03 15:09:40 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:09:40 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:09:41 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:09:41 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:09:42 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.95s bytes=71701
2026-06-03 15:09:42 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more: xml_probe_first (Facebook-friendly)
2026-06-03 15:09:43 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.96s bytes=71701
2026-06-03 15:09:43 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe: no see-more in hierarchy
2026-06-03 15:09:43 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe_first: no tap (skip selector storm)
2026-06-03 15:09:43 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data reuse expand hierarchy (skip redundant dump)
2026-06-03 15:09:43 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=1 total=5.44s
2026-06-03 15:09:45 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_target_tap expand_see_more=False
2026-06-03 15:09:45 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect+tap start strategy=fb_comment_target_tap
2026-06-03 15:09:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:09:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:09:46 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:09:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=5/48 scrcpy_t=1/16 generic_t=0/8 extra_free=5 u2b_free=20 u2f_free=20 tasks=1 loop_max_lag=0.01s scrcpy.sessions=1 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=1 http.hosts=2
2026-06-03 15:09:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:09:47 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.21s bytes=75134
2026-06-03 15:09:47 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data fb_comment_target_tap: already on comment sheet — skip tap
2026-06-03 15:09:47 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_filter_apply expand_see_more=False
2026-06-03 15:09:47 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply start target=all_comments max_steps=5
2026-06-03 15:09:48 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.34s bytes=75134
2026-06-03 15:09:48 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply done switched=False reason=indicator_not_found total=1.35s steps=1
2026-06-03 15:09:49 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:09:49 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:09:49 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:09:50 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comments expand_see_more=False
2026-06-03 15:09:50 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_comments expand=False open_post=False
2026-06-03 15:09:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:09:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:09:51 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.17s bytes=57276
2026-06-03 15:09:51 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:09:56 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:09:56 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:09:56 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:09:57 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.88s bytes=50441
2026-06-03 15:09:59 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:09:59 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:09:59 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:10:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=1 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:10:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:10:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:10:02 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:10:03 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.90s bytes=57017
2026-06-03 15:10:06 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:10:06 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:10:06 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:10:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:10:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:10:09 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:10:09 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.86s bytes=45572
2026-06-03 15:10:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy: 1.5s without frame — requested IDR keyframe
2026-06-03 15:10:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] INFO: Video capture reset
2026-06-03 15:10:12 [INFO] [relay.scrcpy] [ce0217122019d82c05] scrcpy-server: [server] DEBUG: Display: using DisplayManager API
2026-06-03 15:10:13 [INFO] [relay.session_mgr] session stopped: ce0217122019d82c05 (reason=manual_stop, remaining=0)
2026-06-03 15:10:13 [INFO] [relay.agent] auto-resume skipped ce0217122019d82c05: desired=false reason=manual_stop
2026-06-03 15:10:15 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.90s bytes=52248
2026-06-03 15:10:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:10:21 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.88s bytes=45993
2026-06-03 15:10:27 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.20s bytes=39152
2026-06-03 15:10:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:10:33 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.97s bytes=39152
2026-06-03 15:10:39 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.13s bytes=39152
2026-06-03 15:10:46 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.25s bytes=39152
2026-06-03 15:10:46 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment no-growth break after 9 dump cycles (27 swipes, 3 unchanged XML dumps, snapshots=7)
2026-06-03 15:10:46 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment scroll done swipes=27 dumps=7 snapshots=7
2026-06-03 15:10:46 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=7 total=55.28s
2026-06-03 15:10:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=5/48 scrcpy_t=1/16 generic_t=0/8 extra_free=5 u2b_free=20 u2f_free=20 tasks=1 loop_max_lag=0.02s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=1 http.hosts=2
2026-06-03 15:10:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:11:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:11:01 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_posts expand_see_more=True
2026-06-03 15:11:02 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:11:02 [INFO] [relay.u2_session_pool] u2-pool: heartbeat evicted dead session serial=ce021602b062850605
2026-06-03 15:11:12 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:11:12 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_posts expand=True open_post=True
2026-06-03 15:11:13 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.85s bytes=43373
2026-06-03 15:11:15 [INFO] [relay.extra_data.collector] [ce021602b062850605] open_post_before_extract tap #0 kind=timestamp route=click_coord label='1 ngày•Chia sẻ với: Nhóm công khai'
2026-06-03 15:11:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:11:16 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.95s bytes=41865
2026-06-03 15:11:16 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more: xml_probe_first (Facebook-friendly)
2026-06-03 15:11:17 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.82s bytes=41865
2026-06-03 15:11:17 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe: no see-more in hierarchy
2026-06-03 15:11:17 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe_first: no tap (skip selector storm)
2026-06-03 15:11:17 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data reuse expand hierarchy (skip redundant dump)
2026-06-03 15:11:17 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=1 total=5.33s
2026-06-03 15:11:20 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_target_tap expand_see_more=False
2026-06-03 15:11:20 [INFO] [relay.u2_session_pool] u2-pool: connected serial=ce021602b062850605
2026-06-03 15:11:20 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect+tap start strategy=fb_comment_target_tap
2026-06-03 15:11:21 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.23s bytes=45669
2026-06-03 15:11:21 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data fb_comment_target_tap: already on comment sheet — skip tap
2026-06-03 15:11:21 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_filter_apply expand_see_more=False
2026-06-03 15:11:21 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply start target=all_comments max_steps=5
2026-06-03 15:11:22 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.01s bytes=45669
2026-06-03 15:11:22 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply done switched=False reason=indicator_not_found total=1.02s steps=1
2026-06-03 15:11:24 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comments expand_see_more=False
2026-06-03 15:11:24 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_comments expand=False open_post=False
2026-06-03 15:11:26 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.18s bytes=28908
2026-06-03 15:11:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:11:31 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.85s bytes=47895
2026-06-03 15:11:37 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.12s bytes=58030
2026-06-03 15:11:43 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.06s bytes=53966
2026-06-03 15:11:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=5/48 scrcpy_t=1/16 generic_t=0/8 extra_free=5 u2b_free=20 u2f_free=20 tasks=2 loop_max_lag=0.02s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=1 http.hosts=2
2026-06-03 15:11:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:11:49 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.11s bytes=49992
2026-06-03 15:11:55 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.12s bytes=49992
2026-06-03 15:12:01 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.85s bytes=49992
2026-06-03 15:12:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:12:06 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.06s bytes=49992
2026-06-03 15:12:12 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.93s bytes=49992
2026-06-03 15:12:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:12:18 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.43s bytes=49992
2026-06-03 15:12:24 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.03s bytes=49992
2026-06-03 15:12:24 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment no-growth break after 10 dump cycles (30 swipes, 3 unchanged XML dumps, snapshots=6)
2026-06-03 15:12:24 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment scroll done swipes=30 dumps=6 snapshots=6
2026-06-03 15:12:24 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=6 total=59.57s
2026-06-03 15:12:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:12:40 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_posts expand_see_more=True
2026-06-03 15:12:42 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:12:42 [INFO] [relay.u2_session_pool] u2-pool: heartbeat evicted dead session serial=ce021602b062850605
2026-06-03 15:12:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=5/48 scrcpy_t=1/16 generic_t=0/8 extra_free=5 u2b_free=20 u2f_free=20 tasks=1 loop_max_lag=0.02s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 15:12:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:12:50 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:12:50 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_posts expand=True open_post=True
2026-06-03 15:12:52 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.17s bytes=44138
2026-06-03 15:12:54 [INFO] [relay.extra_data.collector] [ce021602b062850605] open_post_before_extract tap #0 kind=timestamp route=click_coord label='1 ngày•Chia sẻ với: Nhóm công khai'
2026-06-03 15:12:55 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.84s bytes=41864
2026-06-03 15:12:55 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more: xml_probe_first (Facebook-friendly)
2026-06-03 15:12:56 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.81s bytes=41864
2026-06-03 15:12:56 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe: no see-more in hierarchy
2026-06-03 15:12:56 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe_first: no tap (skip selector storm)
2026-06-03 15:12:56 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data reuse expand hierarchy (skip redundant dump)
2026-06-03 15:12:56 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=1 total=5.52s
2026-06-03 15:12:58 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_target_tap expand_see_more=False
2026-06-03 15:12:58 [INFO] [relay.u2_session_pool] u2-pool: connected serial=ce021602b062850605
2026-06-03 15:12:58 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect+tap start strategy=fb_comment_target_tap
2026-06-03 15:12:59 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.03s bytes=47306
2026-06-03 15:13:00 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data fb_comment_target_tap: already on comment sheet — skip tap
2026-06-03 15:13:00 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_filter_apply expand_see_more=False
2026-06-03 15:13:00 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply start target=all_comments max_steps=5
2026-06-03 15:13:01 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.14s bytes=47306
2026-06-03 15:13:01 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply done switched=False reason=indicator_not_found total=1.14s steps=1
2026-06-03 15:13:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:13:03 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comments expand_see_more=False
2026-06-03 15:13:03 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_comments expand=False open_post=False
2026-06-03 15:13:04 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.00s bytes=30456
2026-06-03 15:13:10 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.98s bytes=48815
2026-06-03 15:13:13 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:13:13 [INFO] [relay.u2_session_pool] u2-pool: heartbeat evicted dead session serial=ce021602b062850605
2026-06-03 15:13:16 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.14s bytes=61175
2026-06-03 15:13:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:13:22 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.23s bytes=49992
2026-06-03 15:13:28 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.11s bytes=49992
2026-06-03 15:13:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:13:34 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.82s bytes=49992
2026-06-03 15:13:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.20s bytes=49992
2026-06-03 15:13:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment no-growth break after 6 dump cycles (18 swipes, 3 unchanged XML dumps, snapshots=4)
2026-06-03 15:13:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment scroll done swipes=18 dumps=4 snapshots=4
2026-06-03 15:13:40 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=4 total=36.81s
2026-06-03 15:13:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=5/48 scrcpy_t=1/16 generic_t=0/8 extra_free=6 u2b_free=20 u2f_free=20 tasks=0 loop_max_lag=0.02s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 15:13:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:13:55 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_posts expand_see_more=True
2026-06-03 15:13:56 [INFO] [relay.u2_session_pool] u2-pool: connected serial=ce021602b062850605
2026-06-03 15:13:56 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_posts expand=True open_post=True
2026-06-03 15:13:57 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.09s bytes=46799
2026-06-03 15:13:59 [INFO] [relay.extra_data.collector] [ce021602b062850605] open_post_before_extract tap #0 kind=timestamp route=click_coord label='1 ngày•Chia sẻ với: Nhóm công khai'
2026-06-03 15:14:00 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.82s bytes=57533
2026-06-03 15:14:00 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more: xml_probe_first (Facebook-friendly)
2026-06-03 15:14:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:14:01 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.88s bytes=57533
2026-06-03 15:14:01 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe: no see-more in hierarchy
2026-06-03 15:14:01 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe_first: no tap (skip selector storm)
2026-06-03 15:14:01 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data reuse expand hierarchy (skip redundant dump)
2026-06-03 15:14:01 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=1 total=5.57s
2026-06-03 15:14:04 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_target_tap expand_see_more=False
2026-06-03 15:14:04 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect+tap start strategy=fb_comment_target_tap
2026-06-03 15:14:05 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.24s bytes=57533
2026-06-03 15:14:05 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data fb_comment_target_tap: already on comment sheet — skip tap
2026-06-03 15:14:05 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_filter_apply expand_see_more=False
2026-06-03 15:14:05 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply start target=all_comments max_steps=5
2026-06-03 15:14:06 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.95s bytes=57533
2026-06-03 15:14:06 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply done switched=False reason=indicator_not_found total=0.96s steps=1
2026-06-03 15:14:08 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comments expand_see_more=False
2026-06-03 15:14:08 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_comments expand=False open_post=False
2026-06-03 15:14:09 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.95s bytes=39796
2026-06-03 15:14:14 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:14:14 [INFO] [relay.u2_session_pool] u2-pool: heartbeat evicted dead session serial=ce021602b062850605
2026-06-03 15:14:15 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.18s bytes=39796
2026-06-03 15:14:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:14:21 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.95s bytes=39796
2026-06-03 15:14:27 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.88s bytes=39796
2026-06-03 15:14:27 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment no-growth break after 3 dump cycles (9 swipes, 3 unchanged XML dumps, snapshots=1)
2026-06-03 15:14:27 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment scroll done swipes=9 dumps=1 snapshots=1
2026-06-03 15:14:27 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=1 total=18.52s
2026-06-03 15:14:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:14:43 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_posts expand_see_more=True
2026-06-03 15:14:43 [INFO] [relay.u2_session_pool] u2-pool: connected serial=ce021602b062850605
2026-06-03 15:14:43 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_posts expand=True open_post=True
2026-06-03 15:14:44 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.99s bytes=51622
2026-06-03 15:14:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=5/48 scrcpy_t=1/16 generic_t=0/8 extra_free=5 u2b_free=20 u2f_free=20 tasks=1 loop_max_lag=0.02s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=1 http.hosts=2
2026-06-03 15:14:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:14:46 [INFO] [relay.extra_data.collector] [ce021602b062850605] open_post_before_extract tap #0 kind=timestamp route=click_coord label='1 ngày•Chia sẻ với: Nhóm công khai'
2026-06-03 15:14:48 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.92s bytes=57531
2026-06-03 15:14:48 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more: xml_probe_first (Facebook-friendly)
2026-06-03 15:14:49 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.05s bytes=57531
2026-06-03 15:14:49 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe: no see-more in hierarchy
2026-06-03 15:14:49 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe_first: no tap (skip selector storm)
2026-06-03 15:14:49 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data reuse expand hierarchy (skip redundant dump)
2026-06-03 15:14:49 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=1 total=5.72s
2026-06-03 15:14:52 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_target_tap expand_see_more=False
2026-06-03 15:14:52 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect+tap start strategy=fb_comment_target_tap
2026-06-03 15:14:52 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.85s bytes=57531
2026-06-03 15:14:52 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data fb_comment_target_tap: already on comment sheet — skip tap
2026-06-03 15:14:53 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_filter_apply expand_see_more=False
2026-06-03 15:14:53 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply start target=all_comments max_steps=5
2026-06-03 15:14:54 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.15s bytes=57531
2026-06-03 15:14:54 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply done switched=False reason=indicator_not_found total=1.16s steps=1
2026-06-03 15:14:56 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comments expand_see_more=False
2026-06-03 15:14:56 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_comments expand=False open_post=False
2026-06-03 15:14:57 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.02s bytes=39358
2026-06-03 15:15:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:15:02 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.23s bytes=39358
2026-06-03 15:15:07 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.92s bytes=39358
2026-06-03 15:15:13 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.95s bytes=39358
2026-06-03 15:15:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:15:19 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.97s bytes=39358
2026-06-03 15:15:19 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment no-growth break after 4 dump cycles (12 swipes, 3 unchanged XML dumps, snapshots=2)
2026-06-03 15:15:19 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment scroll done swipes=12 dumps=2 snapshots=2
2026-06-03 15:15:19 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=2 total=23.05s
2026-06-03 15:15:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:15:34 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_posts expand_see_more=True
2026-06-03 15:15:34 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:15:34 [INFO] [relay.u2_session_pool] u2-pool: heartbeat evicted dead session serial=ce021602b062850605
2026-06-03 15:15:45 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:15:45 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_posts expand=True open_post=True
2026-06-03 15:15:46 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.13s bytes=58748
2026-06-03 15:15:46 [INFO] [relay.runtime] runtime stats: adb_t=4/48 u2_t=5/48 scrcpy_t=1/16 generic_t=0/8 extra_free=5 u2b_free=20 u2f_free=20 tasks=1 loop_max_lag=0.01s scrcpy.sessions=0 devices.online=2 a11y.serials=2 send_q.qsize=0 send_q.lanes=3 send_q.ctrl=0 send_q.max_lane=0 u2pool.sessions=0 http.hosts=2
2026-06-03 15:15:46 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:15:48 [INFO] [relay.extra_data.collector] [ce021602b062850605] open_post_before_extract tap #0 kind=timestamp route=click_coord label='20 giờ•Chia sẻ với: Nhóm công khai'
2026-06-03 15:15:50 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.98s bytes=56907
2026-06-03 15:15:50 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more: xml_probe_first (Facebook-friendly)
2026-06-03 15:15:51 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.91s bytes=56907
2026-06-03 15:15:51 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe: no see-more in hierarchy
2026-06-03 15:15:51 [INFO] [relay.extra_data.collector] [ce021602b062850605] expand_see_more xml_probe_first: no tap (skip selector storm)
2026-06-03 15:15:51 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data reuse expand hierarchy (skip redundant dump)
2026-06-03 15:15:51 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=1 total=6.05s
2026-06-03 15:15:53 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_target_tap expand_see_more=False
2026-06-03 15:15:53 [INFO] [relay.u2_session_pool] u2-pool: connected serial=ce021602b062850605
2026-06-03 15:15:53 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect+tap start strategy=fb_comment_target_tap
2026-06-03 15:15:55 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.05s bytes=56907
2026-06-03 15:15:55 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data fb_comment_target_tap: already on comment sheet — skip tap
2026-06-03 15:15:55 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comment_filter_apply expand_see_more=False
2026-06-03 15:15:55 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply start target=all_comments max_steps=5
2026-06-03 15:15:56 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.09s bytes=56907
2026-06-03 15:15:56 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data filter_apply done switched=False reason=indicator_not_found total=1.10s steps=1
2026-06-03 15:15:58 [INFO] [relay.agent] extra_data start serial=ce021602b062850605 strategy=fb_comments expand_see_more=False
2026-06-03 15:15:58 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect start strategy=fb_comments expand=False open_post=False
2026-06-03 15:15:59 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.23s bytes=38343
2026-06-03 15:16:01 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:16:05 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.90s bytes=38343
2026-06-03 15:16:10 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.15s bytes=38343
2026-06-03 15:16:16 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 0.89s bytes=38343
2026-06-03 15:16:16 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:16:22 [INFO] [relay.extra_data.collector] [ce021602b062850605] dump_hierarchy ok in 1.11s bytes=38343
2026-06-03 15:16:22 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment no-growth break after 4 dump cycles (12 swipes, 3 unchanged XML dumps, snapshots=2)
2026-06-03 15:16:22 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data comment scroll done swipes=12 dumps=2 snapshots=2
2026-06-03 15:16:22 [INFO] [relay.extra_data.collector] [ce021602b062850605] extra_data collect done snapshots=2 total=23.95s
2026-06-03 15:16:31 [INFO] [relay.supervisor] supervisor tick desired=2 healthy=0 missing=0 pending=0 breaker_open=0 offline=0
2026-06-03 15:16:35 [INFO] [relay.u2_session_pool] u2-pool: reconnected serial=ce021602b062850605
2026-06-03 15:16:35 [INFO] [relay.u2_session_pool] u2-pool: heartbeat evicted dead session serial=ce021602b062850605

