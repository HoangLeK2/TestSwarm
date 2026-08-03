# Research Report: Tối ưu stream scrcpy cho device farm quy mô lớn

**Thời điểm nghiên cứu:** 2026-07-29, Asia/Ho_Chi_Minh
**Phạm vi:** Android physical-device streaming, nhiều phone live đồng thời, độ trễ cực thấp, giữ scrcpy làm capture/encoder/control.

## Mục lục

1. Kết luận
2. Hiện trạng của device-farm
3. Mọi người đang tối ưu theo pattern nào
4. So sánh transport
5. Kiến trúc đề xuất
6. Roadmap và benchmark bắt buộc
7. Security và vận hành
8. Nguồn

## Phương pháp nghiên cứu

- 14 nguồn chính thức/source repository, tài liệu từ 2021-2026.
- Trọng số cao nhất: scrcpy source/docs, W3C, IETF RFC, gRPC docs và Android Open Source Project.
- Từ khóa: `scrcpy low latency raw stream`, `WebRTC congestion control`, `RTP deep queue`, `gRPC flow control`, `QUIC head-of-line`, `Android device WebRTC streaming`, `SFU simulcast`.
- Boundary: không chọn vendor hoặc thư viện gateway cụ thể khi chưa có benchmark tương thích với H.264 output và Python agent hiện tại.

## 1. Kết luận

Hướng đúng không phải bỏ scrcpy. Hướng đúng là:

1. Giữ `scrcpy-server` sát thiết bị để capture và hardware encode H.264.
2. Giữ control/result trên gRPC reliable, độc lập với media.
3. Chuyển video WAN/browser sang RTP/WebRTC, không decode/re-encode tại agent.
4. Mỗi phone là một RTP stream/SSRC riêng; gom 8-16 phone thành một media shard để giới hạn blast radius.
5. Dùng SFU khi một phone có nhiều viewer hoặc cần định tuyến qua Internet.
6. Grid hàng trăm phone dùng quality ladder hoặc mosaic; phone được chọn dùng stream riêng full-rate.
7. Đo glass-to-glass và input-to-photon trước khi tuyên bố đạt latency mục tiêu.

Phase 1 vừa triển khai — lane video lossy riêng, queue nông, result reliable và bỏ hard cap 48 — khớp trực tiếp với khuyến nghị của WebRTC: media không nên có deep queue; frame trung gian nên bị bỏ khi congestion, trong khi dữ liệu reliable vẫn cần queue.

## 2. Hiện trạng của device-farm

Pipeline hiện tại:

```text
Android
  scrcpy-server 3.3.4
    H.264 hardware encoder
    max-bframes=0, IDR interval=1
          |
          | ADB forwarded sockets
          v
agent-boot Python
  Annex-B -> AVCC
  custom frame -> protobuf
          |
          | one bidirectional gRPC RPC per agent
          v
device_farm
  repack frame -> WebSocket
          |
          v
Browser
  WebCodecs VideoDecoder worker -> Canvas
```

Điểm đang làm tốt:

- Không decode/re-encode trên server.
- H.264 baseline, không B-frame, có IDR recovery.
- Audio tắt.
- Frontend đã có decoder worker và backpressure diagnostics.
- Viewer/profile lifecycle đã coalesce và có downgrade grace.
- Phase 1 đã tách reliable result khỏi lossy video.

Điểm còn giới hạn:

- Tất cả phone trong một agent vẫn là message của **một gRPC RPC**.
- gRPC/HTTP2 là reliable transport; mất một TCP packet có thể giữ các byte media phía sau.
- Có nhiều lần đóng gói/chuyển đổi trước browser.
- Không có congestion feedback từ browser về encoder/source profile.
- Chưa có timestamp xuyên suốt để đo capture-to-render.
- Browser phải duy trì nhiều WebCodecs decoder riêng nếu thật sự hiển thị mọi phone.

Profile hiện tại trong `device_farm/config.yaml` là 8 fps, 360 px, 400 kbps. Băng thông video payload xấp xỉ:

| Số phone | 400 kbps/phone | 800 kbps/phone |
|---:|---:|---:|
| 30 | 12 Mbps | 24 Mbps |
| 120 | 48 Mbps | 96 Mbps |
| 500 | 200 Mbps | 400 Mbps |

Các số này chưa gồm RTP/gRPC/TLS/IP overhead và retransmission.

## 3. Mọi người đang tối ưu theo pattern nào

### 3.1 Capture và encode ngay trên nguồn

scrcpy chạy server trên Android, tạo raw H.264 và truyền video/control qua socket riêng. Client chính thức hiển thị frame ngay, mặc định không buffer để giảm latency. scrcpy công bố latency local khoảng 35-70 ms và khuyên giảm resolution để tăng performance.

Kết luận cho hệ thống này:

- Tiếp tục dùng scrcpy.
- Ưu tiên hardware encoder theo device capability.
- H.264 vẫn là lựa chọn an toàn nhất cho WebRTC/WebCodecs/browser.
- Giữ `max-bframes=0`; không thêm display buffer.
- Giảm resolution trước khi giảm FPS quá sâu nếu encoder/device quá tải.

Không phải mọi delay đều sửa được bằng transport. Maintainer scrcpy xác nhận một số OEM encoder tự buffer hoặc encode không kịp real time; lúc đó phải chọn encoder khác, giảm size/FPS/bitrate, hoặc đánh dấu device capability.

### 3.2 Media lossy, control reliable

RFC 8835 nêu rõ deep send queues thường không phù hợp với media real-time; nên bỏ intermediate frames không còn hữu ích. Reliable data thì queue vẫn có giá trị.

Pattern production:

```text
media:    bounded + lossy + latest-frame bias + keyframe recovery
control:  ordered + reliable + timeout + idempotency
results:  reliable + bounded wait + correlation id
```

Phase 1 hiện tại đã đi đúng pattern này. Không nên gộp video trở lại cùng lane với command/result.

### 3.3 RTP/WebRTC cho media Internet

WebRTC dùng SRTP/RTCP, congestion control, NACK/PLI và jitter-buffer control. Browser có native media pipeline thay vì ứng dụng tự xây toàn bộ transport, recovery và scheduling trên WebSocket.

Google Cuttlefish dùng WebRTC để điều khiển Android virtual devices trong browser. Mẫu Android Emulator container của Google cũng dùng gRPC endpoint cho control và WebRTC bridge cho video. Đây gần như chính xác là seam phù hợp với device-farm:

```text
gRPC = control plane
WebRTC = media plane
```

Khi browser báo PLI, gateway map nó thành scrcpy IDR/reset-video request. Không retransmit frame đã quá cũ chỉ để đạt “đủ dữ liệu”.

### 3.4 SFU cho fan-out và định tuyến

Nếu một phone có nhiều viewer, gửi lại cùng upstream cho từng browser làm tăng băng thông tại agent. SFU nhận một upstream và forward theo subscriber. SFU cũng giải quyết NAT/TURN routing và cho phép chỉ forward track cần thiết.

Không cần SFU ngay nếu mỗi phone chỉ có một viewer cùng LAN. Với dashboard cloud, nhiều user hoặc multi-tenant, SFU là hướng production hợp lý.

### 3.5 Quality ladder thay vì một profile cho mọi surface

“Tất cả phone live” không đồng nghĩa tất cả phone phải là 30 fps/720p:

| Surface | Profile khởi điểm để benchmark |
|---|---|
| Phone đang điều khiển | 15-30 fps, 540-720 px, 0.8-2 Mbps |
| Tile đang nhìn thấy | 5-8 fps, 360 px, 250-500 kbps |
| Tile ngoài viewport nhưng cần fresh | 1-2 fps hoặc latest-frame refresh |
| Phone có nhiều viewer | Một upstream, SFU fan-out |

Profile lifecycle hiện tại đã có nền tảng để nâng/hạ profile. Không nên đặt tổng cap nhỏ kiểu “chỉ 4 phone live”.

### 3.6 Mosaic cho monitoring wall rất lớn

Một browser thường không phải nơi thích hợp để decode hàng trăm H.264 track full-rate. Phương án dùng trong monitoring wall:

- Edge/SFU tạo mosaic 4x4 hoặc 8x8 thành một vài stream.
- Click một tile thì mở individual low-latency stream của phone đó.
- Tất cả phone vẫn quan sát được; browser chỉ giữ vài decoder.

Đổi lại, mosaic cần GPU compose/re-encode và thêm latency. Chỉ dùng cho grid; không dùng cho control view.

## 4. So sánh transport

| Phương án | Latency khi loss/jitter | Congestion/recovery | Browser | Độ phức tạp | Kết luận |
|---|---|---|---|---|---|
| Một gRPC RPC/agent | Kém hơn vì reliable TCP và shared RPC | App tự làm | WebSocket + WebCodecs | Thấp | Giữ tạm sau Phase 1 |
| Nhiều gRPC media shard | Tốt hơn ở app flow control; TCP HOL vẫn còn | App tự làm | WebSocket + WebCodecs | Trung bình | Bước đệm, không phải đích cuối |
| RTP/WebRTC trực tiếp | Tốt | RTCP, congestion control, PLI/NACK | Native | Cao | Tốt cho LAN/1 viewer |
| RTP/WebRTC + SFU | Tốt, thêm một network hop | Native + routing/fan-out | Native | Cao | Khuyến nghị production |
| WebTransport/QUIC | Không cross-stream HOL; có datagram | Phải tự xây media semantics | Khá mới | Rất cao | Chưa chọn cho Phase 2 |
| JPEG/minicap/WebSocket | Dễ nhưng bandwidth/quality kém | Đơn giản | Dễ | Thấp | Chỉ fallback/snapshot |

Lưu ý:

- Thêm nhiều gRPC RPC trên **cùng HTTP/2 channel** không loại bỏ TCP packet-loss HOL. Nếu thử sharding gRPC, cần so sánh cả multiple RPC/same channel và multiple channel/shard.
- gRPC docs nói một write hoàn tất không có nghĩa message đã ra network; framework có thể buffer theo flow control.
- QUIC tránh head-of-line giữa stream, nhưng WebTransport datagram có kích thước hữu hiệu giới hạn; ứng dụng phải tự packetize, fragment, recover và điều khiển congestion. WebRTC trưởng thành hơn cho video.

## 5. Kiến trúc đề xuất

```text
                         +-----------------------+
Android phone ----------| scrcpy-server         |
 H.264 + PTS             | capture/encode/control|
                         +-----------+-----------+
                                     |
                           ADB video/control sockets
                                     |
                         +-----------v-----------+
agent-boot               | Scrcpy session mgr    |
                         | capability/profile    |
                         | IDR mapping            |
                         +------+----------+------+
                                |          |
                  reliable gRPC |          | Annex-B H.264
             command/result/U2  |          v
                                |    +-----+----------------+
                                |    | Native RTP gateway   |
                                |    | packetize only       |
                                |    | no decode/re-encode  |
                                |    +-----+----------------+
                                |          |
                                |       WebRTC shards
                                |       8-16 phones/shard
                                |          |
                         +------v----------v------+
cloud                    | API/control + SFU      |
                         | auth/tenant routing    |
                         +------------+-----------+
                                      |
                              WebRTC + WebSocket API
                                      |
                         +------------v-----------+
browser                  | native video tracks    |
                         | selected phone full    |
                         | grid ladder/mosaic     |
                         +------------------------+
```

### Những gì không nên làm

- Không decode H.264 trong Python rồi encode lại.
- Không tăng gRPC/HTTP2 buffer để “hết drop”; buffer lớn thường biến loss thành latency.
- Không bật H.265 đại trà trước khi kiểm tra browser/WebRTC/OEM matrix.
- Không chạy một PeerConnection cho từng phone mà chưa benchmark browser/agent.
- Không upgrade scrcpy server riêng lẻ. Protocol scrcpy là internal và yêu cầu client/server cùng version.

### Scrcpy 4.0

Source chính thức hiện đã mô tả protocol 4.0 và release mới có tối ưu MediaCodec priority/latency. Tuy nhiên protocol internal có thể thay đổi, đồng thời pipeline hiện parse protocol 3.3.4 trực tiếp.

Khuyến nghị:

1. Không upgrade fleet trực tiếp.
2. Tạo canary 3-5 model/API level.
3. Port parser và control protocol theo đúng 4.0.
4. So sánh startup, first-frame, encoder crash và latency.
5. Chỉ rollout theo device capability/allowlist.

## 6. Roadmap và benchmark bắt buộc

### Phase 1.5 — đo đúng pipeline hiện tại

1. Thêm timestamp:
   - scrcpy PTS/capture;
   - agent receive;
   - agent enqueue/dequeue;
   - backend receive/fan-out;
   - browser packet receive/decode/render.
2. Log riêng:
   - queue age, không chỉ queue size;
   - P-frame drop, key/config eviction;
   - IDR request-to-first-keyframe;
   - command RTT;
   - encoder FPS thực tế.
3. Chạy 30/60/120 phone với cùng scripted animation.
4. Test RTT 20/50/100 ms, jitter và packet loss 0/1/3/5%.

SLO đề xuất để bắt đầu:

| Metric | Control view | Grid |
|---|---:|---:|
| Glass-to-glass p50 | <120 ms LAN, <180 ms cloud | <350 ms |
| Glass-to-glass p95 | <200-250 ms | <500 ms |
| Input-to-photon p95 | <250 ms | N/A |
| IDR recovery p95 | <500 ms | <1 s |
| Command/result loss | 0 | 0 |

Đây là target, không phải kết quả đã đo.

### Phase 2A — WebRTC pilot

1. Native RTP gateway sidecar bên cạnh agent-boot.
2. Packetize H.264 trực tiếp; giữ original PTS.
3. gRPC control vẫn giữ nguyên.
4. 8-16 phone/media shard.
5. PLI -> scrcpy IDR.
6. Pilot 10-20 phone, một browser, không SFU trước.

**Go/no-go:** WebRTC phải giảm p95 latency hoặc recovery rõ rệt mà CPU agent không tăng do re-encode.

### Phase 2B — SFU và all-live dashboard

1. Một upstream/phone vào SFU.
2. Chỉ subscribe visible tracks ở profile tile.
3. Selected track nâng profile.
4. Benchmark individual tracks so với mosaic.
5. TURN HA, regional routing và per-tenant authorization.

## 7. Security và vận hành

- WebRTC bắt buộc DTLS-SRTP; vẫn cần authz gắn `org_id + agent_id + serial`.
- TURN credential phải ngắn hạn, scoped và rotate được.
- Không expose ADB ra Internet.
- Control gRPC giữ TLS/mTLS hoặc enrollment identity hiện tại.
- SFU phải kiểm tra quyền subscribe/publish từng track.
- Rate-limit PLI/IDR để tránh encoder-reset storm.
- Canary scrcpy upgrade theo OEM/API.
- Cảnh báo khi:
  - queue age vượt SLO;
  - browser decode drop tăng;
  - encoder FPS thấp hơn requested;
  - aggregate bitrate sát link capacity;
  - TURN usage hoặc relay RTT tăng bất thường.

## 8. Nguồn

### Chính thức

- [scrcpy developer protocol](https://github.com/Genymobile/scrcpy/blob/master/doc/develop.md)
- [scrcpy video options](https://github.com/Genymobile/scrcpy/blob/master/doc/video.md)
- [scrcpy repository and latency claim](https://github.com/Genymobile/scrcpy)
- [scrcpy releases](https://github.com/Genymobile/scrcpy/releases/)
- [W3C WebRTC Recommendation](https://www.w3.org/TR/webrtc/)
- [RFC 8834: Media Transport and RTP in WebRTC](https://www.rfc-editor.org/rfc/rfc8834.html)
- [RFC 8835: WebRTC Transports](https://www.rfc-editor.org/rfc/rfc8835.html)
- [gRPC flow control](https://grpc.io/docs/guides/flow-control/)
- [gRPC performance best practices](https://grpc.io/docs/guides/performance/)
- [W3C WebTransport](https://www.w3.org/TR/webtransport/)
- [RFC 9000: QUIC](https://www.rfc-editor.org/rfc/rfc9000.html)
- [Android Cuttlefish WebRTC streaming](https://source.android.com/docs/devices/cuttlefish/webrtc)
- [Google Android Emulator container WebRTC bridge](https://github.com/google/android-emulator-container-scripts)
- [LiveKit SFU media features](https://docs.livekit.io/transport/media/advanced/)

### Evidence về OEM encoder

- [scrcpy issue: maintainer explains device encoder buffering/real-time limits](https://github.com/Genymobile/scrcpy/issues/6238)

## Câu hỏi chưa đóng

1. Mục tiêu “all live” là bao nhiêu phone trên một browser: 30, 120 hay 500?
2. Một phone trung bình có bao nhiêu viewer đồng thời?
3. Agent và browser chủ yếu cùng LAN hay qua Internet/TURN?
4. Có chấp nhận mosaic cho grid và individual stream khi click không?
5. SLO chính là glass-to-glass hay input-to-photon?
