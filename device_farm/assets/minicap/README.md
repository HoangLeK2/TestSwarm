# Minicap Binaries

Place prebuilt minicap binaries here, organized by ABI:

```
assets/minicap/
  arm64-v8a/
    minicap        ← executable
    minicap.so     ← shared library
  armeabi-v7a/
    minicap
    minicap.so
  x86_64/
    minicap
    minicap.so
  x86/
    minicap
    minicap.so
```

## Download

Get prebuilt binaries from: https://github.com/DeviceFarmer/minicap/releases

Or build from source:
```bash
git clone https://github.com/DeviceFarmer/minicap
cd minicap
git submodule update --init
ndk-build  # requires Android NDK
```

## Detection

AdbDeviceBootstrap reads `ro.product.cpu.abi` from device to pick the correct ABI folder.
Common values: `arm64-v8a` (most modern phones), `armeabi-v7a` (older 32-bit).
