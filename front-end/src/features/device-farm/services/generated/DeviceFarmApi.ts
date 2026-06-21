/* eslint-disable */
/* tslint:disable */
// @ts-nocheck
/*
 * ---------------------------------------------------------------
 * ## THIS FILE WAS GENERATED VIA SWAGGER-TYPESCRIPT-API        ##
 * ##                                                           ##
 * ## AUTHOR: acacode                                           ##
 * ## SOURCE: https://github.com/acacode/swagger-typescript-api ##
 * ---------------------------------------------------------------
 */

/**
 * SessionOwnerType
 * Owner classification for active control-plane sessions (DF-T-02-013).
 */
export enum SessionOwnerType {
  User = "user",
  Execution = "execution",
  Campaign = "campaign",
  System = "system",
  Unknown = "unknown",
}

/** ExecutionResultStatus */
export enum ExecutionResultStatus {
  Pending = "pending",
  Running = "running",
  Passed = "passed",
  Failed = "failed",
  Error = "error",
}

/** AIExtractBody */
export interface AIExtractBody {
  /** Prompt */
  prompt: string;
  /**
   * Provider
   * @default "openai"
   */
  provider?: string;
  /**
   * Format
   * @default "json"
   */
  format?: string;
  /** Model */
  model?: string | null;
  /** Region */
  region?: Record<string, number> | null;
}

/** AccountCreate */
export interface AccountCreate {
  /** Platform */
  platform: string;
  /** Username */
  username: string;
  /** Password */
  password?: string | null;
  /**
   * Display Name
   * @default ""
   */
  display_name?: string;
  /**
   * Notes
   * @default ""
   */
  notes?: string;
  /**
   * Tags
   * @default ""
   */
  tags?: string;
  /** Proxy Id */
  proxy_id?: string | null;
  /**
   * Account Metadata
   * @default {}
   */
  account_metadata?: Record<string, any>;
}

/** AccountEventListOut */
export interface AccountEventListOut {
  /** Items */
  items: AccountEventOut[];
  /** Next Cursor */
  next_cursor?: string | null;
  /**
   * Has More
   * @default false
   */
  has_more?: boolean;
}

/** AccountEventOut */
export interface AccountEventOut {
  /** Id */
  id: string;
  /** Account Id */
  account_id: string;
  /** Event Type */
  event_type: string;
  /** Device Serial */
  device_serial?: string | null;
  /** Platform */
  platform?: string | null;
  /** Entity Type */
  entity_type?: string | null;
  /** Entity Id */
  entity_id?: string | null;
  /** Details */
  details?: Record<string, any>;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
}

/** AccountGroupCreate */
export interface AccountGroupCreate {
  /**
   * Name
   * @minLength 1
   * @maxLength 255
   */
  name: string;
  /**
   * Description
   * @default ""
   */
  description?: string;
  /**
   * Platform
   * @minLength 1
   * @maxLength 50
   */
  platform: string;
  /**
   * Rotation Strategy
   * @default "round_robin"
   * @pattern ^(round_robin|least_recent)$
   */
  rotation_strategy?: string;
}

/**
 * AccountGroupMemberBatchAdd
 * Body for POST /account-groups/{id}/members. Idempotent; duplicates ignored.
 */
export interface AccountGroupMemberBatchAdd {
  /**
   * Account Ids
   * @maxItems 500
   * @minItems 1
   */
  account_ids: string[];
}

/** AccountGroupMemberBatchResult */
export interface AccountGroupMemberBatchResult {
  /** Added */
  added: number;
  /** Skipped */
  skipped: number;
}

/** AccountGroupMemberOut */
export interface AccountGroupMemberOut {
  /** Account Id */
  account_id: string;
  /** Username */
  username: string;
  /** Display Name */
  display_name: string;
  /** Status */
  status: string;
  /** Position */
  position: number;
  /** Last Used At */
  last_used_at: string | null;
  /**
   * Added At
   * @format date-time
   */
  added_at: string;
}

/** AccountGroupOut */
export interface AccountGroupOut {
  /** Id */
  id: string;
  /** User Id */
  user_id: string | null;
  /** Name */
  name: string;
  /** Description */
  description: string;
  /** Platform */
  platform: string;
  /** Rotation Strategy */
  rotation_strategy: string;
  /** Rotation Cursor */
  rotation_cursor: number;
  /**
   * Member Count
   * @default 0
   */
  member_count?: number;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /**
   * Updated At
   * @format date-time
   */
  updated_at: string;
}

/** AccountGroupUpdate */
export interface AccountGroupUpdate {
  /** Name */
  name?: string | null;
  /** Description */
  description?: string | null;
  /** Rotation Strategy */
  rotation_strategy?: string | null;
}

/** AccountOut */
export interface AccountOut {
  /** Id */
  id: string;
  /** Platform */
  platform: string;
  /** Username */
  username: string;
  /** Display Name */
  display_name: string;
  /** Status */
  status: string;
  /** State */
  state: string;
  /** State Reason */
  state_reason?: string | null;
  /** State Changed At */
  state_changed_at?: string | null;
  /** Cooldown Until */
  cooldown_until: string | null;
  /** Proxy Id */
  proxy_id: string | null;
  /** Notes */
  notes: string;
  /** Tags */
  tags: string;
  /** User Id */
  user_id: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /**
   * Updated At
   * @format date-time
   */
  updated_at: string;
  /** Last Used At */
  last_used_at: string | null;
  /** Total Usage Minutes */
  total_usage_minutes: number;
  /** Usage Today Minutes */
  usage_today_minutes: number;
  /** Usage Reset Date */
  usage_reset_date: string | null;
}

/** AccountStateTransitionBody */
export interface AccountStateTransitionBody {
  /**
   * To
   * Target FSM state
   */
  to: string;
  /**
   * Reason
   * @minLength 1
   * @maxLength 2000
   */
  reason: string;
  /**
   * Ttl Seconds
   * Required when to=cooldown; cooldown_until = now + ttl_seconds
   */
  ttl_seconds?: number | null;
  /**
   * Expected State Changed At
   * Optimistic lock: must match current state_changed_at
   */
  expected_state_changed_at?: string | null;
}

/** AccountStateTransitionOut */
export interface AccountStateTransitionOut {
  /** Id */
  id: string;
  /** State */
  state: string;
  /** Status */
  status: string;
  /** State Reason */
  state_reason: string | null;
  /** State Changed At */
  state_changed_at: string | null;
  /** Cooldown Until */
  cooldown_until: string | null;
}

/**
 * AccountStatusUpdate
 * Legacy status update — routed through FSM (maps ``disabled`` → ``suspended``).
 */
export interface AccountStatusUpdate {
  /** Status */
  status: string;
  /**
   * Reason
   * @default "legacy PATCH /status"
   */
  reason?: string;
  /** Ttl Seconds */
  ttl_seconds?: number | null;
}

/** AccountUpdate */
export interface AccountUpdate {
  /** Password */
  password?: string | null;
  /** Display Name */
  display_name?: string | null;
  /** Notes */
  notes?: string | null;
  /** Tags */
  tags?: string | null;
  /** Proxy Id */
  proxy_id?: string | null;
  /** Account Metadata */
  account_metadata?: Record<string, any> | null;
}

/**
 * AccountWithLinksOut
 * Detailed account response that includes the list of device links.
 */
export interface AccountWithLinksOut {
  /** Id */
  id: string;
  /** Platform */
  platform: string;
  /** Username */
  username: string;
  /** Display Name */
  display_name: string;
  /** Status */
  status: string;
  /** State */
  state: string;
  /** State Reason */
  state_reason?: string | null;
  /** State Changed At */
  state_changed_at?: string | null;
  /** Cooldown Until */
  cooldown_until: string | null;
  /** Proxy Id */
  proxy_id: string | null;
  /** Notes */
  notes: string;
  /** Tags */
  tags: string;
  /** User Id */
  user_id: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /**
   * Updated At
   * @format date-time
   */
  updated_at: string;
  /** Last Used At */
  last_used_at: string | null;
  /** Total Usage Minutes */
  total_usage_minutes: number;
  /** Usage Today Minutes */
  usage_today_minutes: number;
  /** Usage Reset Date */
  usage_reset_date: string | null;
  /**
   * Device Links
   * @default []
   */
  device_links?: DeviceAccountOut[];
}

/** ActivityLogListOut */
export interface ActivityLogListOut {
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
  /** Activities */
  activities: ActivityLogOut[];
}

/** ActivityLogOut */
export interface ActivityLogOut {
  /** Id */
  id: string;
  /** Action */
  action: string;
  /** Entity Type */
  entity_type: string | null;
  /** Entity Id */
  entity_id: string | null;
  /** Device Serial */
  device_serial: string | null;
  /** Device Display */
  device_display?: string | null;
  /** Org Id */
  org_id?: string | null;
  /** User Id */
  user_id: string | null;
  /** User Name */
  user_name?: string | null;
  /** Method */
  method?: string | null;
  /** Path */
  path?: string | null;
  /** Route Template */
  route_template?: string | null;
  /** Status Code */
  status_code?: number | null;
  /** Request Id */
  request_id?: string | null;
  /** Ip Address */
  ip_address?: string | null;
  /** User Agent */
  user_agent?: string | null;
  /** Outcome */
  outcome?: string | null;
  /** Duration Ms */
  duration_ms?: number | null;
  /** Details */
  details: Record<string, any>;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
}

/**
 * AdbRegisterRequest
 * Body for app-after-scan: phone sends its IP so backend can connect via ADB.
 */
export interface AdbRegisterRequest {
  /** Ip */
  ip: string;
  /**
   * Port
   * @default 5555
   */
  port?: number;
  /** Device Key */
  device_key?: string | null;
}

/** AddDeviceBody */
export interface AddDeviceBody {
  /** Device Id */
  device_id: string;
}

/** AddDevicesToGroupBody */
export interface AddDevicesToGroupBody {
  /** Device Ids */
  device_ids: string[];
}

/** AdminForceReleaseBody */
export interface AdminForceReleaseBody {
  /**
   * Reason
   * @minLength 1
   * @maxLength 500
   */
  reason: string;
  /** Session Id */
  session_id?: string | null;
}

/** AdminOverrideOut */
export interface AdminOverrideOut {
  /** Device Id */
  device_id: string;
  /** From State */
  from_state: string;
  /** To State */
  to_state: string;
  /** Old Owner Type */
  old_owner_type?: string | null;
  /** Old Owner Id */
  old_owner_id?: string | null;
  /** Session Id */
  session_id?: string | null;
  /** Reason */
  reason: string;
  /** Actor */
  actor: string;
}

/** AdminResetStateBody */
export interface AdminResetStateBody {
  /**
   * Reason
   * @minLength 1
   * @maxLength 500
   */
  reason: string;
  /**
   * Target State
   * connecting or online; default depends on current state
   */
  target_state?: string | null;
}

/** AnalyticsAdhocOut */
export interface AnalyticsAdhocOut {
  /** Rows */
  rows: Record<string, any>[];
  /** Row Count */
  row_count: number;
}

/** AnalyticsPointOut */
export interface AnalyticsPointOut {
  /** Date */
  date: string;
  /** Resource Type */
  resource_type: string;
  /** Resource Id */
  resource_id: string | null;
  /** Event Type */
  event_type: string;
  /** Count */
  count: number;
  /** Success Count */
  success_count: number;
  /** Fail Count */
  fail_count: number;
  /** Latency P50 */
  latency_p50?: number | null;
  /** Latency P95 */
  latency_p95?: number | null;
}

/** AnalyticsSummaryOut */
export interface AnalyticsSummaryOut {
  /** Window Days */
  window_days: number;
  /** Total Count */
  total_count: number;
  /** Success Count */
  success_count: number;
  /** Fail Count */
  fail_count: number;
  /** Success Rate */
  success_rate: number;
}

/** AnalyticsTimeseriesOut */
export interface AnalyticsTimeseriesOut {
  /** Points */
  points: AnalyticsPointOut[];
}

/** ArtifactUrlOut */
export interface ArtifactUrlOut {
  /** Url */
  url: string | null;
  /** Expires At */
  expires_at: string;
  /** Content Type */
  content_type: string;
  /** Size Bytes */
  size_bytes?: number | null;
  /**
   * Proxy Required
   * @default false
   */
  proxy_required?: boolean;
}

/**
 * AssignAccountBody
 * Used by POST /devices/{device_id}/accounts — assigns an account to a device.
 */
export interface AssignAccountBody {
  /** Account Id */
  account_id: string;
  /**
   * Is Primary
   * @default false
   */
  is_primary?: boolean;
}

/**
 * AssignDeviceBody
 * Used by POST /accounts/{account_id}/devices — assigns a device to an account.
 */
export interface AssignDeviceBody {
  /** Device Id */
  device_id: string;
  /**
   * Is Primary
   * @default false
   */
  is_primary?: boolean;
}

/** Body_bulk_import_csv_api_accounts_import_csv_post */
export interface BodyBulkImportCsvApiAccountsImportCsvPost {
  /**
   * File
   * CSV file with columns: platform, username, password, display_name, tags, notes
   */
  file: string;
}

/** Body_import_scenario_route_api_scenarios_import_post */
export interface BodyImportScenarioRouteApiScenariosImportPost {
  /** File */
  file: string;
}

/** BootstrapAllResult */
export interface BootstrapAllResult {
  /** Relay Id */
  relay_id: string;
  /** Total */
  total: number;
  /** Ok */
  ok: number;
  /** Failed */
  failed: number;
  /** Results */
  results: Record<string, any>[];
}

/**
 * BulkImportBody
 * JSON bulk import body.
 */
export interface BulkImportBody {
  /** Accounts */
  accounts: BulkImportRow[];
}

/** BulkImportResult */
export interface BulkImportResult {
  /** Created */
  created: number;
  /** Skipped */
  skipped: number;
  /** Total */
  total: number;
}

/** BulkImportRow */
export interface BulkImportRow {
  /** Platform */
  platform: string;
  /** Username */
  username: string;
  /** Password */
  password?: string | null;
  /**
   * Display Name
   * @default ""
   */
  display_name?: string;
  /**
   * Tags
   * @default ""
   */
  tags?: string;
  /**
   * Notes
   * @default ""
   */
  notes?: string;
}

/** BulkScheduleToggleIn */
export interface BulkScheduleToggleIn {
  /**
   * Schedule Ids
   * @maxItems 500
   * @minItems 1
   */
  schedule_ids: string[];
}

/** BulkScheduleToggleItemOut */
export interface BulkScheduleToggleItemOut {
  /** Schedule Id */
  schedule_id: string;
  /** Status */
  status: string;
  /** Enabled */
  enabled?: boolean | null;
  /** Error Code */
  error_code?: string | null;
}

/** BulkScheduleToggleOut */
export interface BulkScheduleToggleOut {
  /** Success Count */
  success_count: number;
  /** Fail Count */
  fail_count: number;
  /** Skipped Count */
  skipped_count: number;
  /** Items */
  items: BulkScheduleToggleItemOut[];
}

/** CampaignAccountBindIn */
export interface CampaignAccountBindIn {
  /** Account Group Id */
  account_group_id?: string | null;
  /** Scenario Account Id */
  scenario_account_id?: string | null;
  /** Per Device Accounts */
  per_device_accounts?: Record<string, string>;
}

/** CampaignControlOut */
export interface CampaignControlOut {
  /** Campaign Id */
  campaign_id: string;
  /** Status */
  status: string;
  /** Executions Affected */
  executions_affected: number;
  /** Executions */
  executions?: Record<string, any>[];
  /**
   * Workflows Signalled
   * @default 0
   */
  workflows_signalled?: number;
  /** Warning */
  warning?: string | null;
}

/** CampaignCreate */
export interface CampaignCreate {
  /** Name */
  name: string;
  /**
   * Description
   * @default ""
   */
  description?: string;
  /**
   * Scenario
   * @default {}
   */
  scenario?: Record<string, any>;
  /**
   * Variables
   * @default {}
   */
  variables?: Record<string, any>;
  /** Vars */
  vars?: Record<string, any> | null;
  /** Per Device Overrides */
  per_device_overrides?: Record<string, Record<string, any>> | null;
  /** Account Group Id */
  account_group_id?: string | null;
  /** Scenario Account Id */
  scenario_account_id?: string | null;
  /** Per Device Accounts */
  per_device_accounts?: Record<string, string>;
  /** Tags */
  tags?: string[] | null;
  /** Scenario Refs */
  scenario_refs?: CampaignScenarioRefIn[] | null;
  /**
   * Device Ids
   * @default []
   */
  device_ids?: string[];
  /** Target Group Id */
  target_group_id?: string | null;
}

/** CampaignDeviceOut */
export interface CampaignDeviceOut {
  /** Id */
  id: string;
  /** Serial */
  serial: string;
  /** Name */
  name: string;
}

/** CampaignDispatchExecutionOut */
export interface CampaignDispatchExecutionOut {
  /** Execution Id */
  execution_id: string;
  /** Device Id */
  device_id: string;
  /** Status */
  status: string;
  /** Effective Vars */
  effective_vars?: Record<string, any>;
  /** Account Id */
  account_id?: string | null;
  /** Failure Reason */
  failure_reason?: string | null;
  /** Claim Session Id */
  claim_session_id?: string | null;
  /** Dispatch Source */
  dispatch_source?: string | null;
  /** Workflow Id */
  workflow_id?: string | null;
}

/** CampaignDispatchIn */
export interface CampaignDispatchIn {
  target: CampaignDispatchTargetIn;
  /**
   * Dispatch Strategy
   * @default "parallel"
   * @pattern ^(parallel|sequential)$
   */
  dispatch_strategy?: string;
  /**
   * Allow Partial
   * @default false
   */
  allow_partial?: boolean;
  /**
   * Require Online
   * @default true
   */
  require_online?: boolean;
}

/** CampaignDispatchOut */
export interface CampaignDispatchOut {
  /** Dispatch Id */
  dispatch_id: string;
  /** Campaign Id */
  campaign_id: string;
  /** Dispatch Strategy */
  dispatch_strategy: string;
  /** Target Count */
  target_count: number;
  /** Executions */
  executions?: CampaignDispatchExecutionOut[];
}

/** CampaignDispatchTargetIn */
export interface CampaignDispatchTargetIn {
  /** Device Ids */
  device_ids?: string[];
  /** Device Group Ids */
  device_group_ids?: string[];
}

/** CampaignEntityOut */
export interface CampaignEntityOut {
  /** Id */
  id: string;
  /** Organization Id */
  organization_id: string;
  /** Name */
  name: string;
  /** Description */
  description: string;
  /** Status */
  status: string;
  /** Vars */
  vars?: Record<string, any>;
  /** Per Device Overrides */
  per_device_overrides?: Record<string, Record<string, any>>;
  /** Recovery Policy */
  recovery_policy?: Record<string, any>;
  /** Account Group Id */
  account_group_id?: string | null;
  /** Scenario Account Id */
  scenario_account_id?: string | null;
  /** Per Device Accounts */
  per_device_accounts?: Record<string, string>;
  /** Tags */
  tags?: string[];
  /** Scenario Refs */
  scenario_refs?: CampaignScenarioRefOut[];
  /** Created By */
  created_by?: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /**
   * Updated At
   * @format date-time
   */
  updated_at: string;
  /** Started At */
  started_at?: string | null;
  /** Completed At */
  completed_at?: string | null;
  /** Cancelled At */
  cancelled_at?: string | null;
}

/** CampaignEntityUpdate */
export interface CampaignEntityUpdate {
  /** Name */
  name?: string | null;
  /** Description */
  description?: string | null;
  /** Vars */
  vars?: Record<string, any> | null;
  /** Tags */
  tags?: string[] | null;
  /** Scenario Refs */
  scenario_refs?: CampaignScenarioRefIn[] | null;
  /** Per Device Overrides */
  per_device_overrides?: Record<string, Record<string, any>> | null;
  /** Recovery Policy */
  recovery_policy?: Record<string, any> | null;
}

/** CampaignForceTransitionIn */
export interface CampaignForceTransitionIn {
  /**
   * To Status
   * @minLength 1
   * @maxLength 32
   */
  to_status: string;
  /**
   * Reason
   * @minLength 1
   * @maxLength 2000
   */
  reason: string;
}

/** CampaignForceTransitionOut */
export interface CampaignForceTransitionOut {
  /** Campaign Id */
  campaign_id: string;
  /** From Status */
  from_status: string;
  /** To Status */
  to_status: string;
  /** Changed */
  changed: boolean;
  /** Reason */
  reason?: string | null;
}

/** CampaignOut */
export interface CampaignOut {
  /** Id */
  id: string;
  /** Name */
  name: string;
  /** Description */
  description: string;
  /** Status */
  status: string;
  /** Scenario */
  scenario?: Record<string, any> | null;
  /**
   * Variables
   * @default {}
   */
  variables?: Record<string, any>;
  /**
   * Scenarios
   * @default []
   */
  scenarios?: ScenarioOut[];
  /** User Id */
  user_id: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /** Target Group Id */
  target_group_id?: string | null;
}

/** CampaignRunBody */
export interface CampaignRunBody {
  /**
   * Filter State
   * @default "READY"
   */
  filter_state?: string;
  /** Filter Model */
  filter_model?: string | null;
  /** Filter Tags */
  filter_tags?: string | null;
  /** Max Devices */
  max_devices?: number | null;
}

/** CampaignScenarioRefIn */
export interface CampaignScenarioRefIn {
  /** Scenario Id */
  scenario_id: string;
  /** Scenario Version */
  scenario_version?: number | null;
}

/** CampaignScenarioRefOut */
export interface CampaignScenarioRefOut {
  /** Scenario Id */
  scenario_id: string;
  /** Scenario Version */
  scenario_version: number;
}

/** CapacityGroupBreakdownOut */
export interface CapacityGroupBreakdownOut {
  /** Group Id */
  group_id: string;
  /** Total */
  total: number;
  /** Available */
  available: number;
  /** Busy */
  busy: number;
  /** Dead */
  dead: number;
}

/** CapacityRelayBreakdownOut */
export interface CapacityRelayBreakdownOut {
  /** Relay Host */
  relay_host: string;
  /** Total */
  total: number;
  /** Available */
  available: number;
  /** Busy */
  busy: number;
  /** Dead */
  dead: number;
}

/** CapacityReportOut */
export interface CapacityReportOut {
  /** Filters */
  filters: Record<string, string | null>;
  summary: CapacityStateBreakdownOut;
  /** By State */
  by_state: Record<string, number>;
  /** By Group */
  by_group?: CapacityGroupBreakdownOut[];
  /** By Relay */
  by_relay?: CapacityRelayBreakdownOut[];
  /** Sample Devices */
  sample_devices?: DeviceIdBreakdownOut[];
  /**
   * Devices Scanned
   * @default 0
   */
  devices_scanned?: number;
  /**
   * Latency Ms
   * @default 0
   */
  latency_ms?: number;
}

/** CapacityStateBreakdownOut */
export interface CapacityStateBreakdownOut {
  /**
   * Total
   * @default 0
   */
  total?: number;
  /**
   * Available
   * @default 0
   */
  available?: number;
  /**
   * Busy
   * @default 0
   */
  busy?: number;
  /**
   * Dead
   * @default 0
   */
  dead?: number;
  /**
   * Reconnecting
   * @default 0
   */
  reconnecting?: number;
  /**
   * Connecting
   * @default 0
   */
  connecting?: number;
  /**
   * Unknown
   * @default 0
   */
  unknown?: number;
}

/** ChangePasswordRequest */
export interface ChangePasswordRequest {
  /** Current Password */
  current_password: string;
  /** New Password */
  new_password: string;
}

/** ClipboardSetRequest */
export interface ClipboardSetRequest {
  /** Text */
  text: string;
}

/** CollectionCreate */
export interface CollectionCreate {
  /** Name */
  name: string;
  /**
   * Description
   * @default ""
   */
  description?: string;
  /** Platform */
  platform?: string | null;
}

/** CollectionOut */
export interface CollectionOut {
  /** Id */
  id: string;
  /** Name */
  name: string;
  /** Description */
  description: string;
  /** Platform */
  platform?: string | null;
  /** Item Count */
  item_count: number;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
}

/** CompileScenarioBody */
export interface CompileScenarioBody {
  /** Instructions */
  instructions?: string | null;
  /** Ui Xml */
  ui_xml?: string | null;
  /** Device Serial */
  device_serial?: string | null;
  /** Device Context */
  device_context?: Record<string, any> | null;
}

/**
 * ConnectByIpBody
 * Kết nối thiết bị qua ADB TCP: backend chủ động connect tới IP, không cần QR.
 */
export interface ConnectByIpBody {
  /** Ip */
  ip: string;
  /**
   * Port
   * @default 5555
   */
  port?: number;
}

/** ContentArtifactOut */
export interface ContentArtifactOut {
  /** Id */
  id: string;
  /** Kind */
  kind: string;
  /** Label */
  label: string;
  /** Source */
  source: string;
  /** Url */
  url?: string | null;
  /**
   * Inline
   * @default false
   */
  inline?: boolean;
  /** Size Bytes */
  size_bytes?: number | null;
  /**
   * Status
   * @default "available"
   */
  status?: string;
  /** Mime Type */
  mime_type?: string | null;
}

/** ContentDetailOut */
export interface ContentDetailOut {
  /** Id */
  id: string;
  /** Collection */
  collection: string;
  /** Platform */
  platform?: string | null;
  /** Content Type */
  content_type: string;
  /** Title */
  title?: string | null;
  /** Body */
  body?: string | null;
  /** Author */
  author?: string | null;
  /** Author Id */
  author_id?: string | null;
  /** Url */
  url?: string | null;
  /** Likes Count */
  likes_count?: number | null;
  /** Comments Count */
  comments_count?: number | null;
  /** Shares Count */
  shares_count?: number | null;
  /** Views Count */
  views_count?: number | null;
  /**
   * Media Urls
   * @default []
   */
  media_urls?: string[];
  /** Screenshot Path */
  screenshot_path?: string | null;
  /**
   * Tags
   * @default ""
   */
  tags?: string;
  /** Raw Data */
  raw_data?: Record<string, any> | null;
  /** Device Serial */
  device_serial?: string | null;
  /** Campaign Id */
  campaign_id?: string | null;
  /** Execution Id */
  execution_id?: string | null;
  /** Scenario Name */
  scenario_name?: string | null;
  /** Extracted At */
  extracted_at?: string | null;
  /** Content Date */
  content_date?: string | null;
  /** Created At */
  created_at?: string | null;
  /** Content Hash */
  content_hash?: string | null;
  /** Parent Id */
  parent_id?: string | null;
  /**
   * Item Level
   * @default 0
   */
  item_level?: number;
  /**
   * Artifacts
   * @default []
   */
  artifacts?: ContentArtifactOut[];
  /**
   * Payload
   * @default {}
   */
  payload?: Record<string, any>;
}

/** ContentPermalinkOut */
export interface ContentPermalinkOut {
  /** Token */
  token: string;
  /** Path */
  path: string;
}

/** ContentStatsOut */
export interface ContentStatsOut {
  /** Total Items */
  total_items: number;
  /** By Platform */
  by_platform: Record<string, number>;
  /** By Collection */
  by_collection: Record<string, number>;
  /** Latest Extraction */
  latest_extraction?: string | null;
}

/** DLQBulkRetryBody */
export interface DLQBulkRetryBody {
  /** Execution Ids */
  execution_ids?: string[];
  /** Dlq Ids */
  dlq_ids?: string[];
  /**
   * From Checkpoint
   * @default true
   */
  from_checkpoint?: boolean;
}

/** DLQBulkRetryItemOut */
export interface DLQBulkRetryItemOut {
  /** Dlq Id */
  dlq_id?: string | null;
  /** Execution Id */
  execution_id?: string | null;
  /** Status */
  status: string;
  /** Reason */
  reason?: string | null;
  /** Message */
  message?: string | null;
  /** Replayed To Execution Id */
  replayed_to_execution_id?: string | null;
  /** Entry Status */
  entry_status?: string | null;
}

/** DLQBulkRetryOut */
export interface DLQBulkRetryOut {
  /** Results */
  results: DLQBulkRetryItemOut[];
}

/** DLQCloseBody */
export interface DLQCloseBody {
  /**
   * Reason
   * @minLength 1
   */
  reason: string;
}

/** DLQEntryOut */
export interface DLQEntryOut {
  /** Id */
  id: string;
  /** Execution Id */
  execution_id: string;
  /** Device Serial */
  device_serial: string;
  /** Error */
  error: string | null;
  /** Retry Count */
  retry_count: number;
  /** Status */
  status: string;
  /** Last Attempt At */
  last_attempt_at: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /** Campaign Id */
  campaign_id?: string | null;
  /** Failed Step Id */
  failed_step_id?: string | null;
  /** Failure Reason */
  failure_reason?: string | null;
  /** Failed At */
  failed_at?: string | null;
  /** Closed By */
  closed_by?: string | null;
  /** Closed At */
  closed_at?: string | null;
  /** Close Reason */
  close_reason?: string | null;
  /** Replayed To Execution Id */
  replayed_to_execution_id?: string | null;
  /** Artifact Refs */
  artifact_refs?: Record<string, any>;
}

/** DLQRetryBody */
export interface DLQRetryBody {
  /**
   * From Checkpoint
   * @default true
   */
  from_checkpoint?: boolean;
}

/** DLQSummaryOut */
export interface DLQSummaryOut {
  /** Pending Count */
  pending_count: number;
  /** Alert Threshold */
  alert_threshold: number;
  /** Alert */
  alert: boolean;
  /**
   * Dismissed Offline Count
   * @default 0
   */
  dismissed_offline_count?: number;
  /** Offline Dismiss Minutes */
  offline_dismiss_minutes: number;
}

/** DeviceAccountOut */
export interface DeviceAccountOut {
  /** Id */
  id: string;
  /** Device Id */
  device_id: string;
  /** Account Id */
  account_id: string;
  /** Is Primary */
  is_primary: boolean;
  /**
   * Assigned At
   * @format date-time
   */
  assigned_at: string;
}

/** DeviceClaimBody */
export interface DeviceClaimBody {
  /**
   * Owner Type
   * @default "manual"
   */
  owner_type?: string;
  /**
   * Owner Id
   * @default ""
   */
  owner_id?: string;
  /** Ttl Sec */
  ttl_sec?: number | null;
  /** Ctx */
  ctx?: Record<string, any> | null;
}

/** DeviceClaimOut */
export interface DeviceClaimOut {
  /** Session Id */
  session_id: string;
  /** Device Id */
  device_id: string;
  /** Owner Type */
  owner_type: string;
  /** Owner Id */
  owner_id: string;
  /**
   * Claimed At
   * @format date-time
   */
  claimed_at: string;
  /**
   * Last Heartbeat
   * @format date-time
   */
  last_heartbeat: string;
  /** Ttl Sec */
  ttl_sec: number;
  /** Ctx */
  ctx?: Record<string, any> | null;
}

/** DeviceCreate */
export interface DeviceCreate {
  /** Serial */
  serial: string;
  /**
   * Name
   * @default ""
   */
  name?: string;
  /** User Id */
  user_id?: string | null;
}

/** DeviceGroupCreate */
export interface DeviceGroupCreate {
  /** Name */
  name: string;
  /**
   * Description
   * @default ""
   */
  description?: string;
  /**
   * Color
   * @default "#6366f1"
   */
  color?: string;
}

/**
 * DeviceGroupDetailOut
 * Extended response that includes the full device list (for GET /device-groups/{id}).
 */
export interface DeviceGroupDetailOut {
  /** Id */
  id: string;
  /** Name */
  name: string;
  /** Description */
  description: string;
  /** Color */
  color: string;
  /** User Id */
  user_id: string | null;
  /** Device Count */
  device_count: number;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /**
   * Updated At
   * @format date-time
   */
  updated_at: string;
  /**
   * Devices
   * @default []
   */
  devices?: DeviceOut[];
}

/** DeviceGroupOut */
export interface DeviceGroupOut {
  /** Id */
  id: string;
  /** Name */
  name: string;
  /** Description */
  description: string;
  /** Color */
  color: string;
  /** User Id */
  user_id: string | null;
  /** Device Count */
  device_count: number;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /**
   * Updated At
   * @format date-time
   */
  updated_at: string;
}

/** DeviceGroupUpdate */
export interface DeviceGroupUpdate {
  /** Name */
  name?: string | null;
  /** Description */
  description?: string | null;
  /** Color */
  color?: string | null;
}

/** DeviceIdBreakdownOut */
export interface DeviceIdBreakdownOut {
  /** Db Id */
  db_id: string;
  /** Device Serial */
  device_serial: string;
  /** Adb Serial */
  adb_serial?: string | null;
  /** Relay Serial */
  relay_serial?: string | null;
}

/** DeviceOut */
export interface DeviceOut {
  /** Id */
  id: string;
  /** Db Id */
  db_id?: string | null;
  /** Serial */
  serial: string;
  /**
   * Device Serial
   * @default ""
   */
  device_serial?: string;
  /** Name */
  name: string;
  /** Device Key */
  device_key: string;
  /** User Id */
  user_id: string | null;
  /** Brand */
  brand: string;
  /** Model */
  model: string;
  /** Android Version */
  android_version: string;
  /** Sdk Version */
  sdk_version: number;
  /** Screen Width */
  screen_width: number;
  /** Screen Height */
  screen_height: number;
  /** Last Seen */
  last_seen: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /** Adb Serial */
  adb_serial?: string | null;
  /** Relay Serial */
  relay_serial?: string | null;
  /** Adb Ip */
  adb_ip?: string | null;
  /**
   * Adb Port
   * @default 5555
   */
  adb_port?: number;
  /**
   * Tags
   * @default ""
   */
  tags?: string;
  /** Relay Id */
  relay_id?: string | null;
  /**
   * State
   * @default "unknown"
   */
  state?: string;
  /**
   * Status
   * @default "paired"
   */
  status?: string;
  /** Paired At */
  paired_at?: string | null;
  /** Unpaired At */
  unpaired_at?: string | null;
  /**
   * Notes
   * @default ""
   */
  notes?: string;
}

/** DeviceReleaseBody */
export interface DeviceReleaseBody {
  /** Session Id */
  session_id: string;
}

/** DeviceReserveSessionOut */
export interface DeviceReserveSessionOut {
  /** Session Id */
  session_id: string;
  /** Device Id */
  device_id: string;
  /** Owner Type */
  owner_type: string;
  /** Owner Id */
  owner_id: string;
  /**
   * Claimed At
   * @format date-time
   */
  claimed_at: string;
  /**
   * Last Heartbeat
   * @format date-time
   */
  last_heartbeat: string;
  /** Ttl Sec */
  ttl_sec: number;
  /** Ctx */
  ctx?: Record<string, any> | null;
}

/** DeviceReviveOut */
export interface DeviceReviveOut {
  /** Device Id */
  device_id: string;
  /** From State */
  from_state: string;
  /** To State */
  to_state: string;
  /** Actor */
  actor: string;
}

/** DeviceStateCountsOut */
export interface DeviceStateCountsOut {
  /**
   * Unknown
   * @default 0
   */
  unknown?: number;
  /**
   * Connecting
   * @default 0
   */
  connecting?: number;
  /**
   * Online
   * @default 0
   */
  online?: number;
  /**
   * Busy
   * @default 0
   */
  busy?: number;
  /**
   * Reconnecting
   * @default 0
   */
  reconnecting?: number;
  /**
   * Dead
   * @default 0
   */
  dead?: number;
  /**
   * Total
   * @default 0
   */
  total?: number;
}

/** DoubleTapRequest */
export interface DoubleTapRequest {
  /** X */
  x: number;
  /** Y */
  y: number;
}

/** DragRequest */
export interface DragRequest {
  /** X1 */
  x1: number;
  /** Y1 */
  y1: number;
  /** X2 */
  x2: number;
  /** Y2 */
  y2: number;
  /**
   * Duration Ms
   * @default 1000
   */
  duration_ms?: number;
}

/** EndSessionRequest */
export interface EndSessionRequest {
  /** Session Id */
  session_id: string;
}

/** ExecutionArtifactOut */
export interface ExecutionArtifactOut {
  /** Artifact Type */
  artifact_type: string;
  /** Execution Id */
  execution_id: string;
  /** Device Serial */
  device_serial?: string | null;
  /** Step Index */
  step_index?: number | null;
  /** Step Type */
  step_type?: string | null;
  /** Ok */
  ok?: boolean | null;
  /** Message */
  message?: string | null;
  /** Url */
  url?: string | null;
  /** Metadata */
  metadata?: Record<string, any>;
  /** Created At */
  created_at?: string | null;
}

/** ExecutionCancelBody */
export interface ExecutionCancelBody {
  /**
   * Reason
   * @maxLength 2000
   * @default ""
   */
  reason?: string;
}

/** ExecutionControlOut */
export interface ExecutionControlOut {
  /** Execution Id */
  execution_id: string;
  /** Status */
  status: string;
  /** Action */
  action: string;
  /** Effective Transition */
  effective_transition: boolean;
  /**
   * Workflows Signalled
   * @default 0
   */
  workflows_signalled?: number;
  /** Warning */
  warning?: string | null;
}

/** ExecutionCreate */
export interface ExecutionCreate {
  /**
   * Run Type
   * @minLength 1
   * @maxLength 50
   */
  run_type: string;
  /** Campaign Id */
  campaign_id?: string | null;
  /** Scenario Id */
  scenario_id?: string | null;
  /** Device Ids */
  device_ids?: string[];
  /** Device Config */
  device_config?: Record<string, any>;
  /** Loop Config */
  loop_config?: Record<string, any>;
  /** Error Config */
  error_config?: Record<string, any>;
  /** Meta */
  meta?: Record<string, any>;
}

/** ExecutionEventListOut */
export interface ExecutionEventListOut {
  /** Items */
  items: ExecutionEventOut[];
  /**
   * Has More
   * @default false
   */
  has_more?: boolean;
}

/** ExecutionEventOut */
export interface ExecutionEventOut {
  /** Event Id */
  event_id: string;
  /** Event Type */
  event_type: string;
  /** Schema Version */
  schema_version: string;
  /**
   * Occurred At
   * @format date-time
   */
  occurred_at: string;
  /** Organization Id */
  organization_id: string;
  /** Campaign Id */
  campaign_id?: string | null;
  /** Execution Id */
  execution_id: string;
  /** Step Id */
  step_id?: string | null;
  /** Payload */
  payload?: Record<string, any>;
  /** Tags */
  tags?: string[];
}

/** ExecutionListOut */
export interface ExecutionListOut {
  /** Total */
  total: number;
  /** Items */
  items: ExecutionOut[];
}

/** ExecutionOut */
export interface ExecutionOut {
  /** Id */
  id: string;
  /** Run Type */
  run_type: string;
  /** Status */
  status: string;
  /** Campaign Id */
  campaign_id: string | null;
  /** Scenario Id */
  scenario_id: string | null;
  /** Scenario Version Id */
  scenario_version_id?: string | null;
  /** Device Config */
  device_config: Record<string, any>;
  /** Loop Config */
  loop_config: Record<string, any>;
  /** Error Config */
  error_config: Record<string, any>;
  /** Meta */
  meta: Record<string, any>;
  /** User Id */
  user_id: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /** Started At */
  started_at: string | null;
  /** Finished At */
  finished_at: string | null;
  /** Pause Signal Received At */
  pause_signal_received_at?: string | null;
  /** Cancel Signal Received At */
  cancel_signal_received_at?: string | null;
  /** Cancelled At */
  cancelled_at?: string | null;
  /** Cancel Reason */
  cancel_reason?: string | null;
}

/** ExecutionPatch */
export interface ExecutionPatch {
  /** Status */
  status?: string | null;
  /** Device Config */
  device_config?: Record<string, any> | null;
  /** Loop Config */
  loop_config?: Record<string, any> | null;
  /** Error Config */
  error_config?: Record<string, any> | null;
  /** Meta */
  meta?: Record<string, any> | null;
}

/** ExecutionResultOut */
export interface ExecutionResultOut {
  /** Id */
  id: string;
  /** Execution Id */
  execution_id: string;
  /** Device Id */
  device_id: string;
  /** Status */
  status: string;
  /** Run Time Sec */
  run_time_sec: number | null;
  /** Passed Steps */
  passed_steps: any[];
  /** Failed Steps */
  failed_steps: any[];
  /** Error Detail */
  error_detail: string | null;
  /** Started At */
  started_at: string | null;
  /** Finished At */
  finished_at: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
}

/** ExecutionStepOut */
export interface ExecutionStepOut {
  /** Id */
  id: string;
  /** Execution Id */
  execution_id: string;
  /** Step Index */
  step_index: number;
  /** Step Id */
  step_id?: string | null;
  /** Step Type */
  step_type?: string | null;
  /** Status */
  status: string;
  /** Started At */
  started_at?: string | null;
  /** Ended At */
  ended_at?: string | null;
  /** Duration Ms */
  duration_ms?: number | null;
  /** Error Json */
  error_json?: Record<string, any>;
  /** Effective Config Json */
  effective_config_json?: Record<string, any>;
  /** Artifacts Json */
  artifacts_json?: any[];
  /** Attempts Json */
  attempts_json?: any[];
  /**
   * Marked Ignored
   * @default false
   */
  marked_ignored?: boolean;
  /** Message */
  message?: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /**
   * Updated At
   * @format date-time
   */
  updated_at: string;
}

/** FinishBody */
export interface FinishBody {
  /**
   * Status
   * @default "completed"
   * @pattern ^(completed|failed|cancelled)$
   */
  status?: string;
}

/** FleetStatsFiltersOut */
export interface FleetStatsFiltersOut {
  /** Organization Id */
  organization_id: string;
  /** Group Id */
  group_id?: string | null;
  /** Relay Host */
  relay_host?: string | null;
}

/** FleetStatsOut */
export interface FleetStatsOut {
  filters: FleetStatsFiltersOut;
  devices: DeviceStateCountsOut;
  active_sessions: SessionOwnerCountsOut;
  /**
   * Owner Anomalies
   * Null for read-only callers; empty list or anomalies for devices:manage callers.
   */
  owner_anomalies?: SessionOwnerAnomalyOut[] | null;
}

/**
 * FlowEdgeModel
 * Directed edge between two nodes.
 */
export interface FlowEdgeModel {
  /**
   * Id
   * @minLength 1
   */
  id: string;
  /**
   * Source
   * @minLength 1
   */
  source: string;
  /**
   * Target
   * @minLength 1
   */
  target: string;
  /** Sourcehandle */
  sourceHandle?: string | null;
  /** Targethandle */
  targetHandle?: string | null;
  /**
   * Type
   * @default "default"
   */
  type?: "default" | "conditional" | "error" | "fallback";
  /** Condition */
  condition?: string | null;
  [key: string]: any;
}

/**
 * FlowNodeModel
 * Single node in the scenario graph.
 */
export interface FlowNodeModel {
  /**
   * Id
   * @minLength 1
   */
  id: string;
  /**
   * Type
   * @minLength 1
   */
  type: string;
  /**
   * Config
   * @default {}
   */
  config?: Record<string, any>;
  /**
   * Order
   * @minLength 1
   */
  order: string;
  scope?: NodeScope | null;
  /** Position */
  position?: Record<string, number> | null;
  /** Title */
  title?: string | null;
  /** Description */
  description?: string | null;
  [key: string]: any;
}

/** HTTPValidationError */
export interface HTTPValidationError {
  /** Detail */
  detail?: ValidationError[];
}

/** HierarchyExtractBody */
export interface HierarchyExtractBody {
  /** Filter Class */
  filter_class?: string[] | null;
  /**
   * Exclude Empty
   * @default true
   */
  exclude_empty?: boolean;
  /**
   * Format
   * @default "text"
   */
  format?: string;
  /**
   * Strategy
   * @default "screen_data"
   */
  strategy?: string;
}

/** HitTestRequest */
export interface HitTestRequest {
  /**
   * X
   * @default 0
   */
  x?: number;
  /**
   * Y
   * @default 0
   */
  y?: number;
  /**
   * Rx
   * @default -1
   */
  rx?: number;
  /**
   * Ry
   * @default -1
   */
  ry?: number;
}

/** InputTextRequest */
export interface InputTextRequest {
  /** Text */
  text: string;
}

/** KeyRequest */
export interface KeyRequest {
  /** Key */
  key: string;
}

/** LaunchAppRequest */
export interface LaunchAppRequest {
  /** Package */
  package: string;
}

/** LoginRequest */
export interface LoginRequest {
  /** Email */
  email: string;
  /** Password */
  password: string;
}

/** LogoutRequest */
export interface LogoutRequest {
  /** Refresh Token */
  refresh_token?: string | null;
}

/** LongTapRequest */
export interface LongTapRequest {
  /** X */
  x: number;
  /** Y */
  y: number;
  /**
   * Duration Ms
   * @default 800
   */
  duration_ms?: number;
}

/** McpTokenCreate */
export interface McpTokenCreate {
  /**
   * Name
   * @maxLength 120
   * @default "MCP agent token"
   */
  name?: string;
  /** Scope Type */
  scope_type: "device" | "user";
  /** Scope Ref */
  scope_ref?: string | null;
  /**
   * Preview Consent
   * @default false
   */
  preview_consent?: boolean;
}

/** NodeScope */
export interface NodeScope {
  /** Parentid */
  parentId: string;
  /**
   * Branch
   * @default "steps"
   */
  branch?: string;
}

/** NotificationChannelCreate */
export interface NotificationChannelCreate {
  /**
   * Name
   * @minLength 1
   * @maxLength 255
   */
  name: string;
  /**
   * Type
   * @pattern ^(in_app|telegram|webhook|email|slack)$
   */
  type: string;
  /** Config */
  config?: Record<string, any>;
  /** Events */
  events?: string[];
  /**
   * Is Enabled
   * @default true
   */
  is_enabled?: boolean;
}

/** NotificationChannelOut */
export interface NotificationChannelOut {
  /** Id */
  id: string;
  /** Name */
  name: string;
  /** Type */
  type: string;
  /** Config */
  config: Record<string, any>;
  /** Events */
  events: string[];
  /** Is Enabled */
  is_enabled: boolean;
  /** User Id */
  user_id: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
}

/** NotificationChannelPatch */
export interface NotificationChannelPatch {
  /** Name */
  name?: string | null;
  /** Type */
  type?: string | null;
  /** Config */
  config?: Record<string, any> | null;
  /** Events */
  events?: string[] | null;
  /** Is Enabled */
  is_enabled?: boolean | null;
}

/** NotificationListOut */
export interface NotificationListOut {
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
  /** Notifications */
  notifications: NotificationOut[];
}

/** NotificationOut */
export interface NotificationOut {
  /** Id */
  id: string;
  /** Channel Id */
  channel_id: string | null;
  /** Event */
  event: string;
  /** Title */
  title: string;
  /** Body */
  body: string | null;
  /** Data */
  data: Record<string, any>;
  /** Is Read */
  is_read: boolean;
  /** Read At */
  read_at?: string | null;
  /**
   * Sent At
   * @format date-time
   */
  sent_at: string;
  /** User Id */
  user_id: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /** Unread Count */
  unread_count?: number | null;
}

/** OCRExtractBody */
export interface OCRExtractBody {
  /** Languages */
  languages?: string[];
  /** Region */
  region?: Record<string, number> | null;
  /**
   * Psm
   * @default 11
   */
  psm?: number;
  /**
   * Scale Factor
   * @default 2
   */
  scale_factor?: number;
  /**
   * Confidence Threshold
   * @default 0.5
   */
  confidence_threshold?: number;
}

/** OpenUrlRequest */
export interface OpenUrlRequest {
  /** Url */
  url: string;
  /** Package */
  package?: string | null;
}

/** OrgScenarioBodyIn */
export interface OrgScenarioBodyIn {
  /** Steps */
  steps?: Record<string, any>[] | null;
  /** Nodes */
  nodes?: Record<string, any>[] | null;
  /** Edges */
  edges?: Record<string, any>[] | null;
  /** Variables */
  variables?: Record<string, any> | null;
}

/** OrgScenarioBodyOut */
export interface OrgScenarioBodyOut {
  /** Scenario Id */
  scenario_id: string;
  /** Kind */
  kind: string;
  /** Scenario Version */
  scenario_version: number;
  /** Body Json */
  body_json: Record<string, any>;
  /** Is Runnable */
  is_runnable: boolean;
  /** Validation */
  validation?: Record<string, any>;
}

/** OrgScenarioCloneTemplateIn */
export interface OrgScenarioCloneTemplateIn {
  /** Name Override */
  name_override?: string | null;
}

/** OrgScenarioCreate */
export interface OrgScenarioCreate {
  /**
   * Name
   * @minLength 1
   * @maxLength 255
   */
  name: string;
  /**
   * Kind
   * @default "sequence"
   */
  kind?: "sequence" | "graph";
  /**
   * Description
   * @default ""
   */
  description?: string;
  /** Body Json */
  body_json?: Record<string, any> | null;
  /** Tags */
  tags?: string[];
}

/** OrgScenarioImportOut */
export interface OrgScenarioImportOut {
  /** Scenario Id */
  scenario_id: string;
  /** Name */
  name: string;
  /** Kind */
  kind: string;
  /** Status */
  status: string;
  /** Scenario Version */
  scenario_version: number;
  /** Warnings */
  warnings?: string[];
  /** Created Stub Names */
  created_stub_names?: string[];
}

/** OrgScenarioOut */
export interface OrgScenarioOut {
  /** Id */
  id: string;
  /** Organization Id */
  organization_id: string;
  /**
   * Is System Template
   * @default false
   */
  is_system_template?: boolean;
  /** Name */
  name: string;
  /** Description */
  description: string;
  /** Kind */
  kind: string;
  /** Status */
  status: string;
  /** Scenario Version */
  scenario_version: number;
  /** Tags */
  tags?: string[];
  /** Created By */
  created_by?: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /**
   * Updated At
   * @format date-time
   */
  updated_at: string;
  /**
   * Is Runnable
   * @default false
   */
  is_runnable?: boolean;
  /**
   * Is Recovery Scenario
   * @default false
   */
  is_recovery_scenario?: boolean;
  /**
   * Recovery Usage Count
   * @default 0
   */
  recovery_usage_count?: number;
  /** Last Validation Summary */
  last_validation_summary?: Record<string, any> | null;
  /** Last Validated At */
  last_validated_at?: string | null;
  /** Body Json */
  body_json?: Record<string, any> | null;
}

/** OrgScenarioSummaryOut */
export interface OrgScenarioSummaryOut {
  /** Id */
  id: string;
  /** Organization Id */
  organization_id: string;
  /**
   * Is System Template
   * @default false
   */
  is_system_template?: boolean;
  /** Name */
  name: string;
  /** Description */
  description: string;
  /** Kind */
  kind: string;
  /** Status */
  status: string;
  /** Scenario Version */
  scenario_version: number;
  /** Tags */
  tags?: string[];
  /** Created By */
  created_by?: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /**
   * Updated At
   * @format date-time
   */
  updated_at: string;
  /**
   * Is Runnable
   * @default false
   */
  is_runnable?: boolean;
  /**
   * Is Recovery Scenario
   * @default false
   */
  is_recovery_scenario?: boolean;
  /**
   * Recovery Usage Count
   * @default 0
   */
  recovery_usage_count?: number;
  /** Last Validation Summary */
  last_validation_summary?: Record<string, any> | null;
  /** Last Validated At */
  last_validated_at?: string | null;
}

/** OrgScenarioUpdate */
export interface OrgScenarioUpdate {
  /** Name */
  name?: string | null;
  /** Kind */
  kind?: "sequence" | "graph" | null;
  /** Description */
  description?: string | null;
  /** Status */
  status?: "draft" | "active" | "archived" | null;
  /** Body Json */
  body_json?: Record<string, any> | null;
  /** Tags */
  tags?: string[] | null;
}

/** OrgScenarioValidateIn */
export interface OrgScenarioValidateIn {
  /** Steps */
  steps?: Record<string, any>[] | null;
  /** Nodes */
  nodes?: Record<string, any>[] | null;
  /** Edges */
  edges?: Record<string, any>[] | null;
  /** Variables */
  variables?: Record<string, any> | null;
  /** Campaign Variables */
  campaign_variables?: Record<string, any> | null;
}

/** OrgScenarioValidationOut */
export interface OrgScenarioValidationOut {
  /** Scenario Id */
  scenario_id: string;
  /** Status */
  status: string;
  /** Errors */
  errors?: ApiSchemasOrgScenarioValidationIssueOut[];
  /** Warnings */
  warnings?: ApiSchemasOrgScenarioValidationIssueOut[];
  /** Infos */
  infos?: ApiSchemasOrgScenarioValidationIssueOut[];
  /** Last Validated At */
  last_validated_at?: string | null;
  /** Last Validation Summary */
  last_validation_summary?: Record<string, any> | null;
}

/** OrganizationCreate */
export interface OrganizationCreate {
  /** Businessname */
  businessName: string;
  /** Businessemail */
  businessEmail?: string | null;
  /** Businesslogo */
  businessLogo?: string | null;
}

/** OrganizationInvitationAccept */
export interface OrganizationInvitationAccept {
  /** Token */
  token: string;
}

/** OrganizationInvitationAcceptOut */
export interface OrganizationInvitationAcceptOut {
  /** Organizationid */
  organizationId: string;
  /** Organizationname */
  organizationName: string;
}

/** OrganizationInvitationPreview */
export interface OrganizationInvitationPreview {
  /** Organizationname */
  organizationName: string;
  /** Email */
  email: string;
  /** Status */
  status: string;
  /** Expired */
  expired: boolean;
  /** Existinguser */
  existingUser: boolean;
}

/** OrganizationListOut */
export interface OrganizationListOut {
  /** Items */
  items: OrganizationOut[];
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
}

/** OrganizationMemberInvite */
export interface OrganizationMemberInvite {
  /** Email */
  email: string;
  /**
   * Role
   * @default "member"
   */
  role?: string;
}

/** OrganizationMemberInviteOut */
export interface OrganizationMemberInviteOut {
  /** Email */
  email: string;
  /** Status */
  status: string;
  /** Existinguser */
  existingUser: boolean;
  /** Emailsent */
  emailSent: boolean;
}

/** OrganizationMemberOut */
export interface OrganizationMemberOut {
  /** Id */
  id: string;
  /** Userid */
  userId: string;
  /** Email */
  email: string;
  /** Name */
  name: string;
  /** Role */
  role: string;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
}

/** OrganizationMemberUpdate */
export interface OrganizationMemberUpdate {
  /** Role */
  role: string;
}

/** OrganizationOut */
export interface OrganizationOut {
  /** Id */
  id: string;
  /** Businessname */
  businessName: string;
  /** Businessemail */
  businessEmail: string | null;
  /** Businesslogo */
  businessLogo: string | null;
  /** Slug */
  slug?: string | null;
  /** Status */
  status?: string | null;
  /** Plan */
  plan?: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
}

/** PairRegistryBody */
export interface PairRegistryBody {
  /** Device Serial */
  device_serial: string;
  /**
   * Adb Serial
   * @default ""
   */
  adb_serial?: string;
  /**
   * Relay Serial
   * @default ""
   */
  relay_serial?: string;
  /**
   * Name
   * @default ""
   */
  name?: string;
  /**
   * Model
   * @default ""
   */
  model?: string;
  /**
   * Android Version
   * @default ""
   */
  android_version?: string;
}

/** PairRegistryOut */
export interface PairRegistryOut {
  /** Db Id */
  db_id: string;
  /** Device Serial */
  device_serial: string;
  /** Adb Serial */
  adb_serial?: string | null;
  /** Relay Serial */
  relay_serial?: string | null;
  /** Status */
  status: string;
  /**
   * Device Key
   * Plaintext device key — returned only on first pair
   */
  device_key?: string | null;
  /** Device Key Disclaimer */
  device_key_disclaimer?: string | null;
  /** Created */
  created: boolean;
}

/** PinchRequest */
export interface PinchRequest {
  /** Cx */
  cx: number;
  /** Cy */
  cy: number;
  /**
   * Scale
   * @default 0.5
   */
  scale?: number;
  /**
   * Duration Ms
   * @default 400
   */
  duration_ms?: number;
}

/** PlatformFlagBody */
export interface PlatformFlagBody {
  /**
   * Note
   * @default ""
   */
  note?: string;
}

/** PlatformLifecycleBody */
export interface PlatformLifecycleBody {
  /** Version */
  version?: string | null;
  /**
   * Note
   * @default ""
   */
  note?: string;
}

/** PreviewListItem */
export interface PreviewListItem {
  /** Execution Id */
  execution_id: string;
  /** Status */
  status: string;
  /**
   * Kind
   * @default "preview"
   */
  kind?: string;
  /** Org Scenario Id */
  org_scenario_id?: string | null;
  /** Org Scenario Name */
  org_scenario_name?: string | null;
  /** Device Id */
  device_id?: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /** Finished At */
  finished_at?: string | null;
  /**
   * Artifact Count
   * @default 0
   */
  artifact_count?: number;
  /**
   * Artifacts Purged
   * @default false
   */
  artifacts_purged?: boolean;
  /** Warnings */
  warnings?: string[];
}

/** PreviewListResponse */
export interface PreviewListResponse {
  /** Total */
  total: number;
  /** Items */
  items: PreviewListItem[];
}

/** PreviewStartRequest */
export interface PreviewStartRequest {
  /** Device Id */
  device_id: string;
  /** Scenario Version */
  scenario_version?: number | null;
  /** Vars */
  vars?: Record<string, any>;
  /** Account Id */
  account_id?: string | null;
  /**
   * Force
   * @default false
   */
  force?: boolean;
}

/** PreviewStartResponse */
export interface PreviewStartResponse {
  /** Execution Id */
  execution_id: string;
  /** Status */
  status: string;
  /**
   * Kind
   * @default "preview"
   */
  kind?: string;
  /** Warnings */
  warnings?: string[];
  /** Workflow Id */
  workflow_id?: string | null;
  /** Dispatch Source */
  dispatch_source?: string | null;
  /** Org Scenario Id */
  org_scenario_id: string;
  /** Device Id */
  device_id: string;
}

/** ReconnectPolicyOut */
export interface ReconnectPolicyOut {
  /** Org Id */
  org_id: string;
  /** Interval Base Ms */
  interval_base_ms: number;
  /** Max Interval Ms */
  max_interval_ms: number;
  /** Max Attempts */
  max_attempts: number;
  /** Jitter Factor */
  jitter_factor: number;
  /** Updated At */
  updated_at: string;
  /** Updated By */
  updated_by?: string | null;
  /**
   * Source
   * default or configured
   */
  source: string;
}

/** ReconnectPolicyUpdate */
export interface ReconnectPolicyUpdate {
  /** Interval Base Ms */
  interval_base_ms: number;
  /** Max Interval Ms */
  max_interval_ms: number;
  /** Max Attempts */
  max_attempts: number;
  /** Jitter Factor */
  jitter_factor: number;
}

/** RefreshRequest */
export interface RefreshRequest {
  /** Refresh Token */
  refresh_token: string;
}

/** RegisterDeviceBody */
export interface RegisterDeviceBody {
  /**
   * Name
   * @default ""
   */
  name?: string;
  /**
   * Description
   * @default ""
   */
  description?: string;
}

/** RegisterRelayDeviceBody */
export interface RegisterRelayDeviceBody {
  /**
   * Name
   * @default ""
   */
  name?: string;
}

/** RegisterRequest */
export interface RegisterRequest {
  /** Email */
  email: string;
  /** Name */
  name: string;
  /** Password */
  password: string;
  /**
   * Role
   * @default "operator"
   */
  role?: string;
  /** Invitetoken */
  inviteToken?: string | null;
}

/** RelayAgentOut */
export interface RelayAgentOut {
  /** Relay Id */
  relay_id: string;
  /** User Id */
  user_id?: string | null;
  /** Enrollment Token Id */
  enrollment_token_id?: string | null;
  /** Hostname */
  hostname: string;
  /** Ip */
  ip: string;
  /** Version */
  version: string;
  /** Serials */
  serials: string[];
  /** Device Names */
  device_names?: Record<string, string>;
  /** Status */
  status: string;
  /**
   * Live Connected
   * @default false
   */
  live_connected?: boolean;
  /**
   * Connected At
   * @format date-time
   */
  connected_at: string;
  /** Last Heartbeat At */
  last_heartbeat_at?: string | null;
  /** Disconnected At */
  disconnected_at?: string | null;
}

/** RelayAgentTokenCreate */
export interface RelayAgentTokenCreate {
  /**
   * Name
   * @default ""
   */
  name?: string;
}

/** RelayAgentTokenCreated */
export interface RelayAgentTokenCreated {
  /** Id */
  id: string;
  /** Name */
  name: string;
  /** Prefix */
  prefix: string;
  /** Status */
  status: string;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /** Last Used At */
  last_used_at?: string | null;
  /** Revoked At */
  revoked_at?: string | null;
  /** Token */
  token: string;
}

/** RelayAgentTokenOut */
export interface RelayAgentTokenOut {
  /** Id */
  id: string;
  /** Name */
  name: string;
  /** Prefix */
  prefix: string;
  /** Status */
  status: string;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /** Last Used At */
  last_used_at?: string | null;
  /** Revoked At */
  revoked_at?: string | null;
}

/** RelayBatchJobCreate */
export interface RelayBatchJobCreate {
  /** Serials */
  serials?: string[];
  /**
   * Mode
   * @default "selected"
   */
  mode?: "selected" | "all_visible";
  /**
   * Connect
   * @default true
   */
  connect?: boolean;
}

/** RelayBatchJobItemOut */
export interface RelayBatchJobItemOut {
  /** Id */
  id: string;
  /** Serial */
  serial: string;
  /** Device Id */
  device_id?: string | null;
  /** Status */
  status: string;
  /**
   * Step
   * @default ""
   */
  step?: string;
  /**
   * Attempts
   * @default 0
   */
  attempts?: number;
  /**
   * Error
   * @default ""
   */
  error?: string;
  /** Result */
  result?: Record<string, any>;
}

/** RelayBatchJobOut */
export interface RelayBatchJobOut {
  /** Id */
  id: string;
  /** Relay Id */
  relay_id: string;
  /** Kind */
  kind: string;
  /** Status */
  status: string;
  /** Total */
  total: number;
  /** Ok */
  ok: number;
  /** Failed */
  failed: number;
  /** Pending */
  pending: number;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /** Started At */
  started_at?: string | null;
  /** Finished At */
  finished_at?: string | null;
  /**
   * Updated At
   * @format date-time
   */
  updated_at: string;
  /** Items */
  items?: RelayBatchJobItemOut[];
}

/** RelayCommandOut */
export interface RelayCommandOut {
  /** Ok */
  ok: boolean;
  /**
   * Output
   * @default ""
   */
  output?: string;
  /**
   * Exit Code
   * @default -1
   */
  exit_code?: number;
  /**
   * Error
   * @default ""
   */
  error?: string;
}

/** ReorderScenariosBody */
export interface ReorderScenariosBody {
  /** Ordered Ids */
  ordered_ids: string[];
  /** Scenario Id */
  scenario_id?: string | null;
}

/** RoundRobinBody */
export interface RoundRobinBody {
  /** Account Ids */
  account_ids: string[];
  /** Device Ids */
  device_ids: string[];
}

/** SaveContentBody */
export interface SaveContentBody {
  /** Data */
  data: Record<string, any>;
  /**
   * Collection
   * @default "default"
   */
  collection?: string;
  /** Platform */
  platform?: string | null;
  /**
   * Content Type
   * @default "fb_post"
   */
  content_type?: string;
  /** Dedupe Field */
  dedupe_field?: string | null;
  /**
   * Dedup Action
   * @default "skip"
   */
  dedup_action?: string;
  /**
   * Tags
   * @default ""
   */
  tags?: string;
  /** Device Serial */
  device_serial?: string | null;
  /** Campaign Id */
  campaign_id?: string | null;
}

/** ScenarioCreate */
export interface ScenarioCreate {
  /**
   * Name
   * @default "Scenario"
   */
  name?: string;
  /**
   * Instructions
   * @default ""
   */
  instructions?: string;
  /**
   * Steps
   * @default []
   */
  steps?: any[];
  /**
   * Variables
   * @default {}
   */
  variables?: Record<string, any>;
  /**
   * Order
   * @default 0
   */
  order?: number;
  /**
   * Nodes
   * @default []
   */
  nodes?: FlowNodeModel[];
  /**
   * Edges
   * @default []
   */
  edges?: FlowEdgeModel[];
  /** Account Group Id */
  account_group_id?: string | null;
}

/** ScenarioDeviceVariablesBody */
export interface ScenarioDeviceVariablesBody {
  /** Vars */
  vars?: Record<string, any>;
}

/** ScenarioDeviceVariablesOut */
export interface ScenarioDeviceVariablesOut {
  /** Scenario Id */
  scenario_id: string;
  /** Device Id */
  device_id: string;
  /** Vars */
  vars: Record<string, any>;
}

/** ScenarioOut */
export interface ScenarioOut {
  /** Id */
  id: string;
  /** Campaign Id */
  campaign_id: string;
  /** Name */
  name: string;
  /** Instructions */
  instructions: string;
  /** Steps */
  steps: any[];
  /** Variables */
  variables: Record<string, any>;
  /** Order */
  order: number;
  /**
   * Nodes
   * @default []
   */
  nodes?: any[];
  /**
   * Edges
   * @default []
   */
  edges?: any[];
  /** Account Group Id */
  account_group_id?: string | null;
  /** Account Group Name */
  account_group_name?: string | null;
  last_validation_summary?: ScenarioValidationSummaryOut | null;
  /** Last Validated At */
  last_validated_at?: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /**
   * Updated At
   * @format date-time
   */
  updated_at: string;
}

/** ScenarioPreviewRequest */
export interface ScenarioPreviewRequest {
  /** Steps */
  steps: Record<string, any>[];
  /**
   * Variables
   * @default {}
   */
  variables?: Record<string, any>;
  /** Scenario Id */
  scenario_id?: string | null;
  /**
   * Scenario Device Vars
   * @default {}
   */
  scenario_device_vars?: Record<string, any>;
  /** Account Group Id */
  account_group_id?: string | null;
}

/** ScenarioTemplateCreate */
export interface ScenarioTemplateCreate {
  /** Name */
  name: string;
  /**
   * Display Name
   * @default ""
   */
  display_name?: string;
  /**
   * Description
   * @default ""
   */
  description?: string;
  /**
   * Category
   * @default "general"
   */
  category?: string;
  /**
   * Steps
   * @default []
   */
  steps?: any[];
  /**
   * Variables
   * @default {}
   */
  variables?: Record<string, any>;
  /**
   * Tags
   * @default ""
   */
  tags?: string;
}

/** ScenarioTemplateOut */
export interface ScenarioTemplateOut {
  /** Id */
  id: string;
  /** Name */
  name: string;
  /**
   * Display Name
   * @default ""
   */
  display_name?: string;
  /** Description */
  description: string;
  /** Category */
  category: string;
  /** Steps */
  steps: any[];
  /** Variables */
  variables: Record<string, any>;
  /** Tags */
  tags: string;
  /** Is Builtin */
  is_builtin: boolean;
  /** User Id */
  user_id: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /**
   * Updated At
   * @format date-time
   */
  updated_at: string;
}

/** ScenarioTemplateUpdate */
export interface ScenarioTemplateUpdate {
  /** Name */
  name?: string | null;
  /** Display Name */
  display_name?: string | null;
  /** Description */
  description?: string | null;
  /** Category */
  category?: string | null;
  /** Steps */
  steps?: any[] | null;
  /** Variables */
  variables?: Record<string, any> | null;
  /** Tags */
  tags?: string | null;
}

/** ScenarioUpdate */
export interface ScenarioUpdate {
  /** Name */
  name?: string | null;
  /** Instructions */
  instructions?: string | null;
  /** Steps */
  steps?: any[] | null;
  /** Variables */
  variables?: Record<string, any> | null;
  /** Order */
  order?: number | null;
  /** Nodes */
  nodes?: FlowNodeModel[] | null;
  /** Edges */
  edges?: FlowEdgeModel[] | null;
  /** Account Group Id */
  account_group_id?: string | null;
}

/** ScenarioUpdateBody */
export interface ScenarioUpdateBody {
  /** Scenario */
  scenario: Record<string, any>;
}

/** ScenarioValidationOut */
export interface ScenarioValidationOut {
  /** Status */
  status: "valid" | "invalid";
  /** Errors */
  errors?: ApiSchemasScenarioValidationValidationIssueOut[];
  /** Warnings */
  warnings?: ApiSchemasScenarioValidationValidationIssueOut[];
  /** Infos */
  infos?: ApiSchemasScenarioValidationValidationIssueOut[];
  /** Last Validated At */
  last_validated_at?: string | null;
}

/** ScenarioValidationSummaryOut */
export interface ScenarioValidationSummaryOut {
  /** Status */
  status: "valid" | "invalid";
  /**
   * Error Count
   * @default 0
   */
  error_count?: number;
  /**
   * Warning Count
   * @default 0
   */
  warning_count?: number;
  /**
   * Info Count
   * @default 0
   */
  info_count?: number;
  /** Codes */
  codes?: string[];
}

/** ScheduleConflictOut */
export interface ScheduleConflictOut {
  /** Conflict Id */
  conflict_id: string;
  /** Type */
  type: string;
  /** Severity */
  severity: string;
  /** Impacted Target */
  impacted_target: string;
  /** Suggested Action */
  suggested_action: string;
}

/** ScheduleCreate */
export interface ScheduleCreate {
  /**
   * Name
   * @minLength 1
   * @maxLength 255
   */
  name: string;
  /**
   * Description
   * @default ""
   */
  description?: string;
  /**
   * Target Type
   * @pattern ^(campaign|template|fleet)$
   */
  target_type: string;
  /** Target Id */
  target_id?: string | null;
  /** Inline Steps */
  inline_steps?: Record<string, any>[] | null;
  /** Inline Variables */
  inline_variables?: Record<string, any>;
  /** Device Group Id */
  device_group_id?: string | null;
  /**
   * Filter State
   * @default "READY"
   */
  filter_state?: string;
  /** Filter Model */
  filter_model?: string | null;
  /** Max Devices */
  max_devices?: number | null;
  /** Cron Expression */
  cron_expression?: string | null;
  /**
   * Timezone
   * @default "Asia/Ho_Chi_Minh"
   */
  timezone?: string;
  /** Run At */
  run_at?: string | null;
  /** Skip Dates */
  skip_dates?: string[];
  /** Skip Windows */
  skip_windows?: Record<string, any>[];
  /**
   * Misfire Policy
   * @default "skip"
   * @pattern ^(skip|latest_only|catch_up)$
   */
  misfire_policy?: string;
  /**
   * Random Delay Min
   * @min 0
   * @default 0
   */
  random_delay_min?: number;
  /**
   * Random Delay Max
   * @min 0
   * @default 0
   */
  random_delay_max?: number;
  /**
   * Stagger Devices
   * @default false
   */
  stagger_devices?: boolean;
  /**
   * Stagger Interval Seconds
   * @min 1
   * @max 3600
   * @default 60
   */
  stagger_interval_seconds?: number;
  /**
   * Is Enabled
   * @default true
   */
  is_enabled?: boolean;
  /**
   * Priority
   * @default "normal"
   * @pattern ^(low|normal|high)$
   */
  priority?: string;
  /**
   * Max Concurrent Per Device
   * @min 1
   * @max 10
   * @default 1
   */
  max_concurrent_per_device?: number;
  /** Account Rate Limit Per Hour */
  account_rate_limit_per_hour?: number | null;
  /** Quota Policy */
  quota_policy?: Record<string, any>;
}

/** ScheduleOut */
export interface ScheduleOut {
  /** Id */
  id: string;
  /** Name */
  name: string;
  /** Description */
  description: string;
  /** Target Type */
  target_type: string;
  /** Target Id */
  target_id: string | null;
  /** Inline Steps */
  inline_steps: Record<string, any>[] | null;
  /** Inline Variables */
  inline_variables: Record<string, any>;
  /** Device Group Id */
  device_group_id: string | null;
  /** Filter State */
  filter_state: string;
  /** Filter Model */
  filter_model: string | null;
  /** Max Devices */
  max_devices: number | null;
  /** Cron Expression */
  cron_expression: string | null;
  /** Timezone */
  timezone: string;
  /** Schedule Kind */
  schedule_kind: string;
  /** Run At */
  run_at: string | null;
  /** Skip Dates */
  skip_dates: string[];
  /** Skip Windows */
  skip_windows: Record<string, any>[];
  /** Misfire Policy */
  misfire_policy: string;
  /** Random Delay Min */
  random_delay_min: number;
  /** Random Delay Max */
  random_delay_max: number;
  /** Stagger Devices */
  stagger_devices: boolean;
  /** Stagger Interval Seconds */
  stagger_interval_seconds: number;
  /** Is Enabled */
  is_enabled: boolean;
  /** Status */
  status: string;
  /** Priority */
  priority: string;
  /** Max Concurrent Per Device */
  max_concurrent_per_device: number;
  /** Account Rate Limit Per Hour */
  account_rate_limit_per_hour: number | null;
  /** Quota Policy */
  quota_policy: Record<string, any>;
  /** Deleted At */
  deleted_at: string | null;
  /** Last Run At */
  last_run_at: string | null;
  /** Next Run At */
  next_run_at: string | null;
  /** Run Count */
  run_count: number;
  /** User Id */
  user_id: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /**
   * Updated At
   * @format date-time
   */
  updated_at: string;
}

/** SchedulePatch */
export interface SchedulePatch {
  /** Name */
  name?: string | null;
  /** Description */
  description?: string | null;
  /** Target Type */
  target_type?: string | null;
  /** Target Id */
  target_id?: string | null;
  /** Inline Steps */
  inline_steps?: Record<string, any>[] | null;
  /** Inline Variables */
  inline_variables?: Record<string, any> | null;
  /** Device Group Id */
  device_group_id?: string | null;
  /** Filter State */
  filter_state?: string | null;
  /** Filter Model */
  filter_model?: string | null;
  /** Max Devices */
  max_devices?: number | null;
  /** Cron Expression */
  cron_expression?: string | null;
  /** Timezone */
  timezone?: string | null;
  /** Run At */
  run_at?: string | null;
  /** Skip Dates */
  skip_dates?: string[] | null;
  /** Skip Windows */
  skip_windows?: Record<string, any>[] | null;
  /** Misfire Policy */
  misfire_policy?: string | null;
  /** Random Delay Min */
  random_delay_min?: number | null;
  /** Random Delay Max */
  random_delay_max?: number | null;
  /** Stagger Devices */
  stagger_devices?: boolean | null;
  /** Stagger Interval Seconds */
  stagger_interval_seconds?: number | null;
  /** Is Enabled */
  is_enabled?: boolean | null;
  /** Priority */
  priority?: string | null;
  /** Max Concurrent Per Device */
  max_concurrent_per_device?: number | null;
  /** Account Rate Limit Per Hour */
  account_rate_limit_per_hour?: number | null;
  /** Quota Policy */
  quota_policy?: Record<string, any> | null;
}

/** SchedulePreviewIn */
export interface SchedulePreviewIn {
  /**
   * Target Type
   * @pattern ^(campaign|template|fleet)$
   */
  target_type: string;
  /** Target Id */
  target_id?: string | null;
  /** Cron Expression */
  cron_expression?: string | null;
  /**
   * Timezone
   * @default "Asia/Ho_Chi_Minh"
   */
  timezone?: string;
  /** Run At */
  run_at?: string | null;
  /** Device Group Id */
  device_group_id?: string | null;
  /** Max Devices */
  max_devices?: number | null;
}

/** SchedulePreviewOut */
export interface SchedulePreviewOut {
  /** Conflicts */
  conflicts: ScheduleConflictOut[];
  /** Next Runs */
  next_runs: string[];
}

/** ScheduleRunOut */
export interface ScheduleRunOut {
  /** Id */
  id: string;
  /** Schedule Id */
  schedule_id: string;
  /** Status */
  status: string;
  /** Trigger Source */
  trigger_source: string;
  /** Scheduled At */
  scheduled_at: string | null;
  /**
   * Started At
   * @format date-time
   */
  started_at: string;
  /** Finished At */
  finished_at: string | null;
  /** Deferred Until */
  deferred_until: string | null;
  /** Was Catch Up */
  was_catch_up: boolean;
  /** Execution Id */
  execution_id: string | null;
  /** Devices Dispatched */
  devices_dispatched: number;
  /** Devices Succeeded */
  devices_succeeded: number;
  /** Devices Failed */
  devices_failed: number;
  /** Task Ids */
  task_ids: string[];
  /** Workflow Ids */
  workflow_ids: string[];
  /** Error Code */
  error_code: string | null;
  /** Error Message */
  error_message: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
}

/** ScheduleStatusOut */
export interface ScheduleStatusOut {
  /** Temporal Available */
  temporal_available: boolean;
  /** Fallback Active */
  fallback_active: boolean;
  /** Banner */
  banner: string | null;
  /** Metrics */
  metrics: Record<string, any>;
}

/** ScrcpyAttachRequest */
export interface ScrcpyAttachRequest {
  /** Device Ip */
  device_ip?: string | null;
  /**
   * Adb Port
   * @default 5555
   */
  adb_port?: number;
  /**
   * Enable Control
   * @default true
   */
  enable_control?: boolean;
}

/** ScrollRequest */
export interface ScrollRequest {
  /**
   * Direction
   * @default "down"
   */
  direction?: string;
  /**
   * Distance
   * @default 0.5
   */
  distance?: number;
}

/** SessionListOut */
export interface SessionListOut {
  /** Sessions */
  sessions: ApiSchemasAuthSessionOut[];
}

/** SessionOwnerAnomalyOut */
export interface SessionOwnerAnomalyOut {
  /** Session Id */
  session_id: string;
  /** Device Id */
  device_id: string;
  /** Device Serial */
  device_serial: string;
  /** Owner classification for active control-plane sessions (DF-T-02-013). */
  owner_type: SessionOwnerType;
  /**
   * Owner Id
   * Sensitive owner identifier; only returned to privileged callers.
   */
  owner_id?: string | null;
  /** Reason */
  reason: string;
}

/** SessionOwnerCountsOut */
export interface SessionOwnerCountsOut {
  /**
   * User
   * @default 0
   */
  user?: number;
  /**
   * Execution
   * @default 0
   */
  execution?: number;
  /**
   * Campaign
   * @default 0
   */
  campaign?: number;
  /**
   * System
   * @default 0
   */
  system?: number;
  /**
   * Unknown
   * @default 0
   */
  unknown?: number;
  /**
   * Total
   * @default 0
   */
  total?: number;
}

/** SetClipboardRequest */
export interface SetClipboardRequest {
  /** Text */
  text: string;
}

/** SetEnabledRequest */
export interface SetEnabledRequest {
  /** Enabled */
  enabled: boolean;
}

/** SetPrimaryBody */
export interface SetPrimaryBody {
  /** Account Id */
  account_id: string;
}

/** SetRingerModeRequest */
export interface SetRingerModeRequest {
  /** Mode */
  mode: string;
}

/** StartSessionRequest */
export interface StartSessionRequest {
  /** Device Id */
  device_id: string;
  /** User Id */
  user_id?: string | null;
}

/** StatusUpdate */
export interface StatusUpdate {
  /** Status */
  status: string;
}

/** StepActionBody */
export interface StepActionBody {
  /** Action */
  action: string;
  /** Device Serial */
  device_serial?: string | null;
}

/** SummaryOut */
export interface SummaryOut {
  /** Total Devices */
  total_devices: number;
  /** Passed */
  passed: number;
  /** Failed */
  failed: number;
  /** Running */
  running: number;
  /** Pending */
  pending: number;
  /** Error */
  error: number;
  /** Total Content Items */
  total_content_items: number;
}

/** SwipeRequest */
export interface SwipeRequest {
  /** X1 */
  x1: number;
  /** Y1 */
  y1: number;
  /** X2 */
  x2: number;
  /** Y2 */
  y2: number;
  /**
   * Ms
   * @default 300
   */
  ms?: number;
}

/** TapRequest */
export interface TapRequest {
  /** X */
  x: number;
  /** Y */
  y: number;
}

/** TapSelectorRequest */
export interface TapSelectorRequest {
  /** By */
  by: string;
  /** Value */
  value: string;
}

/** TaskRequest */
export interface TaskRequest {
  /**
   * Fn Name
   * @default "example"
   */
  fn_name?: string;
  /**
   * Priority
   * @default 5
   */
  priority?: number;
  /** Target */
  target?: string | null;
  /**
   * Timeout
   * @default 300
   */
  timeout?: number;
  /**
   * Max Retries
   * @default 2
   */
  max_retries?: number;
}

/** TestNotificationOut */
export interface TestNotificationOut {
  /** Ok */
  ok: boolean;
  /** Message */
  message: string;
}

/** TokenResponse */
export interface TokenResponse {
  /** Access Token */
  access_token: string;
  /** Refresh Token */
  refresh_token: string;
  /**
   * Token Type
   * @default "bearer"
   */
  token_type?: string;
  /** Expires In */
  expires_in: number;
  /** Session Id */
  session_id?: string | null;
}

/** TriggerResponse */
export interface TriggerResponse {
  /** Run Id */
  run_id: string;
  /**
   * Message
   * @default "Schedule triggered"
   */
  message?: string;
}

/** UnpairDeviceOut */
export interface UnpairDeviceOut {
  /** Db Id */
  db_id: string;
  /** Status */
  status: string;
  /**
   * Unpaired At
   * @format date-time
   */
  unpaired_at: string;
}

/** UnreadCountOut */
export interface UnreadCountOut {
  /** Count */
  count: number;
}

/** UpdateTagsBody */
export interface UpdateTagsBody {
  /** Tags */
  tags: string;
}

/** UpsertResultBody */
export interface UpsertResultBody {
  /** @default "pending" */
  status?: ExecutionResultStatus;
  /** Passed Steps */
  passed_steps?: any[];
  /** Failed Steps */
  failed_steps?: any[];
  /** Error Detail */
  error_detail?: string | null;
  /** Run Time Sec */
  run_time_sec?: number | null;
  /** Started At */
  started_at?: string | null;
  /** Finished At */
  finished_at?: string | null;
}

/** UserCreate */
export interface UserCreate {
  /** Email */
  email: string;
  /** Name */
  name: string;
  /** Password */
  password: string;
  /**
   * Role
   * @default "operator"
   */
  role?: string;
}

/** ValidationError */
export interface ValidationError {
  /** Location */
  loc: (string | number)[];
  /** Message */
  msg: string;
  /** Error Type */
  type: string;
  /** Input */
  input?: any;
  /** Context */
  ctx?: object;
}

/** PairBulkBody */
export interface ApiRoutesDevicesPairBulkBody {
  /**
   * Count
   * @default 1
   */
  count?: number;
}

/** PairBulkBody */
export interface ApiRoutesRelayAgentsPairBulkBody {
  /** Serials */
  serials: string[];
}

/** SessionOut */
export interface ApiSchemasAuthSessionOut {
  /** Session Id */
  session_id: string;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /**
   * Last Used At
   * @format date-time
   */
  last_used_at: string;
  /** Last Ip */
  last_ip?: string | null;
  /** User Agent Summary */
  user_agent_summary?: string | null;
  /**
   * Is Current
   * @default false
   */
  is_current?: boolean;
}

/** UserOut */
export interface ApiSchemasAuthUserOut {
  /** Id */
  id: string;
  /** Email */
  email: string;
  /** Name */
  name: string;
  /** Role */
  role: string;
  /** Api Key */
  api_key: string;
  /** Orgrole */
  orgRole?: string | null;
}

/** SessionOut */
export interface ApiSchemasDeviceSessionOut {
  /** Id */
  id: string;
  /** Client Ip */
  client_ip: string;
  /**
   * Connected At
   * @format date-time
   */
  connected_at: string;
  /** Disconnected At */
  disconnected_at: string | null;
}

/** ValidationIssueOut */
export interface ApiSchemasOrgScenarioValidationIssueOut {
  /** Level */
  level: string;
  /** Code */
  code: string;
  /** Message */
  message: string;
  /**
   * Location
   * @default ""
   */
  location?: string;
  /** Hint */
  hint?: string | null;
}

/** ValidationIssueOut */
export interface ApiSchemasScenarioValidationValidationIssueOut {
  /** Level */
  level: "error" | "warning" | "info";
  /** Code */
  code: string;
  /** Message */
  message: string;
  /**
   * Location
   * @default ""
   */
  location?: string;
  /** Hint */
  hint?: string | null;
}

/** UserOut */
export interface ApiSchemasUserUserOut {
  /** Id */
  id: string;
  /** Email */
  email: string;
  /** Name */
  name: string;
  /** Role */
  role: string;
  /** Api Key */
  api_key: string;
  /** Is Active */
  is_active: boolean;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
}

import type {
  AxiosInstance,
  AxiosRequestConfig,
  AxiosResponse,
  HeadersDefaults,
  ResponseType,
} from "axios";
import axios from "axios";

export type QueryParamsType = Record<string | number, any>;

export interface FullRequestParams
  extends Omit<AxiosRequestConfig, "data" | "params" | "url" | "responseType"> {
  /** set parameter to `true` for call `securityWorker` for this request */
  secure?: boolean;
  /** request path */
  path: string;
  /** content type of request body */
  type?: ContentType;
  /** query params */
  query?: QueryParamsType;
  /** format of response (i.e. response.json() -> format: "json") */
  format?: ResponseType;
  /** request body */
  body?: unknown;
}

export type RequestParams = Omit<
  FullRequestParams,
  "body" | "method" | "query" | "path"
>;

export interface ApiConfig<SecurityDataType = unknown>
  extends Omit<AxiosRequestConfig, "data" | "cancelToken"> {
  securityWorker?: (
    securityData: SecurityDataType | null,
  ) => Promise<AxiosRequestConfig | void> | AxiosRequestConfig | void;
  secure?: boolean;
  format?: ResponseType;
}

export enum ContentType {
  Json = "application/json",
  JsonApi = "application/vnd.api+json",
  FormData = "multipart/form-data",
  UrlEncoded = "application/x-www-form-urlencoded",
  Text = "text/plain",
}

export class HttpClient<SecurityDataType = unknown> {
  public instance: AxiosInstance;
  private securityData: SecurityDataType | null = null;
  private securityWorker?: ApiConfig<SecurityDataType>["securityWorker"];
  private secure?: boolean;
  private format?: ResponseType;

  constructor({
    securityWorker,
    secure,
    format,
    ...axiosConfig
  }: ApiConfig<SecurityDataType> = {}) {
    this.instance = axios.create({
      ...axiosConfig,
      baseURL: axiosConfig.baseURL || "",
    });
    this.secure = secure;
    this.format = format;
    this.securityWorker = securityWorker;
  }

  public setSecurityData = (data: SecurityDataType | null) => {
    this.securityData = data;
  };

  protected mergeRequestParams(
    params1: AxiosRequestConfig,
    params2?: AxiosRequestConfig,
  ): AxiosRequestConfig {
    const method = params1.method || (params2 && params2.method);

    return {
      ...this.instance.defaults,
      ...params1,
      ...(params2 || {}),
      headers: {
        ...((method &&
          this.instance.defaults.headers[
            method.toLowerCase() as keyof HeadersDefaults
          ]) ||
          {}),
        ...(params1.headers || {}),
        ...((params2 && params2.headers) || {}),
      },
    };
  }

  protected stringifyFormItem(formItem: unknown) {
    if (typeof formItem === "object" && formItem !== null) {
      return JSON.stringify(formItem);
    } else {
      return `${formItem}`;
    }
  }

  protected createFormData(input: Record<string, unknown>): FormData {
    if (input instanceof FormData) {
      return input;
    }
    return Object.keys(input || {}).reduce((formData, key) => {
      const property = input[key];
      const propertyContent: any[] =
        property instanceof Array ? property : [property];

      for (const formItem of propertyContent) {
        const isFileType = formItem instanceof Blob || formItem instanceof File;
        formData.append(
          key,
          isFileType ? formItem : this.stringifyFormItem(formItem),
        );
      }

      return formData;
    }, new FormData());
  }

  public request = async <T = any, _E = any>({
    secure,
    path,
    type,
    query,
    format,
    body,
    ...params
  }: FullRequestParams): Promise<AxiosResponse<T>> => {
    const secureParams =
      ((typeof secure === "boolean" ? secure : this.secure) &&
        this.securityWorker &&
        (await this.securityWorker(this.securityData))) ||
      {};
    const requestParams = this.mergeRequestParams(params, secureParams);
    const responseFormat = format || this.format || undefined;

    if (
      type === ContentType.FormData &&
      body &&
      body !== null &&
      typeof body === "object"
    ) {
      body = this.createFormData(body as Record<string, unknown>);
    }

    if (
      type === ContentType.Text &&
      body &&
      body !== null &&
      typeof body !== "string"
    ) {
      body = JSON.stringify(body);
    }

    return this.instance.request({
      ...requestParams,
      headers: {
        ...(requestParams.headers || {}),
        ...(type ? { "Content-Type": type } : {}),
      },
      params: query,
      responseType: responseFormat,
      data: body,
      url: path,
    });
  };
}

/**
 * @title Android Device Farm
 * @version 2.0.0
 */
export class DeviceFarmHttpClient<
  SecurityDataType extends unknown,
> extends HttpClient<SecurityDataType> {
  /**
   * No description
   *
   * @name DashboardGet
   * @summary Dashboard
   * @request GET:/
   */
  dashboardGet = (params: RequestParams = {}) =>
    this.request<string, any>({
      path: `/`,
      method: "GET",
      ...params,
    });

  api = {
    /**
     * No description
     *
     * @name ApiSafeModeApiServerSafeModeGet
     * @summary Api Safe Mode
     * @request GET:/api/server/safe-mode
     */
    apiSafeModeApiServerSafeModeGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/server/safe-mode`,
        method: "GET",
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @name ApiServerStatusApiServerStatusGet
     * @summary Api Server Status
     * @request GET:/api/server/status
     */
    apiServerStatusApiServerStatusGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/server/status`,
        method: "GET",
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @name ApiServerVersionApiServerVersionGet
     * @summary Api Server Version
     * @request GET:/api/server/version
     */
    apiServerVersionApiServerVersionGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/server/version`,
        method: "GET",
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @name LivenessApiLiveGet
     * @summary Liveness
     * @request GET:/api/live
     */
    livenessApiLiveGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/live`,
        method: "GET",
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @name ReadinessApiReadyGet
     * @summary Readiness
     * @request GET:/api/ready
     */
    readinessApiReadyGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/ready`,
        method: "GET",
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @name HealthApiHealthGet
     * @summary Health
     * @request GET:/api/health
     */
    healthApiHealthGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/health`,
        method: "GET",
        format: "json",
        ...params,
      }),

    /**
     * @description Debug endpoint — shows connected relay agents and their registered serials.
     *
     * @name RelayStatusApiRelayStatusGet
     * @summary Relay Status
     * @request GET:/api/relay/status
     * @secure
     */
    relayStatusApiRelayStatusGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/relay/status`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @name ApiDevicesLiveApiDevicesLiveGet
     * @summary Api Devices Live
     * @request GET:/api/devices/live
     */
    apiDevicesLiveApiDevicesLiveGet: (
      query?: {
        /** State */
        state?: string | null;
        /** Model */
        model?: string | null;
        /** Limit */
        limit?: number | null;
        /**
         * Offset
         * @default 0
         */
        offset?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/live`,
        method: "GET",
        query: query,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @name ApiConfigApiConfigGet
     * @summary Api Config
     * @request GET:/api/config
     */
    apiConfigApiConfigGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/config`,
        method: "GET",
        format: "json",
        ...params,
      }),

    /**
     * @description Return device events — from DB if available, else in-memory buffer.
     *
     * @name ApiEventsApiEventsGet
     * @summary Api Events
     * @request GET:/api/events
     */
    apiEventsApiEventsGet: (
      query?: {
        /** Serial */
        serial?: string | null;
        /** Event */
        event?: string | null;
        /**
         * Limit
         * @default 50
         */
        limit?: number;
        /**
         * Offset
         * @default 0
         */
        offset?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/events`,
        method: "GET",
        query: query,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @name ApiTasksApiTasksGet
     * @summary Api Tasks
     * @request GET:/api/tasks
     */
    apiTasksApiTasksGet: (
      query?: {
        /** Ids */
        ids?: string | null;
        /** Name Prefix */
        name_prefix?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/tasks`,
        method: "GET",
        query: query,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags auth
     * @name RegisterApiAuthRegisterPost
     * @summary Register
     * @request POST:/api/auth/register
     */
    registerApiAuthRegisterPost: (
      data: RegisterRequest,
      params: RequestParams = {},
    ) =>
      this.request<ApiSchemasAuthUserOut, HTTPValidationError>({
        path: `/api/auth/register`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags auth
     * @name LoginApiAuthLoginPost
     * @summary Login
     * @request POST:/api/auth/login
     */
    loginApiAuthLoginPost: (data: LoginRequest, params: RequestParams = {}) =>
      this.request<TokenResponse, HTTPValidationError>({
        path: `/api/auth/login`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags auth
     * @name RefreshApiAuthRefreshPost
     * @summary Refresh
     * @request POST:/api/auth/refresh
     */
    refreshApiAuthRefreshPost: (
      data: RefreshRequest,
      params: RequestParams = {},
    ) =>
      this.request<TokenResponse, HTTPValidationError>({
        path: `/api/auth/refresh`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags auth
     * @name LogoutApiAuthLogoutPost
     * @summary Logout
     * @request POST:/api/auth/logout
     * @secure
     */
    logoutApiAuthLogoutPost: (
      data: LogoutRequest,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/auth/logout`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        ...params,
      }),

    /**
     * No description
     *
     * @tags auth
     * @name MeApiAuthMeGet
     * @summary Me
     * @request GET:/api/auth/me
     * @secure
     */
    meApiAuthMeGet: (params: RequestParams = {}) =>
      this.request<ApiSchemasAuthUserOut, any>({
        path: `/api/auth/me`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags me
     * @name MyOrganizationApiMeOrganizationGet
     * @summary My Organization
     * @request GET:/api/me/organization
     * @secure
     */
    myOrganizationApiMeOrganizationGet: (params: RequestParams = {}) =>
      this.request<OrganizationOut, any>({
        path: `/api/me/organization`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags me
     * @name ChangePasswordApiMeChangePasswordPost
     * @summary Change Password
     * @request POST:/api/me/change-password
     * @secure
     */
    changePasswordApiMeChangePasswordPost: (
      data: ChangePasswordRequest,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/me/change-password`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        ...params,
      }),

    /**
     * No description
     *
     * @tags me
     * @name ListMySessionsApiMeSessionsGet
     * @summary List My Sessions
     * @request GET:/api/me/sessions
     * @secure
     */
    listMySessionsApiMeSessionsGet: (params: RequestParams = {}) =>
      this.request<SessionListOut, any>({
        path: `/api/me/sessions`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags me
     * @name RevokeOtherSessionsApiMeSessionsDelete
     * @summary Revoke Other Sessions
     * @request DELETE:/api/me/sessions
     * @secure
     */
    revokeOtherSessionsApiMeSessionsDelete: (params: RequestParams = {}) =>
      this.request<void, any>({
        path: `/api/me/sessions`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags me
     * @name RevokeMySessionApiMeSessionsSessionIdDelete
     * @summary Revoke My Session
     * @request DELETE:/api/me/sessions/{session_id}
     * @secure
     */
    revokeMySessionApiMeSessionsSessionIdDelete: (
      sessionId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/me/sessions/${sessionId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminListMembersApiAdminMembersGet
     * @summary Admin List Members
     * @request GET:/api/admin/members
     * @secure
     */
    adminListMembersApiAdminMembersGet: (params: RequestParams = {}) =>
      this.request<OrganizationMemberOut[], any>({
        path: `/api/admin/members`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name GetReconnectPolicyApiAdminReconnectPolicyGet
     * @summary Get Reconnect Policy
     * @request GET:/api/admin/reconnect-policy
     * @secure
     */
    getReconnectPolicyApiAdminReconnectPolicyGet: (
      params: RequestParams = {},
    ) =>
      this.request<ReconnectPolicyOut, any>({
        path: `/api/admin/reconnect-policy`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name PutReconnectPolicyApiAdminReconnectPolicyPut
     * @summary Put Reconnect Policy
     * @request PUT:/api/admin/reconnect-policy
     * @secure
     */
    putReconnectPolicyApiAdminReconnectPolicyPut: (
      data: ReconnectPolicyUpdate,
      params: RequestParams = {},
    ) =>
      this.request<ReconnectPolicyOut, HTTPValidationError>({
        path: `/api/admin/reconnect-policy`,
        method: "PUT",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminForceReleaseApiAdminDevicesDeviceIdForceReleasePost
     * @summary Admin Force Release
     * @request POST:/api/admin/devices/{device_id}/force-release
     * @secure
     */
    adminForceReleaseApiAdminDevicesDeviceIdForceReleasePost: (
      deviceId: string,
      data: AdminForceReleaseBody,
      params: RequestParams = {},
    ) =>
      this.request<AdminOverrideOut, HTTPValidationError>({
        path: `/api/admin/devices/${deviceId}/force-release`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminResetStateApiAdminDevicesDeviceIdResetStatePost
     * @summary Admin Reset State
     * @request POST:/api/admin/devices/{device_id}/reset-state
     * @secure
     */
    adminResetStateApiAdminDevicesDeviceIdResetStatePost: (
      deviceId: string,
      data: AdminResetStateBody,
      params: RequestParams = {},
    ) =>
      this.request<AdminOverrideOut, HTTPValidationError>({
        path: `/api/admin/devices/${deviceId}/reset-state`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Serve the STFService.apk used by Android devices. The file is resolved from a small set of well-known locations: - device_farm/bundle/apks/STFService.apk                (download_bundle.py output) - ../STFService.apk/app/build/outputs/apk/release/...   (local Gradle build)
     *
     * @tags devices
     * @name DownloadStfApkApiDevicesStfApkGet
     * @summary Download STFService APK
     * @request GET:/api/devices/stf-apk
     * @secure
     */
    downloadStfApkApiDevicesStfApkGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/devices/stf-apk`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Backend chủ động kết nối tới thiết bị qua ADB over TCP. Thiết bị cần bật ADB over TCP (Wireless debugging hoặc adb tcpip 5555). Không cần QR: chỉ cần nhập IP và bấm Kết nối.
     *
     * @tags devices
     * @name ConnectDeviceByIpApiDevicesConnectAdbPost
     * @summary Connect Device By Ip
     * @request POST:/api/devices/connect-adb
     * @secure
     */
    connectDeviceByIpApiDevicesConnectAdbPost: (
      data: ConnectByIpBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/connect-adb`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Đăng ký thiết bị: chỉ tạo bản ghi (serial = pending-xxx), chưa kết nối điện thoại. Để kết nối điện thoại thật, user vào thẻ thiết bị → nhấn Kết nối → quét mã QR (key=device_key).
     *
     * @tags devices
     * @name RegisterDeviceApiDevicesRegisterPost
     * @summary Register Device
     * @request POST:/api/devices/register
     * @secure
     */
    registerDeviceApiDevicesRegisterPost: (
      data: RegisterDeviceBody,
      params: RequestParams = {},
    ) =>
      this.request<DeviceOut, HTTPValidationError>({
        path: `/api/devices/register`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name CreatePairingApiDevicesPairPost
     * @summary Create Pairing
     * @request POST:/api/devices/pair
     * @secure
     */
    createPairingApiDevicesPairPost: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/devices/pair`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Tạo nhiều pairing cùng lúc để kết nối nhiều thiết bị. Mỗi thiết bị dùng một URL (copy hoặc quét QR).
     *
     * @tags devices
     * @name CreatePairingBulkApiDevicesPairBulkPost
     * @summary Create Pairing Bulk
     * @request POST:/api/devices/pair/bulk
     * @secure
     */
    createPairingBulkApiDevicesPairBulkPost: (
      data: ApiRoutesDevicesPairBulkBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/pair/bulk`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Poll until device connects and pairing is complete.
     *
     * @tags devices
     * @name PollPairingApiDevicesPairPairingIdGet
     * @summary Poll Pairing
     * @request GET:/api/devices/pair/{pairing_id}
     * @secure
     */
    pollPairingApiDevicesPairPairingIdGet: (
      pairingId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/pair/${pairingId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name ListDevicesApiDevicesGet
     * @summary List Devices
     * @request GET:/api/devices
     * @secure
     */
    listDevicesApiDevicesGet: (
      query?: {
        /** Cursor */
        cursor?: string | null;
        /** Limit */
        limit?: number | null;
        /** State */
        state?: string | null;
        /** Group Id */
        group_id?: string | null;
        /** Owner Type */
        owner_type?: string | null;
        /** Relay Host */
        relay_host?: string | null;
        /** Tag */
        tag?: string | null;
        /** Q */
        q?: string | null;
        /** Sort */
        sort?: string | null;
        /** Device Id */
        device_id?: string | null;
        /** Device Serial */
        device_serial?: string | null;
        /** Adb Serial */
        adb_serial?: string | null;
        /** Relay Serial */
        relay_serial?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Đăng ký thiết bị thủ công bằng serial (dùng cho script/admin). Đăng ký từ UI phải qua POST /pair + quét mã QR, không dùng endpoint này. Semantics: - If no device with this serial exists: create and assign to current user. - If it exists without an owner (user_id is NULL): claim it for current user. - If it already belongs to current user: idempotent (optionally updates name). - If it belongs to another user: 409.
     *
     * @tags devices
     * @name CreateDeviceApiDevicesPost
     * @summary Create Device
     * @request POST:/api/devices
     * @secure
     */
    createDeviceApiDevicesPost: (
      data: DeviceCreate,
      params: RequestParams = {},
    ) =>
      this.request<DeviceOut, HTTPValidationError>({
        path: `/api/devices`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name DeviceCapacityReportApiDevicesCapacityGet
     * @summary Device Capacity Report
     * @request GET:/api/devices/capacity
     * @secure
     */
    deviceCapacityReportApiDevicesCapacityGet: (
      query?: {
        /** Group Id */
        group_id?: string | null;
        /** Tag */
        tag?: string | null;
        /** State */
        state?: string | null;
        /** Relay Host */
        relay_host?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<CapacityReportOut, HTTPValidationError>({
        path: `/api/devices/capacity`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Fleet health summary: device FSM counts and active sessions by owner type.
     *
     * @tags devices
     * @name FleetStatsApiDevicesFleetStatsGet
     * @summary Fleet Stats
     * @request GET:/api/devices/fleet/stats
     * @secure
     */
    fleetStatsApiDevicesFleetStatsGet: (
      query?: {
        /** Group Id */
        group_id?: string | null;
        /** Relay Host */
        relay_host?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<FleetStatsOut, HTTPValidationError>({
        path: `/api/devices/fleet/stats`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name GetDeviceApiDevicesDeviceIdGet
     * @summary Get Device
     * @request GET:/api/devices/{device_id}
     * @secure
     */
    getDeviceApiDevicesDeviceIdGet: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<DeviceOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Xoá thiết bị của user hiện tại và mọi liên kết campaign-device.
     *
     * @tags devices
     * @name DeleteDeviceApiDevicesDeviceIdDelete
     * @summary Delete Device
     * @request DELETE:/api/devices/{device_id}
     * @secure
     */
    deleteDeviceApiDevicesDeviceIdDelete: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/devices/${deviceId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name UpdateTagsApiDevicesDeviceIdTagsPatch
     * @summary Update Tags
     * @request PATCH:/api/devices/{device_id}/tags
     * @secure
     */
    updateTagsApiDevicesDeviceIdTagsPatch: (
      deviceId: string,
      data: UpdateTagsBody,
      params: RequestParams = {},
    ) =>
      this.request<DeviceOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}/tags`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name DeviceSessionsApiDevicesDeviceIdSessionsGet
     * @summary Device Sessions
     * @request GET:/api/devices/{device_id}/sessions
     * @secure
     */
    deviceSessionsApiDevicesDeviceIdSessionsGet: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<ApiSchemasDeviceSessionOut[], HTTPValidationError>({
        path: `/api/devices/${deviceId}/sessions`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Transition DEAD → CONNECTING after physical intervention (DF-T-02-005).
     *
     * @tags devices
     * @name ReviveDeviceApiDevicesDeviceIdRevivePost
     * @summary Revive a DEAD device (admin)
     * @request POST:/api/devices/{device_id}/revive
     * @secure
     */
    reviveDeviceApiDevicesDeviceIdRevivePost: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<DeviceReviveOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}/revive`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name BootstrapDeviceApiDevicesDeviceIdBootstrapPost
     * @summary Bootstrap Device
     * @request POST:/api/devices/{device_id}/bootstrap
     * @secure
     */
    bootstrapDeviceApiDevicesDeviceIdBootstrapPost: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<RelayCommandOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}/bootstrap`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name RestartU2ApiDevicesDeviceIdRestartU2Post
     * @summary Restart U2
     * @request POST:/api/devices/{device_id}/restart-u2
     * @secure
     */
    restartU2ApiDevicesDeviceIdRestartU2Post: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<RelayCommandOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}/restart-u2`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name RestartAtxApiDevicesDeviceIdRestartAtxPost
     * @summary Restart Atx
     * @request POST:/api/devices/{device_id}/restart-atx
     * @secure
     */
    restartAtxApiDevicesDeviceIdRestartAtxPost: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<RelayCommandOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}/restart-atx`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name RestartScrcpyApiDevicesDeviceIdRestartScrcpyPost
     * @summary Restart Scrcpy
     * @request POST:/api/devices/{device_id}/restart-scrcpy
     * @secure
     */
    restartScrcpyApiDevicesDeviceIdRestartScrcpyPost: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<RelayCommandOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}/restart-scrcpy`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags users
     * @name ListUsersApiUsersGet
     * @summary List Users
     * @request GET:/api/users
     * @secure
     */
    listUsersApiUsersGet: (params: RequestParams = {}) =>
      this.request<ApiSchemasUserUserOut[], any>({
        path: `/api/users`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags users
     * @name CreateUserApiUsersPost
     * @summary Create User
     * @request POST:/api/users
     * @secure
     */
    createUserApiUsersPost: (data: UserCreate, params: RequestParams = {}) =>
      this.request<ApiSchemasUserUserOut, HTTPValidationError>({
        path: `/api/users`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags users
     * @name GetUserApiUsersUserIdGet
     * @summary Get User
     * @request GET:/api/users/{user_id}
     * @secure
     */
    getUserApiUsersUserIdGet: (userId: string, params: RequestParams = {}) =>
      this.request<ApiSchemasUserUserOut, HTTPValidationError>({
        path: `/api/users/${userId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name ListCampaignsApiCampaignsGet
     * @summary List Campaigns
     * @request GET:/api/campaigns
     * @secure
     */
    listCampaignsApiCampaignsGet: (
      query?: {
        /**
         * Include Archived
         * @default false
         */
        include_archived?: boolean;
      },
      params: RequestParams = {},
    ) =>
      this.request<CampaignOut[], HTTPValidationError>({
        path: `/api/campaigns`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name CreateCampaignApiCampaignsPost
     * @summary Create Campaign
     * @request POST:/api/campaigns
     * @secure
     */
    createCampaignApiCampaignsPost: (
      data: CampaignCreate,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/campaigns`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name GetCampaignApiCampaignsCampaignIdGet
     * @summary Get Campaign
     * @request GET:/api/campaigns/{campaign_id}
     * @secure
     */
    getCampaignApiCampaignsCampaignIdGet: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<CampaignOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name PatchCampaignEntityApiCampaignsCampaignIdPatch
     * @summary Patch Campaign Entity
     * @request PATCH:/api/campaigns/{campaign_id}
     * @secure
     */
    patchCampaignEntityApiCampaignsCampaignIdPatch: (
      campaignId: string,
      data: CampaignEntityUpdate,
      params: RequestParams = {},
    ) =>
      this.request<CampaignEntityOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name DeleteCampaignApiCampaignsCampaignIdDelete
     * @summary Delete Campaign
     * @request DELETE:/api/campaigns/{campaign_id}
     * @secure
     */
    deleteCampaignApiCampaignsCampaignIdDelete: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<CampaignEntityOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}`,
        method: "DELETE",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Fan-out campaign dispatch to explicit devices or device groups (DF-T-04-008).
     *
     * @tags campaigns
     * @name DispatchCampaignRouteApiCampaignsCampaignIdDispatchPost
     * @summary Dispatch Campaign Route
     * @request POST:/api/campaigns/{campaign_id}/dispatch
     * @secure
     */
    dispatchCampaignRouteApiCampaignsCampaignIdDispatchPost: (
      campaignId: string,
      data: CampaignDispatchIn,
      query?: {
        /**
         * Include Vars
         * Include effective_vars per execution (large fleets: keep false)
         * @default false
         */
        include_vars?: boolean;
      },
      params: RequestParams = {},
    ) =>
      this.request<CampaignDispatchOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/dispatch`,
        method: "POST",
        query: query,
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Bind account_group, scenario_account, or per-device account map (DF-T-04-009).
     *
     * @tags campaigns
     * @name BindCampaignAccountsRouteApiCampaignsCampaignIdAccountsPost
     * @summary Bind Campaign Accounts Route
     * @request POST:/api/campaigns/{campaign_id}/accounts
     * @secure
     */
    bindCampaignAccountsRouteApiCampaignsCampaignIdAccountsPost: (
      campaignId: string,
      data: CampaignAccountBindIn,
      params: RequestParams = {},
    ) =>
      this.request<CampaignEntityOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/accounts`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name UnbindCampaignAccountsRouteApiCampaignsCampaignIdAccountsDelete
     * @summary Unbind Campaign Accounts Route
     * @request DELETE:/api/campaigns/{campaign_id}/accounts
     * @secure
     */
    unbindCampaignAccountsRouteApiCampaignsCampaignIdAccountsDelete: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<CampaignEntityOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/accounts`,
        method: "DELETE",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name ArchiveCampaignRouteApiCampaignsCampaignIdArchivePost
     * @summary Archive Campaign Route
     * @request POST:/api/campaigns/{campaign_id}/archive
     * @secure
     */
    archiveCampaignRouteApiCampaignsCampaignIdArchivePost: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<CampaignEntityOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/archive`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name ForceTransitionCampaignApiCampaignsCampaignIdForceTransitionPost
     * @summary Force Transition Campaign
     * @request POST:/api/campaigns/{campaign_id}/force-transition
     * @secure
     */
    forceTransitionCampaignApiCampaignsCampaignIdForceTransitionPost: (
      campaignId: string,
      data: CampaignForceTransitionIn,
      params: RequestParams = {},
    ) =>
      this.request<CampaignForceTransitionOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/force-transition`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name UpdateStatusApiCampaignsCampaignIdStatusPatch
     * @summary Update Status
     * @request PATCH:/api/campaigns/{campaign_id}/status
     * @secure
     */
    updateStatusApiCampaignsCampaignIdStatusPatch: (
      campaignId: string,
      data: StatusUpdate,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/status`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name PauseCampaignApiCampaignsCampaignIdPausePost
     * @summary Pause Campaign
     * @request POST:/api/campaigns/{campaign_id}/pause
     * @secure
     */
    pauseCampaignApiCampaignsCampaignIdPausePost: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<CampaignControlOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/pause`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name ResumeCampaignApiCampaignsCampaignIdResumePost
     * @summary Resume Campaign
     * @request POST:/api/campaigns/{campaign_id}/resume
     * @secure
     */
    resumeCampaignApiCampaignsCampaignIdResumePost: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<CampaignControlOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/resume`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name CancelCampaignApiCampaignsCampaignIdCancelPost
     * @summary Cancel Campaign
     * @request POST:/api/campaigns/{campaign_id}/cancel
     * @secure
     */
    cancelCampaignApiCampaignsCampaignIdCancelPost: (
      campaignId: string,
      data: ExecutionCancelBody | null,
      params: RequestParams = {},
    ) =>
      this.request<CampaignControlOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/cancel`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Send retry_step or skip_step signal to workflows paused on error. When a step fails and its on_error policy is "pause", the workflow blocks waiting for this signal. - action="retry": re-execute the failed step from the beginning - action="skip":  skip the failed step and continue with the next one device_serial: if provided, only signal the workflow for that device. if None, signal all paused-on-error workflows for this campaign.
     *
     * @tags campaigns
     * @name StepActionApiCampaignsCampaignIdStepActionPost
     * @summary Step Action
     * @request POST:/api/campaigns/{campaign_id}/step-action
     * @secure
     */
    stepActionApiCampaignsCampaignIdStepActionPost: (
      campaignId: string,
      data: StepActionBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/step-action`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name CampaignDevicesApiCampaignsCampaignIdDevicesGet
     * @summary Campaign Devices
     * @request GET:/api/campaigns/{campaign_id}/devices
     * @secure
     */
    campaignDevicesApiCampaignsCampaignIdDevicesGet: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<CampaignDeviceOut[], HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/devices`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name AddDeviceApiCampaignsCampaignIdDevicesPost
     * @summary Add Device
     * @request POST:/api/campaigns/{campaign_id}/devices
     * @secure
     */
    addDeviceApiCampaignsCampaignIdDevicesPost: (
      campaignId: string,
      data: AddDeviceBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/devices`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name RemoveDeviceApiCampaignsCampaignIdDevicesDeviceIdDelete
     * @summary Remove Device
     * @request DELETE:/api/campaigns/{campaign_id}/devices/{device_id}
     * @secure
     */
    removeDeviceApiCampaignsCampaignIdDevicesDeviceIdDelete: (
      campaignId: string,
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/devices/${deviceId}`,
        method: "DELETE",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Return number of content items scraped for this campaign.
     *
     * @tags campaigns
     * @name CampaignContentStatsApiCampaignsCampaignIdContentStatsGet
     * @summary Campaign Content Stats
     * @request GET:/api/campaigns/{campaign_id}/content/stats
     * @secure
     */
    campaignContentStatsApiCampaignsCampaignIdContentStatsGet: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/content/stats`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name UpdateScenarioApiCampaignsCampaignIdScenarioPatch
     * @summary Update Scenario
     * @request PATCH:/api/campaigns/{campaign_id}/scenario
     * @secure
     */
    updateScenarioApiCampaignsCampaignIdScenarioPatch: (
      campaignId: string,
      data: ScenarioUpdateBody,
      query?: {
        /**
         * Force
         * Allow save despite validation errors
         * @default false
         */
        force?: boolean;
      },
      params: RequestParams = {},
    ) =>
      this.request<CampaignOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/scenario`,
        method: "PATCH",
        query: query,
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name CompileScenarioApiCampaignsCampaignIdCompileScenarioPost
     * @summary Compile Scenario
     * @request POST:/api/campaigns/{campaign_id}/compile-scenario
     * @secure
     */
    compileScenarioApiCampaignsCampaignIdCompileScenarioPost: (
      campaignId: string,
      data: CompileScenarioBody,
      params: RequestParams = {},
    ) =>
      this.request<CampaignOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/compile-scenario`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name ListScenariosApiCampaignsCampaignIdScenariosGet
     * @summary List Scenarios
     * @request GET:/api/campaigns/{campaign_id}/scenarios
     * @secure
     */
    listScenariosApiCampaignsCampaignIdScenariosGet: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<ScenarioOut[], HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/scenarios`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name CreateScenarioApiCampaignsCampaignIdScenariosPost
     * @summary Create Scenario
     * @request POST:/api/campaigns/{campaign_id}/scenarios
     * @secure
     */
    createScenarioApiCampaignsCampaignIdScenariosPost: (
      campaignId: string,
      data: ScenarioCreate,
      params: RequestParams = {},
    ) =>
      this.request<ScenarioOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/scenarios`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name ReorderScenariosRouteApiCampaignsCampaignIdScenariosReorderPost
     * @summary Reorder Scenarios Route
     * @request POST:/api/campaigns/{campaign_id}/scenarios/reorder
     * @secure
     */
    reorderScenariosRouteApiCampaignsCampaignIdScenariosReorderPost: (
      campaignId: string,
      data: ReorderScenariosBody,
      params: RequestParams = {},
    ) =>
      this.request<ScenarioOut[], HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/scenarios/reorder`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name GetScenarioApiCampaignsCampaignIdScenariosScenarioIdGet
     * @summary Get Scenario
     * @request GET:/api/campaigns/{campaign_id}/scenarios/{scenario_id}
     * @secure
     */
    getScenarioApiCampaignsCampaignIdScenariosScenarioIdGet: (
      campaignId: string,
      scenarioId: string,
      params: RequestParams = {},
    ) =>
      this.request<ScenarioOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/scenarios/${scenarioId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name UpdateScenarioRouteApiCampaignsCampaignIdScenariosScenarioIdPatch
     * @summary Update Scenario Route
     * @request PATCH:/api/campaigns/{campaign_id}/scenarios/{scenario_id}
     * @secure
     */
    updateScenarioRouteApiCampaignsCampaignIdScenariosScenarioIdPatch: (
      campaignId: string,
      scenarioId: string,
      data: ScenarioUpdate,
      query?: {
        /**
         * Force
         * Allow save despite validation errors
         * @default false
         */
        force?: boolean;
      },
      params: RequestParams = {},
    ) =>
      this.request<ScenarioOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/scenarios/${scenarioId}`,
        method: "PATCH",
        query: query,
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name DeleteScenarioRouteApiCampaignsCampaignIdScenariosScenarioIdDelete
     * @summary Delete Scenario Route
     * @request DELETE:/api/campaigns/{campaign_id}/scenarios/{scenario_id}
     * @secure
     */
    deleteScenarioRouteApiCampaignsCampaignIdScenariosScenarioIdDelete: (
      campaignId: string,
      scenarioId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/scenarios/${scenarioId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name GetScenarioDeviceVariablesEndpointApiCampaignsCampaignIdScenariosScenarioIdDevicesDeviceIdVariablesGet
     * @summary Get Scenario Device Variables Endpoint
     * @request GET:/api/campaigns/{campaign_id}/scenarios/{scenario_id}/devices/{device_id}/variables
     * @secure
     */
    getScenarioDeviceVariablesEndpointApiCampaignsCampaignIdScenariosScenarioIdDevicesDeviceIdVariablesGet:
      (
        campaignId: string,
        scenarioId: string,
        deviceId: string,
        params: RequestParams = {},
      ) =>
        this.request<ScenarioDeviceVariablesOut, HTTPValidationError>({
          path: `/api/campaigns/${campaignId}/scenarios/${scenarioId}/devices/${deviceId}/variables`,
          method: "GET",
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags campaigns
     * @name ReplaceScenarioDeviceVariablesEndpointApiCampaignsCampaignIdScenariosScenarioIdDevicesDeviceIdVariablesPut
     * @summary Replace Scenario Device Variables Endpoint
     * @request PUT:/api/campaigns/{campaign_id}/scenarios/{scenario_id}/devices/{device_id}/variables
     * @secure
     */
    replaceScenarioDeviceVariablesEndpointApiCampaignsCampaignIdScenariosScenarioIdDevicesDeviceIdVariablesPut:
      (
        campaignId: string,
        scenarioId: string,
        deviceId: string,
        data: ScenarioDeviceVariablesBody,
        params: RequestParams = {},
      ) =>
        this.request<ScenarioDeviceVariablesOut, HTTPValidationError>({
          path: `/api/campaigns/${campaignId}/scenarios/${scenarioId}/devices/${deviceId}/variables`,
          method: "PUT",
          body: data,
          secure: true,
          type: ContentType.Json,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags campaigns
     * @name MergeScenarioDeviceVariablesEndpointApiCampaignsCampaignIdScenariosScenarioIdDevicesDeviceIdVariablesPatch
     * @summary Merge Scenario Device Variables Endpoint
     * @request PATCH:/api/campaigns/{campaign_id}/scenarios/{scenario_id}/devices/{device_id}/variables
     * @secure
     */
    mergeScenarioDeviceVariablesEndpointApiCampaignsCampaignIdScenariosScenarioIdDevicesDeviceIdVariablesPatch:
      (
        campaignId: string,
        scenarioId: string,
        deviceId: string,
        data: ScenarioDeviceVariablesBody,
        params: RequestParams = {},
      ) =>
        this.request<ScenarioDeviceVariablesOut, HTTPValidationError>({
          path: `/api/campaigns/${campaignId}/scenarios/${scenarioId}/devices/${deviceId}/variables`,
          method: "PATCH",
          body: data,
          secure: true,
          type: ContentType.Json,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags campaigns
     * @name DeleteScenarioDeviceVariableKeyEndpointApiCampaignsCampaignIdScenariosScenarioIdDevicesDeviceIdVariablesKeyDelete
     * @summary Delete Scenario Device Variable Key Endpoint
     * @request DELETE:/api/campaigns/{campaign_id}/scenarios/{scenario_id}/devices/{device_id}/variables/{key}
     * @secure
     */
    deleteScenarioDeviceVariableKeyEndpointApiCampaignsCampaignIdScenariosScenarioIdDevicesDeviceIdVariablesKeyDelete:
      (
        campaignId: string,
        scenarioId: string,
        deviceId: string,
        key: string,
        params: RequestParams = {},
      ) =>
        this.request<Record<string, any>, HTTPValidationError>({
          path: `/api/campaigns/${campaignId}/scenarios/${scenarioId}/devices/${deviceId}/variables/${key}`,
          method: "DELETE",
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * @description Run full scenario validation (shape + semantic + lint) and persist summary.
     *
     * @tags campaigns
     * @name ValidateScenarioRouteApiCampaignsCampaignIdScenariosScenarioIdValidatePost
     * @summary Validate Scenario Route
     * @request POST:/api/campaigns/{campaign_id}/scenarios/{scenario_id}/validate
     * @secure
     */
    validateScenarioRouteApiCampaignsCampaignIdScenariosScenarioIdValidatePost:
      (campaignId: string, scenarioId: string, params: RequestParams = {}) =>
        this.request<ScenarioValidationOut, HTTPValidationError>({
          path: `/api/campaigns/${campaignId}/scenarios/${scenarioId}/validate`,
          method: "POST",
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags campaigns
     * @name CompileScenarioRowApiCampaignsCampaignIdScenariosScenarioIdCompilePost
     * @summary Compile Scenario Row
     * @request POST:/api/campaigns/{campaign_id}/scenarios/{scenario_id}/compile
     * @secure
     */
    compileScenarioRowApiCampaignsCampaignIdScenariosScenarioIdCompilePost: (
      campaignId: string,
      scenarioId: string,
      data: CompileScenarioBody,
      params: RequestParams = {},
    ) =>
      this.request<ScenarioOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/scenarios/${scenarioId}/compile`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name ListRunsApiCampaignsCampaignIdRunsGet
     * @summary List Runs
     * @request GET:/api/campaigns/{campaign_id}/runs
     * @secure
     */
    listRunsApiCampaignsCampaignIdRunsGet: (
      campaignId: string,
      query?: {
        /**
         * Limit
         * @default 20
         */
        limit?: number;
        /**
         * Offset
         * @default 0
         */
        offset?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/runs`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name GetRunApiCampaignsCampaignIdRunsRunIdGet
     * @summary Get Run
     * @request GET:/api/campaigns/{campaign_id}/runs/{run_id}
     * @secure
     */
    getRunApiCampaignsCampaignIdRunsRunIdGet: (
      campaignId: string,
      runId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/runs/${runId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name RunContentStatsApiCampaignsCampaignIdRunsRunIdContentStatsGet
     * @summary Run Content Stats
     * @request GET:/api/campaigns/{campaign_id}/runs/{run_id}/content/stats
     * @secure
     */
    runContentStatsApiCampaignsCampaignIdRunsRunIdContentStatsGet: (
      campaignId: string,
      runId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/runs/${runId}/content/stats`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags organizations
     * @name ListMyOrganizationsApiOrganizationsGet
     * @summary List My Organizations
     * @request GET:/api/organizations
     * @secure
     */
    listMyOrganizationsApiOrganizationsGet: (
      query?: {
        /** Search */
        search?: string | null;
        /**
         * Offset
         * @min 0
         * @default 0
         */
        offset?: number;
        /**
         * Limit
         * @min 1
         * @max 100
         * @default 50
         */
        limit?: number;
        /**
         * Ensure Id
         * Always include this org if accessible
         */
        ensure_id?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<OrganizationListOut, HTTPValidationError>({
        path: `/api/organizations`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags organizations
     * @name CreateOrganizationApiOrganizationsPost
     * @summary Create Organization
     * @request POST:/api/organizations
     * @secure
     */
    createOrganizationApiOrganizationsPost: (
      data: OrganizationCreate,
      params: RequestParams = {},
    ) =>
      this.request<OrganizationOut, HTTPValidationError>({
        path: `/api/organizations`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags organizations
     * @name ListOrganizationMembersApiOrganizationsMembersGet
     * @summary List Organization Members
     * @request GET:/api/organizations/members
     * @secure
     */
    listOrganizationMembersApiOrganizationsMembersGet: (
      params: RequestParams = {},
    ) =>
      this.request<OrganizationMemberOut[], any>({
        path: `/api/organizations/members`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags organizations
     * @name InviteOrganizationMemberApiOrganizationsMembersPost
     * @summary Invite Organization Member
     * @request POST:/api/organizations/members
     * @secure
     */
    inviteOrganizationMemberApiOrganizationsMembersPost: (
      data: OrganizationMemberInvite,
      params: RequestParams = {},
    ) =>
      this.request<OrganizationMemberInviteOut, HTTPValidationError>({
        path: `/api/organizations/members`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags organizations
     * @name AcceptOrganizationInvitationRouteApiOrganizationsInvitationsAcceptPost
     * @summary Accept Organization Invitation Route
     * @request POST:/api/organizations/invitations/accept
     * @secure
     */
    acceptOrganizationInvitationRouteApiOrganizationsInvitationsAcceptPost: (
      data: OrganizationInvitationAccept,
      params: RequestParams = {},
    ) =>
      this.request<OrganizationInvitationAcceptOut, HTTPValidationError>({
        path: `/api/organizations/invitations/accept`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags organizations
     * @name PreviewOrganizationInvitationApiOrganizationsInvitationsTokenGet
     * @summary Preview Organization Invitation
     * @request GET:/api/organizations/invitations/{token}
     */
    previewOrganizationInvitationApiOrganizationsInvitationsTokenGet: (
      token: string,
      params: RequestParams = {},
    ) =>
      this.request<OrganizationInvitationPreview, HTTPValidationError>({
        path: `/api/organizations/invitations/${token}`,
        method: "GET",
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags organizations
     * @name UpdateOrganizationMemberApiOrganizationsMembersMemberUserIdPatch
     * @summary Update Organization Member
     * @request PATCH:/api/organizations/members/{member_user_id}
     * @secure
     */
    updateOrganizationMemberApiOrganizationsMembersMemberUserIdPatch: (
      memberUserId: string,
      data: OrganizationMemberUpdate,
      params: RequestParams = {},
    ) =>
      this.request<OrganizationMemberOut, HTTPValidationError>({
        path: `/api/organizations/members/${memberUserId}`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags organizations
     * @name RemoveOrganizationMemberApiOrganizationsMembersMemberUserIdDelete
     * @summary Remove Organization Member
     * @request DELETE:/api/organizations/members/{member_user_id}
     * @secure
     */
    removeOrganizationMemberApiOrganizationsMembersMemberUserIdDelete: (
      memberUserId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/organizations/members/${memberUserId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags organizations
     * @name UnlockOrganizationMemberApiOrganizationsMembersMemberUserIdUnlockPost
     * @summary Unlock Organization Member
     * @request POST:/api/organizations/members/{member_user_id}/unlock
     * @secure
     */
    unlockOrganizationMemberApiOrganizationsMembersMemberUserIdUnlockPost: (
      memberUserId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/organizations/members/${memberUserId}/unlock`,
        method: "POST",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenario-templates
     * @name ListScenarioTemplatesApiScenarioTemplatesGet
     * @summary List Scenario Templates
     * @request GET:/api/scenario-templates
     * @secure
     */
    listScenarioTemplatesApiScenarioTemplatesGet: (
      query?: {
        /** Category */
        category?: string | null;
        /** Tags */
        tags?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<ScenarioTemplateOut[], HTTPValidationError>({
        path: `/api/scenario-templates`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenario-templates
     * @name CreateScenarioTemplateApiScenarioTemplatesPost
     * @summary Create Scenario Template
     * @request POST:/api/scenario-templates
     * @secure
     */
    createScenarioTemplateApiScenarioTemplatesPost: (
      data: ScenarioTemplateCreate,
      params: RequestParams = {},
    ) =>
      this.request<ScenarioTemplateOut, HTTPValidationError>({
        path: `/api/scenario-templates`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenario-templates
     * @name GetScenarioTemplateApiScenarioTemplatesTemplateIdGet
     * @summary Get Scenario Template
     * @request GET:/api/scenario-templates/{template_id}
     * @secure
     */
    getScenarioTemplateApiScenarioTemplatesTemplateIdGet: (
      templateId: string,
      params: RequestParams = {},
    ) =>
      this.request<ScenarioTemplateOut, HTTPValidationError>({
        path: `/api/scenario-templates/${templateId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenario-templates
     * @name UpdateScenarioTemplateApiScenarioTemplatesTemplateIdPatch
     * @summary Update Scenario Template
     * @request PATCH:/api/scenario-templates/{template_id}
     * @secure
     */
    updateScenarioTemplateApiScenarioTemplatesTemplateIdPatch: (
      templateId: string,
      data: ScenarioTemplateUpdate,
      params: RequestParams = {},
    ) =>
      this.request<ScenarioTemplateOut, HTTPValidationError>({
        path: `/api/scenario-templates/${templateId}`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenario-templates
     * @name DeleteScenarioTemplateApiScenarioTemplatesTemplateIdDelete
     * @summary Delete Scenario Template
     * @request DELETE:/api/scenario-templates/{template_id}
     * @secure
     */
    deleteScenarioTemplateApiScenarioTemplatesTemplateIdDelete: (
      templateId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/scenario-templates/${templateId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenario-templates
     * @name DuplicateScenarioTemplateApiScenarioTemplatesTemplateIdDuplicatePost
     * @summary Duplicate Scenario Template
     * @request POST:/api/scenario-templates/{template_id}/duplicate
     * @secure
     */
    duplicateScenarioTemplateApiScenarioTemplatesTemplateIdDuplicatePost: (
      templateId: string,
      params: RequestParams = {},
    ) =>
      this.request<ScenarioTemplateOut, HTTPValidationError>({
        path: `/api/scenario-templates/${templateId}/duplicate`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenarios
     * @name ListScenariosApiScenariosGet
     * @summary List Scenarios
     * @request GET:/api/scenarios
     * @secure
     */
    listScenariosApiScenariosGet: (
      query?: {
        /**
         * Org
         * Organization scope (superadmin only override)
         */
        org?: string | null;
        /**
         * Include Archived
         * @default false
         */
        include_archived?: boolean;
        /** Tag */
        tag?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<OrgScenarioSummaryOut[], HTTPValidationError>({
        path: `/api/scenarios`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenarios
     * @name CreateScenarioRouteApiScenariosPost
     * @summary Create Scenario Route
     * @request POST:/api/scenarios
     * @secure
     */
    createScenarioRouteApiScenariosPost: (
      data: OrgScenarioCreate,
      params: RequestParams = {},
    ) =>
      this.request<OrgScenarioOut, HTTPValidationError>({
        path: `/api/scenarios`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenarios
     * @name ScenarioTemplateSummaryOutApiScenariosTemplatesGet
     * @summary  Scenario Template Summary Out
     * @request GET:/api/scenarios/templates
     * @secure
     */
    scenarioTemplateSummaryOutApiScenariosTemplatesGet: (
      query: {
        /** T */
        t: any;
      },
      params: RequestParams = {},
    ) =>
      this.request<OrgScenarioSummaryOut[], HTTPValidationError>({
        path: `/api/scenarios/templates`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenarios
     * @name ImportScenarioRouteApiScenariosImportPost
     * @summary Import Scenario Route
     * @request POST:/api/scenarios/import
     * @secure
     */
    importScenarioRouteApiScenariosImportPost: (
      data: BodyImportScenarioRouteApiScenariosImportPost,
      query?: {
        /**
         * Resolve
         * @default "reject"
         * @pattern ^(reject|create_stub)$
         */
        resolve?: string;
      },
      params: RequestParams = {},
    ) =>
      this.request<OrgScenarioImportOut, HTTPValidationError>({
        path: `/api/scenarios/import`,
        method: "POST",
        query: query,
        body: data,
        secure: true,
        type: ContentType.FormData,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenarios
     * @name CloneScenarioTemplateRouteApiScenariosTemplatesTemplateIdClonePost
     * @summary Clone Scenario Template Route
     * @request POST:/api/scenarios/templates/{template_id}/clone
     * @secure
     */
    cloneScenarioTemplateRouteApiScenariosTemplatesTemplateIdClonePost: (
      templateId: string,
      data: OrgScenarioCloneTemplateIn,
      params: RequestParams = {},
    ) =>
      this.request<OrgScenarioImportOut, HTTPValidationError>({
        path: `/api/scenarios/templates/${templateId}/clone`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenarios
     * @name GetScenarioApiScenariosScenarioIdGet
     * @summary Get Scenario
     * @request GET:/api/scenarios/{scenario_id}
     * @secure
     */
    getScenarioApiScenariosScenarioIdGet: (
      scenarioId: string,
      params: RequestParams = {},
    ) =>
      this.request<OrgScenarioOut, HTTPValidationError>({
        path: `/api/scenarios/${scenarioId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenarios
     * @name PatchScenarioApiScenariosScenarioIdPatch
     * @summary Patch Scenario
     * @request PATCH:/api/scenarios/{scenario_id}
     * @secure
     */
    patchScenarioApiScenariosScenarioIdPatch: (
      scenarioId: string,
      data: OrgScenarioUpdate,
      params: RequestParams = {},
    ) =>
      this.request<OrgScenarioOut, HTTPValidationError>({
        path: `/api/scenarios/${scenarioId}`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenarios
     * @name DeleteScenarioApiScenariosScenarioIdDelete
     * @summary Delete Scenario
     * @request DELETE:/api/scenarios/{scenario_id}
     * @secure
     */
    deleteScenarioApiScenariosScenarioIdDelete: (
      scenarioId: string,
      params: RequestParams = {},
    ) =>
      this.request<OrgScenarioOut, HTTPValidationError>({
        path: `/api/scenarios/${scenarioId}`,
        method: "DELETE",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenarios
     * @name ExportScenarioRouteApiScenariosScenarioIdExportGet
     * @summary Export Scenario Route
     * @request GET:/api/scenarios/{scenario_id}/export
     * @secure
     */
    exportScenarioRouteApiScenariosScenarioIdExportGet: (
      scenarioId: string,
      query?: {
        /**
         * Format
         * @default "yaml"
         * @pattern ^(yaml|json)$
         */
        format?: string;
        /** Version */
        version?: number | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/scenarios/${scenarioId}/export`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenarios
     * @name ValidateScenarioRouteApiScenariosScenarioIdValidatePost
     * @summary Validate Scenario Route
     * @request POST:/api/scenarios/{scenario_id}/validate
     * @secure
     */
    validateScenarioRouteApiScenariosScenarioIdValidatePost: (
      scenarioId: string,
      data: OrgScenarioValidateIn | null,
      params: RequestParams = {},
    ) =>
      this.request<OrgScenarioValidationOut, HTTPValidationError>({
        path: `/api/scenarios/${scenarioId}/validate`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenarios
     * @name GetScenarioBodyRouteApiScenariosScenarioIdBodyGet
     * @summary Get Scenario Body Route
     * @request GET:/api/scenarios/{scenario_id}/body
     * @secure
     */
    getScenarioBodyRouteApiScenariosScenarioIdBodyGet: (
      scenarioId: string,
      params: RequestParams = {},
    ) =>
      this.request<OrgScenarioBodyOut, HTTPValidationError>({
        path: `/api/scenarios/${scenarioId}/body`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenarios
     * @name PostScenarioBodyRouteApiScenariosScenarioIdBodyPost
     * @summary Post Scenario Body Route
     * @request POST:/api/scenarios/{scenario_id}/body
     * @secure
     */
    postScenarioBodyRouteApiScenariosScenarioIdBodyPost: (
      scenarioId: string,
      data: OrgScenarioBodyIn,
      query?: {
        /**
         * Force
         * Save despite semantic validation errors
         * @default false
         */
        force?: boolean;
      },
      params: RequestParams = {},
    ) =>
      this.request<OrgScenarioBodyOut, HTTPValidationError>({
        path: `/api/scenarios/${scenarioId}/body`,
        method: "POST",
        query: query,
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags scenarios
     * @name RestoreScenarioRouteApiScenariosScenarioIdRestorePost
     * @summary Restore Scenario Route
     * @request POST:/api/scenarios/{scenario_id}/restore
     * @secure
     */
    restoreScenarioRouteApiScenariosScenarioIdRestorePost: (
      scenarioId: string,
      params: RequestParams = {},
    ) =>
      this.request<OrgScenarioOut, HTTPValidationError>({
        path: `/api/scenarios/${scenarioId}/restore`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Run scenario on one device as an isolated preview execution (DF-T-04-018).
     *
     * @tags scenarios
     * @name StartScenarioPreviewApiScenariosScenarioIdPreviewPost
     * @summary Start Scenario Preview
     * @request POST:/api/scenarios/{scenario_id}/preview
     * @secure
     */
    startScenarioPreviewApiScenariosScenarioIdPreviewPost: (
      scenarioId: string,
      data: PreviewStartRequest,
      params: RequestParams = {},
    ) =>
      this.request<PreviewStartResponse, HTTPValidationError>({
        path: `/api/scenarios/${scenarioId}/preview`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description List all device groups for the authenticated user (includes device count).
     *
     * @tags device-groups
     * @name ListDeviceGroupsApiDeviceGroupsGet
     * @summary List Device Groups
     * @request GET:/api/device-groups
     * @secure
     */
    listDeviceGroupsApiDeviceGroupsGet: (params: RequestParams = {}) =>
      this.request<DeviceGroupOut[], any>({
        path: `/api/device-groups`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-groups
     * @name CreateDeviceGroupApiDeviceGroupsPost
     * @summary Create Device Group
     * @request POST:/api/device-groups
     * @secure
     */
    createDeviceGroupApiDeviceGroupsPost: (
      data: DeviceGroupCreate,
      params: RequestParams = {},
    ) =>
      this.request<DeviceGroupOut, HTTPValidationError>({
        path: `/api/device-groups`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Get group with full device list.
     *
     * @tags device-groups
     * @name GetDeviceGroupApiDeviceGroupsGroupIdGet
     * @summary Get Device Group
     * @request GET:/api/device-groups/{group_id}
     * @secure
     */
    getDeviceGroupApiDeviceGroupsGroupIdGet: (
      groupId: string,
      params: RequestParams = {},
    ) =>
      this.request<DeviceGroupDetailOut, HTTPValidationError>({
        path: `/api/device-groups/${groupId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-groups
     * @name UpdateDeviceGroupApiDeviceGroupsGroupIdPatch
     * @summary Update Device Group
     * @request PATCH:/api/device-groups/{group_id}
     * @secure
     */
    updateDeviceGroupApiDeviceGroupsGroupIdPatch: (
      groupId: string,
      data: DeviceGroupUpdate,
      params: RequestParams = {},
    ) =>
      this.request<DeviceGroupOut, HTTPValidationError>({
        path: `/api/device-groups/${groupId}`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Delete group and all its memberships. Devices themselves are NOT deleted.
     *
     * @tags device-groups
     * @name DeleteDeviceGroupApiDeviceGroupsGroupIdDelete
     * @summary Delete Device Group
     * @request DELETE:/api/device-groups/{group_id}
     * @secure
     */
    deleteDeviceGroupApiDeviceGroupsGroupIdDelete: (
      groupId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/device-groups/${groupId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * @description Add one or more devices to the group. Already-present devices are ignored.
     *
     * @tags device-groups
     * @name AddDevicesApiDeviceGroupsGroupIdDevicesPost
     * @summary Add Devices
     * @request POST:/api/device-groups/{group_id}/devices
     * @secure
     */
    addDevicesApiDeviceGroupsGroupIdDevicesPost: (
      groupId: string,
      data: AddDevicesToGroupBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/device-groups/${groupId}/devices`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Remove a device from the group. The device itself is NOT deleted.
     *
     * @tags device-groups
     * @name RemoveDeviceApiDeviceGroupsGroupIdDevicesDeviceIdDelete
     * @summary Remove Device
     * @request DELETE:/api/device-groups/{group_id}/devices/{device_id}
     * @secure
     */
    removeDeviceApiDeviceGroupsGroupIdDevicesDeviceIdDelete: (
      groupId: string,
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/device-groups/${groupId}/devices/${deviceId}`,
        method: "DELETE",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description List accounts owned by the current user with optional filters.
     *
     * @tags accounts
     * @name ListAccountsEndpointApiAccountsGet
     * @summary List Accounts Endpoint
     * @request GET:/api/accounts
     * @secure
     */
    listAccountsEndpointApiAccountsGet: (
      query?: {
        /** Platform */
        platform?: string | null;
        /** Status */
        status?: string | null;
        /** State */
        state?: string | null;
        /**
         * Include States
         * Override default listing; comma-separated in OpenAPI as repeated params
         */
        include_states?: string[] | null;
        /** Tags */
        tags?: string | null;
        /**
         * Limit
         * @min 1
         * @max 200
         * @default 50
         */
        limit?: number;
        /**
         * Offset
         * @min 0
         * @default 0
         */
        offset?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<AccountOut[], HTTPValidationError>({
        path: `/api/accounts`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Create a new account. Password is encrypted before storage.
     *
     * @tags accounts
     * @name CreateAccountEndpointApiAccountsPost
     * @summary Create Account Endpoint
     * @request POST:/api/accounts
     * @secure
     */
    createAccountEndpointApiAccountsPost: (
      data: AccountCreate,
      params: RequestParams = {},
    ) =>
      this.request<AccountOut, HTTPValidationError>({
        path: `/api/accounts`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Bulk import accounts from a JSON array. Duplicate (platform, username) pairs are skipped.
     *
     * @tags accounts
     * @name BulkImportJsonApiAccountsImportPost
     * @summary Bulk Import Json
     * @request POST:/api/accounts/import
     * @secure
     */
    bulkImportJsonApiAccountsImportPost: (
      data: BulkImportBody,
      params: RequestParams = {},
    ) =>
      this.request<BulkImportResult, HTTPValidationError>({
        path: `/api/accounts/import`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Stream-import accounts from a CSV file upload. Reads the upload in 64 KB chunks, parses CSV incrementally, and flushes batches of up to 500 rows to the DB via INSERT ON CONFLICT DO NOTHING — so memory usage stays flat regardless of file size. Expected CSV columns: platform, username, password, display_name, tags, notes
     *
     * @tags accounts
     * @name BulkImportCsvApiAccountsImportCsvPost
     * @summary Bulk Import Csv
     * @request POST:/api/accounts/import-csv
     * @secure
     */
    bulkImportCsvApiAccountsImportCsvPost: (
      data: BodyBulkImportCsvApiAccountsImportCsvPost,
      params: RequestParams = {},
    ) =>
      this.request<BulkImportResult, HTTPValidationError>({
        path: `/api/accounts/import-csv`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.FormData,
        format: "json",
        ...params,
      }),

    /**
     * @description Auto-assign active accounts to devices in round-robin order.
     *
     * @tags accounts
     * @name RoundRobinAssignEndpointApiAccountsRoundRobinPost
     * @summary Round Robin Assign Endpoint
     * @request POST:/api/accounts/round-robin
     * @secure
     */
    roundRobinAssignEndpointApiAccountsRoundRobinPost: (
      data: RoundRobinBody,
      params: RequestParams = {},
    ) =>
      this.request<Record<string, any>, HTTPValidationError>({
        path: `/api/accounts/round-robin`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Transition account FSM state with validation, audit, and domain event.
     *
     * @tags accounts
     * @name TransitionAccountStateApiAccountsAccountIdStatePost
     * @summary Transition Account State
     * @request POST:/api/accounts/{account_id}/state
     * @secure
     */
    transitionAccountStateApiAccountsAccountIdStatePost: (
      accountId: string,
      data: AccountStateTransitionBody,
      params: RequestParams = {},
    ) =>
      this.request<AccountStateTransitionOut, HTTPValidationError>({
        path: `/api/accounts/${accountId}/state`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Get account details including device links.
     *
     * @tags accounts
     * @name GetAccountEndpointApiAccountsAccountIdGet
     * @summary Get Account Endpoint
     * @request GET:/api/accounts/{account_id}
     * @secure
     */
    getAccountEndpointApiAccountsAccountIdGet: (
      accountId: string,
      params: RequestParams = {},
    ) =>
      this.request<AccountWithLinksOut, HTTPValidationError>({
        path: `/api/accounts/${accountId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Update account fields. Password (if provided) is re-encrypted before storage.
     *
     * @tags accounts
     * @name UpdateAccountEndpointApiAccountsAccountIdPatch
     * @summary Update Account Endpoint
     * @request PATCH:/api/accounts/{account_id}
     * @secure
     */
    updateAccountEndpointApiAccountsAccountIdPatch: (
      accountId: string,
      data: AccountUpdate,
      params: RequestParams = {},
    ) =>
      this.request<AccountOut, HTTPValidationError>({
        path: `/api/accounts/${accountId}`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Delete account and all its device links (cascade).
     *
     * @tags accounts
     * @name DeleteAccountEndpointApiAccountsAccountIdDelete
     * @summary Delete Account Endpoint
     * @request DELETE:/api/accounts/{account_id}
     * @secure
     */
    deleteAccountEndpointApiAccountsAccountIdDelete: (
      accountId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/accounts/${accountId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * @description Paginated account profile / session timeline (newest first).
     *
     * @tags accounts
     * @name ListAccountEventsEndpointApiAccountsAccountIdEventsGet
     * @summary List Account Events Endpoint
     * @request GET:/api/accounts/{account_id}/events
     * @secure
     */
    listAccountEventsEndpointApiAccountsAccountIdEventsGet: (
      accountId: string,
      query?: {
        /**
         * Limit
         * @min 1
         * @max 200
         * @default 50
         */
        limit?: number;
        /** Cursor */
        cursor?: string | null;
        /** Event Type */
        event_type?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<AccountEventListOut, HTTPValidationError>({
        path: `/api/accounts/${accountId}/events`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Set account status via FSM (legacy alias). Prefer POST /state.
     *
     * @tags accounts
     * @name UpdateAccountStatusApiAccountsAccountIdStatusPatch
     * @summary Update Account Status
     * @request PATCH:/api/accounts/{account_id}/status
     * @secure
     */
    updateAccountStatusApiAccountsAccountIdStatusPatch: (
      accountId: string,
      data: AccountStatusUpdate,
      params: RequestParams = {},
    ) =>
      this.request<AccountOut, HTTPValidationError>({
        path: `/api/accounts/${accountId}/status`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description List all device-account links for an account.
     *
     * @tags accounts
     * @name ListAccountDevicesEndpointApiAccountsAccountIdDevicesGet
     * @summary List Account Devices Endpoint
     * @request GET:/api/accounts/{account_id}/devices
     * @secure
     */
    listAccountDevicesEndpointApiAccountsAccountIdDevicesGet: (
      accountId: string,
      params: RequestParams = {},
    ) =>
      this.request<DeviceAccountOut[], HTTPValidationError>({
        path: `/api/accounts/${accountId}/devices`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Assign a device to an account.
     *
     * @tags accounts
     * @name AssignDeviceToAccountApiAccountsAccountIdDevicesPost
     * @summary Assign Device To Account
     * @request POST:/api/accounts/{account_id}/devices
     * @secure
     */
    assignDeviceToAccountApiAccountsAccountIdDevicesPost: (
      accountId: string,
      data: AssignDeviceBody,
      params: RequestParams = {},
    ) =>
      this.request<DeviceAccountOut, HTTPValidationError>({
        path: `/api/accounts/${accountId}/devices`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Remove a device-account link.
     *
     * @tags accounts
     * @name UnassignDeviceFromAccountApiAccountsAccountIdDevicesDeviceIdDelete
     * @summary Unassign Device From Account
     * @request DELETE:/api/accounts/{account_id}/devices/{device_id}
     * @secure
     */
    unassignDeviceFromAccountApiAccountsAccountIdDevicesDeviceIdDelete: (
      accountId: string,
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/accounts/${accountId}/devices/${deviceId}`,
        method: "DELETE",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description List all accounts assigned to a device.
     *
     * @tags accounts
     * @name ListDeviceAccountsEndpointApiDevicesDeviceIdAccountsGet
     * @summary List Device Accounts Endpoint
     * @request GET:/api/devices/{device_id}/accounts
     * @secure
     */
    listDeviceAccountsEndpointApiDevicesDeviceIdAccountsGet: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<DeviceAccountOut[], HTTPValidationError>({
        path: `/api/devices/${deviceId}/accounts`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Assign an account to a device.
     *
     * @tags accounts
     * @name AssignAccountToDeviceEndpointApiDevicesDeviceIdAccountsPost
     * @summary Assign Account To Device Endpoint
     * @request POST:/api/devices/{device_id}/accounts
     * @secure
     */
    assignAccountToDeviceEndpointApiDevicesDeviceIdAccountsPost: (
      deviceId: string,
      data: AssignAccountBody,
      params: RequestParams = {},
    ) =>
      this.request<DeviceAccountOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}/accounts`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Set the primary account for a device (demotes existing primary).
     *
     * @tags accounts
     * @name SetPrimaryAccountEndpointApiDevicesDeviceIdAccountsPrimaryPost
     * @summary Set Primary Account Endpoint
     * @request POST:/api/devices/{device_id}/accounts/primary
     * @secure
     */
    setPrimaryAccountEndpointApiDevicesDeviceIdAccountsPrimaryPost: (
      deviceId: string,
      data: SetPrimaryBody,
      params: RequestParams = {},
    ) =>
      this.request<DeviceAccountOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}/accounts/primary`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags account-groups
     * @name ListAccountGroupsApiAccountGroupsGet
     * @summary List Account Groups
     * @request GET:/api/account-groups
     * @secure
     */
    listAccountGroupsApiAccountGroupsGet: (
      query?: {
        /** Platform */
        platform?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<AccountGroupOut[], HTTPValidationError>({
        path: `/api/account-groups`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags account-groups
     * @name CreateAccountGroupApiAccountGroupsPost
     * @summary Create Account Group
     * @request POST:/api/account-groups
     * @secure
     */
    createAccountGroupApiAccountGroupsPost: (
      data: AccountGroupCreate,
      params: RequestParams = {},
    ) =>
      this.request<AccountGroupOut, HTTPValidationError>({
        path: `/api/account-groups`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags account-groups
     * @name GetAccountGroupApiAccountGroupsGroupIdGet
     * @summary Get Account Group
     * @request GET:/api/account-groups/{group_id}
     * @secure
     */
    getAccountGroupApiAccountGroupsGroupIdGet: (
      groupId: string,
      params: RequestParams = {},
    ) =>
      this.request<AccountGroupOut, HTTPValidationError>({
        path: `/api/account-groups/${groupId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags account-groups
     * @name UpdateAccountGroupApiAccountGroupsGroupIdPatch
     * @summary Update Account Group
     * @request PATCH:/api/account-groups/{group_id}
     * @secure
     */
    updateAccountGroupApiAccountGroupsGroupIdPatch: (
      groupId: string,
      data: AccountGroupUpdate,
      params: RequestParams = {},
    ) =>
      this.request<AccountGroupOut, HTTPValidationError>({
        path: `/api/account-groups/${groupId}`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags account-groups
     * @name DeleteAccountGroupApiAccountGroupsGroupIdDelete
     * @summary Delete Account Group
     * @request DELETE:/api/account-groups/{group_id}
     * @secure
     */
    deleteAccountGroupApiAccountGroupsGroupIdDelete: (
      groupId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/account-groups/${groupId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags account-groups
     * @name ListAccountGroupMembersApiAccountGroupsGroupIdMembersGet
     * @summary List Account Group Members
     * @request GET:/api/account-groups/{group_id}/members
     * @secure
     */
    listAccountGroupMembersApiAccountGroupsGroupIdMembersGet: (
      groupId: string,
      params: RequestParams = {},
    ) =>
      this.request<AccountGroupMemberOut[], HTTPValidationError>({
        path: `/api/account-groups/${groupId}/members`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags account-groups
     * @name AddAccountGroupMembersApiAccountGroupsGroupIdMembersPost
     * @summary Add Account Group Members
     * @request POST:/api/account-groups/{group_id}/members
     * @secure
     */
    addAccountGroupMembersApiAccountGroupsGroupIdMembersPost: (
      groupId: string,
      data: AccountGroupMemberBatchAdd,
      params: RequestParams = {},
    ) =>
      this.request<AccountGroupMemberBatchResult, HTTPValidationError>({
        path: `/api/account-groups/${groupId}/members`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags account-groups
     * @name RemoveAccountGroupMemberApiAccountGroupsGroupIdMembersAccountIdDelete
     * @summary Remove Account Group Member
     * @request DELETE:/api/account-groups/{group_id}/members/{account_id}
     * @secure
     */
    removeAccountGroupMemberApiAccountGroupsGroupIdMembersAccountIdDelete: (
      groupId: string,
      accountId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/account-groups/${groupId}/members/${accountId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * @description Pick one usable account and return the ``__ACCOUNT_*`` variable bundle. Used by the Control Record "Run test" / step-by-step flow so the same account is reused across multiple preview calls in one session — avoids login-step mismatch where step 2 (username) and step 3 (password) would otherwise be satisfied from two different accounts. Advances the group's rotation cursor just like a real dispatch so repeated sessions rotate.
     *
     * @tags account-groups
     * @name ResolveAccountGroupApiAccountGroupsGroupIdResolvePost
     * @summary Resolve Account Group
     * @request POST:/api/account-groups/{group_id}/resolve
     * @secure
     */
    resolveAccountGroupApiAccountGroupsGroupIdResolvePost: (
      groupId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/account-groups/${groupId}/resolve`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Stream content export directly to the client — no temp file, no job queue. CSV streams row-by-row via chunked transfer encoding. XLSX is built in-memory with openpyxl write-only mode then sent as a single response.
     *
     * @tags content
     * @name StreamExportApiContentExportStreamGet
     * @summary Stream Export
     * @request GET:/api/content/export/stream
     * @secure
     */
    streamExportApiContentExportStreamGet: (
      query?: {
        /**
         * Format
         * @default "csv"
         * @pattern ^(csv|xlsx)$
         */
        format?: string;
        /** Collection */
        collection?: string | null;
        /** Platform */
        platform?: string | null;
        /** Content Type */
        content_type?: string | null;
        /** Search */
        search?: string | null;
        /** Device Serial */
        device_serial?: string | null;
        /** Campaign Id */
        campaign_id?: string | null;
        /** Execution Id */
        execution_id?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/content/export/stream`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags content
     * @name LegacyExportRemovedApiContentExportPost
     * @summary Legacy Export Removed
     * @request POST:/api/content/export
     * @secure
     */
    legacyExportRemovedApiContentExportPost: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/content/export`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags content
     * @name LegacyExportListRemovedApiContentExportsListGet
     * @summary Legacy Export List Removed
     * @request GET:/api/content/exports/list
     * @secure
     */
    legacyExportListRemovedApiContentExportsListGet: (
      params: RequestParams = {},
    ) =>
      this.request<any, any>({
        path: `/api/content/exports/list`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags content
     * @name LegacyExportDetailRemovedApiContentExportsExportIdGet
     * @summary Legacy Export Detail Removed
     * @request GET:/api/content/exports/{export_id}
     * @secure
     */
    legacyExportDetailRemovedApiContentExportsExportIdGet: (
      exportId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/content/exports/${exportId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags content
     * @name LegacyExportDownloadRemovedApiContentExportsExportIdDownloadGet
     * @summary Legacy Export Download Removed
     * @request GET:/api/content/exports/{export_id}/download
     * @secure
     */
    legacyExportDownloadRemovedApiContentExportsExportIdDownloadGet: (
      exportId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/content/exports/${exportId}/download`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags content
     * @name ListContentApiContentGet
     * @summary List Content
     * @request GET:/api/content
     * @secure
     */
    listContentApiContentGet: (
      query?: {
        /** Collection */
        collection?: string | null;
        /** Platform */
        platform?: string | null;
        /** Content Type */
        content_type?: string | null;
        /** Search */
        search?: string | null;
        /** Device Serial */
        device_serial?: string | null;
        /** Campaign Id */
        campaign_id?: string | null;
        /** Execution Id */
        execution_id?: string | null;
        /** Content Hash */
        content_hash?: string | null;
        /** Parent Id */
        parent_id?: string | null;
        /**
         * Limit
         * @min 1
         * @max 500
         * @default 50
         */
        limit?: number;
        /**
         * Offset
         * @min 0
         * @default 0
         */
        offset?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/content`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags content
     * @name GetStatsApiContentStatsGet
     * @summary Get Stats
     * @request GET:/api/content/stats
     * @secure
     */
    getStatsApiContentStatsGet: (params: RequestParams = {}) =>
      this.request<ContentStatsOut, any>({
        path: `/api/content/stats`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Platform-qualified content type registry (DF-T-06-001).
     *
     * @tags content
     * @name ListContentTypesApiContentTypesGet
     * @summary List Content Types
     * @request GET:/api/content/types
     * @secure
     */
    listContentTypesApiContentTypesGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/content/types`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags content
     * @name RefreshContentTypesApiContentTypesRefreshPost
     * @summary Refresh Content Types
     * @request POST:/api/content/types/refresh
     * @secure
     */
    refreshContentTypesApiContentTypesRefreshPost: (
      params: RequestParams = {},
    ) =>
      this.request<any, any>({
        path: `/api/content/types/refresh`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Save extracted content with deduplication (used by scenarios and MCP).
     *
     * @tags content
     * @name SaveContentApiContentSavePost
     * @summary Save Content
     * @request POST:/api/content/save
     * @secure
     */
    saveContentApiContentSavePost: (
      data: SaveContentBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/content/save`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags content
     * @name GetContentItemApiContentItemIdGet
     * @summary Get Content Item
     * @request GET:/api/content/{item_id}
     * @secure
     */
    getContentItemApiContentItemIdGet: (
      itemId: string,
      query?: {
        /**
         * Share
         * Content share JWT from permalink
         */
        share?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<ContentDetailOut, HTTPValidationError>({
        path: `/api/content/${itemId}`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags content
     * @name DeleteContentItemApiContentItemIdDelete
     * @summary Delete Content Item
     * @request DELETE:/api/content/{item_id}
     * @secure
     */
    deleteContentItemApiContentItemIdDelete: (
      itemId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/content/${itemId}`,
        method: "DELETE",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags content
     * @name DownloadContentArtifactApiContentItemIdArtifactsArtifactIdDownloadGet
     * @summary Download Content Artifact
     * @request GET:/api/content/{item_id}/artifacts/{artifact_id}/download
     * @secure
     */
    downloadContentArtifactApiContentItemIdArtifactsArtifactIdDownloadGet: (
      itemId: string,
      artifactId: string,
      query?: {
        /** Share */
        share?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/content/${itemId}/artifacts/${artifactId}/download`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags content
     * @name CreateContentPermalinkApiContentItemIdPermalinkPost
     * @summary Create Content Permalink
     * @request POST:/api/content/{item_id}/permalink
     * @secure
     */
    createContentPermalinkApiContentItemIdPermalinkPost: (
      itemId: string,
      params: RequestParams = {},
    ) =>
      this.request<ContentPermalinkOut, HTTPValidationError>({
        path: `/api/content/${itemId}/permalink`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags content
     * @name ListCollectionsApiContentCollectionsListGet
     * @summary List Collections
     * @request GET:/api/content/collections/list
     * @secure
     */
    listCollectionsApiContentCollectionsListGet: (params: RequestParams = {}) =>
      this.request<CollectionOut[], any>({
        path: `/api/content/collections/list`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags content
     * @name CreateCollectionApiContentCollectionsPost
     * @summary Create Collection
     * @request POST:/api/content/collections
     * @secure
     */
    createCollectionApiContentCollectionsPost: (
      data: CollectionCreate,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/content/collections`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags content
     * @name DeleteCollectionApiContentCollectionsNameDelete
     * @summary Delete Collection
     * @request DELETE:/api/content/collections/{name}
     * @secure
     */
    deleteCollectionApiContentCollectionsNameDelete: (
      name: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/content/collections/${name}`,
        method: "DELETE",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Stream artifact bytes through the API (browser-safe; avoids internal MinIO hosts).
     *
     * @tags artifacts
     * @name GetArtifactContentApiArtifactsArtifactIdContentGet
     * @summary Get Artifact Content
     * @request GET:/api/artifacts/{artifact_id}/content
     * @secure
     */
    getArtifactContentApiArtifactsArtifactIdContentGet: (
      artifactId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/artifacts/${artifactId}/content`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags artifacts
     * @name GetArtifactSignedUrlApiArtifactsArtifactIdUrlGet
     * @summary Get Artifact Signed Url
     * @request GET:/api/artifacts/{artifact_id}/url
     * @secure
     */
    getArtifactSignedUrlApiArtifactsArtifactIdUrlGet: (
      artifactId: string,
      query?: {
        /**
         * Ttl Seconds
         * @default 3600
         */
        ttl_seconds?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<ArtifactUrlOut, HTTPValidationError>({
        path: `/api/artifacts/${artifactId}/url`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags schedules
     * @name ListSchedulesEndpointApiSchedulesGet
     * @summary List Schedules Endpoint
     * @request GET:/api/schedules
     * @secure
     */
    listSchedulesEndpointApiSchedulesGet: (
      query?: {
        /**
         * Offset
         * @default 0
         */
        offset?: number;
        /**
         * Limit
         * @default 50
         */
        limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<ScheduleOut[], HTTPValidationError>({
        path: `/api/schedules`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags schedules
     * @name CreateScheduleEndpointApiSchedulesPost
     * @summary Create Schedule Endpoint
     * @request POST:/api/schedules
     * @secure
     */
    createScheduleEndpointApiSchedulesPost: (
      data: ScheduleCreate,
      params: RequestParams = {},
    ) =>
      this.request<ScheduleOut, HTTPValidationError>({
        path: `/api/schedules`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags schedules
     * @name PreviewScheduleEndpointApiSchedulesPreviewPost
     * @summary Preview Schedule Endpoint
     * @request POST:/api/schedules/preview
     * @secure
     */
    previewScheduleEndpointApiSchedulesPreviewPost: (
      data: SchedulePreviewIn,
      params: RequestParams = {},
    ) =>
      this.request<SchedulePreviewOut, HTTPValidationError>({
        path: `/api/schedules/preview`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags schedules
     * @name ScheduleStatusEndpointApiSchedulesSystemStatusGet
     * @summary Schedule Status Endpoint
     * @request GET:/api/schedules/system/status
     * @secure
     */
    scheduleStatusEndpointApiSchedulesSystemStatusGet: (
      params: RequestParams = {},
    ) =>
      this.request<ScheduleStatusOut, any>({
        path: `/api/schedules/system/status`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags schedules
     * @name BulkPauseEndpointApiSchedulesBulkPausePost
     * @summary Bulk Pause Endpoint
     * @request POST:/api/schedules/bulk/pause
     * @secure
     */
    bulkPauseEndpointApiSchedulesBulkPausePost: (
      data: BulkScheduleToggleIn,
      params: RequestParams = {},
    ) =>
      this.request<BulkScheduleToggleOut, HTTPValidationError>({
        path: `/api/schedules/bulk/pause`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags schedules
     * @name BulkResumeEndpointApiSchedulesBulkResumePost
     * @summary Bulk Resume Endpoint
     * @request POST:/api/schedules/bulk/resume
     * @secure
     */
    bulkResumeEndpointApiSchedulesBulkResumePost: (
      data: BulkScheduleToggleIn,
      params: RequestParams = {},
    ) =>
      this.request<BulkScheduleToggleOut, HTTPValidationError>({
        path: `/api/schedules/bulk/resume`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags schedules
     * @name GetScheduleEndpointApiSchedulesScheduleIdGet
     * @summary Get Schedule Endpoint
     * @request GET:/api/schedules/{schedule_id}
     * @secure
     */
    getScheduleEndpointApiSchedulesScheduleIdGet: (
      scheduleId: string,
      params: RequestParams = {},
    ) =>
      this.request<ScheduleOut, HTTPValidationError>({
        path: `/api/schedules/${scheduleId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags schedules
     * @name UpdateScheduleEndpointApiSchedulesScheduleIdPatch
     * @summary Update Schedule Endpoint
     * @request PATCH:/api/schedules/{schedule_id}
     * @secure
     */
    updateScheduleEndpointApiSchedulesScheduleIdPatch: (
      scheduleId: string,
      data: SchedulePatch,
      params: RequestParams = {},
    ) =>
      this.request<ScheduleOut, HTTPValidationError>({
        path: `/api/schedules/${scheduleId}`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags schedules
     * @name DeleteScheduleEndpointApiSchedulesScheduleIdDelete
     * @summary Delete Schedule Endpoint
     * @request DELETE:/api/schedules/{schedule_id}
     * @secure
     */
    deleteScheduleEndpointApiSchedulesScheduleIdDelete: (
      scheduleId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/schedules/${scheduleId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags schedules
     * @name ToggleScheduleEndpointApiSchedulesScheduleIdTogglePost
     * @summary Toggle Schedule Endpoint
     * @request POST:/api/schedules/{schedule_id}/toggle
     * @secure
     */
    toggleScheduleEndpointApiSchedulesScheduleIdTogglePost: (
      scheduleId: string,
      params: RequestParams = {},
    ) =>
      this.request<ScheduleOut, HTTPValidationError>({
        path: `/api/schedules/${scheduleId}/toggle`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags schedules
     * @name RunNowEndpointApiSchedulesScheduleIdRunNowPost
     * @summary Run Now Endpoint
     * @request POST:/api/schedules/{schedule_id}/run-now
     * @secure
     */
    runNowEndpointApiSchedulesScheduleIdRunNowPost: (
      scheduleId: string,
      params: RequestParams = {},
    ) =>
      this.request<TriggerResponse, HTTPValidationError>({
        path: `/api/schedules/${scheduleId}/run-now`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags schedules
     * @name ListRunsEndpointApiSchedulesScheduleIdRunsGet
     * @summary List Runs Endpoint
     * @request GET:/api/schedules/{schedule_id}/runs
     * @secure
     */
    listRunsEndpointApiSchedulesScheduleIdRunsGet: (
      scheduleId: string,
      query?: {
        /**
         * Offset
         * @default 0
         */
        offset?: number;
        /**
         * Limit
         * @default 50
         */
        limit?: number;
        /** Status */
        status?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<ScheduleRunOut[], HTTPValidationError>({
        path: `/api/schedules/${scheduleId}/runs`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags schedules
     * @name GetRunEndpointApiSchedulesScheduleIdRunsRunIdGet
     * @summary Get Run Endpoint
     * @request GET:/api/schedules/{schedule_id}/runs/{run_id}
     * @secure
     */
    getRunEndpointApiSchedulesScheduleIdRunsRunIdGet: (
      scheduleId: string,
      runId: string,
      params: RequestParams = {},
    ) =>
      this.request<ScheduleRunOut, HTTPValidationError>({
        path: `/api/schedules/${scheduleId}/runs/${runId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name CreateExecutionEndpointApiExecutionsPost
     * @summary Create Execution Endpoint
     * @request POST:/api/executions
     * @secure
     */
    createExecutionEndpointApiExecutionsPost: (
      data: ExecutionCreate,
      params: RequestParams = {},
    ) =>
      this.request<ExecutionOut, HTTPValidationError>({
        path: `/api/executions`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name ListExecutionsEndpointApiExecutionsGet
     * @summary List Executions Endpoint
     * @request GET:/api/executions
     * @secure
     */
    listExecutionsEndpointApiExecutionsGet: (
      query?: {
        /** Run Type */
        run_type?: string | null;
        /** Status Filter */
        status_filter?: string | null;
        /** Campaign Id */
        campaign_id?: string | null;
        /** Scenario Id */
        scenario_id?: string | null;
        /**
         * Offset
         * @default 0
         */
        offset?: number;
        /**
         * Limit
         * @default 50
         */
        limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<ExecutionListOut, HTTPValidationError>({
        path: `/api/executions`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description List dead-letter queue entries (failed executions). Pass `campaign_id` to scope to a single campaign's failures. Empty-string query values (e.g. `?campaign_id=` or `?status=`) are coerced to `None` so they do not silently filter to zero rows.
     *
     * @tags executions
     * @name ListDlqApiExecutionsDlqGet
     * @summary List Dlq
     * @request GET:/api/executions/dlq
     * @secure
     */
    listDlqApiExecutionsDlqGet: (
      query?: {
        /** Status */
        status?: string | null;
        /** Campaign Id */
        campaign_id?: string | null;
        /**
         * Offset
         * @default 0
         */
        offset?: number;
        /**
         * Limit
         * @default 50
         */
        limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<DLQEntryOut[], HTTPValidationError>({
        path: `/api/executions/dlq`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Return DLQ counters for operator alerting.
     *
     * @tags executions
     * @name DlqSummaryApiExecutionsDlqSummaryGet
     * @summary Dlq Summary
     * @request GET:/api/executions/dlq/summary
     * @secure
     */
    dlqSummaryApiExecutionsDlqSummaryGet: (
      query?: {
        /** Campaign Id */
        campaign_id?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<DLQSummaryOut, HTTPValidationError>({
        path: `/api/executions/dlq/summary`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Return DLQ detail for a failed execution (DF-T-04-012).
     *
     * @tags executions
     * @name GetDlqByExecutionApiExecutionsDlqExecutionsExecutionIdGet
     * @summary Get Dlq By Execution
     * @request GET:/api/executions/dlq/executions/{execution_id}
     * @secure
     */
    getDlqByExecutionApiExecutionsDlqExecutionsExecutionIdGet: (
      executionId: string,
      params: RequestParams = {},
    ) =>
      this.request<DLQEntryOut, HTTPValidationError>({
        path: `/api/executions/dlq/executions/${executionId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Bulk replay DLQ entries (max 50 per request).
     *
     * @tags executions
     * @name BulkRetryDlqApiExecutionsDlqBulkRetryPost
     * @summary Bulk Retry Dlq
     * @request POST:/api/executions/dlq/bulk-retry
     * @secure
     */
    bulkRetryDlqApiExecutionsDlqBulkRetryPost: (
      data: DLQBulkRetryBody,
      params: RequestParams = {},
    ) =>
      this.request<DLQBulkRetryOut, HTTPValidationError>({
        path: `/api/executions/dlq/bulk-retry`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Replay a DLQ entry (Epic 04 checkpoint replay or legacy re-enqueue).
     *
     * @tags executions
     * @name RetryDlqApiExecutionsDlqDlqIdRetryPost
     * @summary Retry Dlq
     * @request POST:/api/executions/dlq/{dlq_id}/retry
     * @secure
     */
    retryDlqApiExecutionsDlqDlqIdRetryPost: (
      dlqId: string,
      data: DLQRetryBody | null,
      params: RequestParams = {},
    ) =>
      this.request<DLQEntryOut, HTTPValidationError>({
        path: `/api/executions/dlq/${dlqId}/retry`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Close a DLQ entry without replaying (DF-T-04-012).
     *
     * @tags executions
     * @name CloseDlqApiExecutionsDlqDlqIdClosePost
     * @summary Close Dlq
     * @request POST:/api/executions/dlq/{dlq_id}/close
     * @secure
     */
    closeDlqApiExecutionsDlqDlqIdClosePost: (
      dlqId: string,
      data: DLQCloseBody,
      params: RequestParams = {},
    ) =>
      this.request<DLQEntryOut, HTTPValidationError>({
        path: `/api/executions/dlq/${dlqId}/close`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Dismiss a DLQ entry without retrying.
     *
     * @tags executions
     * @name DismissDlqApiExecutionsDlqDlqIdDelete
     * @summary Dismiss Dlq
     * @request DELETE:/api/executions/dlq/{dlq_id}
     * @secure
     */
    dismissDlqApiExecutionsDlqDlqIdDelete: (
      dlqId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/executions/dlq/${dlqId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name GetExecutionEndpointApiExecutionsExecutionIdGet
     * @summary Get Execution Endpoint
     * @request GET:/api/executions/{execution_id}
     * @secure
     */
    getExecutionEndpointApiExecutionsExecutionIdGet: (
      executionId: string,
      params: RequestParams = {},
    ) =>
      this.request<ExecutionOut, HTTPValidationError>({
        path: `/api/executions/${executionId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name PatchExecutionEndpointApiExecutionsExecutionIdPatch
     * @summary Patch Execution Endpoint
     * @request PATCH:/api/executions/{execution_id}
     * @secure
     */
    patchExecutionEndpointApiExecutionsExecutionIdPatch: (
      executionId: string,
      data: ExecutionPatch,
      params: RequestParams = {},
    ) =>
      this.request<ExecutionOut, HTTPValidationError>({
        path: `/api/executions/${executionId}`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name DeleteExecutionEndpointApiExecutionsExecutionIdDelete
     * @summary Delete Execution Endpoint
     * @request DELETE:/api/executions/{execution_id}
     * @secure
     */
    deleteExecutionEndpointApiExecutionsExecutionIdDelete: (
      executionId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/executions/${executionId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * @description Catch-up endpoint — events after ``since`` event_id (exclusive), ordered.
     *
     * @tags executions
     * @name ListExecutionEventsApiExecutionsExecutionIdEventsGet
     * @summary List Execution Events
     * @request GET:/api/executions/{execution_id}/events
     * @secure
     */
    listExecutionEventsApiExecutionsExecutionIdEventsGet: (
      executionId: string,
      query?: {
        /** Since */
        since?: string | null;
        /**
         * Limit
         * @default 100
         */
        limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<ExecutionEventListOut, HTTPValidationError>({
        path: `/api/executions/${executionId}/events`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description SSE live stream with ``Last-Event-ID`` resume support (DF-T-04-013).
     *
     * @tags executions
     * @name StreamExecutionEventsApiExecutionsExecutionIdEventsStreamGet
     * @summary Stream Execution Events
     * @request GET:/api/executions/{execution_id}/events/stream
     * @secure
     */
    streamExecutionEventsApiExecutionsExecutionIdEventsStreamGet: (
      executionId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/executions/${executionId}/events/stream`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Phase 5 — crawl stats for an execution: content count, LLM fallbacks, dedup skipped (from Execution.meta), latest checkpoint, run time per device.
     *
     * @tags executions
     * @name GetExecutionStatsEndpointApiExecutionsExecutionIdStatsGet
     * @summary Get Execution Stats Endpoint
     * @request GET:/api/executions/{execution_id}/stats
     * @secure
     */
    getExecutionStatsEndpointApiExecutionsExecutionIdStatsGet: (
      executionId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/executions/${executionId}/stats`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name StartEndpointApiExecutionsExecutionIdStartPost
     * @summary Start Endpoint
     * @request POST:/api/executions/{execution_id}/start
     * @secure
     */
    startEndpointApiExecutionsExecutionIdStartPost: (
      executionId: string,
      params: RequestParams = {},
    ) =>
      this.request<ExecutionOut, HTTPValidationError>({
        path: `/api/executions/${executionId}/start`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name FinishEndpointApiExecutionsExecutionIdFinishPost
     * @summary Finish Endpoint
     * @request POST:/api/executions/{execution_id}/finish
     * @secure
     */
    finishEndpointApiExecutionsExecutionIdFinishPost: (
      executionId: string,
      data: FinishBody,
      params: RequestParams = {},
    ) =>
      this.request<ExecutionOut, HTTPValidationError>({
        path: `/api/executions/${executionId}/finish`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name PauseExecutionEndpointApiExecutionsExecutionIdPausePost
     * @summary Pause Execution Endpoint
     * @request POST:/api/executions/{execution_id}/pause
     * @secure
     */
    pauseExecutionEndpointApiExecutionsExecutionIdPausePost: (
      executionId: string,
      params: RequestParams = {},
    ) =>
      this.request<ExecutionControlOut, HTTPValidationError>({
        path: `/api/executions/${executionId}/pause`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name ResumeExecutionEndpointApiExecutionsExecutionIdResumePost
     * @summary Resume Execution Endpoint
     * @request POST:/api/executions/{execution_id}/resume
     * @secure
     */
    resumeExecutionEndpointApiExecutionsExecutionIdResumePost: (
      executionId: string,
      params: RequestParams = {},
    ) =>
      this.request<ExecutionControlOut, HTTPValidationError>({
        path: `/api/executions/${executionId}/resume`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name CancelEndpointApiExecutionsExecutionIdCancelPost
     * @summary Cancel Endpoint
     * @request POST:/api/executions/{execution_id}/cancel
     * @secure
     */
    cancelEndpointApiExecutionsExecutionIdCancelPost: (
      executionId: string,
      data: ExecutionCancelBody | null,
      params: RequestParams = {},
    ) =>
      this.request<ExecutionControlOut, HTTPValidationError>({
        path: `/api/executions/${executionId}/cancel`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name ListDevicesEndpointApiExecutionsExecutionIdDevicesGet
     * @summary List Devices Endpoint
     * @request GET:/api/executions/{execution_id}/devices
     * @secure
     */
    listDevicesEndpointApiExecutionsExecutionIdDevicesGet: (
      executionId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/executions/${executionId}/devices`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name AddDeviceEndpointApiExecutionsExecutionIdDevicesPost
     * @summary Add Device Endpoint
     * @request POST:/api/executions/{execution_id}/devices
     * @secure
     */
    addDeviceEndpointApiExecutionsExecutionIdDevicesPost: (
      executionId: string,
      data: AddDeviceBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/executions/${executionId}/devices`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name RemoveDeviceEndpointApiExecutionsExecutionIdDevicesDeviceIdDelete
     * @summary Remove Device Endpoint
     * @request DELETE:/api/executions/{execution_id}/devices/{device_id}
     * @secure
     */
    removeDeviceEndpointApiExecutionsExecutionIdDevicesDeviceIdDelete: (
      executionId: string,
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/executions/${executionId}/devices/${deviceId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name ListResultsEndpointApiExecutionsExecutionIdResultsGet
     * @summary List Results Endpoint
     * @request GET:/api/executions/{execution_id}/results
     * @secure
     */
    listResultsEndpointApiExecutionsExecutionIdResultsGet: (
      executionId: string,
      params: RequestParams = {},
    ) =>
      this.request<ExecutionResultOut[], HTTPValidationError>({
        path: `/api/executions/${executionId}/results`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name GetResultEndpointApiExecutionsExecutionIdResultsDeviceIdGet
     * @summary Get Result Endpoint
     * @request GET:/api/executions/{execution_id}/results/{device_id}
     * @secure
     */
    getResultEndpointApiExecutionsExecutionIdResultsDeviceIdGet: (
      executionId: string,
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<ExecutionResultOut, HTTPValidationError>({
        path: `/api/executions/${executionId}/results/${deviceId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name UpsertResultEndpointApiExecutionsExecutionIdResultsDeviceIdPut
     * @summary Upsert Result Endpoint
     * @request PUT:/api/executions/{execution_id}/results/{device_id}
     * @secure
     */
    upsertResultEndpointApiExecutionsExecutionIdResultsDeviceIdPut: (
      executionId: string,
      deviceId: string,
      data: UpsertResultBody,
      params: RequestParams = {},
    ) =>
      this.request<ExecutionResultOut, HTTPValidationError>({
        path: `/api/executions/${executionId}/results/${deviceId}`,
        method: "PUT",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Normalized per-step rows including artifacts_json (DF-T-04-010).
     *
     * @tags executions
     * @name ListExecutionStepsEndpointApiExecutionsExecutionIdStepsGet
     * @summary List Execution Steps Endpoint
     * @request GET:/api/executions/{execution_id}/steps
     * @secure
     */
    listExecutionStepsEndpointApiExecutionsExecutionIdStepsGet: (
      executionId: string,
      params: RequestParams = {},
    ) =>
      this.request<ExecutionStepOut[], HTTPValidationError>({
        path: `/api/executions/${executionId}/steps`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name SummaryEndpointApiExecutionsExecutionIdSummaryGet
     * @summary Summary Endpoint
     * @request GET:/api/executions/{execution_id}/summary
     * @secure
     */
    summaryEndpointApiExecutionsExecutionIdSummaryGet: (
      executionId: string,
      params: RequestParams = {},
    ) =>
      this.request<SummaryOut, HTTPValidationError>({
        path: `/api/executions/${executionId}/summary`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description List execution artifacts from result step screenshots + saved content screenshots.
     *
     * @tags executions
     * @name ListExecutionArtifactsApiExecutionsExecutionIdArtifactsGet
     * @summary List Execution Artifacts
     * @request GET:/api/executions/{execution_id}/artifacts
     * @secure
     */
    listExecutionArtifactsApiExecutionsExecutionIdArtifactsGet: (
      executionId: string,
      query?: {
        /**
         * Content Offset
         * @default 0
         */
        content_offset?: number;
        /**
         * Content Limit
         * @default 200
         */
        content_limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<ExecutionArtifactOut[], HTTPValidationError>({
        path: `/api/executions/${executionId}/artifacts`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Pin execution so artifacts skip retention cleanup (DF-T-06-011).
     *
     * @tags executions
     * @name PinExecutionApiExecutionsExecutionIdPinPost
     * @summary Pin Execution
     * @request POST:/api/executions/{execution_id}/pin
     * @secure
     */
    pinExecutionApiExecutionsExecutionIdPinPost: (
      executionId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/executions/${executionId}/pin`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags executions
     * @name UnpinExecutionApiExecutionsExecutionIdPinDelete
     * @summary Unpin Execution
     * @request DELETE:/api/executions/{execution_id}/pin
     * @secure
     */
    unpinExecutionApiExecutionsExecutionIdPinDelete: (
      executionId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/executions/${executionId}/pin`,
        method: "DELETE",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags relay-agents
     * @name ListRelayAgentsApiRelayAgentsGet
     * @summary List Relay Agents
     * @request GET:/api/relay-agents
     * @secure
     */
    listRelayAgentsApiRelayAgentsGet: (params: RequestParams = {}) =>
      this.request<RelayAgentOut[], any>({
        path: `/api/relay-agents`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags relay-agents
     * @name ListRelayAgentTokensApiRelayAgentsTokensGet
     * @summary List Relay Agent Tokens
     * @request GET:/api/relay-agents/tokens
     * @secure
     */
    listRelayAgentTokensApiRelayAgentsTokensGet: (params: RequestParams = {}) =>
      this.request<RelayAgentTokenOut[], any>({
        path: `/api/relay-agents/tokens`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags relay-agents
     * @name CreateRelayAgentTokenApiRelayAgentsTokensPost
     * @summary Create Relay Agent Token
     * @request POST:/api/relay-agents/tokens
     * @secure
     */
    createRelayAgentTokenApiRelayAgentsTokensPost: (
      data: RelayAgentTokenCreate,
      params: RequestParams = {},
    ) =>
      this.request<RelayAgentTokenCreated, HTTPValidationError>({
        path: `/api/relay-agents/tokens`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags relay-agents
     * @name RevokeRelayAgentTokenApiRelayAgentsTokensTokenIdDelete
     * @summary Revoke Relay Agent Token
     * @request DELETE:/api/relay-agents/tokens/{token_id}
     * @secure
     */
    revokeRelayAgentTokenApiRelayAgentsTokensTokenIdDelete: (
      tokenId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/relay-agents/tokens/${tokenId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags relay-agents
     * @name CreateRelayProvisionJobApiRelayAgentsRelayIdJobsProvisionPost
     * @summary Create Relay Provision Job
     * @request POST:/api/relay-agents/{relay_id}/jobs/provision
     * @secure
     */
    createRelayProvisionJobApiRelayAgentsRelayIdJobsProvisionPost: (
      relayId: string,
      data: RelayBatchJobCreate,
      params: RequestParams = {},
    ) =>
      this.request<RelayBatchJobOut, HTTPValidationError>({
        path: `/api/relay-agents/${relayId}/jobs/provision`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags relay-agents
     * @name CreateRelayClaimConnectJobApiRelayAgentsRelayIdJobsClaimConnectPost
     * @summary Create Relay Claim Connect Job
     * @request POST:/api/relay-agents/{relay_id}/jobs/claim-connect
     * @secure
     */
    createRelayClaimConnectJobApiRelayAgentsRelayIdJobsClaimConnectPost: (
      relayId: string,
      data: RelayBatchJobCreate,
      params: RequestParams = {},
    ) =>
      this.request<RelayBatchJobOut, HTTPValidationError>({
        path: `/api/relay-agents/${relayId}/jobs/claim-connect`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags relay-agents
     * @name GetRelayJobApiRelayAgentsRelayIdJobsJobIdGet
     * @summary Get Relay Job
     * @request GET:/api/relay-agents/{relay_id}/jobs/{job_id}
     * @secure
     */
    getRelayJobApiRelayAgentsRelayIdJobsJobIdGet: (
      relayId: string,
      jobId: string,
      params: RequestParams = {},
    ) =>
      this.request<RelayBatchJobOut, HTTPValidationError>({
        path: `/api/relay-agents/${relayId}/jobs/${jobId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags relay-agents
     * @name ListRelayJobItemsApiRelayAgentsRelayIdJobsJobIdItemsGet
     * @summary List Relay Job Items
     * @request GET:/api/relay-agents/{relay_id}/jobs/{job_id}/items
     * @secure
     */
    listRelayJobItemsApiRelayAgentsRelayIdJobsJobIdItemsGet: (
      relayId: string,
      jobId: string,
      query?: {
        /** Status */
        status?: string | null;
        /**
         * Limit
         * @min 1
         * @max 1000
         * @default 500
         */
        limit?: number;
        /**
         * Offset
         * @min 0
         * @default 0
         */
        offset?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<RelayBatchJobItemOut[], HTTPValidationError>({
        path: `/api/relay-agents/${relayId}/jobs/${jobId}/items`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags relay-agents
     * @name GetRelayAgentApiRelayAgentsRelayIdGet
     * @summary Get Relay Agent
     * @request GET:/api/relay-agents/{relay_id}
     * @secure
     */
    getRelayAgentApiRelayAgentsRelayIdGet: (
      relayId: string,
      params: RequestParams = {},
    ) =>
      this.request<RelayAgentOut, HTTPValidationError>({
        path: `/api/relay-agents/${relayId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Register/claim a device from an ADB serial currently reported by agent-boot.
     *
     * @tags relay-agents
     * @name RegisterRelayDeviceApiRelayAgentsRelayIdDevicesSerialRegisterPost
     * @summary Register Relay Device
     * @request POST:/api/relay-agents/{relay_id}/devices/{serial}/register
     * @secure
     */
    registerRelayDeviceApiRelayAgentsRelayIdDevicesSerialRegisterPost: (
      relayId: string,
      serial: string,
      data: RegisterRelayDeviceBody,
      params: RequestParams = {},
    ) =>
      this.request<DeviceOut, HTTPValidationError>({
        path: `/api/relay-agents/${relayId}/devices/${serial}/register`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Send the device-agent URL to STFService via agent-boot/ADB; no QR scan required.
     *
     * @tags relay-agents
     * @name PushConnectUrlToDeviceApiRelayAgentsRelayIdDevicesSerialPushConnectUrlPost
     * @summary Push Connect Url To Device
     * @request POST:/api/relay-agents/{relay_id}/devices/{serial}/push-connect-url
     * @secure
     */
    pushConnectUrlToDeviceApiRelayAgentsRelayIdDevicesSerialPushConnectUrlPost:
      (
        relayId: string,
        serial: string,
        query?: {
          /**
           * Device Id
           * Logical device id when DB serial is pending-* but ADB path serial is physical
           */
          device_id?: string | null;
        },
        params: RequestParams = {},
      ) =>
        this.request<RelayCommandOut, HTTPValidationError>({
          path: `/api/relay-agents/${relayId}/devices/${serial}/push-connect-url`,
          method: "POST",
          query: query,
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags relay-agents
     * @name BootstrapAllApiRelayAgentsRelayIdBootstrapAllPost
     * @summary Bootstrap All
     * @request POST:/api/relay-agents/{relay_id}/bootstrap-all
     * @secure
     */
    bootstrapAllApiRelayAgentsRelayIdBootstrapAllPost: (
      relayId: string,
      params: RequestParams = {},
    ) =>
      this.request<BootstrapAllResult, HTTPValidationError>({
        path: `/api/relay-agents/${relayId}/bootstrap-all`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Create one pairing token per serial for a relay agent. Auth: X-Relay-Api-Key header (same key as gRPC). Returns {serial: ws_url} so agent can inject unique URLs per device.
     *
     * @tags relay-agents
     * @name RelayPairBulkApiRelayAgentsRelayIdPairBulkPost
     * @summary Relay Pair Bulk
     * @request POST:/api/relay-agents/{relay_id}/pair-bulk
     */
    relayPairBulkApiRelayAgentsRelayIdPairBulkPost: (
      relayId: string,
      data: ApiRoutesRelayAgentsPairBulkBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/relay-agents/${relayId}/pair-bulk`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name RegistryPairDeviceApiDevicesRegistryPairPost
     * @summary Registry Pair Device
     * @request POST:/api/devices/registry/pair
     * @secure
     */
    registryPairDeviceApiDevicesRegistryPairPost: (
      data: PairRegistryBody,
      params: RequestParams = {},
    ) =>
      this.request<PairRegistryOut, HTTPValidationError>({
        path: `/api/devices/registry/pair`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name RegistryUnpairDeviceApiDevicesDeviceIdUnpairPost
     * @summary Registry Unpair Device
     * @request POST:/api/devices/{device_id}/unpair
     * @secure
     */
    registryUnpairDeviceApiDevicesDeviceIdUnpairPost: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<UnpairDeviceOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}/unpair`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name ClaimDeviceApiDevicesDeviceIdClaimPost
     * @summary Claim Device
     * @request POST:/api/devices/{device_id}/claim
     * @secure
     */
    claimDeviceApiDevicesDeviceIdClaimPost: (
      deviceId: string,
      data: DeviceClaimBody,
      params: RequestParams = {},
    ) =>
      this.request<DeviceClaimOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}/claim`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name ReleaseDeviceApiDevicesDeviceIdReleasePost
     * @summary Release Device
     * @request POST:/api/devices/{device_id}/release
     * @secure
     */
    releaseDeviceApiDevicesDeviceIdReleasePost: (
      deviceId: string,
      data: DeviceReleaseBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${deviceId}/release`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name GetDeviceActiveSessionApiDevicesDeviceIdSessionGet
     * @summary Get Device Active Session
     * @request GET:/api/devices/{device_id}/session
     * @secure
     */
    getDeviceActiveSessionApiDevicesDeviceIdSessionGet: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<DeviceReserveSessionOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}/session`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name HeartbeatSessionApiSessionsSessionIdHeartbeatPost
     * @summary Heartbeat Session
     * @request POST:/api/sessions/{session_id}/heartbeat
     * @secure
     */
    heartbeatSessionApiSessionsSessionIdHeartbeatPost: (
      sessionId: string,
      params: RequestParams = {},
    ) =>
      this.request<DeviceReserveSessionOut, HTTPValidationError>({
        path: `/api/sessions/${sessionId}/heartbeat`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags notifications
     * @name ListChannelsApiNotificationChannelsGet
     * @summary List Channels
     * @request GET:/api/notification-channels
     * @secure
     */
    listChannelsApiNotificationChannelsGet: (params: RequestParams = {}) =>
      this.request<NotificationChannelOut[], any>({
        path: `/api/notification-channels`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags notifications
     * @name CreateChannelApiNotificationChannelsPost
     * @summary Create Channel
     * @request POST:/api/notification-channels
     * @secure
     */
    createChannelApiNotificationChannelsPost: (
      data: NotificationChannelCreate,
      params: RequestParams = {},
    ) =>
      this.request<NotificationChannelOut, HTTPValidationError>({
        path: `/api/notification-channels`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags notifications
     * @name UpdateChannelApiNotificationChannelsChannelIdPatch
     * @summary Update Channel
     * @request PATCH:/api/notification-channels/{channel_id}
     * @secure
     */
    updateChannelApiNotificationChannelsChannelIdPatch: (
      channelId: string,
      data: NotificationChannelPatch,
      params: RequestParams = {},
    ) =>
      this.request<NotificationChannelOut, HTTPValidationError>({
        path: `/api/notification-channels/${channelId}`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags notifications
     * @name DeleteChannelApiNotificationChannelsChannelIdDelete
     * @summary Delete Channel
     * @request DELETE:/api/notification-channels/{channel_id}
     * @secure
     */
    deleteChannelApiNotificationChannelsChannelIdDelete: (
      channelId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/notification-channels/${channelId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags notifications
     * @name TestChannelApiNotificationChannelsChannelIdTestPost
     * @summary Test Channel
     * @request POST:/api/notification-channels/{channel_id}/test
     * @secure
     */
    testChannelApiNotificationChannelsChannelIdTestPost: (
      channelId: string,
      params: RequestParams = {},
    ) =>
      this.request<TestNotificationOut, HTTPValidationError>({
        path: `/api/notification-channels/${channelId}/test`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags notifications
     * @name ListNotificationsApiNotificationsGet
     * @summary List Notifications
     * @request GET:/api/notifications
     * @secure
     */
    listNotificationsApiNotificationsGet: (
      query?: {
        /** Unread */
        unread?: boolean | null;
        /**
         * Offset
         * @default 0
         */
        offset?: number;
        /**
         * Limit
         * @default 50
         */
        limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<NotificationListOut, HTTPValidationError>({
        path: `/api/notifications`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags notifications
     * @name UnreadCountApiNotificationsUnreadCountGet
     * @summary Unread Count
     * @request GET:/api/notifications/unread-count
     * @secure
     */
    unreadCountApiNotificationsUnreadCountGet: (params: RequestParams = {}) =>
      this.request<UnreadCountOut, any>({
        path: `/api/notifications/unread-count`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags notifications
     * @name MarkReadApiNotificationsNotificationIdReadPatch
     * @summary Mark Read
     * @request PATCH:/api/notifications/{notification_id}/read
     * @secure
     */
    markReadApiNotificationsNotificationIdReadPatch: (
      notificationId: string,
      params: RequestParams = {},
    ) =>
      this.request<NotificationOut, HTTPValidationError>({
        path: `/api/notifications/${notificationId}/read`,
        method: "PATCH",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags notifications
     * @name MarkAllReadApiNotificationsReadAllPost
     * @summary Mark All Read
     * @request POST:/api/notifications/read-all
     * @secure
     */
    markAllReadApiNotificationsReadAllPost: (params: RequestParams = {}) =>
      this.request<UnreadCountOut, any>({
        path: `/api/notifications/read-all`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags analytics
     * @name ListActivityApiAnalyticsActivityGet
     * @summary List Activity
     * @request GET:/api/analytics/activity
     * @secure
     */
    listActivityApiAnalyticsActivityGet: (
      query?: {
        /** Action */
        action?: string | null;
        /** Device Serial */
        device_serial?: string | null;
        /**
         * Offset
         * @default 0
         */
        offset?: number;
        /**
         * Limit
         * @default 50
         */
        limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<ActivityLogListOut, HTTPValidationError>({
        path: `/api/analytics/activity`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags analytics
     * @name TimeseriesApiAnalyticsTimeseriesGet
     * @summary Timeseries
     * @request GET:/api/analytics/timeseries
     * @secure
     */
    timeseriesApiAnalyticsTimeseriesGet: (
      query: {
        /**
         * Dimension
         * @pattern ^(device|campaign|platform|account|event_type)$
         */
        dimension: string;
        /** Resource Id */
        resource_id?: string | null;
        /** Event Type */
        event_type?: string | null;
        /** From */
        from: string;
        /** To */
        to: string;
        /**
         * Granularity
         * @default "day"
         * @pattern ^(day|week)$
         */
        granularity?: string;
      },
      params: RequestParams = {},
    ) =>
      this.request<AnalyticsTimeseriesOut, HTTPValidationError>({
        path: `/api/analytics/timeseries`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags analytics
     * @name SummaryApiAnalyticsSummaryGet
     * @summary Summary
     * @request GET:/api/analytics/summary
     * @secure
     */
    summaryApiAnalyticsSummaryGet: (
      query?: {
        /**
         * Window Days
         * @default 7
         */
        window_days?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<AnalyticsSummaryOut, HTTPValidationError>({
        path: `/api/analytics/summary`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags analytics
     * @name AdhocQueryApiAnalyticsAdhocQueryPost
     * @summary Adhoc Query
     * @request POST:/api/analytics/adhoc-query
     * @secure
     */
    adhocQueryApiAnalyticsAdhocQueryPost: (
      data: Record<string, any>,
      params: RequestParams = {},
    ) =>
      this.request<AnalyticsAdhocOut, HTTPValidationError>({
        path: `/api/analytics/adhoc-query`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags analytics
     * @name AuditExportApiAnalyticsAuditExportGet
     * @summary Audit Export
     * @request GET:/api/analytics/audit/export
     * @secure
     */
    auditExportApiAnalyticsAuditExportGet: (
      query: {
        /** From */
        from: string;
        /** To */
        to: string;
        /** Action */
        action?: string | null;
        /** Actor */
        actor?: string | null;
        /** Resource Type */
        resource_type?: string | null;
        /** Resource Id */
        resource_id?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<string, HTTPValidationError>({
        path: `/api/analytics/audit/export`,
        method: "GET",
        query: query,
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags preview
     * @name ListPreviewsApiPreviewGet
     * @summary List Previews
     * @request GET:/api/preview
     * @secure
     */
    listPreviewsApiPreviewGet: (
      query?: {
        /** Org */
        org?: string | null;
        /** User */
        user?: string | null;
        /** Since */
        since?: string | null;
        /**
         * Limit
         * @min 1
         * @max 200
         * @default 50
         */
        limit?: number;
        /**
         * Offset
         * @min 0
         * @default 0
         */
        offset?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<PreviewListResponse, HTTPValidationError>({
        path: `/api/preview`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags social-ext
     * @name ListSocialPlatformsApiSocialExtPlatformsGet
     * @summary List Social Platforms
     * @request GET:/api/social-ext/platforms
     * @secure
     */
    listSocialPlatformsApiSocialExtPlatformsGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/social-ext/platforms`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags social-ext
     * @name GetSocialPlatformStepsApiSocialExtPlatformsPlatformStepsGet
     * @summary Get Social Platform Steps
     * @request GET:/api/social-ext/platforms/{platform}/steps
     * @secure
     */
    getSocialPlatformStepsApiSocialExtPlatformsPlatformStepsGet: (
      platform: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/social-ext/platforms/${platform}/steps`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags social-ext
     * @name LoadSocialPlatformApiSocialExtPlatformsPlatformLoadPost
     * @summary Load Social Platform
     * @request POST:/api/social-ext/platforms/{platform}/load
     * @secure
     */
    loadSocialPlatformApiSocialExtPlatformsPlatformLoadPost: (
      platform: string,
      data: PlatformLifecycleBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/social-ext/platforms/${platform}/load`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags social-ext
     * @name UnloadSocialPlatformApiSocialExtPlatformsPlatformUnloadPost
     * @summary Unload Social Platform
     * @request POST:/api/social-ext/platforms/{platform}/unload
     * @secure
     */
    unloadSocialPlatformApiSocialExtPlatformsPlatformUnloadPost: (
      platform: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/social-ext/platforms/${platform}/unload`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags social-ext
     * @name MigrateSocialPlatformApiSocialExtPlatformsPlatformMigratePost
     * @summary Migrate Social Platform
     * @request POST:/api/social-ext/platforms/{platform}/migrate
     * @secure
     */
    migrateSocialPlatformApiSocialExtPlatformsPlatformMigratePost: (
      platform: string,
      data: PlatformLifecycleBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/social-ext/platforms/${platform}/migrate`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags social-ext
     * @name GetSocialPlatformVersionHistoryApiSocialExtPlatformsPlatformVersionHistoryGet
     * @summary Get Social Platform Version History
     * @request GET:/api/social-ext/platforms/{platform}/version-history
     * @secure
     */
    getSocialPlatformVersionHistoryApiSocialExtPlatformsPlatformVersionHistoryGet:
      (platform: string, params: RequestParams = {}) =>
        this.request<any, HTTPValidationError>({
          path: `/api/social-ext/platforms/${platform}/version-history`,
          method: "GET",
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags social-ext
     * @name ListOrgSocialPlatformFlagsApiSocialExtOrgsOrgIdPlatformsGet
     * @summary List Org Social Platform Flags
     * @request GET:/api/social-ext/orgs/{org_id}/platforms
     * @secure
     */
    listOrgSocialPlatformFlagsApiSocialExtOrgsOrgIdPlatformsGet: (
      orgId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/social-ext/orgs/${orgId}/platforms`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags social-ext
     * @name EnableOrgSocialPlatformApiSocialExtOrgsOrgIdPlatformsPlatformEnablePost
     * @summary Enable Org Social Platform
     * @request POST:/api/social-ext/orgs/{org_id}/platforms/{platform}/enable
     * @secure
     */
    enableOrgSocialPlatformApiSocialExtOrgsOrgIdPlatformsPlatformEnablePost: (
      orgId: string,
      platform: string,
      data: PlatformFlagBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/social-ext/orgs/${orgId}/platforms/${platform}/enable`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags social-ext
     * @name DisableOrgSocialPlatformApiSocialExtOrgsOrgIdPlatformsPlatformDisablePost
     * @summary Disable Org Social Platform
     * @request POST:/api/social-ext/orgs/{org_id}/platforms/{platform}/disable
     * @secure
     */
    disableOrgSocialPlatformApiSocialExtOrgsOrgIdPlatformsPlatformDisablePost: (
      orgId: string,
      platform: string,
      data: PlatformFlagBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/social-ext/orgs/${orgId}/platforms/${platform}/disable`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags mcp
     * @name ListMcpToolsApiMcpToolsGet
     * @summary List Mcp Tools
     * @request GET:/api/mcp/tools
     * @secure
     */
    listMcpToolsApiMcpToolsGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/mcp/tools`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags mcp
     * @name ListMcpAuditLogApiMcpAuditLogGet
     * @summary List Mcp Audit Log
     * @request GET:/api/mcp/audit-log
     * @secure
     */
    listMcpAuditLogApiMcpAuditLogGet: (
      query?: {
        /** Tool Name */
        tool_name?: string | null;
        /** Session Id */
        session_id?: string | null;
        /** Agent Id */
        agent_id?: string | null;
        /**
         * Limit
         * @min 1
         * @max 200
         * @default 50
         */
        limit?: number;
        /**
         * Offset
         * @min 0
         * @default 0
         */
        offset?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/mcp/audit-log`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags mcp
     * @name ListMcpTokensApiMcpTokensGet
     * @summary List Mcp Tokens
     * @request GET:/api/mcp/tokens
     * @secure
     */
    listMcpTokensApiMcpTokensGet: (
      query?: {
        /**
         * Include Revoked
         * @default false
         */
        include_revoked?: boolean;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/mcp/tokens`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags mcp
     * @name CreateMcpTokenApiMcpTokensPost
     * @summary Create Mcp Token
     * @request POST:/api/mcp/tokens
     * @secure
     */
    createMcpTokenApiMcpTokensPost: (
      data: McpTokenCreate,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/mcp/tokens`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags mcp
     * @name RevokeMcpTokenApiMcpTokensTokenIdRevokePost
     * @summary Revoke Mcp Token
     * @request POST:/api/mcp/tokens/{token_id}/revoke
     * @secure
     */
    revokeMcpTokenApiMcpTokensTokenIdRevokePost: (
      tokenId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/mcp/tokens/${tokenId}/revoke`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiConnectInfoApiConnectInfoGet
     * @summary Api Connect Info
     * @request GET:/api/connect/info
     * @secure
     */
    apiConnectInfoApiConnectInfoGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/connect/info`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiScenarioSchemaApiScenarioSchemaGet
     * @summary Api Scenario Schema
     * @request GET:/api/scenario/schema
     * @secure
     */
    apiScenarioSchemaApiScenarioSchemaGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/scenario/schema`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiConnectRegisterApiConnectRegisterPost
     * @summary Api Connect Register
     * @request POST:/api/connect/register
     * @secure
     */
    apiConnectRegisterApiConnectRegisterPost: (
      data: AdbRegisterRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/connect/register`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiScrcpyAttachApiDevicesSerialScrcpyAttachPost
     * @summary Api Scrcpy Attach
     * @request POST:/api/devices/{serial}/scrcpy/attach
     * @secure
     */
    apiScrcpyAttachApiDevicesSerialScrcpyAttachPost: (
      serial: string,
      data: ScrcpyAttachRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/scrcpy/attach`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiScrcpyDetachApiDevicesSerialScrcpyDetachPost
     * @summary Api Scrcpy Detach
     * @request POST:/api/devices/{serial}/scrcpy/detach
     * @secure
     */
    apiScrcpyDetachApiDevicesSerialScrcpyDetachPost: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/scrcpy/detach`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiSessionsStartApiSessionsStartPost
     * @summary Api Sessions Start
     * @request POST:/api/sessions/start
     * @secure
     */
    apiSessionsStartApiSessionsStartPost: (
      data: StartSessionRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/sessions/start`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiSessionsEndApiSessionsEndPost
     * @summary Api Sessions End
     * @request POST:/api/sessions/end
     * @secure
     */
    apiSessionsEndApiSessionsEndPost: (
      data: EndSessionRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/sessions/end`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiSessionsGetApiSessionsSessionIdGet
     * @summary Api Sessions Get
     * @request GET:/api/sessions/{session_id}
     * @secure
     */
    apiSessionsGetApiSessionsSessionIdGet: (
      sessionId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/sessions/${sessionId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiDevicesReserveApiDevicesSerialReservePost
     * @summary Api Devices Reserve
     * @request POST:/api/devices/{serial}/reserve
     * @secure
     */
    apiDevicesReserveApiDevicesSerialReservePost: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/reserve`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiDevicesReleaseApiDevicesSerialReleasePost
     * @summary Api Devices Release
     * @request POST:/api/devices/{serial}/release
     * @secure
     */
    apiDevicesReleaseApiDevicesSerialReleasePost: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/release`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiTapApiTapSerialPost
     * @summary Api Tap
     * @request POST:/api/tap/{serial}
     * @secure
     */
    apiTapApiTapSerialPost: (
      serial: string,
      data: TapRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/tap/${serial}`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiSwipeApiSwipeSerialPost
     * @summary Api Swipe
     * @request POST:/api/swipe/{serial}
     * @secure
     */
    apiSwipeApiSwipeSerialPost: (
      serial: string,
      data: SwipeRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/swipe/${serial}`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiKeyApiKeySerialPost
     * @summary Api Key
     * @request POST:/api/key/{serial}
     * @secure
     */
    apiKeyApiKeySerialPost: (
      serial: string,
      data: KeyRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/key/${serial}`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiLaunchAppApiLaunchAppSerialPost
     * @summary Api Launch App
     * @request POST:/api/launch_app/{serial}
     * @secure
     */
    apiLaunchAppApiLaunchAppSerialPost: (
      serial: string,
      data: LaunchAppRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/launch_app/${serial}`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiOpenUrlApiOpenUrlSerialPost
     * @summary Api Open Url
     * @request POST:/api/open_url/{serial}
     * @secure
     */
    apiOpenUrlApiOpenUrlSerialPost: (
      serial: string,
      data: OpenUrlRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/open_url/${serial}`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiInputTextApiDevicesSerialInputTextPost
     * @summary Api Input Text
     * @request POST:/api/devices/{serial}/input_text
     * @secure
     */
    apiInputTextApiDevicesSerialInputTextPost: (
      serial: string,
      data: InputTextRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/input_text`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiLongTapApiDevicesSerialLongTapPost
     * @summary Api Long Tap
     * @request POST:/api/devices/{serial}/long_tap
     * @secure
     */
    apiLongTapApiDevicesSerialLongTapPost: (
      serial: string,
      data: LongTapRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/long_tap`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiScrollApiDevicesSerialScrollPost
     * @summary Api Scroll
     * @request POST:/api/devices/{serial}/scroll
     * @secure
     */
    apiScrollApiDevicesSerialScrollPost: (
      serial: string,
      data: ScrollRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/scroll`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiDoubleTapApiDevicesSerialDoubleTapPost
     * @summary Api Double Tap
     * @request POST:/api/devices/{serial}/double_tap
     * @secure
     */
    apiDoubleTapApiDevicesSerialDoubleTapPost: (
      serial: string,
      data: DoubleTapRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/double_tap`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiPinchApiDevicesSerialPinchPost
     * @summary Api Pinch
     * @request POST:/api/devices/{serial}/pinch
     * @secure
     */
    apiPinchApiDevicesSerialPinchPost: (
      serial: string,
      data: PinchRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/pinch`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiDragApiDevicesSerialDragPost
     * @summary Api Drag
     * @request POST:/api/devices/{serial}/drag
     * @secure
     */
    apiDragApiDevicesSerialDragPost: (
      serial: string,
      data: DragRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/drag`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiSetClipboardApiDevicesSerialClipboardPost
     * @summary Api Set Clipboard
     * @request POST:/api/devices/{serial}/clipboard
     * @secure
     */
    apiSetClipboardApiDevicesSerialClipboardPost: (
      serial: string,
      data: ClipboardSetRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/clipboard`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiGetClipboardApiDevicesSerialClipboardGet
     * @summary Api Get Clipboard
     * @request GET:/api/devices/{serial}/clipboard
     * @secure
     */
    apiGetClipboardApiDevicesSerialClipboardGet: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/clipboard`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiHierarchyApiDevicesSerialHierarchyGet
     * @summary Api Hierarchy
     * @request GET:/api/devices/{serial}/hierarchy
     * @secure
     */
    apiHierarchyApiDevicesSerialHierarchyGet: (
      serial: string,
      query?: {
        /**
         * Refresh
         * @default false
         */
        refresh?: boolean;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/hierarchy`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiUiElementsApiDevicesSerialUiElementsGet
     * @summary Api Ui Elements
     * @request GET:/api/devices/{serial}/ui_elements
     * @secure
     */
    apiUiElementsApiDevicesSerialUiElementsGet: (
      serial: string,
      query?: {
        /**
         * Refresh
         * @default true
         */
        refresh?: boolean;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/ui_elements`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiTapSelectorApiTapSelectorSerialPost
     * @summary Api Tap Selector
     * @request POST:/api/tap_selector/{serial}
     * @secure
     */
    apiTapSelectorApiTapSelectorSerialPost: (
      serial: string,
      data: TapSelectorRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/tap_selector/${serial}`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiHitTestApiDevicesSerialHitTestPost
     * @summary Api Hit Test
     * @request POST:/api/devices/{serial}/hit_test
     * @secure
     */
    apiHitTestApiDevicesSerialHitTestPost: (
      serial: string,
      data: HitTestRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/hit_test`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiGetTaskApiTasksTaskIdGet
     * @summary Api Get Task
     * @request GET:/api/tasks/{task_id}
     * @secure
     */
    apiGetTaskApiTasksTaskIdGet: (taskId: string, params: RequestParams = {}) =>
      this.request<any, HTTPValidationError>({
        path: `/api/tasks/${taskId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiShellApiAgentSerialShellPost
     * @summary Api Shell
     * @request POST:/api/agent/{serial}/shell
     * @secure
     */
    apiShellApiAgentSerialShellPost: (
      serial: string,
      data: Record<string, any>,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/agent/${serial}/shell`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiEnqueueTaskApiTaskPost
     * @summary Api Enqueue Task
     * @request POST:/api/task
     * @secure
     */
    apiEnqueueTaskApiTaskPost: (
      data: TaskRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/task`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiScenarioPreviewApiDevicesSerialScenarioPreviewPost
     * @summary Api Scenario Preview
     * @request POST:/api/devices/{serial}/scenario/preview
     * @secure
     */
    apiScenarioPreviewApiDevicesSerialScenarioPreviewPost: (
      serial: string,
      data: ScenarioPreviewRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/scenario/preview`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description SSE endpoint: streams step results as they complete. Each event is a JSON object with the step result. Final event has type "done" with full summary.
     *
     * @tags device-control
     * @name ApiScenarioPreviewStreamApiDevicesSerialScenarioPreviewStreamPost
     * @summary Api Scenario Preview Stream
     * @request POST:/api/devices/{serial}/scenario/preview-stream
     * @secure
     */
    apiScenarioPreviewStreamApiDevicesSerialScenarioPreviewStreamPost: (
      serial: string,
      data: ScenarioPreviewRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/scenario/preview-stream`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiScenarioPreviewStreamCancelApiDevicesSerialScenarioPreviewStreamTraceIdCancelPost
     * @summary Api Scenario Preview Stream Cancel
     * @request POST:/api/devices/{serial}/scenario/preview-stream/{trace_id}/cancel
     * @secure
     */
    apiScenarioPreviewStreamCancelApiDevicesSerialScenarioPreviewStreamTraceIdCancelPost:
      (serial: string, traceId: string, params: RequestParams = {}) =>
        this.request<any, HTTPValidationError>({
          path: `/api/devices/${serial}/scenario/preview-stream/${traceId}/cancel`,
          method: "POST",
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiScenarioRunApiDevicesSerialScenarioRunPost
     * @summary Api Scenario Run
     * @request POST:/api/devices/{serial}/scenario/run
     * @secure
     */
    apiScenarioRunApiDevicesSerialScenarioRunPost: (
      serial: string,
      data: ScenarioPreviewRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/scenario/run`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiSessionsScenarioRunApiSessionsSessionIdScenarioRunPost
     * @summary Api Sessions Scenario Run
     * @request POST:/api/sessions/{session_id}/scenario/run
     * @secure
     */
    apiSessionsScenarioRunApiSessionsSessionIdScenarioRunPost: (
      sessionId: string,
      data: ScenarioPreviewRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/sessions/${sessionId}/scenario/run`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiRunCampaignApiCampaignsCampaignIdRunPost
     * @summary Api Run Campaign
     * @request POST:/api/campaigns/{campaign_id}/run
     * @secure
     */
    apiRunCampaignApiCampaignsCampaignIdRunPost: (
      campaignId: string,
      data: CampaignRunBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/run`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description How campaign runs are executed — for UI/docs.
     *
     * @tags device-control
     * @name ApiExecutionRuntimeApiExecutionRuntimeGet
     * @summary Api Execution Runtime
     * @request GET:/api/execution/runtime
     * @secure
     */
    apiExecutionRuntimeApiExecutionRuntimeGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/execution/runtime`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description List top-level Temporal workflow runs for a campaign. Only returns top-level ScenarioWorkflow entries (normally one per device). Child workflows (ScenarioStepsWorkflow) are excluded — they are an implementation detail and would flood the list.
     *
     * @tags device-control
     * @name ApiListCampaignWorkflowsApiCampaignsCampaignIdWorkflowsGet
     * @summary Api List Campaign Workflows
     * @request GET:/api/campaigns/{campaign_id}/workflows
     * @secure
     */
    apiListCampaignWorkflowsApiCampaignsCampaignIdWorkflowsGet: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/workflows`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description List RUNNING/PAUSED top-level scenario workflows for a specific device serial.
     *
     * @tags device-control
     * @name ApiDeviceRunningWorkflowsApiDevicesSerialRunningWorkflowsGet
     * @summary Api Device Running Workflows
     * @request GET:/api/devices/{serial}/running-workflows
     * @secure
     */
    apiDeviceRunningWorkflowsApiDevicesSerialRunningWorkflowsGet: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/running-workflows`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Query real-time progress of a Temporal scenario workflow. When the child ScenarioStepsWorkflow is paused on error, status is overridden to 'paused_on_error' and error_message is populated.
     *
     * @tags device-control
     * @name ApiWorkflowProgressApiWorkflowsWorkflowIdProgressGet
     * @summary Api Workflow Progress
     * @request GET:/api/workflows/{workflow_id}/progress
     * @secure
     */
    apiWorkflowProgressApiWorkflowsWorkflowIdProgressGet: (
      workflowId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/workflows/${workflowId}/progress`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Query step-by-step execution log for a scenario workflow. - While RUNNING: queries the child steps workflow (live, real-time). - After COMPLETED/FAILED: reads the final result from the parent workflow. Returns a flat list of step entries with index, type, ok, message, depth.
     *
     * @tags device-control
     * @name ApiWorkflowStepsApiWorkflowsWorkflowIdStepsGet
     * @summary Api Workflow Steps
     * @request GET:/api/workflows/{workflow_id}/steps
     * @secure
     */
    apiWorkflowStepsApiWorkflowsWorkflowIdStepsGet: (
      workflowId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/workflows/${workflowId}/steps`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Pause a running scenario workflow at the next step boundary. SECURITY NOTE: workflow_id is caller-supplied and not validated for ownership. Caller-supplied workflow IDs must resolve to a campaign owned by the current user before any Temporal handle is signalled.
     *
     * @tags device-control
     * @name ApiWorkflowPauseApiWorkflowsWorkflowIdPausePost
     * @summary Api Workflow Pause
     * @request POST:/api/workflows/{workflow_id}/pause
     * @secure
     */
    apiWorkflowPauseApiWorkflowsWorkflowIdPausePost: (
      workflowId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/workflows/${workflowId}/pause`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Resume a paused scenario workflow.
     *
     * @tags device-control
     * @name ApiWorkflowResumeApiWorkflowsWorkflowIdResumePost
     * @summary Api Workflow Resume
     * @request POST:/api/workflows/{workflow_id}/resume
     * @secure
     */
    apiWorkflowResumeApiWorkflowsWorkflowIdResumePost: (
      workflowId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/workflows/${workflowId}/resume`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Cancel a scenario workflow — cancels both parent and child steps workflow.
     *
     * @tags device-control
     * @name ApiWorkflowCancelApiWorkflowsWorkflowIdCancelPost
     * @summary Api Workflow Cancel
     * @request POST:/api/workflows/{workflow_id}/cancel
     * @secure
     */
    apiWorkflowCancelApiWorkflowsWorkflowIdCancelPost: (
      workflowId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/workflows/${workflowId}/cancel`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Cancel all running scenarios on a device to allow manual takeover. Cancels every matching Temporal workflow, then force-resets the in-process _scenario_active counter so the WebSocket input gate opens immediately without waiting for the activity to acknowledge cancellation.
     *
     * @tags device-control
     * @name ApiDeviceInterruptApiDevicesSerialInterruptPost
     * @summary Api Device Interrupt
     * @request POST:/api/devices/{serial}/interrupt
     * @secure
     */
    apiDeviceInterruptApiDevicesSerialInterruptPost: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/interrupt`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Get STFService connection status and all event state.
     *
     * @tags device-control, stf-control
     * @name StfStatusApiStfStatusSerialGet
     * @summary Stf Status
     * @request GET:/api/stf/status/{serial}
     * @secure
     */
    stfStatusApiStfStatusSerialGet: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/stf/status/${serial}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control, stf-control
     * @name StfGetClipboardApiStfClipboardSerialGet
     * @summary Stf Get Clipboard
     * @request GET:/api/stf/clipboard/{serial}
     * @secure
     */
    stfGetClipboardApiStfClipboardSerialGet: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/stf/clipboard/${serial}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control, stf-control
     * @name StfSetClipboardApiStfClipboardSerialPost
     * @summary Stf Set Clipboard
     * @request POST:/api/stf/clipboard/{serial}
     * @secure
     */
    stfSetClipboardApiStfClipboardSerialPost: (
      serial: string,
      data: SetClipboardRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/stf/clipboard/${serial}`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control, stf-control
     * @name StfSetWifiApiStfWifiSerialPost
     * @summary Stf Set Wifi
     * @request POST:/api/stf/wifi/{serial}
     * @secure
     */
    stfSetWifiApiStfWifiSerialPost: (
      serial: string,
      data: SetEnabledRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/stf/wifi/${serial}`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control, stf-control
     * @name StfSetBluetoothApiStfBluetoothSerialPost
     * @summary Stf Set Bluetooth
     * @request POST:/api/stf/bluetooth/{serial}
     * @secure
     */
    stfSetBluetoothApiStfBluetoothSerialPost: (
      serial: string,
      data: SetEnabledRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/stf/bluetooth/${serial}`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control, stf-control
     * @name StfSetKeyguardApiStfKeyguardSerialPost
     * @summary Stf Set Keyguard
     * @request POST:/api/stf/keyguard/{serial}
     * @secure
     */
    stfSetKeyguardApiStfKeyguardSerialPost: (
      serial: string,
      data: SetEnabledRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/stf/keyguard/${serial}`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control, stf-control
     * @name StfSetWakeLockApiStfWakelockSerialPost
     * @summary Stf Set Wake Lock
     * @request POST:/api/stf/wakelock/{serial}
     * @secure
     */
    stfSetWakeLockApiStfWakelockSerialPost: (
      serial: string,
      data: SetEnabledRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/stf/wakelock/${serial}`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control, stf-control
     * @name StfSetRingerApiStfRingerSerialPost
     * @summary Stf Set Ringer
     * @request POST:/api/stf/ringer/{serial}
     * @secure
     */
    stfSetRingerApiStfRingerSerialPost: (
      serial: string,
      data: SetRingerModeRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/stf/ringer/${serial}`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control, stf-control
     * @name StfSetMuteApiStfMuteSerialPost
     * @summary Stf Set Mute
     * @request POST:/api/stf/mute/{serial}
     * @secure
     */
    stfSetMuteApiStfMuteSerialPost: (
      serial: string,
      data: SetEnabledRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/stf/mute/${serial}`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control, stf-control
     * @name StfIdentifyApiStfIdentifySerialPost
     * @summary Stf Identify
     * @request POST:/api/stf/identify/{serial}
     * @secure
     */
    stfIdentifyApiStfIdentifySerialPost: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/stf/identify/${serial}`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control, stf-control
     * @name StfGetDisplayApiStfDisplaySerialGet
     * @summary Stf Get Display
     * @request GET:/api/stf/display/{serial}
     * @secure
     */
    stfGetDisplayApiStfDisplaySerialGet: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/stf/display/${serial}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control, stf-control
     * @name StfGetPropertiesApiStfPropertiesSerialGet
     * @summary Stf Get Properties
     * @request GET:/api/stf/properties/{serial}
     * @secure
     */
    stfGetPropertiesApiStfPropertiesSerialGet: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/stf/properties/${serial}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),
  };
  health = {
    /**
     * No description
     *
     * @name RootHealthHealthGet
     * @summary Root Health
     * @request GET:/health
     */
    rootHealthHealthGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/health`,
        method: "GET",
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @name RootReadinessHealthReadyGet
     * @summary Root Readiness
     * @request GET:/health/ready
     */
    rootReadinessHealthReadyGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/health/ready`,
        method: "GET",
        format: "json",
        ...params,
      }),
  };
  ping = {
    /**
     * No description
     *
     * @name PingPingGet
     * @summary Ping
     * @request GET:/ping
     */
    pingPingGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/ping`,
        method: "GET",
        format: "json",
        ...params,
      }),
  };
  stream = {
    /**
     * No description
     *
     * @name MjpegStreamStreamSerialGet
     * @summary Mjpeg Stream
     * @request GET:/stream/{serial}
     * @secure
     */
    mjpegStreamStreamSerialGet: (
      serial: string,
      query?: {
        /**
         * Fps
         * @default 0
         */
        fps?: number;
        /**
         * Fresh
         * @default false
         */
        fresh?: boolean;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/stream/${serial}`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),
  };
  screenshot = {
    /**
     * No description
     *
     * @name ScreenshotScreenshotSerialGet
     * @summary Screenshot
     * @request GET:/screenshot/{serial}
     * @secure
     */
    screenshotScreenshotSerialGet: (
      serial: string,
      query?: {
        /**
         * Fresh
         * @default false
         */
        fresh?: boolean;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/screenshot/${serial}`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),
  };
  screenshotB64 = {
    /**
     * @description Screenshot as base64 JPEG. Cropping is done client-side.
     *
     * @name ScreenshotB64ScreenshotB64SerialGet
     * @summary Screenshot B64
     * @request GET:/screenshot-b64/{serial}
     * @secure
     */
    screenshotB64ScreenshotB64SerialGet: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/screenshot-b64/${serial}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),
  };
  devices = {
    /**
     * No description
     *
     * @tags extraction
     * @name ApiExtractHierarchyDevicesSerialExtractHierarchyPost
     * @summary Api Extract Hierarchy
     * @request POST:/devices/{serial}/extract/hierarchy
     * @secure
     */
    apiExtractHierarchyDevicesSerialExtractHierarchyPost: (
      serial: string,
      data: HierarchyExtractBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/devices/${serial}/extract/hierarchy`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags extraction
     * @name ApiExtractOcrDevicesSerialExtractOcrPost
     * @summary Api Extract Ocr
     * @request POST:/devices/{serial}/extract/ocr
     * @secure
     */
    apiExtractOcrDevicesSerialExtractOcrPost: (
      serial: string,
      data: OCRExtractBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/devices/${serial}/extract/ocr`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags extraction
     * @name ApiExtractAiDevicesSerialExtractAiPost
     * @summary Api Extract Ai
     * @request POST:/devices/{serial}/extract/ai
     * @secure
     */
    apiExtractAiDevicesSerialExtractAiPost: (
      serial: string,
      data: AIExtractBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/devices/${serial}/extract/ai`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),
  };
}
