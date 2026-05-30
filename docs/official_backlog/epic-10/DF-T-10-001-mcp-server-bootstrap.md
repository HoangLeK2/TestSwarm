# DF-T-10-001 — Bootstrap MCP server stdio (Preview)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-10-001 |
| **Title** | Bootstrap MCP server stdio (Preview) — entrypoint giao thức cho AI agent |
| **Type** | `type:feature` |
| **Epic** | DF-E-10 — MCP Agent Tools (Preview) |
| **Module** | DF-MOD-10 — MCP Agent Tools |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `status:preview`, `module:mcp`, `layer:backend`, `layer:infra`, `type:feature`, `persona:ai-ops`, `risk:auth` |
| **Truy vết — FR refs** | FR-10-01, FR-10-02 |
| **Truy vết — UC refs** | UC-10-01, UC-10-03 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Module MCP Agent Tools cần một entrypoint để AI agent (Claude, GPT, Gemini, ...) kết nối, đọc danh sách tool, và bắt đầu gọi tool. Hiện tại Device Farm chưa có MCP server — agent muốn vận hành thiết bị phải tự gọi REST API, mất kiểm soát phạm vi và mất audit. Ticket này là **foundation block** của toàn bộ DF-E-10: không có MCP server thì các ticket tool sau (DF-T-10-002 → DF-T-10-014) không có chỗ chạy.

Persona hưởng lợi đầu tiên là **AI Operations Supervisor (Preview)** — họ là người cấu hình agent registry MCP và cần một endpoint stdio Device Farm phát hành để đăng ký vào Claude Desktop hoặc agent runtime tương đương. Vị trí trong luồng nghiệp vụ: bước đầu tiên trong sơ đồ "Vòng đời phiên AI agent qua MCP" (module 10 mục 5.1) — agent gọi `tools/list` ngay sau khi kết nối.

> **Cảnh báo Preview:** Đây là phần mở rộng đang được nghiên cứu, **KHÔNG thuộc năng lực cốt lõi** của Device Farm. Contract MCP server có thể bị thu hồi hoặc thay đổi giữa các release. Mọi triển khai dựa vào MCP server đều phải hiểu rõ trạng thái Preview và không được dùng cho workflow production-grade.

Ưu tiên P1 vì là contract foundation cho cả Epic; tuy nhiên SLA và cam kết release vẫn theo nhóm Preview của lộ trình (`99-roadmap-and-faq.md §4.3`).

## 3. Câu chuyện người dùng

> **Là** AI Operations Supervisor (Preview)
> **Tôi muốn** đăng ký Device Farm MCP server vào AI agent runtime (Claude Desktop, agent client tương đương) qua stdio
> **Để** agent có thể đọc tool list `df_*` và bắt đầu thao tác fleet Device Farm theo schema chuẩn thay vì gọi REST API ad-hoc.

Persona phụ: Automation Builder muốn agent dùng MCP đọc tool và preview scenario; Platform Engineer là người cấu hình hạ tầng vận hành MCP server.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp một binary / module Python có thể chạy độc lập với HTTP API, giao tiếp qua stdio theo spec MCP — trace FR-10-01.
- Hệ thống PHẢI expose `tools/list` trả về danh sách `df_*` tool đã đăng ký, mỗi tool có schema input/output đầy đủ — trace FR-10-01, FR-10-02.
- Hệ thống PHẢI từ chối kết nối stdio nếu MCP server chưa được cấp token hoặc cấu hình env thiếu — trace FR-10-04.
- Hệ thống PHẢI ghi log khởi động (thời điểm start, version, số tool đăng ký, profile env) để supervisor truy vết — trace FR-10-09.
- Hệ thống PHẢI gắn header / metadata "Preview" vào response `tools/list` để agent client hiển thị được trạng thái Preview cho người dùng — trace FR-10-01 + DoD Epic.
- Hệ thống NÊN có graceful shutdown — khi nhận SIGTERM thì đóng các session đang mở qua `df_end_session` trước khi exit — trace FR-10-07.
- Hệ thống KHÔNG được expose endpoint nội bộ (admin route, debug route) ra ngoài MCP — trace FR-10-01 phần "không expose endpoint nội bộ".

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Khởi động MCP server và đọc tool list thành công**

```
Given Device Farm staging có HTTP API đang chạy ổn định
And env DEVICE_FARM_MCP_TOKEN và/hoặc MCP_AUTH_TOKEN đã được cấu hình
When team chạy binary MCP server stdio
And kết nối agent client gửi yêu cầu tools/list
Then server trả về danh sách df_* tool kèm schema input/output trong < 1 s
And response có metadata "status: preview"
And log khởi động ghi version + số tool + profile env
```

**AC-2: Từ chối khởi động khi thiếu cấu hình token**

```
Given env DEVICE_FARM_MCP_TOKEN và MCP_AUTH_TOKEN đều rỗng
When team chạy binary MCP server stdio
Then server thoát với exit code khác 0 trong < 5 s
And stderr in lỗi rõ "Missing DEVICE_FARM_MCP_TOKEN or MCP_AUTH_TOKEN"
And không có process nào lắng nghe stdio
```

**AC-3: Graceful shutdown khi nhận SIGTERM**

```
Given MCP server đang chạy
And có 1 session agent đang mở qua df_start_session
When team gửi SIGTERM tới process MCP server
Then server gọi df_end_session để release session đang mở
And persist terminal state vào mcp_sessions trước khi exit
And exit code = 0 trong < 10 s
```

**AC-4: Metadata Preview phải xuất hiện trong tools/list response**

```
Given MCP server đang chạy
When agent client gọi tools/list
Then mỗi tool đều có trường "preview: true" trong description
And response cấp server có trường "status: preview"
And tài liệu tool nêu rõ "contract có thể thay đổi"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm định nghĩa schema chi tiết của từng `df_*` tool — thuộc DF-T-10-002.
- KHÔNG bao gồm logic authentication / verify token — thuộc DF-T-10-003.
- KHÔNG bao gồm tool device.list / device.claim cụ thể — thuộc DF-T-10-004, DF-T-10-005.
- KHÔNG bao gồm rate-limit hay quota — thuộc DF-T-10-012.
- KHÔNG bao gồm UI banner Preview — thuộc DF-T-10-014.
- KHÔNG bao gồm hỗ trợ transport SSE hay HTTP MCP — chỉ stdio cho release Preview này.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Scaffold module `mcp_server/` với entrypoint `python -m device_farm.mcp_server`.
- [ ] Implement protocol handler stdio theo spec MCP (read JSON-RPC over stdin, write JSON-RPC over stdout).
- [ ] Implement `tools/list` handler đọc tool registry (placeholder rỗng, sẽ điền ở DF-T-10-002).
- [ ] Implement graceful shutdown hook (signal SIGTERM/SIGINT → close sessions).
- [ ] Validate env config khi start: ít nhất một token phải set.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả format `tools/list` response, bao gồm field `preview` ở server-level và per-tool.
- [ ] Tài liệu cấu hình env (DEVICE_FARM_MCP_TOKEN, MCP_AUTH_TOKEN, DEVICE_FARM_API_URL).

**Infra / DevOps** (`layer:infra`)

- [ ] Dockerfile cho MCP server (stage độc lập với image HTTP API).
- [ ] Helm chart sidecar / standalone deployment cho staging.
- [ ] Healthcheck (process alive + tools/list trả ≥ 1 entry).

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/modules/10-mcp-agent-tools.md` phần "Quick start MCP server".
- [ ] Thêm cảnh báo Preview to vào README of module.
- [ ] Changelog mục "Added MCP server stdio (Preview)".

**Test** (`layer:test`)

- [ ] Unit test cho protocol handler (parse JSON-RPC, dispatch method).
- [ ] Integration test smoke: start server → tools/list → assert response shape.
- [ ] Test SIGTERM graceful shutdown.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-10-001-01 | Positive | Token env đã set, HTTP API up | Start server, gọi tools/list từ agent client mock | Response < 1 s, có ≥ 1 tool, có flag preview |
| TC-DF-T-10-001-02 | Positive | Server đang chạy, 1 session open | Gửi SIGTERM | Session được release, exit code 0 trong < 10 s |
| TC-DF-T-10-001-03 | Negative | Env không có token nào | Start server | Exit code khác 0 trong < 5 s, stderr in lỗi rõ |
| TC-DF-T-10-001-04 | Negative | Server đang chạy, agent gửi method không tồn tại (vd `foo/bar`) | Gọi method | Response error JSON-RPC code -32601 "Method not found", không crash |
| TC-DF-T-10-001-05 | Edge | HTTP API tạm thời down khi server đã start | Agent gọi tools/list | Vẫn trả tool list từ registry static, kèm warning "downstream API unavailable" |
| TC-DF-T-10-001-06 | Edge | 100 lần tools/list liên tục trong 1 giây | Stress mini | Không leak memory, mỗi response < 1 s |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** Không (ticket foundation DF-E-10).

**Chặn:** DF-T-10-002, DF-T-10-003, DF-T-10-004 → DF-T-10-014 (toàn bộ DF-E-10 đứng trên ticket này).

**Phụ thuộc giữa Epic:**

- DF-E-01 (Nền tảng & Bảo mật) — env config, secret loader. Yêu cầu hạ tầng config quản lý token.
- DF-E-02 (Devices & Control Plane) — HTTP API phải sẵn sàng để các tool sau wrap; ở ticket này chưa wrap nhưng test smoke cần HTTP API up.

**Rủi ro:**

- **Drift giao thức MCP:** spec MCP của Anthropic có thể thay đổi → pin version client SDK, audit định kỳ.
- **Lộ tool không được phép qua tools/list:** nếu registry quên flag preview-only → review checklist trong DoD, ô preview metadata bắt buộc.
- **Process zombie khi shutdown không sạch:** test SIGTERM bắt buộc trong CI.
- **Người dùng nhầm Preview là GA:** disclosure Preview ở mọi entry; phối hợp DF-T-10-014 trên dashboard.

**Phụ thuộc bên ngoài:** MCP SDK / protocol spec (Anthropic) — pin phiên bản; Python ≥ 3.11 cho asyncio stdio.

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage ≥ 80% trên file thay đổi.
- [ ] Tất cả test case TC-DF-T-10-001-* được map sang test tự động hoặc đã chạy manual và lưu evidence.
- [ ] Tài liệu kỹ thuật `docs/modules/10-mcp-agent-tools.md` cập nhật.
- [ ] Tài liệu nghiệp vụ `docs/official_docs/modules/10-mcp-agent-tools.md` đã có cảnh báo Preview rõ ràng.
- [ ] Telemetry (log + metric) cho path khởi động và shutdown đã có.
- [ ] Code review có ≥ 1 approve từ owner module MCP.
- [ ] Release notes ghi rõ "Added MCP server stdio (Preview, no GA SLA, contract may change)".
- [ ] **Đã ghi rõ vào tài liệu nghiệp vụ rằng tool còn ở trạng thái Preview, có warning khi dùng từ AI agent bên ngoài.**
- [ ] Đã chạy thử server stdio ≥ 24h liên tục trong staging với smoke test định kỳ.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [10-mcp-agent-tools.md §5.1 Vòng đời phiên + §6 FR-10-01, FR-10-02](../../official_docs/modules/10-mcp-agent-tools.md).
- **Nhóm người dùng:** [02-personas-and-journeys.md §3.5 AI Operations Supervisor (Preview)](../../official_docs/02-personas-and-journeys.md).
- **Lộ trình:** [99-roadmap-and-faq.md §4.3 — nhóm forward-looking](../../official_docs/99-roadmap-and-faq.md).
- **Thuật ngữ:** MCP, MCP server, df_* tool, Activity log.
