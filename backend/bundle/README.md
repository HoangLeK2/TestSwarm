# Bundle Directory

Chứa các file nhị phân và APK cần thiết để agent hoạt động mà **không cần internet**.

## Cấu trúc

```
bundle/
├── minitouch/
│   ├── arm64-v8a/minitouch      ← Android 64-bit (Samsung, Xiaomi, Oppo... mới)
│   ├── armeabi-v7a/minitouch    ← Android 32-bit cũ (Android < 5.0)
│   ├── x86_64/minitouch         ← Emulator 64-bit
│   └── x86/minitouch            ← Emulator 32-bit
└── apks/
    ├── app-uiautomator.apk          ← uiautomator2 main app
    ├── app-uiautomator-test.apk     ← uiautomator2 test runner (BẮT BUỘC)
    └── STFService.apk               ← Battery/rotation events
```

## Cách tạo bundle

Chạy trên PC (cần internet 1 lần):

```bash
# Tải tất cả (tất cả ABI) — chạy từ thư mục backend (shim `download_bundle.py` hoặc):
python scripts/download_bundle.py

# Chỉ tải arm64 (điện thoại phổ biến nhất)
python download_bundle.py --abi arm64

# Bỏ qua STFService (nếu không cần battery/rotation)
python download_bundle.py --no-stf
```

## Cách deploy lên điện thoại

```bash
# Copy qua ADB
adb push bundle/ /data/data/com.termux/files/home/
# Dùng bản đầy đủ trong scripts/ (không push shim ở root repo — Termux không có package `scripts`)
adb push scripts/agent_local.py scripts/setup_agent.py /data/data/com.termux/files/home/

# Trên Termux
pip install websockets pillow
python agent_local.py --server ws://192.168.x.x:8081/device-agent --auto-setup
```

## File nào cần cho ABI nào?

| Điện thoại | ABI | File cần |
|-----------|-----|---------|
| Samsung, Xiaomi, Oppo, Vivo (2017+) | arm64-v8a | `minitouch/arm64-v8a/minitouch` |
| Điện thoại cũ, Android < 6 | armeabi-v7a | `minitouch/armeabi-v7a/minitouch` |
| Android Studio Emulator | x86_64 / x86 | tương ứng |

> **Tip:** Nếu không chắc, copy cả 4 ABI — `setup_agent.py` sẽ tự detect đúng cái.
