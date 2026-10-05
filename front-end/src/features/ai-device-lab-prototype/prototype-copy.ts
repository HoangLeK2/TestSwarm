export type PrototypeLocale = 'en' | 'vi';

export const prototypeCopy = {
  en: {
    prototype:
      'Interactive prototype · simulated data · no device or payment action',
    brand: 'AI Device Lab',
    nav: {
      overview: 'Overview',
      wizard: 'Create campaign',
      readiness: 'Readiness',
      dashboard: 'Dashboard',
      report: 'Report',
      operator: 'Operator',
      states: 'State map'
    },
    landing: {
      eyebrow: 'Traceable Android testing on real devices',
      title: '12 AI testing lanes. 14 service days.',
      description:
        'Submit one Android app, review the scenario, follow every run and receive evidence that keeps retries and failures visible.',
      cta: 'Start campaign',
      secondary: 'Explore the service',
      stateLabel: 'Landing prototype states',
      signedIn: 'Signed in',
      guest: 'Guest',
      ctaError: 'CTA error',
      signedInMessage:
        'Workspace context is available. A campaign draft can be created.',
      guestMessage: 'Sign in before creating a campaign draft.',
      ctaErrorMessage:
        'The draft service did not create a campaign. No payment or reservation was made.',
      retryCta: 'Retry draft creation',
      packageLabel: 'One-time service package',
      price: 'Price awaiting product approval',
      priceNote:
        'The server-priced amount, currency and refund policy will appear before checkout.',
      metrics: [
        ['12', 'logical testing lanes'],
        ['14', 'service days'],
        ['168', 'scheduled slots']
      ],
      disclaimer:
        'AI testing evidence and Google Play participation are tracked separately. The service does not promise Google approval.',
      benefits: [
        'Scenario review before execution',
        'Expected versus observed evidence',
        'Retry history stays visible'
      ]
    },
    wizard: {
      title: 'Create campaign',
      step: 'Step 1 of 4',
      heading: 'App details',
      description:
        'Tell us which permitted Android build to test and what matters most.',
      appName: 'App name',
      packageName: 'Package name',
      goal: 'Test goal',
      defaultAppName: 'Demo App',
      defaultPackageName: 'com.example.demo',
      defaultGoal: 'Login, browse, checkout and error recovery',
      continue: 'Continue to scenario',
      back: 'Back to overview'
    },
    scenario: {
      step: 'Step 2 of 4',
      heading: 'Review AI scenario',
      description:
        'Every action and assertion must be approved before checkout.',
      stateLabel: 'Scenario prototype states',
      generating: 'Show generating state',
      aiError: 'Show AI error state',
      approved: 'Approved preview',
      denied: 'Show denied state',
      stale: 'Show stale approval',
      generatingHeading: 'Generating scenario',
      generatingBody:
        'The generation job is running. You can wait or return without approving a partial result.',
      aiErrorHeading: 'AI scenario generation failed',
      aiErrorBody:
        'No scenario was approved. Edit the goal or retry the generation job.',
      retryGeneration: 'Retry generation',
      staleHeading: 'Approval is stale',
      staleBody:
        'The test goal changed after approval. Review the new revision before checkout.',
      reviewChanges: 'Review changed goal',
      deniedHeading: 'Scenario needs changes',
      deniedReason:
        'Checkout uses a real purchase, which is outside the permitted test policy.',
      notFailure: 'This is not an app test failure.',
      owner: 'Owner: Developer',
      action: 'Edit test goal',
      steps: [
        'Install permitted build',
        'Launch app',
        'Complete login',
        'Verify expected home state'
      ],
      back: 'Back to app details',
      continue: 'Continue to review'
    },
    review: {
      step: 'Step 3 of 4',
      heading: 'Review service package',
      description:
        'Confirm the immutable app, scenario and policy snapshot before checkout.',
      package: '12 lanes · 14 days · 168 scheduled slots',
      app: 'Demo App · com.example.demo · build pending preflight',
      scenario: 'Scenario version 3 · approved prototype',
      price: 'Server price · awaiting product approval',
      policy:
        'Retries do not add planned slots. Readiness failure after payment does not start the service clock.',
      back: 'Back to scenario',
      continue: 'Continue to payment'
    },
    payment: {
      step: 'Step 4 of 4',
      heading: 'Payment verification',
      description:
        'The provider webhook and billing ledger are authoritative. A browser redirect never starts service.',
      pending: 'Pending provider verification',
      paid: 'Paid · readiness still required',
      failed: 'Payment failed · service clock not started',
      showPending: 'Show pending state',
      showPaid: 'Show paid state',
      showFailed: 'Show failed state',
      stateLabel: 'Payment prototype states',
      retry: 'Retry with a new payment intent',
      openReadiness: 'Open readiness',
      back: 'Back to review'
    },
    readiness: {
      eyebrow: 'Campaign readiness',
      heading: '2 items need attention',
      description:
        'The service clock has not started. Resolve every required item, then run a fresh server check.',
      notFailure: 'Blocked does not mean the app failed.',
      start: 'Start service',
      recheck: 'Recheck readiness',
      ready: 'Ready',
      attention: 'Needs attention',
      stateLabel: 'Readiness prototype states',
      showUnknown: 'Unknown',
      showBlocked: 'Blocked',
      showReady: 'Ready',
      showRunning: 'Running',
      showAttention: 'Needs attention',
      unknownHeading: 'Readiness is unknown',
      unknownDescription:
        'Observations are missing or stale. Run fresh server checks before deciding.',
      readyHeading: 'Ready to start',
      readyDescription:
        'All required checks are fresh and authoritative. Starting is still an explicit action.',
      runningHeading: 'Service is running',
      runningDescription:
        'The start command was accepted once. Progress now belongs on the dashboard.',
      attentionHeading: 'Assistance is required',
      attentionDescription:
        'The campaign remains safe while the assigned owner resolves the permitted action.',
      recheckComplete: 'Fresh checks completed · ready to start',
      recheckBlocked:
        'Fresh checks completed · blockers remain assigned. Start stays disabled.',
      recheckUnknown:
        'Fresh observations are still unavailable. Readiness remains Unknown.',
      openDashboard: 'Open dashboard',
      items: [
        [
          'Payment verified',
          'Ready',
          'Billing service',
          'Billing service · fresh verification'
        ],
        [
          'Scenario approved',
          'Ready',
          'Scenario service',
          'Scenario service · approved snapshot'
        ],
        [
          '12 devices reserved',
          'Ready',
          'Reservation service',
          'Reservation service · active holds'
        ],
        [
          'Track access verified',
          'Needs attention',
          'Operator · recheck account evidence',
          'Account evidence · fresh and verified'
        ],
        [
          'Install preflight',
          'Needs attention',
          'Developer · provide permitted build',
          'Build preflight · permitted build passed'
        ]
      ]
    },
    dashboard: {
      eyebrow: 'Demo App · campaign ADL-2401',
      heading: 'Testing stays explainable',
      running: 'Running',
      axes: [
        ['Service progress', '7 / 14 days', '50', 'Calendar and quota source'],
        [
          'App testing quality',
          '120 / 168 scheduled',
          '71',
          '96 executed · 82 evaluated · 68 passed'
        ],
        [
          'Play participation',
          'Unknown',
          '0',
          'No account-specific opt-in evidence'
        ]
      ],
      lanesTitle: 'Logical lanes',
      lanesDescription:
        'A replacement device keeps the same lane label and never overwrites earlier attempts.',
      openLane: 'Open Tester 03 details',
      lanes: [
        ['Tester 01', 'Pixel 8', 'Passed'],
        ['Tester 02', 'Galaxy S23', 'Passed'],
        ['Tester 03', 'Pixel 7a', 'Blocked'],
        ['Tester 04', 'Xiaomi 13', 'Running']
      ]
    },
    lane: {
      back: 'Back to dashboard',
      heading: 'Tester 03 · blocked run',
      subtitle:
        'Logical lane 03 · device changed once · account continuity unknown',
      status: 'Blocked · permitted assistance required',
      reason:
        'OTP is required. Automation stopped without attempting a bypass.',
      owner:
        'Owner: Developer · complete OTP on the permitted device, then request resume.',
      attempts: 'Attempt history',
      current: 'Attempt 2 · build 43 · current',
      previous: 'Attempt 1 · build 42 · previous',
      currentEvidence: 'Screenshot, step log and assertion available',
      expiredEvidence: 'Evidence unavailable · retention expired',
      retryNote:
        'A step retry belongs to its run attempt. Retrying never creates an extra scheduled slot.',
      runRetry: 'Preview run retry',
      stepRetry: 'Preview step retry',
      runRetryConsequence:
        'A new run attempt uses build 43 and preserves attempts 1 and 2. Scheduled remains 168.',
      stepRetryConsequence:
        'A new step attempt stays inside run attempt 2 and preserves expected versus observed evidence.'
    },
    report: {
      eyebrow: 'Campaign report · version 3',
      heading: 'Evidence that stays actionable',
      state: 'Frozen source snapshot',
      stateLabel: 'Report prototype states',
      generating: 'Generating',
      failed: 'Failed',
      frozen: 'Frozen',
      corrected: 'Corrected',
      generatingMessage:
        'The report job is building an immutable snapshot at the recorded cutoff.',
      failedMessage:
        'Report generation failed. Retry from the same cutoff without changing source results.',
      frozenMessage: 'The source snapshot and checksum are immutable.',
      correctedMessage:
        'The corrected version links to the frozen original and explains each correction.',
      retry: 'Retry from same cutoff',
      correction:
        'Corrected version references version 2; original checksum remains available.',
      metrics: [
        ['168', 'Scheduled'],
        ['154', 'Executed'],
        ['142', 'Evaluated'],
        ['118', 'Passed'],
        ['24', 'Failed']
      ],
      issues: '7 confirmed issues · 5 fixed · 2 still failing',
      missing: 'Missing evidence remains explicit',
      retention: 'Private download · 30-day access window in this prototype',
      download: 'Download prototype PDF'
    },
    operator: {
      eyebrow: 'Operator workspace',
      heading: 'Safe fleet actions with visible consequences',
      replace: 'Replace device',
      cancel: 'Cancel campaign',
      extend: 'Preview extension',
      quarantine: 'Quarantine device',
      replaceConsequence:
        'Tester 03 keeps its lane identity. Earlier attempts and artifacts remain unchanged.',
      cancelConsequence:
        'Future jobs stop; active work drains before reservation release and hygiene verification.',
      extendConsequence:
        'An extension creates a new consent, billing and quota delta. The frozen report remains unchanged.',
      quarantineConsequence:
        'The device becomes ineligible for reservation until an independently verified clean result.',
      noAction:
        'Select an action to inspect its audited consequence. This prototype does not dispatch a command.'
    },
    states: {
      eyebrow: 'Production interaction contract',
      heading: 'Every state has an owner, source and next action',
      description:
        'This map lets frontend and API teams add real integrations without changing the meaning of blocked, failed, paid or verified states.',
      role: 'Visible to',
      source: 'Server source',
      action: 'Primary action',
      secondaryAction: 'Secondary action',
      loadingCopy: 'Loading copy',
      errorCopy: 'Error copy',
      preview: 'Open interactive state',
      previewHeading: 'Interactive state fixture',
      normal: 'Default',
      loading: 'Loading',
      error: 'Error'
    }
  },
  vi: {
    prototype:
      'Prototype tương tác · dữ liệu mô phỏng · không tác động thiết bị hay thanh toán',
    brand: 'AI Device Lab',
    nav: {
      overview: 'Tổng quan',
      wizard: 'Tạo campaign',
      readiness: 'Sẵn sàng',
      dashboard: 'Dashboard',
      report: 'Báo cáo',
      operator: 'Vận hành',
      states: 'Bản đồ trạng thái'
    },
    landing: {
      eyebrow: 'Kiểm thử Android có thể truy vết trên thiết bị thật',
      title: '12 lane kiểm thử AI. 14 ngày dịch vụ.',
      description:
        'Gửi một app Android, duyệt kịch bản, theo dõi từng lần chạy và nhận evidence giữ nguyên lịch sử retry lẫn lỗi.',
      cta: 'Bắt đầu campaign',
      secondary: 'Khám phá dịch vụ',
      stateLabel: 'Các trạng thái prototype của landing',
      signedIn: 'Đã đăng nhập',
      guest: 'Khách',
      ctaError: 'CTA lỗi',
      signedInMessage: 'Đã có workspace context. Có thể tạo campaign draft.',
      guestMessage: 'Đăng nhập trước khi tạo campaign draft.',
      ctaErrorMessage:
        'Dịch vụ draft chưa tạo campaign. Chưa có thanh toán hay reservation nào.',
      retryCta: 'Thử tạo draft lại',
      packageLabel: 'Gói dịch vụ thanh toán một lần',
      price: 'Giá đang chờ product phê duyệt',
      priceNote:
        'Số tiền, loại tiền và chính sách hoàn tiền từ server sẽ hiển thị trước checkout.',
      metrics: [
        ['12', 'lane kiểm thử logic'],
        ['14', 'ngày dịch vụ'],
        ['168', 'slot đã lên lịch']
      ],
      disclaimer:
        'Evidence kiểm thử AI và trạng thái tham gia Google Play được theo dõi riêng. Dịch vụ không cam kết Google phê duyệt.',
      benefits: [
        'Duyệt kịch bản trước khi chạy',
        'Evidence expected và observed',
        'Luôn giữ lịch sử retry'
      ]
    },
    wizard: {
      title: 'Tạo campaign',
      step: 'Bước 1 / 4',
      heading: 'Thông tin app',
      description:
        'Cho biết Android build được phép kiểm thử và mục tiêu quan trọng nhất.',
      appName: 'Tên app',
      packageName: 'Package name',
      goal: 'Mục tiêu kiểm thử',
      defaultAppName: 'Ứng dụng demo',
      defaultPackageName: 'com.example.demo',
      defaultGoal: 'Đăng nhập, duyệt nội dung, checkout và phục hồi lỗi',
      continue: 'Tiếp tục tới kịch bản',
      back: 'Quay lại tổng quan'
    },
    scenario: {
      step: 'Bước 2 / 4',
      heading: 'Duyệt kịch bản AI',
      description: 'Mọi thao tác và assertion phải được duyệt trước checkout.',
      stateLabel: 'Các trạng thái prototype của kịch bản',
      generating: 'Xem trạng thái đang tạo',
      aiError: 'Xem lỗi AI',
      approved: 'Xem trạng thái đã duyệt',
      denied: 'Xem trạng thái bị từ chối',
      stale: 'Xem phê duyệt đã cũ',
      generatingHeading: 'Đang tạo kịch bản',
      generatingBody:
        'Job tạo kịch bản đang chạy. Có thể chờ hoặc quay lại mà không duyệt kết quả chưa hoàn chỉnh.',
      aiErrorHeading: 'Tạo kịch bản AI thất bại',
      aiErrorBody:
        'Chưa có kịch bản nào được duyệt. Sửa mục tiêu hoặc thử lại job tạo kịch bản.',
      retryGeneration: 'Thử tạo lại',
      staleHeading: 'Phê duyệt đã cũ',
      staleBody:
        'Mục tiêu kiểm thử đã thay đổi sau khi duyệt. Cần duyệt revision mới trước checkout.',
      reviewChanges: 'Duyệt mục tiêu đã đổi',
      deniedHeading: 'Kịch bản cần chỉnh sửa',
      deniedReason:
        'Checkout thực hiện mua hàng thật, nằm ngoài policy kiểm thử được phép.',
      notFailure: 'Đây không phải lỗi kiểm thử của app.',
      owner: 'Người xử lý: Developer',
      action: 'Sửa mục tiêu kiểm thử',
      steps: [
        'Cài build được phép',
        'Mở ứng dụng',
        'Hoàn tất đăng nhập',
        'Xác minh trạng thái home mong đợi'
      ],
      back: 'Quay lại thông tin app',
      continue: 'Tiếp tục tới duyệt gói'
    },
    review: {
      step: 'Bước 3 / 4',
      heading: 'Duyệt gói dịch vụ',
      description:
        'Xác nhận snapshot app, kịch bản và policy bất biến trước checkout.',
      package: '12 lane · 14 ngày · 168 scheduled slot',
      app: 'Demo App · com.example.demo · build chờ preflight',
      scenario: 'Kịch bản phiên bản 3 · prototype đã duyệt',
      price: 'Giá từ server · chờ product phê duyệt',
      policy:
        'Retry không tăng planned slot. Readiness lỗi sau thanh toán không bắt đầu đồng hồ dịch vụ.',
      back: 'Quay lại kịch bản',
      continue: 'Tiếp tục tới thanh toán'
    },
    payment: {
      step: 'Bước 4 / 4',
      heading: 'Xác minh thanh toán',
      description:
        'Webhook provider và billing ledger là nguồn sự thật. Browser redirect không bao giờ bắt đầu dịch vụ.',
      pending: 'Chờ provider xác minh',
      paid: 'Đã thanh toán · vẫn cần readiness',
      failed: 'Thanh toán thất bại · đồng hồ dịch vụ chưa bắt đầu',
      showPending: 'Xem trạng thái chờ',
      showPaid: 'Xem trạng thái đã thanh toán',
      showFailed: 'Xem trạng thái thất bại',
      stateLabel: 'Các trạng thái prototype của thanh toán',
      retry: 'Thử lại với payment intent mới',
      openReadiness: 'Mở readiness',
      back: 'Quay lại duyệt gói'
    },
    readiness: {
      eyebrow: 'Mức sẵn sàng của campaign',
      heading: '2 mục cần xử lý',
      description:
        'Đồng hồ dịch vụ chưa bắt đầu. Xử lý mọi mục bắt buộc rồi chạy lại kiểm tra phía server.',
      notFailure: 'Bị chặn không có nghĩa app kiểm thử thất bại.',
      start: 'Bắt đầu dịch vụ',
      recheck: 'Kiểm tra lại',
      ready: 'Sẵn sàng',
      attention: 'Cần xử lý',
      stateLabel: 'Các trạng thái prototype của readiness',
      showUnknown: 'Chưa xác định',
      showBlocked: 'Bị chặn',
      showReady: 'Sẵn sàng',
      showRunning: 'Đang chạy',
      showAttention: 'Cần xử lý',
      unknownHeading: 'Readiness chưa xác định',
      unknownDescription:
        'Observation đang thiếu hoặc đã cũ. Chạy kiểm tra server mới trước khi quyết định.',
      readyHeading: 'Sẵn sàng bắt đầu',
      readyDescription:
        'Mọi kiểm tra bắt buộc đều mới và có thẩm quyền. Bắt đầu vẫn là hành động tường minh.',
      runningHeading: 'Dịch vụ đang chạy',
      runningDescription:
        'Lệnh bắt đầu đã được chấp nhận đúng một lần. Tiến độ tiếp theo nằm trên dashboard.',
      attentionHeading: 'Cần hỗ trợ',
      attentionDescription:
        'Campaign vẫn an toàn trong lúc owner được giao xử lý hành động được phép.',
      recheckComplete: 'Đã kiểm tra mới · sẵn sàng bắt đầu',
      recheckBlocked:
        'Đã kiểm tra mới · blocker vẫn được giao xử lý. Nút bắt đầu tiếp tục bị khoá.',
      recheckUnknown:
        'Observation mới vẫn chưa có. Readiness tiếp tục ở trạng thái Chưa xác định.',
      openDashboard: 'Mở dashboard',
      items: [
        [
          'Thanh toán đã xác minh',
          'Sẵn sàng',
          'Dịch vụ billing',
          'Dịch vụ billing · xác minh mới'
        ],
        [
          'Kịch bản đã duyệt',
          'Sẵn sàng',
          'Dịch vụ scenario',
          'Dịch vụ scenario · snapshot đã duyệt'
        ],
        [
          'Đã giữ 12 thiết bị',
          'Sẵn sàng',
          'Dịch vụ reservation',
          'Dịch vụ reservation · lượt giữ đang hiệu lực'
        ],
        [
          'Đã xác minh quyền track',
          'Cần xử lý',
          'Operator · kiểm tra lại evidence tài khoản',
          'Evidence tài khoản · mới và đã xác minh'
        ],
        [
          'Kiểm tra cài đặt',
          'Cần xử lý',
          'Developer · cung cấp build được phép',
          'Kiểm tra build · build được phép đã đạt'
        ]
      ]
    },
    dashboard: {
      eyebrow: 'Demo App · campaign ADL-2401',
      heading: 'Tiến độ có thể giải thích',
      running: 'Đang chạy',
      axes: [
        ['Tiến độ dịch vụ', '7 / 14 ngày', '50', 'Nguồn lịch và quota'],
        [
          'Chất lượng kiểm thử app',
          '120 / 168 đã lên lịch',
          '71',
          '96 đã chạy · 82 đã đánh giá · 68 đạt'
        ],
        [
          'Tham gia Google Play',
          'Chưa xác định',
          '0',
          'Chưa có evidence opt-in theo từng tài khoản'
        ]
      ],
      lanesTitle: 'Lane logic',
      lanesDescription:
        'Thay thiết bị vẫn giữ nguyên nhãn lane và không ghi đè attempt trước đó.',
      openLane: 'Mở chi tiết Tester 03',
      lanes: [
        ['Tester 01', 'Pixel 8', 'Đạt'],
        ['Tester 02', 'Galaxy S23', 'Đạt'],
        ['Tester 03', 'Pixel 7a', 'Bị chặn'],
        ['Tester 04', 'Xiaomi 13', 'Đang chạy']
      ]
    },
    lane: {
      back: 'Quay lại dashboard',
      heading: 'Tester 03 · run bị chặn',
      subtitle:
        'Lane logic 03 · đã thay thiết bị một lần · continuity tài khoản chưa xác định',
      status: 'Bị chặn · cần hỗ trợ được phép',
      reason:
        'Cần OTP. Automation đã dừng mà không thử vượt qua bước xác minh.',
      owner:
        'Người xử lý: Developer · hoàn thành OTP trên thiết bị được phép rồi yêu cầu tiếp tục.',
      attempts: 'Lịch sử attempt',
      current: 'Attempt 2 · build 43 · hiện tại',
      previous: 'Attempt 1 · build 42 · trước đó',
      currentEvidence: 'Có screenshot, step log và assertion',
      expiredEvidence: 'Không còn evidence · đã hết thời hạn lưu',
      retryNote:
        'Step retry thuộc run attempt. Retry không tạo thêm scheduled slot.',
      runRetry: 'Xem trước run retry',
      stepRetry: 'Xem trước step retry',
      runRetryConsequence:
        'Run attempt mới dùng build 43 và giữ nguyên attempt 1, 2. Scheduled vẫn là 168.',
      stepRetryConsequence:
        'Step attempt mới nằm trong run attempt 2 và giữ evidence expected so với observed.'
    },
    report: {
      eyebrow: 'Báo cáo campaign · phiên bản 3',
      heading: 'Evidence có thể hành động',
      state: 'Snapshot nguồn đã đóng băng',
      stateLabel: 'Các trạng thái prototype của báo cáo',
      generating: 'Đang tạo',
      failed: 'Thất bại',
      frozen: 'Đã đóng băng',
      corrected: 'Đã sửa',
      generatingMessage:
        'Job báo cáo đang tạo snapshot bất biến tại cutoff đã ghi nhận.',
      failedMessage:
        'Tạo báo cáo thất bại. Thử lại từ cùng cutoff mà không đổi kết quả nguồn.',
      frozenMessage: 'Snapshot nguồn và checksum là bất biến.',
      correctedMessage:
        'Phiên bản đã sửa liên kết với bản gốc đóng băng và giải thích từng correction.',
      retry: 'Thử lại từ cùng cutoff',
      correction:
        'Bản sửa tham chiếu phiên bản 2; checksum gốc vẫn còn truy cập được.',
      metrics: [
        ['168', 'Đã lên lịch'],
        ['154', 'Đã chạy'],
        ['142', 'Đã đánh giá'],
        ['118', 'Đạt'],
        ['24', 'Không đạt']
      ],
      issues: '7 lỗi đã xác nhận · 5 đã sửa · 2 vẫn còn lỗi',
      missing: 'Evidence thiếu luôn được ghi rõ',
      retention: 'Download riêng tư · cửa sổ truy cập 30 ngày trong prototype',
      download: 'Tải PDF prototype'
    },
    operator: {
      eyebrow: 'Không gian vận hành',
      heading: 'Thao tác fleet an toàn với hệ quả rõ ràng',
      replace: 'Thay thiết bị',
      cancel: 'Huỷ campaign',
      extend: 'Xem trước gia hạn',
      quarantine: 'Cách ly thiết bị',
      replaceConsequence:
        'Tester 03 giữ nguyên lane. Các attempt và artifact trước đó không thay đổi.',
      cancelConsequence:
        'Job tương lai dừng; công việc đang chạy được drain trước khi nhả reservation và xác minh vệ sinh.',
      extendConsequence:
        'Gia hạn tạo consent, billing và quota delta mới. Báo cáo đã đóng băng không thay đổi.',
      quarantineConsequence:
        'Thiết bị không còn đủ điều kiện reservation cho tới khi được xác minh sạch độc lập.',
      noAction:
        'Chọn thao tác để xem hệ quả được audit. Prototype này không dispatch lệnh.'
    },
    states: {
      eyebrow: 'Interaction contract production',
      heading: 'Mỗi trạng thái đều có owner, nguồn và hành động tiếp theo',
      description:
        'Bản đồ này giúp đội frontend và API nối tích hợp thật mà không đổi nghĩa của trạng thái blocked, failed, paid hoặc verified.',
      role: 'Vai trò thấy',
      source: 'Nguồn server',
      action: 'Hành động chính',
      secondaryAction: 'Hành động phụ',
      loadingCopy: 'Nội dung khi tải',
      errorCopy: 'Nội dung khi lỗi',
      preview: 'Mở trạng thái tương tác',
      previewHeading: 'Fixture trạng thái tương tác',
      normal: 'Mặc định',
      loading: 'Đang tải',
      error: 'Lỗi'
    }
  }
} as const;
