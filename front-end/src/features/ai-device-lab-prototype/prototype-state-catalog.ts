import type { PrototypeLocale } from './prototype-copy';

type Localized = Record<PrototypeLocale, string>;

type StateDefinition = {
  view: Localized;
  state: Localized;
  role: Localized;
  source: string;
  action: Localized;
};

const customer = { en: 'Developer', vi: 'Developer' };
const owner = { en: 'Workspace owner', vi: 'Workspace owner' };
const operator = { en: 'Operator', vi: 'Operator' };
const guest = { en: 'Guest', vi: 'Khách' };

const views = {
  landing: { en: 'Landing', vi: 'Landing' },
  wizard: { en: 'Wizard', vi: 'Wizard' },
  readiness: { en: 'Readiness', vi: 'Readiness' },
  lane: { en: 'Lane detail', vi: 'Chi tiết lane' },
  report: { en: 'Report', vi: 'Báo cáo' },
  operator: { en: 'Operator', vi: 'Vận hành' }
} satisfies Record<string, Localized>;

const definitions: StateDefinition[] = [
  {
    view: views.landing,
    state: { en: 'Guest', vi: 'Khách' },
    role: guest,
    source: 'Auth session + product package config',
    action: { en: 'Sign in and start', vi: 'Đăng nhập và bắt đầu' }
  },
  {
    view: views.landing,
    state: { en: 'Signed in', vi: 'Đã đăng nhập' },
    role: customer,
    source: 'Auth session + workspace context',
    action: { en: 'Create campaign draft', vi: 'Tạo campaign draft' }
  },
  {
    view: views.landing,
    state: { en: 'CTA error', vi: 'CTA lỗi' },
    role: customer,
    source: 'Draft API error response',
    action: { en: 'Retry or contact owner', vi: 'Thử lại hoặc liên hệ owner' }
  },
  {
    view: views.wizard,
    state: { en: 'Draft', vi: 'Bản nháp' },
    role: customer,
    source: 'Campaign draft revision',
    action: { en: 'Complete app details', vi: 'Hoàn tất thông tin app' }
  },
  {
    view: views.wizard,
    state: { en: 'Generating scenario', vi: 'Đang tạo kịch bản' },
    role: customer,
    source: 'Scenario generation job',
    action: { en: 'Wait or cancel generation', vi: 'Chờ hoặc huỷ tạo kịch bản' }
  },
  {
    view: views.wizard,
    state: { en: 'AI generation error', vi: 'Lỗi tạo kịch bản AI' },
    role: customer,
    source: 'Scenario job terminal error',
    action: { en: 'Edit goal and retry', vi: 'Sửa mục tiêu và thử lại' }
  },
  {
    view: views.wizard,
    state: { en: 'Denied scenario', vi: 'Kịch bản bị từ chối' },
    role: customer,
    source: 'Policy review decision',
    action: {
      en: 'Remove disallowed actions',
      vi: 'Bỏ thao tác không được phép'
    }
  },
  {
    view: views.wizard,
    state: { en: 'Approved scenario', vi: 'Kịch bản đã duyệt' },
    role: owner,
    source: 'Immutable scenario approval',
    action: { en: 'Review package snapshot', vi: 'Duyệt snapshot gói' }
  },
  {
    view: views.wizard,
    state: { en: 'Stale approval', vi: 'Phê duyệt đã cũ' },
    role: owner,
    source: 'Draft and approval revision mismatch',
    action: { en: 'Review changed scenario', vi: 'Duyệt lại kịch bản đã đổi' }
  },
  {
    view: views.wizard,
    state: { en: 'Pending checkout', vi: 'Checkout đang chờ' },
    role: owner,
    source: 'Payment intent + provider state',
    action: {
      en: 'Wait for provider verification',
      vi: 'Chờ provider xác minh'
    }
  },
  {
    view: views.wizard,
    state: { en: 'Paid checkout', vi: 'Checkout đã thanh toán' },
    role: owner,
    source: 'Verified payment event + entitlement',
    action: { en: 'Open readiness', vi: 'Mở readiness' }
  },
  {
    view: views.wizard,
    state: { en: 'Failed checkout', vi: 'Checkout thất bại' },
    role: owner,
    source: 'Verified provider failure',
    action: { en: 'Retry with a new intent', vi: 'Thử lại với intent mới' }
  },
  {
    view: views.readiness,
    state: { en: 'Unknown readiness', vi: 'Readiness chưa xác định' },
    role: owner,
    source: 'Missing or stale readiness observations',
    action: { en: 'Run fresh checks', vi: 'Chạy kiểm tra mới' }
  },
  {
    view: views.readiness,
    state: { en: 'Blocked readiness', vi: 'Readiness bị chặn' },
    role: customer,
    source: 'Versioned readiness checklist',
    action: { en: 'Resolve assigned blockers', vi: 'Xử lý blocker được giao' }
  },
  {
    view: views.readiness,
    state: { en: 'Ready to start', vi: 'Sẵn sàng bắt đầu' },
    role: owner,
    source: 'Atomic server readiness check',
    action: { en: 'Start service once', vi: 'Bắt đầu dịch vụ một lần' }
  },
  {
    view: views.readiness,
    state: { en: 'Running service', vi: 'Dịch vụ đang chạy' },
    role: customer,
    source: 'Service campaign timeline',
    action: { en: 'Open dashboard', vi: 'Mở dashboard' }
  },
  {
    view: views.readiness,
    state: { en: 'Needs attention', vi: 'Cần xử lý' },
    role: customer,
    source: 'Blocker owner + reason + freshness',
    action: {
      en: 'Complete permitted assistance',
      vi: 'Hoàn tất hỗ trợ được phép'
    }
  },
  {
    view: views.lane,
    state: { en: 'Device changed', vi: 'Đã đổi thiết bị' },
    role: customer,
    source: 'Lane assignment intervals',
    action: { en: 'Compare device history', vi: 'So sánh lịch sử thiết bị' }
  },
  {
    view: views.lane,
    state: { en: 'Account changed', vi: 'Đã đổi tài khoản' },
    role: customer,
    source: 'Participation identity events',
    action: {
      en: 'Review continuity impact',
      vi: 'Kiểm tra ảnh hưởng continuity'
    }
  },
  {
    view: views.lane,
    state: { en: 'Run retry', vi: 'Run retry' },
    role: customer,
    source: 'Run attempt lineage',
    action: { en: 'Compare attempts', vi: 'So sánh attempt' }
  },
  {
    view: views.lane,
    state: { en: 'Step retry', vi: 'Step retry' },
    role: customer,
    source: 'Step result attempt path',
    action: {
      en: 'Inspect expected and observed',
      vi: 'Xem expected và observed'
    }
  },
  {
    view: views.lane,
    state: { en: 'Missing media', vi: 'Thiếu media' },
    role: customer,
    source: 'Artifact capture error record',
    action: { en: 'Read capture failure', vi: 'Đọc lỗi capture' }
  },
  {
    view: views.lane,
    state: { en: 'Expired media', vi: 'Media hết hạn' },
    role: customer,
    source: 'Artifact retention availability',
    action: { en: 'Use retained manifest', vi: 'Dùng manifest còn lưu' }
  },
  {
    view: views.report,
    state: { en: 'Generating report', vi: 'Đang tạo báo cáo' },
    role: owner,
    source: 'Report job + frozen cutoff',
    action: { en: 'Wait for snapshot completion', vi: 'Chờ hoàn tất snapshot' }
  },
  {
    view: views.report,
    state: { en: 'Failed report', vi: 'Báo cáo lỗi' },
    role: owner,
    source: 'Report job terminal error',
    action: { en: 'Retry from same cutoff', vi: 'Thử lại từ cùng cutoff' }
  },
  {
    view: views.report,
    state: { en: 'Frozen report', vi: 'Báo cáo đã đóng băng' },
    role: customer,
    source: 'Immutable report version + checksum',
    action: { en: 'Review or download', vi: 'Duyệt hoặc download' }
  },
  {
    view: views.report,
    state: { en: 'Corrected report', vi: 'Báo cáo đã sửa' },
    role: customer,
    source: 'Correction lineage to prior version',
    action: { en: 'Compare report versions', vi: 'So sánh phiên bản báo cáo' }
  },
  {
    view: views.operator,
    state: { en: 'Replacement requested', vi: 'Yêu cầu thay thiết bị' },
    role: operator,
    source: 'Fleet command + reservation transaction',
    action: { en: 'Drain then replace', vi: 'Drain rồi thay thiết bị' }
  },
  {
    view: views.operator,
    state: { en: 'Extension preview', vi: 'Xem trước gia hạn' },
    role: operator,
    source: 'Policy + billing + quota delta',
    action: { en: 'Request owner consent', vi: 'Yêu cầu owner đồng ý' }
  },
  {
    view: views.operator,
    state: { en: 'Cancellation requested', vi: 'Yêu cầu huỷ' },
    role: operator,
    source: 'Durable cancellation saga',
    action: { en: 'Drain and finalize', vi: 'Drain và hoàn tất' }
  },
  {
    view: views.operator,
    state: { en: 'Quarantined device', vi: 'Thiết bị bị cách ly' },
    role: operator,
    source: 'Hygiene verification result',
    action: {
      en: 'Keep ineligible until clean',
      vi: 'Giữ không đủ điều kiện tới khi sạch'
    }
  }
];

type StateInteraction = {
  secondaryAction: Localized;
  loadingCopy: Localized;
  errorCopy: Localized;
};

type InteractionRow = readonly [
  state: string,
  secondaryEn: string,
  secondaryVi: string,
  loadingEn: string,
  loadingVi: string,
  errorEn: string,
  errorVi: string
];

const interactionRows = [
  [
    'Guest',
    'Compare the package',
    'So sánh gói dịch vụ',
    'Checking sign-in status.',
    'Đang kiểm tra đăng nhập.',
    'Sign-in status is unavailable. Retry before starting.',
    'Không có trạng thái đăng nhập. Thử lại trước khi bắt đầu.'
  ],
  [
    'Signed in',
    'Switch workspace',
    'Đổi workspace',
    'Loading workspace context.',
    'Đang tải workspace context.',
    'Workspace context failed to load. Retry without creating a draft.',
    'Không tải được workspace. Thử lại mà chưa tạo draft.'
  ],
  [
    'CTA error',
    'Return to overview',
    'Quay lại tổng quan',
    'Creating a campaign draft.',
    'Đang tạo campaign draft.',
    'Draft creation failed. No payment or reservation was created.',
    'Tạo draft thất bại. Chưa có thanh toán hay reservation.'
  ],
  [
    'Draft',
    'Discard the draft',
    'Bỏ bản nháp',
    'Saving the current draft revision.',
    'Đang lưu revision bản nháp.',
    'Draft save failed. Keep local input and retry.',
    'Lưu draft thất bại. Giữ input và thử lại.'
  ],
  [
    'Generating scenario',
    'Cancel generation',
    'Huỷ tạo kịch bản',
    'Generating actions and assertions.',
    'Đang tạo action và assertion.',
    'Generation stopped. Edit the goal or retry.',
    'Tạo kịch bản đã dừng. Sửa mục tiêu hoặc thử lại.'
  ],
  [
    'AI generation error',
    'Edit the test goal',
    'Sửa mục tiêu kiểm thử',
    'Preparing a new generation attempt.',
    'Đang chuẩn bị lần tạo mới.',
    'The retry failed. Keep the error and original goal visible.',
    'Thử lại thất bại. Giữ lỗi và mục tiêu gốc hiển thị.'
  ],
  [
    'Denied scenario',
    'View policy details',
    'Xem chi tiết policy',
    'Loading the policy decision.',
    'Đang tải quyết định policy.',
    'The denial reason is unavailable. Contact the workspace owner.',
    'Không tải được lý do từ chối. Liên hệ workspace owner.'
  ],
  [
    'Approved scenario',
    'Compare approval revision',
    'So sánh revision đã duyệt',
    'Verifying the immutable approval.',
    'Đang xác minh phê duyệt bất biến.',
    'Approval cannot be verified. Block checkout.',
    'Không xác minh được phê duyệt. Chặn checkout.'
  ],
  [
    'Stale approval',
    'Restore approved revision',
    'Khôi phục revision đã duyệt',
    'Loading the revision difference.',
    'Đang tải khác biệt revision.',
    'Revision comparison failed. Keep checkout blocked.',
    'So sánh revision thất bại. Tiếp tục chặn checkout.'
  ],
  [
    'Pending checkout',
    'Cancel checkout',
    'Huỷ checkout',
    'Reconciling provider and ledger state.',
    'Đang đối soát provider và ledger.',
    'Provider status is unavailable. Keep checkout pending.',
    'Không có trạng thái provider. Giữ checkout ở pending.'
  ],
  [
    'Paid checkout',
    'View payment receipt',
    'Xem biên nhận thanh toán',
    'Loading verified entitlement.',
    'Đang tải entitlement đã xác minh.',
    'Entitlement cannot be verified. Do not start service.',
    'Không xác minh được entitlement. Không bắt đầu dịch vụ.'
  ],
  [
    'Failed checkout',
    'Return to package review',
    'Quay lại duyệt gói',
    'Loading the provider failure reason.',
    'Đang tải lý do provider thất bại.',
    'A new payment intent could not be created. Keep service stopped.',
    'Không tạo được payment intent mới. Giữ dịch vụ chưa chạy.'
  ],
  [
    'Unknown readiness',
    'Return to package review',
    'Quay lại duyệt gói',
    'Running fresh readiness checks.',
    'Đang chạy kiểm tra readiness mới.',
    'Checks are unavailable. Readiness stays Unknown.',
    'Không chạy được kiểm tra. Readiness vẫn Chưa xác định.'
  ],
  [
    'Blocked readiness',
    'View all blocker owners',
    'Xem mọi owner của blocker',
    'Refreshing blocker evidence.',
    'Đang làm mới evidence blocker.',
    'Blockers could not be refreshed. Keep Start disabled.',
    'Không làm mới được blocker. Tiếp tục khoá Bắt đầu.'
  ],
  [
    'Ready to start',
    'Run final checks again',
    'Chạy lại kiểm tra cuối',
    'Confirming an atomic ready snapshot.',
    'Đang xác nhận snapshot sẵn sàng nguyên tử.',
    'The ready snapshot is stale. Disable Start and recheck.',
    'Snapshot sẵn sàng đã cũ. Khoá Bắt đầu và kiểm tra lại.'
  ],
  [
    'Running service',
    'Open campaign dashboard',
    'Mở dashboard campaign',
    'Loading the service timeline.',
    'Đang tải timeline dịch vụ.',
    'Timeline is unavailable. Do not infer completion.',
    'Không tải được timeline. Không suy diễn hoàn tất.'
  ],
  [
    'Needs attention',
    'Snooze until owner update',
    'Chờ owner cập nhật',
    'Loading the assigned assistance task.',
    'Đang tải tác vụ hỗ trợ được giao.',
    'Assistance details are unavailable. Keep the lane blocked.',
    'Không tải được chi tiết hỗ trợ. Giữ lane bị chặn.'
  ],
  [
    'Device changed',
    'Compare device intervals',
    'So sánh khoảng thiết bị',
    'Loading assignment history.',
    'Đang tải lịch sử assignment.',
    'Device history is unavailable. Preserve the last known device.',
    'Không tải được lịch sử thiết bị. Giữ thiết bị đã biết gần nhất.'
  ],
  [
    'Account changed',
    'Compare participation events',
    'So sánh event tham gia',
    'Loading account continuity events.',
    'Đang tải event continuity tài khoản.',
    'Continuity evidence is missing. Keep participation Unknown.',
    'Thiếu evidence continuity. Giữ trạng thái tham gia Chưa xác định.'
  ],
  [
    'Run retry',
    'Open the previous attempt',
    'Mở attempt trước',
    'Loading run-attempt lineage.',
    'Đang tải lineage run attempt.',
    'Retry lineage failed to load. Do not merge attempts.',
    'Không tải được lineage retry. Không gộp attempt.'
  ],
  [
    'Step retry',
    'Open expected versus observed',
    'Mở expected so với observed',
    'Loading step-attempt lineage.',
    'Đang tải lineage step attempt.',
    'Step lineage failed to load. Keep the run result unchanged.',
    'Không tải được lineage step. Giữ nguyên kết quả run.'
  ],
  [
    'Missing media',
    'Open capture error log',
    'Mở log lỗi capture',
    'Checking artifact capture status.',
    'Đang kiểm tra trạng thái capture artifact.',
    'Artifact status is unavailable. Mark evidence as missing.',
    'Không có trạng thái artifact. Ghi evidence là thiếu.'
  ],
  [
    'Expired media',
    'Open retained manifest',
    'Mở manifest còn lưu',
    'Checking retention availability.',
    'Đang kiểm tra thời hạn lưu.',
    'Retention lookup failed. Do not present an expired URL.',
    'Tra cứu retention thất bại. Không hiển thị URL đã hết hạn.'
  ],
  [
    'Generating report',
    'Cancel report job',
    'Huỷ job báo cáo',
    'Building the frozen report snapshot.',
    'Đang tạo snapshot báo cáo đóng băng.',
    'Report generation stopped. Retry from the same cutoff.',
    'Tạo báo cáo đã dừng. Thử lại từ cùng cutoff.'
  ],
  [
    'Failed report',
    'Open report job log',
    'Mở log job báo cáo',
    'Preparing a same-cutoff retry.',
    'Đang chuẩn bị retry cùng cutoff.',
    'Report retry failed. Preserve the failed job and cutoff.',
    'Retry báo cáo thất bại. Giữ job lỗi và cutoff.'
  ],
  [
    'Frozen report',
    'Compare prior version',
    'So sánh phiên bản trước',
    'Verifying report checksum.',
    'Đang xác minh checksum báo cáo.',
    'Checksum verification failed. Disable download.',
    'Xác minh checksum thất bại. Khoá download.'
  ],
  [
    'Corrected report',
    'Open original report',
    'Mở báo cáo gốc',
    'Loading correction lineage.',
    'Đang tải lineage correction.',
    'Correction lineage is unavailable. Keep both versions distinct.',
    'Không tải được lineage correction. Giữ hai phiên bản tách biệt.'
  ],
  [
    'Replacement requested',
    'Cancel replacement',
    'Huỷ thay thiết bị',
    'Draining work before replacement.',
    'Đang drain công việc trước khi thay.',
    'Replacement failed. Keep the old assignment and audit event.',
    'Thay thiết bị thất bại. Giữ assignment cũ và audit event.'
  ],
  [
    'Extension preview',
    'Discard extension preview',
    'Bỏ bản xem trước gia hạn',
    'Calculating billing and quota delta.',
    'Đang tính billing và quota delta.',
    'Extension preview failed. Do not change service dates.',
    'Xem trước gia hạn thất bại. Không đổi ngày dịch vụ.'
  ],
  [
    'Cancellation requested',
    'Withdraw cancellation',
    'Rút yêu cầu huỷ',
    'Draining active work safely.',
    'Đang drain công việc đang chạy an toàn.',
    'Cancellation stalled. Keep reservations until hygiene completes.',
    'Huỷ bị kẹt. Giữ reservation tới khi hygiene hoàn tất.'
  ],
  [
    'Quarantined device',
    'Open hygiene evidence',
    'Mở evidence hygiene',
    'Verifying the clean result.',
    'Đang xác minh kết quả sạch.',
    'Hygiene verification failed. Keep the device ineligible.',
    'Xác minh hygiene thất bại. Giữ thiết bị không đủ điều kiện.'
  ]
] satisfies readonly InteractionRow[];

const stateInteractions = new Map<string, StateInteraction>(
  interactionRows.map(
    ([
      state,
      secondaryEn,
      secondaryVi,
      loadingEn,
      loadingVi,
      errorEn,
      errorVi
    ]) => [
      state,
      {
        secondaryAction: { en: secondaryEn, vi: secondaryVi },
        loadingCopy: { en: loadingEn, vi: loadingVi },
        errorCopy: { en: errorEn, vi: errorVi }
      }
    ]
  )
);

export type PrototypeStateSpec = {
  id: string;
  view: string;
  state: string;
  role: string;
  source: string;
  action: string;
  secondaryAction: string;
  loadingCopy: string;
  errorCopy: string;
};

function toSourceIdentifier(source: string): string {
  return `server.${source
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_|_$/g, '')}`;
}

function toStateId(view: string, state: string): string {
  return `${view}-${state}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}

export function getPrototypeStateCatalog(
  locale: PrototypeLocale
): PrototypeStateSpec[] {
  return definitions.map((definition) => {
    const view = definition.view[locale];
    const state = definition.state[locale];
    const source = toSourceIdentifier(definition.source);
    const interaction = stateInteractions.get(definition.state.en);

    if (!interaction) {
      throw new Error(`Missing interaction copy for ${definition.state.en}`);
    }

    return {
      id: toStateId(definition.view.en, definition.state.en),
      view,
      state,
      role: definition.role[locale],
      source,
      action: definition.action[locale],
      secondaryAction: interaction.secondaryAction[locale],
      loadingCopy: interaction.loadingCopy[locale],
      errorCopy: interaction.errorCopy[locale]
    };
  });
}
