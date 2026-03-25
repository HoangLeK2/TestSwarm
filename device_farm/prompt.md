**Role:**
You are a senior Android systems engineer and distributed device-farm architect with deep expertise in Android internals, reverse engineering, remote device control, and large-scale device farm infrastructure.

---

**Objective:**
Design a complete architecture to remotely control Android devices through the web **without using ADB (Android Debug Bridge)** while still leveraging the following tools:

* OpenSTF
* minitouch
* uiautomator2
* scrcpy or alternative screen streaming

The system must allow:

1. Remote screen streaming
2. Remote touch control
3. UI automation
4. Device management
5. Command execution

All communication between device and server must happen over **WebSocket or TCP**, and devices must connect via an **Agent Android App** instead of ADB.

---

**Context:**
Traditional OpenSTF architecture relies heavily on ADB for:

* pushing binaries
* starting services
* port forwarding
* executing shell commands

The goal is to **remove ADB entirely** and replace it with a **custom device agent** installed on the Android device.

---

**Requirements:**

1. **Device Agent App**

   * Android APK that runs as a background service
   * Maintains a persistent WebSocket connection to the device farm server
   * Responsible for launching and managing:

     * minitouch
     * uiautomator2 server
     * screen streaming service
   * Acts as a TCP/WebSocket bridge

2. **Screen Streaming**

   * Use MediaProjection or scrcpy-like encoder
   * Encode screen using H264
   * Stream frames over WebSocket or WebRTC

3. **Touch Injection**

   * Use minitouch if possible
   * Or use AccessibilityService / InputManager
   * Must support multi-touch

4. **Automation**

   * Start and manage uiautomator2 server
   * Allow external clients to send automation commands

5. **Service Management**

   * Agent must start/stop binaries
   * Monitor processes
   * Restart crashed services

6. **Networking**

   * Replace adb forward with:

     * WebSocket tunnel
     * TCP proxy
   * Support multiple concurrent device sessions

7. **Security**

   * Device authentication
   * Secure WebSocket (WSS)
   * Device registration

---

**Deliverables:**

Provide:

1. Full architecture diagram
2. Agent internal architecture
3. Process lifecycle management
4. Network protocol design
5. Screen streaming pipeline
6. Touch control pipeline
7. How to run minitouch and uiautomator2 without ADB
8. Limitations due to Android sandbox / SELinux
9. Comparison with traditional STF + ADB architecture
10. Suggested tech stack (server + Android)

---

**Extra Analysis:**

Also explain:

* How large device farms (AWS Device Farm, BrowserStack) avoid ADB bottlenecks
* Whether it is possible to completely eliminate ADB in production systems
* What system permissions or device owner privileges may be required.

---

**Output format:**

Provide a structured answer with sections:

1. High-level architecture
2. Device agent design
3. Communication protocol
4. Screen streaming system
5. Touch injection system
6. Automation layer
7. Security and scalability
8. Risks and limitations
