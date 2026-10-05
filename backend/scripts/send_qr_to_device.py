#!/usr/bin/env python3
"""
Decode a QR code image and inject its content into STFService on a device via ADB.

Usage:
    python send_qr_to_device.py <qr_image_path> [<device_serial>]

    <device_serial>  ADB serial (e.g. 192.168.1.5:5555). Omit to use the only connected device.

Requirements:
    pip install pyzbar pillow
"""

import subprocess
import sys


def decode_qr(image_path: str) -> str:
    try:
        from pyzbar.pyzbar import decode
        from PIL import Image
    except ImportError:
        print("Missing deps. Run: pip install pyzbar pillow")
        sys.exit(1)

    img = Image.open(image_path)
    results = decode(img)
    if not results:
        print(f"No QR code found in: {image_path}")
        sys.exit(1)
    return results[0].data.decode("utf-8")


def send_to_device(qr_content: str, serial: str | None) -> None:
    serial_flags = ["-s", serial] if serial else []

    cmd = (
        ["adb"] + serial_flags + [
            "shell", "am", "start",
            "-n", "jp.co.cyberagent.stf/.IdentityActivity",
            "-a", "jp.co.cyberagent.stf.ACTION_IDENTIFY",
            "--activity-single-top",
            "--es", "qr_content", qr_content,
        ]
    )

    print(f"[QR content] {qr_content[:80]}{'...' if len(qr_content) > 80 else ''}")
    print(f"[ADB cmd   ] {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ADB error: {result.stderr.strip()}")
        sys.exit(1)
    print(f"[OK] {result.stdout.strip()}")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    image_path = sys.argv[1]
    serial = sys.argv[2] if len(sys.argv) >= 3 else None

    qr_content = decode_qr(image_path)
    send_to_device(qr_content, serial)


if __name__ == "__main__":
    main()
