# Runbook: scrcpy bi den man o man login hoac secure screen

Timestamp: 2026-06-06 Asia/Ho_Chi_Minh

## Ket luan ngan

Neu scrcpy chi bi den o mot so man nhu login, PIN, banking, password manager, DRM video, hoac man hinh bao "khong cho chup anh man hinh", nguyen nhan kha nang cao la Android/app dang chan capture bang `FLAG_SECURE` hoac protected buffer. Day la hanh vi bao mat cua Android, khong phai loi bitrate/FPS/restart scrcpy.

Trong device-farm, khong nen coi day la loi stream de auto restart lien tuc. Huong dung la phan loai secure screen, tiep tuc dieu khien bang ADB/u2/scrcpy control neu duoc phep, va hien thi trang thai ro cho operator.

## Bang chung

- Android Developers: `FLAG_SECURE` khong cho screenshot va khong hien thi window tren non-secure display; screenshot se bi blank.
  https://developer.android.com/security/fraud-prevention/activities
- AOSP: tu Android 10, silent screen-buffer capture bi han che; capture qua MediaProjection can user consent va van bi gioi han boi secure content.
  https://source.android.com/docs/core/permissions/restricted-screen-reading
- scrcpy issue #5216: maintainer giai thich Android 12+ khong capture secure content bang shell permission; secure content se den man.
  https://github.com/Genymobile/scrcpy/issues/5216
- scrcpy issue #3049: voi Android 12+, non-root scrcpy khong mirror duoc app yeu cau `FLAG_SECURE`; cac cach root/LSposed/Magisk la ngoai luong chinh va rui ro.
  https://github.com/Genymobile/scrcpy/issues/3049

## Context trong repo

Local scrcpy receiver khoi dong scrcpy-server truc tiep voi:

- `video=true`
- `video_codec=h264`
- `max_fps`, `max_size`, `video_bit_rate`
- `stay_awake=true`
- `send_frame_meta=true`

Tham chieu: `device_farm/runtime/transports/scrcpy_receiver.py`.

Khong co option nao trong duong nay co the bypass `FLAG_SECURE`. Relay van co control socket, nen co the tiep tuc gui input trong mot so truong hop du video bi den.

## Cach xac minh nhanh

Khi dang o man bi den, chay:

```bash
adb -s <serial> exec-out screencap -p > /tmp/device-screen.png
```

Neu file cung den/blank trong khi man hinh that tren device co noi dung, day gan nhu chac la secure capture restriction.

Kiem tra focused window:

```bash
adb -s <serial> shell dumpsys window | grep -Ei "mCurrentFocus|mFocusedApp|FLAG_SECURE|fl="
```

Neu thay `FLAG_SECURE` hoac flag window co bit secure, khong nen restart scrcpy de "fix".

Phan biet nhanh:

- Den toan bo sau khi start moi app, screenshot ADB cung blank: secure screen.
- Den toan bo moi luc, screenshot ADB van co noi dung: loi decoder/transport/encoder, debug scrcpy pipeline.
- Co frame cu dung im, sau do den/lag: co the la encoder/IDR/backpressure, debug stream.

## Huong xu ly khuyen nghi

### 1. App minh so huu

Tao debug/test build khong bat `FLAG_SECURE` o flow can dieu khien tu farm.

Android native:

```kotlin
if (!BuildConfig.DEBUG) {
    window.setFlags(
        WindowManager.LayoutParams.FLAG_SECURE,
        WindowManager.LayoutParams.FLAG_SECURE,
    )
}
```

Hoac gan theo config rieng `ALLOW_SCREEN_CAPTURE_FOR_TESTS`.

### 2. App ben thu ba, khong so huu

Khong co cach supported trong scrcpy non-root de lam hien secure content tren Android 12+. Khong dua bypass vao default fleet.

Neu co uy quyen ro rang cho lab/test device, cac huong root/LSposed/Magisk/LSPatch co the vo hieu hoa `FLAG_SECURE`, nhung rui ro cao:

- khong on dinh giua OEM/Android version;
- co the vi pham policy cua app dich;
- khong giai duoc DRM/protected video surface nhu Widevine;
- tang rui ro bao mat device farm.

### 3. Man lock/PIN/SIM/login he thong

Unlock truoc khi attach scrcpy neu co the. Neu can blind input:

```bash
adb -s <serial> shell input text '<pin>'
adb -s <serial> shell input keyevent 66
```

Voi pattern/password, dung u2/ADB coordinate step da duoc phep thay vi phu thuoc video.

### 4. Trong device-farm UI/runtime

Nen them "secure screen mode":

- detect frame gan nhu all-black trong N frame lien tiep trong khi device van awake;
- chay `screencap` probe co timeout ngan de xac nhan;
- neu secure, hien overlay: "Protected screen - video unavailable, control may still work";
- khong auto restart scrcpy neu da classify la secure;
- tiep tuc cho ADB/u2/scrcpy-control gui input neu task duoc phep.

## Next step de implement

1. Them helper probe trong relay/device client: all-black frame threshold + optional `adb screencap`.
2. Them status event `secure_screen_detected`.
3. Frontend hien overlay thay vi loading/blank vinh vien.
4. Scenario authoring: them step/runbook cho blind unlock/login bang u2/ADB.

