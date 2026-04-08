#!/usr/bin/env python3
"""Test scrcpy control — with video drain to prevent server blocking."""
import socket, struct, subprocess, time, sys, threading

SERIAL = "172.16.0.84:5555"
PORT = 29999
ADB = "adb"
SCRCPY_JAR = "/opt/homebrew/share/scrcpy/scrcpy-server"
SCRCPY_VER = "3.3.4"
DEVICE_PATH = "/data/local/tmp/scrcpy-server"

print("[1] Push + start scrcpy-server...")
subprocess.run([ADB, "-s", SERIAL, "push", SCRCPY_JAR, DEVICE_PATH],
               capture_output=True, timeout=15)
proc = subprocess.Popen(
    [ADB, "-s", SERIAL, "shell",
     f"CLASSPATH={DEVICE_PATH} "
     f"app_process / com.genymobile.scrcpy.Server "
     f"{SCRCPY_VER} "
     f"tunnel_forward=true video=true audio=false control=true "
     f"video_codec=h264 max_fps=30 max_size=800 video_bit_rate=8000000 "
     f"send_device_meta=true send_frame_meta=true send_dummy_byte=true "
     f"raw_video_stream=false cleanup=true power_on=true"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(1.5)
if proc.poll() is not None:
    print("ERROR: scrcpy-server died"); sys.exit(1)

subprocess.run([ADB, "-s", SERIAL, "forward", f"tcp:{PORT}", "localabstract:scrcpy"],
               capture_output=True, timeout=10)

video = socket.socket(); video.settimeout(5); video.connect(("127.0.0.1", PORT))
ctrl = socket.socket(); ctrl.settimeout(5); ctrl.connect(("127.0.0.1", PORT))

# Handshake
video.recv(1)
name_buf = b""
while len(name_buf) < 64: name_buf += video.recv(64 - len(name_buf))
meta = b""
while len(meta) < 12: meta += video.recv(12 - len(meta))
_, vw, vh = struct.unpack(">III", meta)

wm = subprocess.run([ADB, "-s", SERIAL, "shell", "wm", "size"],
                    capture_output=True, text=True, timeout=5)
real_w, real_h = 1080, 2316
for line in wm.stdout.strip().splitlines():
    if "x" in line:
        parts = line.split(":")[-1].strip().split("x")
        real_w, real_h = int(parts[0]), int(parts[1])
print(f"    video={vw}x{vh}, real={real_w}x{real_h}")

# CRITICAL: drain video data to prevent server blocking
frame_count = [0]
def drain_video():
    buf = bytearray(65536)
    while True:
        try:
            n = video.recv_into(buf)
            if n == 0: break
            frame_count[0] += 1
        except: break
threading.Thread(target=drain_video, daemon=True).start()

# Drain device messages from control socket
def drain_ctrl():
    while True:
        try:
            d = ctrl.recv(4096)
            if not d: break
        except: break
threading.Thread(target=drain_ctrl, daemon=True).start()

def send_touch(action, x, y, pressure, pointer_id, sw, sh):
    msg = struct.pack(">BBQiiHHHII", 2, action, pointer_id, x, y, sw, sh, pressure, 0, 0)
    ctrl.sendall(msg)

def send_key(keycode):
    ctrl.sendall(struct.pack(">BBIII", 0, 0, keycode, 0, 0))  # DOWN
    ctrl.sendall(struct.pack(">BBIII", 0, 1, keycode, 0, 0))  # UP

cx, cy = real_w // 2, real_h // 2
PF = 0xFFFFFFFFFFFFFFFE  # GENERIC_FINGER

print(f"\n{'='*60}")
print("TEST 1: HOME key")
send_key(3)
time.sleep(2)
print("  → Device should go to home screen")

print(f"\n{'='*60}")
print("TEST 2: Tap center (finger, real coords)")
send_touch(0, cx, cy, 0xFFFF, PF, real_w, real_h)
time.sleep(0.05)
send_touch(1, cx, cy, 0, PF, real_w, real_h)
time.sleep(2)
print(f"  → Tapped ({cx},{cy}), video frames drained: {frame_count[0]}")

print(f"\n{'='*60}")
print("TEST 3: Swipe down (finger, real coords)")
sx, sy = real_w // 2, real_h // 3
ex, ey = real_w // 2, real_h * 2 // 3
send_touch(0, sx, sy, 0xFFFF, PF, real_w, real_h)
for i in range(1, 21):
    t = i / 20
    mx = int(sx + (ex - sx) * t)
    my = int(sy + (ey - sy) * t)
    time.sleep(0.015)
    send_touch(2, mx, my, 0xFFFF, PF, real_w, real_h)
send_touch(1, ex, ey, 0, PF, real_w, real_h)
time.sleep(2)
print(f"  → Swiped ({sx},{sy})→({ex},{ey}), frames: {frame_count[0]}")

print(f"\n{'='*60}")
print("TEST 4: adb shell input tap (bypass scrcpy)")
subprocess.run([ADB, "-s", SERIAL, "shell", "input", "tap",
                str(cx), str(cy)], timeout=10)
time.sleep(2)
print("  → adb input tap done")

# Cleanup
print("\nCleaning up...")
proc.terminate()
subprocess.run([ADB, "-s", SERIAL, "forward", "--remove", f"tcp:{PORT}"],
               capture_output=True, timeout=5)
print("Done! Which tests made the device react?")
print("  1=HOME key, 2=tap, 3=swipe, 4=adb input tap")
