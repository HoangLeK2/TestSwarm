---
name: U2 via agent-boot gRPC
overview: Move uiautomator2 execution to agent-boot (which has ADB) and expose a dedicated gRPC service so device_farm calls high-level U2 actions instead of proxying raw HTTP.
todos: []
isProject: false
---

# Move U2 to agent-boot with dedicated gRPC service

## Current Architecture (problem)

```mermaid
sequenceDiagram
    participant DF as device_farm<br/>"Docker"
    participant AB as agent
```



