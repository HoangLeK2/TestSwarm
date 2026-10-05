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

/** AcceptanceCandidateOut */
export interface AcceptanceCandidateOut {
  /** Id */
  id: string;
  /** Version */
  version: string;
  /** Source Kind */
  source_kind: string;
  /** Environment */
  environment: string;
  /** Commit Sha */
  commit_sha: string;
  /** Schema Version */
  schema_version: string;
  /** Status */
  status: string;
  /** Rollback Owner */
  rollback_owner: string | null;
  /** Oncall Owner */
  oncall_owner: string | null;
  /** Frozen At */
  frozen_at: string | null;
}

/** AcceptanceDecisionOut */
export interface AcceptanceDecisionOut {
  /** Id */
  id: string;
  /** Candidate Id */
  candidate_id: string;
  /** Evaluation Key */
  evaluation_key: string;
  /** Verdict */
  verdict: string;
  /** Blockers */
  blockers: Record<string, any>[];
  /** Requirement Summary */
  requirement_summary: Record<string, any>;
  /** Pack Sha256 */
  pack_sha256: string;
  /** Signer Snapshot */
  signer_snapshot: Record<string, any>;
  /** Rationale */
  rationale: string;
  /**
   * Evaluated At
   * @format date-time
   */
  evaluated_at: string;
}

/** AcceptanceRequirementIn */
export interface AcceptanceRequirementIn {
  /**
   * Requirement Key
   * @minLength 1
   * @maxLength 128
   */
  requirement_key: string;
  /**
   * Adl Id
   * @minLength 6
   * @maxLength 16
   */
  adl_id: string;
  /**
   * Acceptance Id
   * @minLength 1
   * @maxLength 32
   */
  acceptance_id: string;
  /**
   * Test Id
   * @minLength 1
   * @maxLength 32
   */
  test_id: string;
  /**
   * Expected
   * @minLength 1
   * @maxLength 4000
   */
  expected: string;
  /**
   * Observed
   * @minLength 1
   * @maxLength 4000
   */
  observed: string;
  /** Status */
  status: string;
  /** Required Evidence Level */
  required_evidence_level: string;
  /** Observed Evidence Level */
  observed_evidence_level: string;
  /** Evidence Refs */
  evidence_refs: string[];
  /** Reviewer Id */
  reviewer_id?: string | null;
  /** Executed At */
  executed_at?: string | null;
  /** Blocker */
  blocker?: string | null;
}

/** AccountActionListOut */
export interface AccountActionListOut {
  /** Items */
  items: AccountActionOut[];
  /** Next Cursor */
  next_cursor?: string | null;
  /** Has More */
  has_more: boolean;
}

/** AccountActionOut */
export interface AccountActionOut {
  /** Id */
  id: string;
  /** Account Id */
  account_id: string;
  /** Status */
  status: string;
  /** Action */
  action: string;
  /** Platform */
  platform?: string | null;
  /** Target Type */
  target_type?: string | null;
  /** Target Id */
  target_id?: string | null;
  /** Target Label */
  target_label?: string | null;
  /** Current Activity */
  current_activity?: string | null;
  /** Error Code */
  error_code?: string | null;
  /** Error Message */
  error_message?: string | null;
  /** Device Serial */
  device_serial?: string | null;
  /** Execution Id */
  execution_id?: string | null;
  /** Step Id */
  step_id?: string | null;
  /** Artifact Refs */
  artifact_refs?: any[];
  /** Details */
  details: Record<string, any>;
  /** Started At */
  started_at?: string | null;
  /** Completed At */
  completed_at?: string | null;
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

/** AccountActionSummaryOut */
export interface AccountActionSummaryOut {
  /** Total */
  total: number;
  /** Pending */
  pending: number;
  /** Running */
  running: number;
  /** Succeeded */
  succeeded: number;
  /** Failed */
  failed: number;
  /** Current Activity */
  current_activity?: string | null;
}

/** AccountAvailableDevicesOut */
export interface AccountAvailableDevicesOut {
  /** Items */
  items?: DeviceOut[];
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
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

/** AccountDiscoveryCompleteIn */
export interface AccountDiscoveryCompleteIn {
  /**
   * Candidate Count
   * @min 0
   */
  candidate_count: number;
}

/** AccountDiscoveryFailedIn */
export interface AccountDiscoveryFailedIn {
  /**
   * Error
   * @minLength 1
   * @maxLength 1000
   */
  error: string;
}

/** AccountDiscoveryStateOut */
export interface AccountDiscoveryStateOut {
  /** Id */
  id: string;
  /** Org Id */
  org_id: string;
  /** Account Id */
  account_id: string;
  /** Platform */
  platform: string;
  /** Status */
  status:
    | "uninitialized"
    | "discovery_requested"
    | "discovering"
    | "ready"
    | "active"
    | "error";
  /** Initialized At */
  initialized_at?: string | null;
  /** Discovery Requested At */
  discovery_requested_at?: string | null;
  /** Discovery Started At */
  discovery_started_at?: string | null;
  /** Last Discovery At */
  last_discovery_at?: string | null;
  /** Next Discovery At */
  next_discovery_at?: string | null;
  /** Last Error */
  last_error?: string | null;
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
  /** Request Created */
  request_created?: boolean | null;
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

/** AccountImportFormatCreate */
export interface AccountImportFormatCreate {
  /**
   * Slug
   * @minLength 3
   * @maxLength 100
   */
  slug: string;
  /**
   * Name
   * @minLength 1
   * @maxLength 255
   */
  name: string;
  /**
   * Description
   * @maxLength 2000
   * @default ""
   */
  description?: string;
  /**
   * Delimiter
   * @minLength 1
   * @maxLength 10
   * @default "|"
   */
  delimiter?: string;
  /**
   * Platform
   * @minLength 1
   * @maxLength 50
   */
  platform: string;
  /**
   * Fields
   * @maxItems 50
   * @minItems 1
   */
  fields: string[];
  /**
   * Is Active
   * @default true
   */
  is_active?: boolean;
}

/** AccountImportFormatListOut */
export interface AccountImportFormatListOut {
  /** Items */
  items: AccountImportFormatOut[];
}

/** AccountImportFormatOut */
export interface AccountImportFormatOut {
  /** Id */
  id: string;
  /** Slug */
  slug: string;
  /** Name */
  name: string;
  /**
   * Description
   * @default ""
   */
  description?: string;
  /**
   * Delimiter
   * @default "|"
   */
  delimiter?: string;
  /** Platform */
  platform: string;
  /** Fields */
  fields: string[];
  /**
   * Is Active
   * @default true
   */
  is_active?: boolean;
  /**
   * Is Builtin
   * @default false
   */
  is_builtin?: boolean;
  /** Created By User Id */
  created_by_user_id?: string | null;
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

/** AccountImportFormatUpdate */
export interface AccountImportFormatUpdate {
  /** Name */
  name?: string | null;
  /** Description */
  description?: string | null;
  /** Delimiter */
  delimiter?: string | null;
  /** Platform */
  platform?: string | null;
  /** Fields */
  fields?: string[] | null;
  /** Is Active */
  is_active?: boolean | null;
}

/** AccountLoginScenarioEnsureIn */
export interface AccountLoginScenarioEnsureIn {
  /**
   * Platform
   * @minLength 1
   * @maxLength 100
   */
  platform: string;
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
  /** Observed Display Name */
  observed_display_name?: string | null;
  /** Friends Count */
  friends_count?: number | null;
  /** Friends Observed At */
  friends_observed_at?: string | null;
  /** Assigned Device Name */
  assigned_device_name?: string | null;
  verification_hold?: AccountVerificationHoldOut | null;
  /** Verification Hold Until */
  verification_hold_until?: string | null;
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
   * Expected State Changed At
   * Optimistic lock: must match current state_changed_at
   */
  expected_state_changed_at?: string | null;
  /** Optional reminder window when moving an account into suspended/verification-required state. */
  verification_hold?: AccountVerificationHoldBody | null;
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
  verification_hold?: AccountVerificationHoldOut | null;
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

/** AccountVerificationHoldBody */
export interface AccountVerificationHoldBody {
  /**
   * Preset
   * @default "one_week"
   */
  preset?: "one_week" | "two_weeks" | "custom";
  /** Remind At */
  remind_at?: string | null;
  /**
   * Notify Web
   * @default true
   */
  notify_web?: boolean;
  /**
   * Notify Telegram
   * @default true
   */
  notify_telegram?: boolean;
}

/** AccountVerificationHoldOut */
export interface AccountVerificationHoldOut {
  /** Preset */
  preset: string;
  /**
   * Remind At
   * @format date-time
   */
  remind_at: string;
  /**
   * Notify Web
   * @default true
   */
  notify_web?: boolean;
  /**
   * Notify Telegram
   * @default true
   */
  notify_telegram?: boolean;
  /** Created At */
  created_at?: string | null;
  /** Created By User Id */
  created_by_user_id?: string | null;
}

/** AccountVerificationOut */
export interface AccountVerificationOut {
  /** Assignment Id */
  assignment_id?: string | null;
  /** Status */
  status: string;
  /** Reason */
  reason: string;
  /**
   * Attempted At
   * @format date-time
   */
  attempted_at: string;
  /** Verified At */
  verified_at?: string | null;
  /** Attempt Id */
  attempt_id: string;
  /** Duration Ms */
  duration_ms?: number | null;
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
  /** Observed Display Name */
  observed_display_name?: string | null;
  /** Friends Count */
  friends_count?: number | null;
  /** Friends Observed At */
  friends_observed_at?: string | null;
  /** Assigned Device Name */
  assigned_device_name?: string | null;
  verification_hold?: AccountVerificationHoldOut | null;
  /** Verification Hold Until */
  verification_hold_until?: string | null;
  /**
   * Device Links
   * @default []
   */
  device_links?: DeviceAccountOut[];
}

/** ActiveFleetSessionListOut */
export interface ActiveFleetSessionListOut {
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
  /** Sessions */
  sessions: ActiveFleetSessionOut[];
}

/** ActiveFleetSessionOut */
export interface ActiveFleetSessionOut {
  /** Session Id */
  session_id: string;
  /** Device Id */
  device_id: string;
  /** Device Serial */
  device_serial: string;
  /** Device Name */
  device_name: string;
  /** Owner classification for active control-plane sessions (DF-T-02-013). */
  owner_type: SessionOwnerType;
  /** Source */
  source: "active_session" | "busy_claim";
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /**
   * Duplicate For Device
   * @default false
   */
  duplicate_for_device?: boolean;
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

/** AdminAccountListOut */
export interface AdminAccountListOut {
  /** Items */
  items: AdminAccountOut[];
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
  /** Byworkspace */
  byWorkspace?: AdminWorkspaceMetricOut[];
}

/** AdminAccountOut */
export interface AdminAccountOut {
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
  /** Observed Display Name */
  observed_display_name?: string | null;
  /** Friends Count */
  friends_count?: number | null;
  /** Friends Observed At */
  friends_observed_at?: string | null;
  /** Assigned Device Name */
  assigned_device_name?: string | null;
  verification_hold?: AccountVerificationHoldOut | null;
  /** Verification Hold Until */
  verification_hold_until?: string | null;
  /** Workspaceid */
  workspaceId: string;
  /** Workspacename */
  workspaceName?: string | null;
}

/** AdminAgentListOut */
export interface AdminAgentListOut {
  /** Items */
  items: AdminAgentOut[];
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
}

/** AdminAgentOut */
export interface AdminAgentOut {
  /** Relay Id */
  relay_id: string;
  /** Workspaceid */
  workspaceId: string;
  /** Workspacename */
  workspaceName?: string | null;
  /**
   * Workspacekind
   * @default "tenant"
   */
  workspaceKind?: string;
  /** User Id */
  user_id?: string | null;
  /** Enrollment Token Id */
  enrollment_token_id?: string | null;
  /**
   * Name
   * @default ""
   */
  name?: string;
  /**
   * Hostname
   * @default ""
   */
  hostname?: string;
  /**
   * Ip
   * @default ""
   */
  ip?: string;
  /**
   * Version
   * @default ""
   */
  version?: string;
  /** Serials */
  serials?: string[];
  /**
   * Status
   * @default "unknown"
   */
  status?: string;
  /**
   * Health
   * @default "offline"
   */
  health?: string;
  /**
   * Connected
   * @default false
   */
  connected?: boolean;
  /**
   * Devicecount
   * @default 0
   */
  deviceCount?: number;
  /** Connected At */
  connected_at?: string | null;
  /** Last Heartbeat At */
  last_heartbeat_at?: string | null;
  /** Disconnected At */
  disconnected_at?: string | null;
  /** Created At */
  created_at?: string | null;
}

/** AdminAgentPhoneAssign */
export interface AdminAgentPhoneAssign {
  /**
   * Targetworkspaceid
   * @minLength 1
   */
  targetWorkspaceId: string;
  /**
   * Serials
   * @minItems 1
   */
  serials: string[];
}

/** AdminAgentPhoneAssignOut */
export interface AdminAgentPhoneAssignOut {
  /** Items */
  items: AdminAgentPhoneOut[];
  /** Total */
  total: number;
}

/** AdminAgentPhoneListOut */
export interface AdminAgentPhoneListOut {
  /** Items */
  items: AdminAgentPhoneOut[];
  /** Total */
  total: number;
  /**
   * Offset
   * @default 0
   */
  offset?: number;
  /**
   * Limit
   * @default 100
   */
  limit?: number;
}

/** AdminAgentPhoneOut */
export interface AdminAgentPhoneOut {
  /** Serial */
  serial: string;
  /** Deviceid */
  deviceId?: string | null;
  /**
   * Registered
   * @default false
   */
  registered?: boolean;
  /**
   * Name
   * @default ""
   */
  name?: string;
  /**
   * Brand
   * @default ""
   */
  brand?: string;
  /**
   * Model
   * @default ""
   */
  model?: string;
  /**
   * Status
   * @default "ready"
   */
  status?: string;
  /**
   * State
   * @default "unknown"
   */
  state?: string;
  /** Last Seen */
  last_seen?: string | null;
  /** Managedbyworkspaceid */
  managedByWorkspaceId?: string | null;
  /** Managedbyworkspacename */
  managedByWorkspaceName?: string | null;
  /** Assignedworkspaceid */
  assignedWorkspaceId?: string | null;
  /** Assignedworkspacename */
  assignedWorkspaceName?: string | null;
  /**
   * Pooled
   * @default true
   */
  pooled?: boolean;
}

/** AdminAgentPhoneUnassign */
export interface AdminAgentPhoneUnassign {
  /**
   * Serials
   * @minItems 1
   */
  serials: string[];
}

/** AdminAgentTokenCreate */
export interface AdminAgentTokenCreate {
  /**
   * Workspaceid
   * @minLength 1
   */
  workspaceId: string;
  /**
   * Name
   * @maxLength 255
   * @default ""
   */
  name?: string;
  /** Owneruserid */
  ownerUserId?: string | null;
}

/** AdminAgentTokenCreated */
export interface AdminAgentTokenCreated {
  /** Id */
  id: string;
  /** Workspaceid */
  workspaceId: string;
  /** Workspacename */
  workspaceName?: string | null;
  /** User Id */
  user_id: string;
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

/** AdminAgentTokenOut */
export interface AdminAgentTokenOut {
  /** Id */
  id: string;
  /** Workspaceid */
  workspaceId: string;
  /** Workspacename */
  workspaceName?: string | null;
  /** User Id */
  user_id: string;
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

/** AdminAgentUpdate */
export interface AdminAgentUpdate {
  /** Name */
  name?: string | null;
  /** Status */
  status?: string | null;
  /** Workspaceid */
  workspaceId?: string | null;
}

/** AdminAssignableWorkspaceListOut */
export interface AdminAssignableWorkspaceListOut {
  /** Items */
  items: AdminAssignableWorkspaceOut[];
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
}

/** AdminAssignableWorkspaceOut */
export interface AdminAssignableWorkspaceOut {
  /** Id */
  id: string;
  /** Businessname */
  businessName: string;
  /** Status */
  status: string;
}

/** AdminContentItemOut */
export interface AdminContentItemOut {
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
  /** Parent Item Id */
  parent_item_id?: string | null;
  /** Parent Item Hash */
  parent_item_hash?: string | null;
  /** Parent Item Author */
  parent_item_author?: string | null;
  /** Parent Item Body */
  parent_item_body?: string | null;
  /** Parent Item Content Type */
  parent_item_content_type?: string | null;
  /**
   * Item Level
   * @default 0
   */
  item_level?: number;
  /** Workspaceid */
  workspaceId: string;
  /** Workspacename */
  workspaceName?: string | null;
}

/** AdminContentListOut */
export interface AdminContentListOut {
  /** Items */
  items: AdminContentItemOut[];
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
  /** Byworkspace */
  byWorkspace?: AdminWorkspaceMetricOut[];
}

/** AdminDashboardSummaryOut */
export interface AdminDashboardSummaryOut {
  /**
   * Totalworkspaces
   * @default 0
   */
  totalWorkspaces?: number;
  /**
   * Activeworkspaces
   * @default 0
   */
  activeWorkspaces?: number;
  /**
   * Suspendedworkspaces
   * @default 0
   */
  suspendedWorkspaces?: number;
  /**
   * Archivedworkspaces
   * @default 0
   */
  archivedWorkspaces?: number;
  /**
   * Totalagents
   * @default 0
   */
  totalAgents?: number;
  /**
   * Onlineagents
   * @default 0
   */
  onlineAgents?: number;
  /**
   * Offlineagents
   * @default 0
   */
  offlineAgents?: number;
  /**
   * Staleagents
   * @default 0
   */
  staleAgents?: number;
  /**
   * Totaldevices
   * @default 0
   */
  totalDevices?: number;
  /**
   * Assigneddevices
   * @default 0
   */
  assignedDevices?: number;
  /**
   * Unassigneddevices
   * @default 0
   */
  unassignedDevices?: number;
  /** Devicesbyworkspace */
  devicesByWorkspace?: Record<string, any>[];
  /** Agentsbyworkspace */
  agentsByWorkspace?: Record<string, any>[];
}

/** AdminDeviceListOut */
export interface AdminDeviceListOut {
  /** Items */
  items: AdminDeviceOut[];
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
}

/** AdminDeviceOut */
export interface AdminDeviceOut {
  /** Id */
  id: string;
  /** Serial */
  serial: string;
  /**
   * Device Serial
   * @default ""
   */
  device_serial?: string;
  /**
   * Name
   * @default ""
   */
  name?: string;
  /** Workspaceid */
  workspaceId: string;
  /** Workspacename */
  workspaceName?: string | null;
  /** Managedbyworkspaceid */
  managedByWorkspaceId?: string | null;
  /** Managedbyworkspacename */
  managedByWorkspaceName?: string | null;
  /** User Id */
  user_id?: string | null;
  /**
   * Brand
   * @default ""
   */
  brand?: string;
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
   * Status
   * @default "paired"
   */
  status?: string;
  /**
   * State
   * @default "unknown"
   */
  state?: string;
  /**
   * Assigned
   * @default false
   */
  assigned?: boolean;
  /**
   * Transferable
   * @default true
   */
  transferable?: boolean;
  /**
   * Pooled
   * @default true
   */
  pooled?: boolean;
  /** Last Seen */
  last_seen?: string | null;
  /** Paired At */
  paired_at?: string | null;
  /** Unpaired At */
  unpaired_at?: string | null;
  /** Created At */
  created_at?: string | null;
  /** Updated At */
  updated_at?: string | null;
}

/** AdminDeviceTransfer */
export interface AdminDeviceTransfer {
  /** Workspaceid */
  workspaceId?: string | null;
  /** Userid */
  userId?: string | null;
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

/** AdminOwnerOut */
export interface AdminOwnerOut {
  /** User Id */
  user_id: string;
  /** Email */
  email: string;
  /** Name */
  name: string;
  /** Role */
  role: string;
  /**
   * Is Active
   * @default true
   */
  is_active?: boolean;
  /**
   * Mustchangepassword
   * @default false
   */
  mustChangePassword?: boolean;
  /** Created At */
  created_at?: string | null;
}

/** AdminOwnerPasswordReset */
export interface AdminOwnerPasswordReset {
  /** Password */
  password?: string | null;
}

/** AdminOwnerPasswordResetOut */
export interface AdminOwnerPasswordResetOut {
  owner: AdminOwnerOut;
  /** Temporarypassword */
  temporaryPassword: string;
}

/** AdminOwnerUpdate */
export interface AdminOwnerUpdate {
  /** Is Active */
  is_active?: boolean | null;
  /** Mustchangepassword */
  mustChangePassword?: boolean | null;
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

/** AdminUserCreate */
export interface AdminUserCreate {
  /**
   * Email
   * @minLength 3
   * @maxLength 255
   */
  email: string;
  /**
   * Name
   * @minLength 1
   * @maxLength 255
   */
  name: string;
  /** Password */
  password?: string | null;
  /**
   * Workspaceids
   * @maxItems 200
   */
  workspaceIds?: string[];
}

/** AdminUserCreated */
export interface AdminUserCreated {
  /** User Id */
  user_id: string;
  /** Email */
  email: string;
  /** Name */
  name: string;
  /** Platformrole */
  platformRole: string;
  /**
   * Is Active
   * @default true
   */
  is_active?: boolean;
  /**
   * Adminworkspacecount
   * @default 0
   */
  adminWorkspaceCount?: number;
  /** Adminworkspaces */
  adminWorkspaces?: AdminUserWorkspaceOut[];
  /** Created At */
  created_at?: string | null;
  /** Temporarypassword */
  temporaryPassword?: string | null;
}

/** AdminUserListOut */
export interface AdminUserListOut {
  /** Items */
  items: AdminUserOut[];
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
}

/** AdminUserOut */
export interface AdminUserOut {
  /** User Id */
  user_id: string;
  /** Email */
  email: string;
  /** Name */
  name: string;
  /** Platformrole */
  platformRole: string;
  /**
   * Is Active
   * @default true
   */
  is_active?: boolean;
  /**
   * Adminworkspacecount
   * @default 0
   */
  adminWorkspaceCount?: number;
  /** Adminworkspaces */
  adminWorkspaces?: AdminUserWorkspaceOut[];
  /** Created At */
  created_at?: string | null;
}

/** AdminUserPasswordResetOut */
export interface AdminUserPasswordResetOut {
  admin: AdminUserOut;
  /** Temporarypassword */
  temporaryPassword: string;
}

/** AdminUserUpdate */
export interface AdminUserUpdate {
  /** Name */
  name?: string | null;
  /** Is Active */
  is_active?: boolean | null;
}

/** AdminUserWorkspaceBulkOut */
export interface AdminUserWorkspaceBulkOut {
  admin: AdminUserOut;
  /** Assigned */
  assigned?: AdminUserWorkspaceBulkResult[];
  /** Removed */
  removed?: AdminUserWorkspaceBulkResult[];
  /** Skipped */
  skipped?: AdminUserWorkspaceBulkResult[];
}

/** AdminUserWorkspaceBulkResult */
export interface AdminUserWorkspaceBulkResult {
  /** Workspaceid */
  workspaceId: string;
  /** Workspacename */
  workspaceName?: string | null;
  /** Status */
  status: string;
  /** Reason */
  reason?: string | null;
}

/** AdminUserWorkspaceBulkUpdate */
export interface AdminUserWorkspaceBulkUpdate {
  /**
   * Workspaceids
   * @maxItems 200
   * @minItems 1
   */
  workspaceIds: string[];
}

/** AdminUserWorkspaceOut */
export interface AdminUserWorkspaceOut {
  /** Id */
  id: string;
  /** Businessname */
  businessName: string;
  /** Status */
  status: string;
  /** Joined At */
  joined_at?: string | null;
}

/** AdminWorkspaceAccessAdminOut */
export interface AdminWorkspaceAccessAdminOut {
  /** User Id */
  user_id: string;
  /** Email */
  email: string;
  /** Name */
  name: string;
  /**
   * Role
   * @default "admin"
   */
  role?: string;
  /**
   * Is Active
   * @default true
   */
  is_active?: boolean;
  /** Created At */
  created_at?: string | null;
  /** Joined At */
  joined_at?: string | null;
  /** Workspaceid */
  workspaceId: string;
  /** Workspacename */
  workspaceName: string;
}

/** AdminWorkspaceAccessMemberOut */
export interface AdminWorkspaceAccessMemberOut {
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
  /** Workspaceid */
  workspaceId: string;
  /** Workspacename */
  workspaceName: string;
}

/** AdminWorkspaceAccessOut */
export interface AdminWorkspaceAccessOut {
  /** Members */
  members?: AdminWorkspaceAccessMemberOut[];
  /** Admins */
  admins?: AdminWorkspaceAccessAdminOut[];
}

/** AdminWorkspaceAdminAssign */
export interface AdminWorkspaceAdminAssign {
  /**
   * Userid
   * @minLength 1
   */
  userId: string;
}

/** AdminWorkspaceAdminOut */
export interface AdminWorkspaceAdminOut {
  /** User Id */
  user_id: string;
  /** Email */
  email: string;
  /** Name */
  name: string;
  /**
   * Role
   * @default "admin"
   */
  role?: string;
  /**
   * Is Active
   * @default true
   */
  is_active?: boolean;
  /** Created At */
  created_at?: string | null;
  /** Joined At */
  joined_at?: string | null;
}

/** AdminWorkspaceCreate */
export interface AdminWorkspaceCreate {
  /**
   * Businessname
   * @minLength 1
   * @maxLength 255
   */
  businessName: string;
  /** Kind */
  kind?: string | null;
  /** Description */
  description?: string | null;
  /** Businessemail */
  businessEmail?: string | null;
  /** Businesslogo */
  businessLogo?: string | null;
  /** Owneruserid */
  ownerUserId?: string | null;
  /** Owneremail */
  ownerEmail?: string | null;
  /** Ownername */
  ownerName?: string | null;
  /** Ownerpassword */
  ownerPassword?: string | null;
  /** Adminuserids */
  adminUserIds?: string[];
}

/** AdminWorkspaceCreated */
export interface AdminWorkspaceCreated {
  /** Id */
  id: string;
  /** Businessname */
  businessName: string;
  /**
   * Description
   * @default ""
   */
  description?: string;
  /** Businessemail */
  businessEmail?: string | null;
  /** Businesslogo */
  businessLogo?: string | null;
  /** Slug */
  slug?: string | null;
  /** Status */
  status: string;
  /** Plan */
  plan: string;
  /**
   * Kind
   * @default "tenant"
   */
  kind?: string;
  owner?: AdminOwnerOut | null;
  /** Workspaceadmins */
  workspaceAdmins?: AdminWorkspaceAdminOut[];
  /**
   * Agentcount
   * @default 0
   */
  agentCount?: number;
  /**
   * Devicecount
   * @default 0
   */
  deviceCount?: number;
  /**
   * Membercount
   * @default 0
   */
  memberCount?: number;
  /**
   * Admincount
   * @default 0
   */
  adminCount?: number;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /** Updated At */
  updated_at?: string | null;
  /** Temporarypassword */
  temporaryPassword?: string | null;
}

/** AdminWorkspaceDependenciesOut */
export interface AdminWorkspaceDependenciesOut {
  /**
   * Agents
   * @default 0
   */
  agents?: number;
  /**
   * Devices
   * @default 0
   */
  devices?: number;
  /**
   * Members
   * @default 0
   */
  members?: number;
}

/** AdminWorkspaceListOut */
export interface AdminWorkspaceListOut {
  /** Items */
  items: AdminWorkspaceOut[];
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
}

/** AdminWorkspaceMetricOut */
export interface AdminWorkspaceMetricOut {
  /** Workspaceid */
  workspaceId: string;
  /** Workspacename */
  workspaceName?: string | null;
  /**
   * Count
   * @default 0
   */
  count?: number;
}

/** AdminWorkspaceOut */
export interface AdminWorkspaceOut {
  /** Id */
  id: string;
  /** Businessname */
  businessName: string;
  /**
   * Description
   * @default ""
   */
  description?: string;
  /** Businessemail */
  businessEmail?: string | null;
  /** Businesslogo */
  businessLogo?: string | null;
  /** Slug */
  slug?: string | null;
  /** Status */
  status: string;
  /** Plan */
  plan: string;
  /**
   * Kind
   * @default "tenant"
   */
  kind?: string;
  owner?: AdminOwnerOut | null;
  /** Workspaceadmins */
  workspaceAdmins?: AdminWorkspaceAdminOut[];
  /**
   * Agentcount
   * @default 0
   */
  agentCount?: number;
  /**
   * Devicecount
   * @default 0
   */
  deviceCount?: number;
  /**
   * Membercount
   * @default 0
   */
  memberCount?: number;
  /**
   * Admincount
   * @default 0
   */
  adminCount?: number;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /** Updated At */
  updated_at?: string | null;
}

/** AdminWorkspaceTransferOwner */
export interface AdminWorkspaceTransferOwner {
  /**
   * Userid
   * @minLength 1
   */
  userId: string;
}

/** AdminWorkspaceUpdate */
export interface AdminWorkspaceUpdate {
  /** Businessname */
  businessName?: string | null;
  /** Description */
  description?: string | null;
  /** Businessemail */
  businessEmail?: string | null;
  /** Businesslogo */
  businessLogo?: string | null;
  /** Status */
  status?: string | null;
  /** Plan */
  plan?: string | null;
  /** Kind */
  kind?: string | null;
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

/** ApproveWizardScenarioIn */
export interface ApproveWizardScenarioIn {
  /**
   * Operation Id
   * @minLength 8
   * @maxLength 128
   */
  operation_id: string;
  /**
   * Scenario Version Id
   * @minLength 1
   * @maxLength 64
   */
  scenario_version_id: string;
  /**
   * Expected Content Hash
   * @minLength 64
   * @maxLength 64
   */
  expected_content_hash: string;
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
   * CSV file with columns: platform, username, password, display_name, tags, notes, email, totp_secret, cookies, token
   */
  file: File | Blob;
}

/** Body_bulk_import_txt_api_accounts_import_txt_post */
export interface BodyBulkImportTxtApiAccountsImportTxtPost {
  /**
   * File
   * TXT file containing one account per line
   */
  file: File | Blob;
  /** Format Id */
  format_id?: string | null;
  /** Format Slug */
  format_slug?: string | null;
}

/** Body_import_scenario_body_into_existing_route_api_scenarios__scenario_id__import_body_post */
export interface BodyImportScenarioBodyIntoExistingRouteApiScenariosScenarioIdImportBodyPost {
  /** File */
  file: File | Blob;
}

/** Body_import_scenario_route_api_scenarios_import_post */
export interface BodyImportScenarioRouteApiScenariosImportPost {
  /** File */
  file: File | Blob;
}

/** Body_upload_step_template_route_api_scenarios__scenario_id__image_templates_post */
export interface BodyUploadStepTemplateRouteApiScenariosScenarioIdImageTemplatesPost {
  /** File */
  file: File | Blob;
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

/** BuildAcceptanceCandidateIn */
export interface BuildAcceptanceCandidateIn {
  /**
   * Version
   * @minLength 1
   * @maxLength 64
   */
  version: string;
  /** Source Kind */
  source_kind: string;
  /**
   * Environment
   * @minLength 1
   * @maxLength 64
   */
  environment: string;
  /**
   * Commit Sha
   * @minLength 1
   * @maxLength 64
   */
  commit_sha: string;
  /**
   * Schema Version
   * @minLength 1
   * @maxLength 64
   */
  schema_version: string;
  /** Rollback Owner */
  rollback_owner?: string | null;
  /** Oncall Owner */
  oncall_owner?: string | null;
  /** Requirements */
  requirements: AcceptanceRequirementIn[];
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
  /** Email */
  email?: string | null;
  /** Totp Secret */
  totp_secret?: string | null;
  /** Cookies */
  cookies?: string | null;
  /** Token */
  token?: string | null;
  /**
   * Account Metadata
   * @default {}
   */
  account_metadata?: Record<string, any>;
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

/** CampaignAllocationSnapshotItemIn */
export interface CampaignAllocationSnapshotItemIn {
  /**
   * Device Id
   * @minLength 1
   * @maxLength 36
   */
  device_id: string;
  /**
   * External Entity Id
   * @minLength 1
   * @maxLength 36
   */
  external_entity_id: string;
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
  /** Recovery Policy */
  recovery_policy?: Record<string, any>;
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
  /** External Entity Id */
  external_entity_id?: string | null;
  /** Dispatch Source */
  dispatch_source?: string | null;
  /** Workflow Id */
  workflow_id?: string | null;
}

/** CampaignDispatchIn */
export interface CampaignDispatchIn {
  target: CampaignDispatchTargetIn;
  source_pool?: CampaignSourcePoolIn | null;
  /** Allocation Snapshot */
  allocation_snapshot?: CampaignAllocationSnapshotItemIn[];
  /**
   * Allocation Policy
   * @default "one_per_device"
   */
  allocation_policy?: "one_per_device";
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
  /** Requirements */
  requirements?: Record<string, any> | null;
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

/** CampaignDispatchPreviewAssignmentOut */
export interface CampaignDispatchPreviewAssignmentOut {
  /** Device Id */
  device_id: string;
  /** Device Serial */
  device_serial: string;
  /** Device Name */
  device_name?: string | null;
  /** External Entity Id */
  external_entity_id: string;
  /** Display Name */
  display_name: string;
  /** Platform */
  platform: string;
  /** Entity Type */
  entity_type: string;
}

/** CampaignDispatchPreviewOut */
export interface CampaignDispatchPreviewOut {
  /** Campaign Id */
  campaign_id: string;
  /** Allocation Policy */
  allocation_policy: string;
  /** Device Count */
  device_count: number;
  /** Available Source Count */
  available_source_count: number;
  /** Assignments */
  assignments?: CampaignDispatchPreviewAssignmentOut[];
}

/** CampaignDispatchTargetIn */
export interface CampaignDispatchTargetIn {
  /** Device Ids */
  device_ids?: string[];
  /** Device Group Ids */
  device_group_ids?: string[];
  /** External Entity Ids */
  external_entity_ids?: string[];
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
  /** Recovery Policy */
  recovery_policy?: Record<string, any> | null;
  /** Tags */
  tags?: string[] | null;
  /** Scenario Refs */
  scenario_refs?: CampaignScenarioRefIn[] | null;
  /** Per Device Overrides */
  per_device_overrides?: Record<string, Record<string, any>> | null;
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

/** CampaignFunnelOut */
export interface CampaignFunnelOut {
  /** Service Campaign Id */
  service_campaign_id: string;
  /** Acquisition Id */
  acquisition_id: string;
  /** Completed Steps */
  completed_steps: number;
  /** Next Step */
  next_step: string | null;
  /** Events */
  events: FunnelEventOut[];
}

/** CampaignMonitorExecutionOut */
export interface CampaignMonitorExecutionOut {
  /** Execution Id */
  execution_id: string;
  /** Status */
  status: string;
  context: ExecutionTraceContextOut;
  summary: ExecutionTaskLogSummaryOut;
  /** Current Step Type */
  current_step_type?: string | null;
  /** Message */
  message?: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /** Started At */
  started_at?: string | null;
  /** Finished At */
  finished_at?: string | null;
  /** Last Event At */
  last_event_at?: string | null;
}

/** CampaignMonitorOut */
export interface CampaignMonitorOut {
  /** Campaign Id */
  campaign_id: string;
  /** Total */
  total: number;
  /** Limit */
  limit: number;
  /** Executions */
  executions?: CampaignMonitorExecutionOut[];
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

/** CampaignPageOut */
export interface CampaignPageOut {
  /** Total */
  total: number;
  /** Items */
  items: (CampaignEntityOut | CampaignOut)[];
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
  /**
   * Repeat Count
   * @min 1
   * @max 20
   * @default 1
   */
  repeat_count?: number;
}

/** CampaignScenarioRefOut */
export interface CampaignScenarioRefOut {
  /** Scenario Id */
  scenario_id: string;
  /** Scenario Version */
  scenario_version: number;
  /**
   * Repeat Count
   * @default 1
   */
  repeat_count?: number;
}

/** CampaignSourcePoolIn */
export interface CampaignSourcePoolIn {
  /**
   * Platform
   * @minLength 1
   * @maxLength 32
   */
  platform: string;
  /**
   * Entity Type
   * @minLength 1
   * @maxLength 32
   */
  entity_type: string;
  /** Search */
  search?: string | null;
  /** Output Prefix */
  output_prefix?: string | null;
  /**
   * Statuses
   * @maxItems 10
   * @minItems 1
   */
  statuses?: string[];
}

/** CancelServiceCampaignIn */
export interface CancelServiceCampaignIn {
  /**
   * Idempotency Key
   * @minLength 8
   * @maxLength 128
   */
  idempotency_key: string;
  /**
   * Reason
   * @minLength 3
   * @maxLength 1000
   */
  reason: string;
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

/** ClientFunnelEventIn */
export interface ClientFunnelEventIn {
  /**
   * Event Id
   * @minLength 8
   * @maxLength 128
   */
  event_id: string;
  /**
   * Event Name
   * @pattern ^(landing_view|start_click)$
   */
  event_name: string;
  /**
   * Occurred At
   * @format date-time
   */
  occurred_at: string;
  /** Attribution */
  attribution?: Record<string, string>;
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

/** ComputeKpiSnapshotIn */
export interface ComputeKpiSnapshotIn {
  /**
   * Query Version
   * @minLength 1
   * @maxLength 64
   */
  query_version: string;
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

/** ConnectLocalEmulatorBody */
export interface ConnectLocalEmulatorBody {
  /**
   * Serial
   * @pattern ^emulator-[0-9]{4,5}$
   */
  serial: string;
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
  /** Parent Item Id */
  parent_item_id?: string | null;
  /** Parent Item Hash */
  parent_item_hash?: string | null;
  /** Parent Item Author */
  parent_item_author?: string | null;
  /** Parent Item Body */
  parent_item_body?: string | null;
  /** Parent Item Content Type */
  parent_item_content_type?: string | null;
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

/** CreateFarmRunIn */
export interface CreateFarmRunIn {
  /**
   * Lane Id
   * @minLength 1
   * @maxLength 64
   */
  lane_id: string;
  /**
   * Slot Id
   * @minLength 1
   * @maxLength 64
   */
  slot_id: string;
  /**
   * Execution Id
   * @minLength 1
   * @maxLength 64
   */
  execution_id: string;
  /**
   * Scenario Version Id
   * @minLength 1
   * @maxLength 64
   */
  scenario_version_id: string;
  /**
   * App Build Id
   * @minLength 1
   * @maxLength 64
   */
  app_build_id: string;
  /**
   * Reservation Id
   * @minLength 1
   * @maxLength 64
   */
  reservation_id: string;
  /**
   * Approval Id
   * @minLength 1
   * @maxLength 64
   */
  approval_id: string;
  /**
   * Idempotency Key
   * @minLength 8
   * @maxLength 128
   */
  idempotency_key: string;
  /**
   * Deadline At
   * @format date-time
   */
  deadline_at: string;
  /**
   * Reason
   * @minLength 1
   * @maxLength 64
   * @default "scheduled"
   */
  reason?: string;
}

/** CreateIssueIn */
export interface CreateIssueIn {
  /**
   * Source Attempt Id
   * @minLength 1
   * @maxLength 64
   */
  source_attempt_id: string;
  /**
   * Severity
   * @pattern ^(minor|major|critical)$
   */
  severity: string;
  /**
   * Assertion Key
   * @minLength 1
   * @maxLength 255
   */
  assertion_key: string;
  /**
   * Expected
   * @minLength 1
   * @maxLength 4000
   */
  expected: string;
  /**
   * Actual
   * @minLength 1
   * @maxLength 4000
   */
  actual: string;
  /** Reproduction */
  reproduction: Record<string, any>;
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
  /**
   * Display Message
   * @default ""
   */
  display_message?: string;
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
  /**
   * Verification Status
   * @default "unknown"
   */
  verification_status?: string;
  /** Verified At */
  verified_at?: string | null;
  /** Verification Attempted At */
  verification_attempted_at?: string | null;
  /** Verification Evidence */
  verification_evidence?: Record<string, any>;
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

/** DeviceGroupAvailableDevicesOut */
export interface DeviceGroupAvailableDevicesOut {
  /** Items */
  items: DeviceOut[];
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
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

/** DeviceHygieneResultIn */
export interface DeviceHygieneResultIn {
  /**
   * Target Type
   * @pattern ^(physical|emulator)$
   */
  target_type: string;
  /**
   * Protocol Version
   * @minLength 1
   * @maxLength 64
   */
  protocol_version: string;
  /** Reset Succeeded */
  reset_succeeded: boolean;
  /** Readback Clean */
  readback_clean: boolean;
  /** Evidence Ref */
  evidence_ref?: string | null;
  /**
   * Active Run
   * @default false
   */
  active_run?: boolean;
  /** Service Campaign Id */
  service_campaign_id?: string | null;
}

/** DeviceHygieneResultOut */
export interface DeviceHygieneResultOut {
  /** Device Id */
  device_id: string;
  /** Target Type */
  target_type: string;
  /** State */
  state: string;
  /** Protocol Version */
  protocol_version: string;
  /** Reason Code */
  reason_code: string;
  /** Verification Evidence Ref */
  verification_evidence_ref: string | null;
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

/** DeviceNameUpdate */
export interface DeviceNameUpdate {
  /**
   * Name
   * @maxLength 255
   * @default ""
   */
  name?: string;
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
  /** Managed By Org Id */
  managed_by_org_id?: string | null;
  /** Managed By Relay Id */
  managed_by_relay_id?: string | null;
  /** Managed By Relay Name */
  managed_by_relay_name?: string | null;
  /** Managed By Relay Hostname */
  managed_by_relay_hostname?: string | null;
  /** Managed By Relay Label */
  managed_by_relay_label?: string | null;
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
   * Transport Online
   * @default false
   */
  transport_online?: boolean;
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

/** DevicePlatformSessionOut */
export interface DevicePlatformSessionOut {
  /** Id */
  id: string;
  /** Org Id */
  org_id: string;
  /** Device Id */
  device_id: string;
  /** Platform */
  platform: string;
  /** Account Id */
  account_id?: string | null;
  /** State */
  state: string;
  /** State Reason */
  state_reason?: string | null;
  /** Established At */
  established_at?: string | null;
  /** Last Ready At */
  last_ready_at?: string | null;
  /** Last Checked At */
  last_checked_at?: string | null;
  /** Invalidated At */
  invalidated_at?: string | null;
  /** Login Attempt Id */
  login_attempt_id?: string | null;
  /** Establishment Method */
  establishment_method?: string | null;
  /** App Package */
  app_package: string;
  /** App Version */
  app_version?: string | null;
  /** Display Name Observed */
  display_name_observed?: string | null;
  /** Evidence */
  evidence?: Record<string, any>;
  /** Version */
  version: number;
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

/** DeviceTargetGroupOut */
export interface DeviceTargetGroupOut {
  /** Id */
  id: string;
  /** Platform */
  platform: string;
  /** Entity Type */
  entity_type: string;
  /** External Id */
  external_id?: string | null;
  /** Canonical Url */
  canonical_url?: string | null;
  /** Display Name */
  display_name: string;
  /** Status */
  status: string;
}

/** DeviceTargetGroupsOut */
export interface DeviceTargetGroupsOut {
  /** Device Id */
  device_id: string;
  /** Groups */
  groups: DeviceTargetGroupOut[];
  /**
   * Added Count
   * @default 0
   */
  added_count?: number;
  /**
   * Removed Count
   * @default 0
   */
  removed_count?: number;
  /**
   * Unchanged Count
   * @default 0
   */
  unchanged_count?: number;
}

/** DeviceTargetGroupsReplaceIn */
export interface DeviceTargetGroupsReplaceIn {
  /**
   * External Entity Ids
   * @maxItems 500
   */
  external_entity_ids: string[];
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

/** EvaluateAcceptanceCandidateIn */
export interface EvaluateAcceptanceCandidateIn {
  /**
   * Evaluation Key
   * @minLength 8
   * @maxLength 128
   */
  evaluation_key: string;
}

/** EvidenceDownloadOut */
export interface EvidenceDownloadOut {
  /** Url */
  url: string;
  /** Expires At */
  expires_at: string;
  /** Content Type */
  content_type: string;
}

/** EvidenceSummaryOut */
export interface EvidenceSummaryOut {
  /** Id */
  id: string;
  /** Step Path */
  step_path: string;
  /** Step Attempt Index */
  step_attempt_index: number;
  /** Kind */
  kind: string;
  /** Status */
  status: string;
  /**
   * Captured At
   * @format date-time
   */
  captured_at: string;
  /** Capture Error Code */
  capture_error_code: string | null;
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
  /** Account Id */
  account_id?: string | null;
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

/** ExecutionTaskLogDlqOut */
export interface ExecutionTaskLogDlqOut {
  /** Id */
  id: string;
  /** Status */
  status: string;
  /** Device Serial */
  device_serial: string;
  /** Error */
  error?: string | null;
  /** Failed Step Id */
  failed_step_id?: string | null;
  /** Failure Reason */
  failure_reason?: string | null;
  /** Failed At */
  failed_at?: string | null;
  /** Artifact Refs */
  artifact_refs?: Record<string, any>;
  /**
   * Retry Count
   * @default 0
   */
  retry_count?: number;
}

/** ExecutionTaskLogOut */
export interface ExecutionTaskLogOut {
  /** Execution Id */
  execution_id: string;
  /** Status */
  status: string;
  context: ExecutionTraceContextOut;
  summary: ExecutionTaskLogSummaryOut;
  /** Steps */
  steps?: ExecutionTaskLogStepOut[];
  /** Account Actions */
  account_actions?: Record<string, any>[];
  /** Events */
  events?: Record<string, any>[];
  /**
   * Has More Steps
   * @default false
   */
  has_more_steps?: boolean;
  /**
   * Has More Events
   * @default false
   */
  has_more_events?: boolean;
  /** Last Event Id */
  last_event_id?: string | null;
  dlq?: ExecutionTaskLogDlqOut | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /** Started At */
  started_at?: string | null;
  /** Finished At */
  finished_at?: string | null;
}

/** ExecutionTaskLogStepOut */
export interface ExecutionTaskLogStepOut {
  /** Id */
  id: string;
  /** Execution Id */
  execution_id: string;
  /** Device Id */
  device_id?: string | null;
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
  /** Trace */
  trace?: Record<string, any>;
  /** Account Actions */
  account_actions?: Record<string, any>[];
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

/** ExecutionTaskLogSummaryOut */
export interface ExecutionTaskLogSummaryOut {
  /**
   * Total Steps
   * @default 0
   */
  total_steps?: number;
  /**
   * Completed Steps
   * @default 0
   */
  completed_steps?: number;
  /**
   * Failed Steps
   * @default 0
   */
  failed_steps?: number;
  /**
   * Running Steps
   * @default 0
   */
  running_steps?: number;
  /** Current Step Index */
  current_step_index?: number | null;
  /** Counters */
  counters?: Record<string, number>;
}

/** ExecutionTraceContextOut */
export interface ExecutionTraceContextOut {
  /** Org Id */
  org_id?: string | null;
  /** Dispatch Id */
  dispatch_id?: string | null;
  /** Campaign Id */
  campaign_id?: string | null;
  /** Execution Id */
  execution_id: string;
  /** Workflow Id */
  workflow_id?: string | null;
  /** Scenario Id */
  scenario_id?: string | null;
  /** Scenario Version Id */
  scenario_version_id?: string | null;
  /** Scenario Plan */
  scenario_plan?: any[];
  /** Device Id */
  device_id?: string | null;
  /** Device Serial */
  device_serial?: string | null;
  /** Device Name */
  device_name?: string | null;
  /** Account Id */
  account_id?: string | null;
  /** Account Label */
  account_label?: string | null;
  /** Account Platform */
  account_platform?: string | null;
}

/** ExtendServiceCampaignIn */
export interface ExtendServiceCampaignIn {
  /**
   * Order Id
   * @minLength 1
   * @maxLength 64
   */
  order_id: string;
  /**
   * Entitlement Id
   * @minLength 1
   * @maxLength 64
   */
  entitlement_id: string;
  /**
   * Idempotency Key
   * @minLength 8
   * @maxLength 128
   */
  idempotency_key: string;
  /**
   * Added Service Days
   * @exclusiveMin 0
   * @max 365
   */
  added_service_days: number;
  consent: ExtensionConsentIn;
}

/** ExtensionConsentIn */
export interface ExtensionConsentIn {
  /** Accepted */
  accepted: boolean;
  /**
   * Accepted At
   * @format date-time
   */
  accepted_at: string;
  /**
   * Policy Version
   * @minLength 1
   * @maxLength 64
   */
  policy_version: string;
  /**
   * Pricing Version
   * @minLength 1
   * @maxLength 64
   */
  pricing_version: string;
  /**
   * Amount Minor
   * @exclusiveMin 0
   */
  amount_minor: number;
  /**
   * Currency
   * @minLength 3
   * @maxLength 3
   */
  currency: string;
}

/** ExternalEntityBulkObserveIn */
export interface ExternalEntityBulkObserveIn {
  /**
   * Items
   * @maxItems 500
   * @minItems 1
   */
  items: ExternalEntityObserveIn[];
}

/** ExternalEntityBulkObserveOut */
export interface ExternalEntityBulkObserveOut {
  /** Items */
  items: ExternalEntityObserveOut[];
  /** Observed Count */
  observed_count: number;
  /** Created Count */
  created_count: number;
}

/** ExternalEntityListOut */
export interface ExternalEntityListOut {
  /** Items */
  items: ExternalEntityOut[];
  /** Total */
  total: number;
  /** Limit */
  limit: number;
  /** Offset */
  offset: number;
}

/** ExternalEntityObserveIn */
export interface ExternalEntityObserveIn {
  /**
   * Platform
   * @minLength 1
   * @maxLength 32
   */
  platform: string;
  /**
   * Entity Type
   * @minLength 1
   * @maxLength 32
   */
  entity_type: string;
  /**
   * Display Name
   * @minLength 1
   * @maxLength 500
   */
  display_name: string;
  /** External Id */
  external_id?: string | null;
  /** Canonical Url */
  canonical_url?: string | null;
  /**
   * Status
   * @maxLength 24
   * @default "candidate"
   */
  status?: string;
  /** Attributes */
  attributes?: Record<string, any>;
  /** Metrics */
  metrics?: Record<string, any>;
  /** Observed At */
  observed_at?: string | null;
  /** Query */
  query?: string | null;
  /** Rank */
  rank?: number | null;
  /** Discovery Context */
  discovery_context?: Record<string, any>;
  /** Raw Data */
  raw_data?: Record<string, any>;
  /** Account Id */
  account_id?: string | null;
  /** Execution Id */
  execution_id?: string | null;
}

/** ExternalEntityObserveOut */
export interface ExternalEntityObserveOut {
  entity: ExternalEntityOut;
  /** Created */
  created: boolean;
}

/** ExternalEntityOut */
export interface ExternalEntityOut {
  /** Id */
  id: string;
  /** Org Id */
  org_id: string;
  /** Platform */
  platform: string;
  /** Entity Type */
  entity_type: string;
  /** Identity Key */
  identity_key: string;
  /** Identity Confidence */
  identity_confidence: string;
  /** External Id */
  external_id?: string | null;
  /** Canonical Url */
  canonical_url?: string | null;
  /** Display Name */
  display_name: string;
  /** Status */
  status: string;
  /** Current Attributes */
  current_attributes?: Record<string, any>;
  /** Current Metrics */
  current_metrics?: Record<string, any>;
  /**
   * First Seen At
   * @format date-time
   */
  first_seen_at: string;
  /**
   * Last Seen At
   * @format date-time
   */
  last_seen_at: string;
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

/** FarmEventIn */
export interface FarmEventIn {
  /**
   * Schema Version
   * @pattern ^adl-farm-event-v1$
   */
  schema_version: string;
  /**
   * Execution Id
   * @minLength 1
   * @maxLength 36
   */
  execution_id: string;
  /**
   * Source
   * @minLength 1
   * @maxLength 64
   */
  source: string;
  /**
   * Event Id
   * @minLength 1
   * @maxLength 128
   */
  event_id: string;
  /**
   * Event Type
   * @pattern ^(accepted|running|step|assertion|uncertain|blocked|deadline|cancelled|completed)$
   */
  event_type: string;
  /**
   * Occurred At
   * @format date-time
   */
  occurred_at: string;
  /** Sequence */
  sequence?: number | null;
  /** Reason Code */
  reason_code?: string | null;
  /** Assertion Passed */
  assertion_passed?: boolean | null;
  /** Step Path */
  step_path?: string | null;
  /** Step Attempt Index */
  step_attempt_index?: number | null;
  /**
   * Artifact Refs
   * @maxItems 100
   */
  artifact_refs?: string[];
}

/** FarmEventOut */
export interface FarmEventOut {
  /** Event Id */
  event_id: string;
  /** Job Id */
  job_id: string;
  /** Job Status */
  job_status: string;
  /** Verdict */
  verdict: string | null;
  /** Terminal Reason */
  terminal_reason: string | null;
}

/** FarmRunOut */
export interface FarmRunOut {
  /** Job Id */
  job_id: string;
  /** Run Attempt Id */
  run_attempt_id: string;
  /** Execution Id */
  execution_id: string;
  /** Slot Id */
  slot_id: string;
  /** Lane Id */
  lane_id: string;
  /** Device Id */
  device_id: string;
  /** Reservation Id */
  reservation_id: string;
  /** Scenario Version Id */
  scenario_version_id: string;
  /** Scenario Hash */
  scenario_hash: string;
  /** Policy Version */
  policy_version: string;
  /** Schema Version */
  schema_version: string;
  /** Status */
  status: string;
  /** Verdict */
  verdict: string | null;
  /** Terminal Reason */
  terminal_reason: string | null;
  /**
   * Deadline At
   * @format date-time
   */
  deadline_at: string;
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

/** FleetLifecycleOperationOut */
export interface FleetLifecycleOperationOut {
  /** Id */
  id: string;
  /** Service Campaign Id */
  service_campaign_id: string;
  /** Lane Id */
  lane_id: string | null;
  /** Operation Type */
  operation_type: string;
  /** Status */
  status: string;
  /** Checkpoint */
  checkpoint: string;
  /** Old Reservation Id */
  old_reservation_id: string | null;
  /** New Reservation Id */
  new_reservation_id: string | null;
  /** Reason */
  reason: string;
  /** Error Code */
  error_code: string | null;
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

/** FreezeKpiCohortIn */
export interface FreezeKpiCohortIn {
  /**
   * Cohort Key
   * @minLength 1
   * @maxLength 128
   */
  cohort_key: string;
  /** Definition Id */
  definition_id: string;
  /** Source Kind */
  source_kind: string;
  /**
   * Window Start
   * @format date-time
   */
  window_start: string;
  /**
   * Window End
   * @format date-time
   */
  window_end: string;
  /**
   * Timezone
   * @minLength 1
   * @maxLength 64
   */
  timezone: string;
  /**
   * Service Campaign Ids
   * @minItems 1
   */
  service_campaign_ids: string[];
}

/** FunnelEventOut */
export interface FunnelEventOut {
  /** Event Id */
  event_id: string;
  /** Event Name */
  event_name: string;
  /** Source Type */
  source_type: string;
  /** Source Ref */
  source_ref: string | null;
  /** Attribution */
  attribution: Record<string, string>;
  /**
   * Source Occurred At
   * @format date-time
   */
  source_occurred_at: string;
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

/** IssueListOut */
export interface IssueListOut {
  /** Items */
  items: IssueSummaryOut[];
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
}

/** IssueSummaryOut */
export interface IssueSummaryOut {
  /** Id */
  id: string;
  /** Source Attempt Id */
  source_attempt_id: string;
  /** Source Build Id */
  source_build_id: string;
  /** Source Scenario Version Id */
  source_scenario_version_id: string;
  /** Severity */
  severity: string;
  /** Assertion Key */
  assertion_key: string;
  /** Expected */
  expected: string;
  /** Actual */
  actual: string;
  /** Reproduction */
  reproduction: Record<string, any>;
  /** Fingerprint */
  fingerprint: string;
  /** Status */
  status: string;
  /**
   * Retest Count
   * @default 0
   */
  retest_count?: number;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
}

/** KeyRequest */
export interface KeyRequest {
  /** Key */
  key: string;
}

/** KpiAssistanceOut */
export interface KpiAssistanceOut {
  /** Id */
  id: string;
  /** Event Id */
  event_id: string;
  /** Service Campaign Id */
  service_campaign_id: string;
  /** Actor Id */
  actor_id: string;
  /** Assistance Type */
  assistance_type: string;
  /** Classification */
  classification: string;
  /** Reason */
  reason: string;
  /**
   * Occurred At
   * @format date-time
   */
  occurred_at: string;
}

/** KpiCohortOut */
export interface KpiCohortOut {
  /** Id */
  id: string;
  /** Cohort Key */
  cohort_key: string;
  /** Definition Id */
  definition_id: string;
  /** Source Kind */
  source_kind: string;
  /**
   * Window Start
   * @format date-time
   */
  window_start: string;
  /**
   * Window End
   * @format date-time
   */
  window_end: string;
  /** Timezone */
  timezone: string;
  /** Status */
  status: string;
  /** Frozen At */
  frozen_at: string | null;
}

/** KpiDefinitionOut */
export interface KpiDefinitionOut {
  /** Id */
  id: string;
  /** Version */
  version: string;
  /** Definitions */
  definitions: Record<string, any>;
  /** Status */
  status: string;
  /** Signed By */
  signed_by: string | null;
  /** Signed At */
  signed_at: string | null;
}

/** KpiSnapshotOut */
export interface KpiSnapshotOut {
  /** Id */
  id: string;
  /** Cohort Id */
  cohort_id: string;
  /** Query Version */
  query_version: string;
  /** Source Kind */
  source_kind: string;
  /** Result Status */
  result_status: string;
  /** Self Serve Numerator */
  self_serve_numerator: number;
  /** Self Serve Denominator */
  self_serve_denominator: number;
  /** Trace Numerator */
  trace_numerator: number;
  /** Trace Denominator */
  trace_denominator: number;
  /** Details */
  details: Record<string, any>;
  /**
   * Data Freshness At
   * @format date-time
   */
  data_freshness_at: string;
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

/** ManagedAgentConnectBody */
export interface ManagedAgentConnectBody {
  /** Wsbaseurl */
  wsBaseUrl?: string | null;
}

/** MaterializeSlotsOut */
export interface MaterializeSlotsOut {
  /** Service Campaign Id */
  service_campaign_id: string;
  /** Slot Count */
  slot_count: number;
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

/** NotificationChannelTestRequest */
export interface NotificationChannelTestRequest {
  /**
   * Type
   * @pattern ^(in_app|telegram|webhook|email|slack)$
   */
  type: string;
  /** Config */
  config?: Record<string, any>;
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
  /** Requirements */
  requirements?: Record<string, any> | null;
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
  /** Requirements */
  requirements?: Record<string, any> | null;
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

/** ParticipationListOut */
export interface ParticipationListOut {
  /** Items */
  items: ParticipationSummaryOut[];
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
}

/** ParticipationRecordOut */
export interface ParticipationRecordOut {
  participation: ParticipationSummaryOut;
  /** Event Id */
  event_id: string;
  /** Event Type */
  event_type: string;
  /** Review State */
  review_state: string;
  /**
   * Observed At
   * @format date-time
   */
  observed_at: string;
}

/** ParticipationSummaryOut */
export interface ParticipationSummaryOut {
  /** Id */
  id: string;
  /** Masked Label */
  masked_label: string;
  /** Track Name */
  track_name: string;
  /** Current Status */
  current_status: string;
  /** Evidence Grade */
  evidence_grade: string;
  /** Active Segment No */
  active_segment_no: number;
  /** Last Observed At */
  last_observed_at: string | null;
  /** Gap Reason */
  gap_reason: string | null;
}

/** PaymentReconciliationListOut */
export interface PaymentReconciliationListOut {
  /** Items */
  items: PaymentReconciliationOut[];
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
}

/** PaymentReconciliationOut */
export interface PaymentReconciliationOut {
  /** Id */
  id: string;
  /** Order Id */
  order_id: string;
  /** Provider */
  provider: string;
  /** Reason Code */
  reason_code: string;
  /** Status */
  status: string;
  /** Attempts */
  attempts: number;
  /** Last Error Code */
  last_error_code: string | null;
  /**
   * Available At
   * @format date-time
   */
  available_at: string;
  /** Resolved At */
  resolved_at: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
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

/** ReadinessCheckOut */
export interface ReadinessCheckOut {
  /** Key */
  key: string;
  /** Status */
  status: string;
  /** Required */
  required: boolean;
  /** Reason Code */
  reason_code: string;
  /**
   * Observed At
   * @format date-time
   */
  observed_at: string;
  /** Source Type */
  source_type: string;
  /** Source Ref */
  source_ref: string | null;
  /** Source Version */
  source_version: string | null;
  /** Owner */
  owner: string;
  /** Next Action */
  next_action: string | null;
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

/** RecordKpiAssistanceIn */
export interface RecordKpiAssistanceIn {
  /**
   * Event Id
   * @minLength 1
   * @maxLength 128
   */
  event_id: string;
  /** Service Campaign Id */
  service_campaign_id: string;
  /**
   * Assistance Type
   * @minLength 1
   * @maxLength 64
   */
  assistance_type: string;
  /** Classification */
  classification: string;
  /**
   * Reason
   * @minLength 3
   * @maxLength 1000
   */
  reason: string;
  /**
   * Occurred At
   * @format date-time
   */
  occurred_at: string;
}

/** RecordParticipationIn */
export interface RecordParticipationIn {
  /**
   * Pseudonymous Account Ref
   * @minLength 1
   * @maxLength 128
   */
  pseudonymous_account_ref: string;
  /**
   * Masked Label
   * @minLength 1
   * @maxLength 128
   */
  masked_label: string;
  /**
   * Track Name
   * @minLength 1
   * @maxLength 64
   */
  track_name: string;
  /**
   * Event Type
   * @pattern ^(invited|opted_in|installed|opened|lost|rejoined|unknown|corrected)$
   */
  event_type: string;
  /**
   * Source Type
   * @minLength 1
   * @maxLength 32
   */
  source_type: string;
  /** Source Ref */
  source_ref?: string | null;
  /** Evidence Ref */
  evidence_ref?: string | null;
  /**
   * Evidence Grade
   * @pattern ^(none|self_attested|operator_attested|provider_verified)$
   */
  evidence_grade: string;
  /**
   * Observed At
   * @format date-time
   */
  observed_at: string;
  /**
   * Approve
   * @default false
   */
  approve?: boolean;
  /** Correction Of Id */
  correction_of_id?: string | null;
  /** Limitations */
  limitations?: string | null;
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

/** RegisterRelayDeviceItemOut */
export interface RegisterRelayDeviceItemOut {
  /** Serial */
  serial: string;
  /** Status */
  status: string;
  /** Device Id */
  device_id?: string | null;
  /** Name */
  name?: string | null;
  /** Message */
  message?: string | null;
}

/** RegisterRelayDevicesBody */
export interface RegisterRelayDevicesBody {
  /** Serials */
  serials?: string[];
}

/** RegisterRelayDevicesOut */
export interface RegisterRelayDevicesOut {
  /** Results */
  results: RegisterRelayDeviceItemOut[];
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
  /**
   * Name
   * @default ""
   */
  name?: string;
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
  /** Device Connections */
  device_connections?: Record<string, RelayDeviceConnectionOut>;
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

/** RelayDeviceConnectionOut */
export interface RelayDeviceConnectionOut {
  /**
   * Registered
   * @default false
   */
  registered?: boolean;
  /** Device Id */
  device_id?: string | null;
  /**
   * Device Agent Connected
   * @default false
   */
  device_agent_connected?: boolean;
}

/** ReorderScenariosBody */
export interface ReorderScenariosBody {
  /** Ordered Ids */
  ordered_ids: string[];
  /** Scenario Id */
  scenario_id?: string | null;
}

/** ReplaceLaneDeviceIn */
export interface ReplaceLaneDeviceIn {
  /**
   * New Device Id
   * @minLength 1
   * @maxLength 64
   */
  new_device_id: string;
  /**
   * Idempotency Key
   * @minLength 8
   * @maxLength 128
   */
  idempotency_key: string;
  /**
   * Reason
   * @minLength 3
   * @maxLength 1000
   */
  reason: string;
}

/** ReportDownloadOut */
export interface ReportDownloadOut {
  /** Url */
  url: string;
  /** Expires At */
  expires_at: string;
  /** Content Type */
  content_type: string;
}

/** ReportListOut */
export interface ReportListOut {
  /** Items */
  items: ReportSummaryOut[];
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
}

/** ReportSummaryOut */
export interface ReportSummaryOut {
  /** Id */
  id: string;
  /** Version */
  version: number;
  /** Schema Version */
  schema_version: string;
  /**
   * Cutoff At
   * @format date-time
   */
  cutoff_at: string;
  /** Builder Version */
  builder_version: string;
  /** Summary */
  summary: Record<string, any>;
  /** Manifest Sha256 */
  manifest_sha256: string;
  /** Status */
  status: string;
  /** Download Available */
  download_available: boolean;
  /** Pdf Sha256 */
  pdf_sha256: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
}

/** RequestRetestIn */
export interface RequestRetestIn {
  /**
   * Target Build Id
   * @minLength 1
   * @maxLength 64
   */
  target_build_id: string;
  /**
   * Target Scenario Version Id
   * @minLength 1
   * @maxLength 64
   */
  target_scenario_version_id: string;
  /**
   * Lane Scope
   * @maxItems 12
   * @minItems 1
   */
  lane_scope: string[];
  /**
   * Idempotency Key
   * @minLength 8
   * @maxLength 128
   */
  idempotency_key: string;
  /** Consent */
  consent: Record<string, any>;
}

/** ReservationSummaryOut */
export interface ReservationSummaryOut {
  /** Id */
  id: string;
  /** State */
  state: string;
  /**
   * Starts At
   * @format date-time
   */
  starts_at: string;
  /**
   * Ends At
   * @format date-time
   */
  ends_at: string;
  /** Released At */
  released_at: string | null;
}

/** RetestRequestOut */
export interface RetestRequestOut {
  /** Id */
  id: string;
  /** Issue Id */
  issue_id: string;
  /** Source Attempt Id */
  source_attempt_id: string;
  /** Target Build Id */
  target_build_id: string;
  /** Target Scenario Version Id */
  target_scenario_version_id: string;
  /** Lane Scope */
  lane_scope: string[];
  /** Status */
  status: string;
  /** New Attempt Id */
  new_attempt_id: string | null;
  /** Verdict */
  verdict: string | null;
  /** Verdict Reason */
  verdict_reason: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
}

/** RoundRobinBody */
export interface RoundRobinBody {
  /** Account Ids */
  account_ids: string[];
  /** Device Ids */
  device_ids: string[];
}

/** RunAttemptSummaryOut */
export interface RunAttemptSummaryOut {
  /** Id */
  id: string;
  /** Attempt No */
  attempt_no: number;
  /** Status */
  status: string;
  /** Outcome */
  outcome: string | null;
  /** Observed Build */
  observed_build: Record<string, any>;
  /** Failure Reason */
  failure_reason: string | null;
  /** Started At */
  started_at: string | null;
  /** Finished At */
  finished_at: string | null;
  /** Evidence */
  evidence: EvidenceSummaryOut[];
}

/** RunSlotDetailOut */
export interface RunSlotDetailOut {
  /** Id */
  id: string;
  /** Service Day */
  service_day: number;
  /**
   * Planned At
   * @format date-time
   */
  planned_at: string;
  /** Execution Status */
  execution_status: string;
  /** App Verdict */
  app_verdict: string | null;
  /** Play Participation State */
  play_participation_state: string;
  /** Attempts */
  attempts: RunAttemptSummaryOut[];
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
  /** Content Type */
  content_type: string;
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

/** SaveWizardDraftIn */
export interface SaveWizardDraftIn {
  /**
   * Expected Revision
   * @min 0
   */
  expected_revision: number;
  /**
   * Package Name
   * @minLength 3
   * @maxLength 255
   */
  package_name: string;
  /**
   * Closed Track Link
   * @minLength 8
   * @maxLength 4000
   */
  closed_track_link: string;
  /**
   * Test Goal
   * @minLength 1
   * @maxLength 8000
   */
  test_goal: string;
  /** Test Environment */
  test_environment?: Record<string, any>;
  build: WizardDraftBuildIn;
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
   * Requirements
   * @default {}
   */
  requirements?: Record<string, any>;
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
  /**
   * Requirements
   * @default {}
   */
  requirements?: Record<string, any>;
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
   * Persist Account Login Execution
   * @default false
   */
  persist_account_login_execution?: boolean;
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
  /** Requirements */
  requirements?: Record<string, any> | null;
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
   * @pattern ^(campaign|template|org_scenario|fleet)$
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
   * Device Serials
   * @maxItems 500
   */
  device_serials?: string[];
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
  /** Device Serials */
  device_serials: string[];
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
  /** Device Serials */
  device_serials?: string[] | null;
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
   * @pattern ^(campaign|template|org_scenario|fleet)$
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
  /** Viewer Id */
  viewer_id?: string | null;
  /** Profile */
  profile?: string | null;
  /** Max Fps */
  max_fps?: number | null;
  /** Max Width */
  max_width?: number | null;
  /** Bitrate */
  bitrate?: number | null;
}

/** ScrcpyDetachRequest */
export interface ScrcpyDetachRequest {
  /** Viewer Id */
  viewer_id?: string | null;
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

/** ServiceCampaignCreateIn */
export interface ServiceCampaignCreateIn {
  /**
   * Creation Intent Key
   * @minLength 8
   * @maxLength 128
   */
  creation_intent_key: string;
  /** Runtime Campaign Id */
  runtime_campaign_id: string;
  /**
   * Package Name
   * @minLength 3
   * @maxLength 255
   */
  package_name: string;
  /**
   * Timezone
   * @minLength 1
   * @maxLength 64
   */
  timezone: string;
  /**
   * Plan Version
   * @minLength 1
   * @maxLength 64
   */
  plan_version: string;
  /**
   * Acquisition Events
   * @maxItems 2
   */
  acquisition_events?: ClientFunnelEventIn[];
}

/** ServiceCampaignOut */
export interface ServiceCampaignOut {
  /** Id */
  id: string;
  /** Runtime Campaign Id */
  runtime_campaign_id: string;
  /** Package Name */
  package_name: string;
  /** Timezone */
  timezone: string;
  /** Plan Version */
  plan_version: string;
  /** Status */
  status: string;
  /** Lane Count */
  lane_count: number;
  /** Started At */
  started_at: string | null;
  /** End At */
  end_at: string | null;
}

/** ServiceExtensionOut */
export interface ServiceExtensionOut {
  /** Id */
  id: string;
  /** Service Campaign Id */
  service_campaign_id: string;
  /**
   * Previous End At
   * @format date-time
   */
  previous_end_at: string;
  /**
   * New End At
   * @format date-time
   */
  new_end_at: string;
  /** Added Service Days */
  added_service_days: number;
  /** Order Id */
  order_id: string;
  /** Entitlement Id */
  entitlement_id: string;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
}

/** ServiceLaneDetailOut */
export interface ServiceLaneDetailOut {
  /** Id */
  id: string;
  /** Ordinal */
  ordinal: number;
  /** Tester Label */
  tester_label: string;
  /** Reservations */
  reservations: ReservationSummaryOut[];
  /** Slots */
  slots: RunSlotDetailOut[];
  /** Slot Total */
  slot_total: number;
  /** Slot Offset */
  slot_offset: number;
  /** Slot Limit */
  slot_limit: number;
}

/** ServiceLaneListOut */
export interface ServiceLaneListOut {
  /** Items */
  items: ServiceLaneSummaryOut[];
  /** Total */
  total: number;
  /** Offset */
  offset: number;
  /** Limit */
  limit: number;
}

/** ServiceLaneSummaryOut */
export interface ServiceLaneSummaryOut {
  /** Id */
  id: string;
  /** Ordinal */
  ordinal: number;
  /** Tester Label */
  tester_label: string;
  /** Planned Slots */
  planned_slots: number;
  /** Terminal Slots */
  terminal_slots: number;
  /** Active Reservation Count */
  active_reservation_count: number;
}

/** ServiceProgressOut */
export interface ServiceProgressOut {
  /** Service */
  service: Record<string, number | string>;
  /** App Quality */
  app_quality: Record<string, number>;
  /** Play Participation */
  play_participation: Record<string, number>;
}

/** SessionDescription */
export interface SessionDescription {
  /**
   * Type
   * @pattern ^offer$
   */
  type: string;
  /**
   * Sdp
   * @minLength 1
   */
  sdp: string;
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

/** SignKpiDefinitionIn */
export interface SignKpiDefinitionIn {
  /**
   * Version
   * @minLength 1
   * @maxLength 64
   */
  version: string;
  /** Definitions */
  definitions: Record<string, string>;
}

/** StartCampaignIn */
export interface StartCampaignIn {
  /**
   * Idempotency Key
   * @minLength 8
   * @maxLength 128
   */
  idempotency_key: string;
}

/** StartCampaignOut */
export interface StartCampaignOut {
  /** Started */
  started: boolean;
  /** Campaign Status */
  campaign_status: string;
  /** Started At */
  started_at: string | null;
  /** Readiness Revision */
  readiness_revision: number;
  /** Readiness Status */
  readiness_status: string;
  /** Intent Id */
  intent_id: string | null;
  /** Checks */
  checks: ReadinessCheckOut[];
}

/** StartSessionRequest */
export interface StartSessionRequest {
  /** Device Id */
  device_id: string;
  /** User Id */
  user_id?: string | null;
}

/** StartWizardCheckoutIn */
export interface StartWizardCheckoutIn {
  /**
   * Approval Id
   * @minLength 1
   * @maxLength 36
   */
  approval_id: string;
  /**
   * Idempotency Key
   * @minLength 8
   * @maxLength 128
   */
  idempotency_key: string;
}

/** StartWizardGenerationIn */
export interface StartWizardGenerationIn {
  /**
   * Operation Id
   * @minLength 8
   * @maxLength 128
   */
  operation_id: string;
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
  /**
   * Cancelled
   * @default 0
   */
  cancelled?: number;
  /**
   * Total Device Runs
   * @default 0
   */
  total_device_runs?: number;
  /** Total Content Items */
  total_content_items: number;
  /** Latest Dispatch Id */
  latest_dispatch_id?: string | null;
  /**
   * Latest Dispatch Target Count
   * @default 0
   */
  latest_dispatch_target_count?: number;
  /**
   * Latest Dispatch Finished Count
   * @default 0
   */
  latest_dispatch_finished_count?: number;
  /**
   * Latest Dispatch Running Count
   * @default 0
   */
  latest_dispatch_running_count?: number;
  /**
   * Latest Dispatch Pending Count
   * @default 0
   */
  latest_dispatch_pending_count?: number;
  /**
   * Latest Dispatch Failed Count
   * @default 0
   */
  latest_dispatch_failed_count?: number;
  /**
   * Latest Dispatch Workflow Started Count
   * @default 0
   */
  latest_dispatch_workflow_started_count?: number;
  /**
   * Latest Dispatch Fallback Count
   * @default 0
   */
  latest_dispatch_fallback_count?: number;
  /** Latest Dispatch Created At */
  latest_dispatch_created_at?: string | null;
  /** Latest Dispatch First Started At */
  latest_dispatch_first_started_at?: string | null;
  /** Latest Dispatch Latest Finished At */
  latest_dispatch_latest_finished_at?: string | null;
  /** Latest Dispatch Elapsed Ms */
  latest_dispatch_elapsed_ms?: number | null;
  /** Latest Dispatch Terminal Ms */
  latest_dispatch_terminal_ms?: number | null;
  /** Latest Dispatch To First Start Ms */
  latest_dispatch_to_first_start_ms?: number | null;
  /** Latest Dispatch To Start P95 Ms */
  latest_dispatch_to_start_p95_ms?: number | null;
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

/** WebRTCSessionCreate */
export interface WebRTCSessionCreate {
  /**
   * Serial
   * @minLength 1
   */
  serial: string;
  /**
   * Viewer Id
   * @minLength 1
   */
  viewer_id: string;
  /**
   * Ttl Seconds
   * @min 1
   * @max 1800
   * @default 300
   */
  ttl_seconds?: number;
  /** Control */
  control?: boolean | null;
  /** Profile */
  profile?: string | null;
  /** Max Fps */
  max_fps?: number | null;
  /** Max Width */
  max_width?: number | null;
  /** Bitrate */
  bitrate?: number | null;
}

/** WebRTCSessionHeartbeat */
export interface WebRTCSessionHeartbeat {
  /**
   * Ttl Seconds
   * @min 1
   * @max 1800
   * @default 300
   */
  ttl_seconds?: number;
}

/** WizardApprovalOut */
export interface WizardApprovalOut {
  /** Id */
  id: string;
  /** Scenario Version Id */
  scenario_version_id: string;
  /** Content Hash */
  content_hash: string;
  /** Policy Version */
  policy_version: string;
  /** Assertions */
  assertions: Record<string, any>[];
  /** Allowed Operations */
  allowed_operations: string[];
  /**
   * Approved At
   * @format date-time
   */
  approved_at: string;
}

/** WizardCheckoutOut */
export interface WizardCheckoutOut {
  /** Order Id */
  order_id: string;
  /** Intent Id */
  intent_id: string;
  /** Status */
  status: string;
  /** Checkout Url */
  checkout_url: string | null;
  /** Expires At */
  expires_at: string | null;
  /** Blocker Code */
  blocker_code: string | null;
}

/** WizardDraftBuildIn */
export interface WizardDraftBuildIn {
  /**
   * Version Name
   * @minLength 1
   * @maxLength 128
   */
  version_name: string;
  /**
   * Version Code
   * @minLength 1
   * @maxLength 64
   */
  version_code: string;
  /**
   * Source Kind
   * @pattern ^(closed_track|uploaded_artifact)$
   */
  source_kind: string;
  /** Source Ref */
  source_ref?: string | null;
  /** Checksum Sha256 */
  checksum_sha256?: string | null;
}

/** WizardGenerationOut */
export interface WizardGenerationOut {
  /** Operation Id */
  operation_id: string;
  /** Status */
  status: string;
  /** Error Code */
  error_code: string | null;
  /** Scenario Version Id */
  scenario_version_id: string | null;
  /** Content Hash */
  content_hash: string | null;
  /** Scenario */
  scenario: Record<string, any> | null;
}

/** WizardIntakeOut */
export interface WizardIntakeOut {
  /** Id */
  id: string;
  /** Revision */
  revision: number;
  /** Input Version */
  input_version: number;
  /** Package Name */
  package_name: string;
  /** Closed Track Link */
  closed_track_link: string;
  /** Test Goal */
  test_goal: string;
  /** Test Environment */
  test_environment: Record<string, any>;
  /** Status */
  status: string;
  /** Build */
  build: Record<string, any>;
}

/** WizardPaymentOut */
export interface WizardPaymentOut {
  /** Provider Configured */
  provider_configured: boolean;
  /** Provider */
  provider: string | null;
  /** Amount Minor */
  amount_minor: number | null;
  /** Currency */
  currency: string | null;
  /** Pricing Version */
  pricing_version: string | null;
  /** Policy Version */
  policy_version: string;
  /** Quota */
  quota: Record<string, number>;
  /** Blocker Code */
  blocker_code: string | null;
  /** Order */
  order: Record<string, any> | null;
  /** Checkout Status */
  checkout_status: string | null;
  /** Checkout Expires At */
  checkout_expires_at: string | null;
  /** Checkout Error Code */
  checkout_error_code: string | null;
  /** Entitlement */
  entitlement: Record<string, any> | null;
}

/** WizardStateOut */
export interface WizardStateOut {
  campaign: ServiceCampaignOut;
  /** Current Step */
  current_step: string;
  intake: WizardIntakeOut | null;
  generation: WizardGenerationOut | null;
  approval: WizardApprovalOut | null;
  payment: WizardPaymentOut;
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
  /** Defaultorgid */
  defaultOrgId?: string | null;
  /**
   * Mustchangepassword
   * @default false
   */
  mustChangePassword?: boolean;
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
     * No description
     *
     * @tags admin
     * @name AdminListAdminUsersApiAdminWorkspaceAdminsGet
     * @summary Admin List Admin Users
     * @request GET:/api/admin/workspace-admins
     * @secure
     */
    adminListAdminUsersApiAdminWorkspaceAdminsGet: (
      query?: {
        /** Search */
        search?: string | null;
        /** Status */
        status?: string | null;
        /** Workspaceid */
        workspaceId?: string | null;
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
      },
      params: RequestParams = {},
    ) =>
      this.request<AdminUserListOut, HTTPValidationError>({
        path: `/api/admin/workspace-admins`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminCreateAdminUserApiAdminWorkspaceAdminsPost
     * @summary Admin Create Admin User
     * @request POST:/api/admin/workspace-admins
     * @secure
     */
    adminCreateAdminUserApiAdminWorkspaceAdminsPost: (
      data: AdminUserCreate,
      params: RequestParams = {},
    ) =>
      this.request<AdminUserCreated, HTTPValidationError>({
        path: `/api/admin/workspace-admins`,
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
     * @name AdminListAccountsApiAdminAccountsGet
     * @summary Admin List Accounts
     * @request GET:/api/admin/accounts
     * @secure
     */
    adminListAccountsApiAdminAccountsGet: (
      query?: {
        /** Search */
        search?: string | null;
        /** Platform */
        platform?: string | null;
        /** Status */
        status?: string | null;
        /** State */
        state?: string | null;
        /** Workspaceid */
        workspaceId?: string | null;
        /**
         * Offset
         * @min 0
         * @default 0
         */
        offset?: number;
        /**
         * Limit
         * @min 1
         * @max 200
         * @default 50
         */
        limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<AdminAccountListOut, HTTPValidationError>({
        path: `/api/admin/accounts`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminListContentApiAdminContentGet
     * @summary Admin List Content
     * @request GET:/api/admin/content
     * @secure
     */
    adminListContentApiAdminContentGet: (
      query?: {
        /** Search */
        search?: string | null;
        /** Collection */
        collection?: string | null;
        /** Platform */
        platform?: string | null;
        /** Content Type */
        content_type?: string | null;
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
        /** Workspaceid */
        workspaceId?: string | null;
        /**
         * Offset
         * @min 0
         * @default 0
         */
        offset?: number;
        /**
         * Limit
         * @min 1
         * @max 500
         * @default 50
         */
        limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<AdminContentListOut, HTTPValidationError>({
        path: `/api/admin/content`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminUpdateAdminUserApiAdminWorkspaceAdminsAdminUserIdPatch
     * @summary Admin Update Admin User
     * @request PATCH:/api/admin/workspace-admins/{admin_user_id}
     * @secure
     */
    adminUpdateAdminUserApiAdminWorkspaceAdminsAdminUserIdPatch: (
      adminUserId: string,
      data: AdminUserUpdate,
      params: RequestParams = {},
    ) =>
      this.request<AdminUserOut, HTTPValidationError>({
        path: `/api/admin/workspace-admins/${adminUserId}`,
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
     * @tags admin
     * @name AdminResetWorkspaceAdminPasswordApiAdminWorkspaceAdminsAdminUserIdResetPasswordPost
     * @summary Admin Reset Workspace Admin Password
     * @request POST:/api/admin/workspace-admins/{admin_user_id}/reset-password
     * @secure
     */
    adminResetWorkspaceAdminPasswordApiAdminWorkspaceAdminsAdminUserIdResetPasswordPost:
      (
        adminUserId: string,
        data: AdminOwnerPasswordReset,
        params: RequestParams = {},
      ) =>
        this.request<AdminUserPasswordResetOut, HTTPValidationError>({
          path: `/api/admin/workspace-admins/${adminUserId}/reset-password`,
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
     * @name AdminBulkAssignWorkspaceAdminApiAdminWorkspaceAdminsAdminUserIdWorkspacesPost
     * @summary Admin Bulk Assign Workspace Admin
     * @request POST:/api/admin/workspace-admins/{admin_user_id}/workspaces
     * @secure
     */
    adminBulkAssignWorkspaceAdminApiAdminWorkspaceAdminsAdminUserIdWorkspacesPost:
      (
        adminUserId: string,
        data: AdminUserWorkspaceBulkUpdate,
        params: RequestParams = {},
      ) =>
        this.request<AdminUserWorkspaceBulkOut, HTTPValidationError>({
          path: `/api/admin/workspace-admins/${adminUserId}/workspaces`,
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
     * @name AdminBulkRemoveWorkspaceAdminApiAdminWorkspaceAdminsAdminUserIdWorkspacesRemovePost
     * @summary Admin Bulk Remove Workspace Admin
     * @request POST:/api/admin/workspace-admins/{admin_user_id}/workspaces/remove
     * @secure
     */
    adminBulkRemoveWorkspaceAdminApiAdminWorkspaceAdminsAdminUserIdWorkspacesRemovePost:
      (
        adminUserId: string,
        data: AdminUserWorkspaceBulkUpdate,
        params: RequestParams = {},
      ) =>
        this.request<AdminUserWorkspaceBulkOut, HTTPValidationError>({
          path: `/api/admin/workspace-admins/${adminUserId}/workspaces/remove`,
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
     * @name AdminWorkspaceSummaryApiAdminDashboardSummaryGet
     * @summary Admin Workspace Summary
     * @request GET:/api/admin/dashboard/summary
     * @secure
     */
    adminWorkspaceSummaryApiAdminDashboardSummaryGet: (
      query?: {
        /** Workspaceid */
        workspaceId?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<AdminDashboardSummaryOut, HTTPValidationError>({
        path: `/api/admin/dashboard/summary`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminListWorkspacesApiAdminWorkspacesGet
     * @summary Admin List Workspaces
     * @request GET:/api/admin/workspaces
     * @secure
     */
    adminListWorkspacesApiAdminWorkspacesGet: (
      query?: {
        /** Search */
        search?: string | null;
        /** Status */
        status?: string | null;
        /** Workspaceid */
        workspaceId?: string | null;
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
      },
      params: RequestParams = {},
    ) =>
      this.request<AdminWorkspaceListOut, HTTPValidationError>({
        path: `/api/admin/workspaces`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminCreateWorkspaceApiAdminWorkspacesPost
     * @summary Admin Create Workspace
     * @request POST:/api/admin/workspaces
     * @secure
     */
    adminCreateWorkspaceApiAdminWorkspacesPost: (
      data: AdminWorkspaceCreate,
      params: RequestParams = {},
    ) =>
      this.request<AdminWorkspaceCreated, HTTPValidationError>({
        path: `/api/admin/workspaces`,
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
     * @name AdminListAssignableWorkspacesApiAdminWorkspacesAssignableGet
     * @summary Admin List Assignable Workspaces
     * @request GET:/api/admin/workspaces/assignable
     * @secure
     */
    adminListAssignableWorkspacesApiAdminWorkspacesAssignableGet: (
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
         * @max 200
         * @default 100
         */
        limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<AdminAssignableWorkspaceListOut, HTTPValidationError>({
        path: `/api/admin/workspaces/assignable`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminGetWorkspaceApiAdminWorkspacesWorkspaceIdGet
     * @summary Admin Get Workspace
     * @request GET:/api/admin/workspaces/{workspace_id}
     * @secure
     */
    adminGetWorkspaceApiAdminWorkspacesWorkspaceIdGet: (
      workspaceId: string,
      params: RequestParams = {},
    ) =>
      this.request<AdminWorkspaceOut, HTTPValidationError>({
        path: `/api/admin/workspaces/${workspaceId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminUpdateWorkspaceApiAdminWorkspacesWorkspaceIdPatch
     * @summary Admin Update Workspace
     * @request PATCH:/api/admin/workspaces/{workspace_id}
     * @secure
     */
    adminUpdateWorkspaceApiAdminWorkspacesWorkspaceIdPatch: (
      workspaceId: string,
      data: AdminWorkspaceUpdate,
      params: RequestParams = {},
    ) =>
      this.request<AdminWorkspaceOut, HTTPValidationError>({
        path: `/api/admin/workspaces/${workspaceId}`,
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
     * @tags admin
     * @name AdminDeleteWorkspaceApiAdminWorkspacesWorkspaceIdDelete
     * @summary Admin Delete Workspace
     * @request DELETE:/api/admin/workspaces/{workspace_id}
     * @secure
     */
    adminDeleteWorkspaceApiAdminWorkspacesWorkspaceIdDelete: (
      workspaceId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/admin/workspaces/${workspaceId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminWorkspaceDependenciesApiAdminWorkspacesWorkspaceIdDependenciesGet
     * @summary Admin Workspace Dependencies
     * @request GET:/api/admin/workspaces/{workspace_id}/dependencies
     * @secure
     */
    adminWorkspaceDependenciesApiAdminWorkspacesWorkspaceIdDependenciesGet: (
      workspaceId: string,
      params: RequestParams = {},
    ) =>
      this.request<AdminWorkspaceDependenciesOut, HTTPValidationError>({
        path: `/api/admin/workspaces/${workspaceId}/dependencies`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Members and admins for one workspace, or for every visible workspace.
     *
     * @tags admin
     * @name AdminWorkspaceAccessApiAdminWorkspaceAccessGet
     * @summary Admin Workspace Access
     * @request GET:/api/admin/workspace-access
     * @secure
     */
    adminWorkspaceAccessApiAdminWorkspaceAccessGet: (
      query?: {
        /** Workspaceid */
        workspaceId?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<AdminWorkspaceAccessOut, HTTPValidationError>({
        path: `/api/admin/workspace-access`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminListWorkspaceAdminsApiAdminWorkspacesWorkspaceIdAdminsGet
     * @summary Admin List Workspace Admins
     * @request GET:/api/admin/workspaces/{workspace_id}/admins
     * @secure
     */
    adminListWorkspaceAdminsApiAdminWorkspacesWorkspaceIdAdminsGet: (
      workspaceId: string,
      params: RequestParams = {},
    ) =>
      this.request<AdminWorkspaceAdminOut[], HTTPValidationError>({
        path: `/api/admin/workspaces/${workspaceId}/admins`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminAssignWorkspaceAdminApiAdminWorkspacesWorkspaceIdAdminsPost
     * @summary Admin Assign Workspace Admin
     * @request POST:/api/admin/workspaces/{workspace_id}/admins
     * @secure
     */
    adminAssignWorkspaceAdminApiAdminWorkspacesWorkspaceIdAdminsPost: (
      workspaceId: string,
      data: AdminWorkspaceAdminAssign,
      params: RequestParams = {},
    ) =>
      this.request<AdminWorkspaceAdminOut, HTTPValidationError>({
        path: `/api/admin/workspaces/${workspaceId}/admins`,
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
     * @name AdminListWorkspaceMembersApiAdminWorkspacesWorkspaceIdMembersGet
     * @summary Admin List Workspace Members
     * @request GET:/api/admin/workspaces/{workspace_id}/members
     * @secure
     */
    adminListWorkspaceMembersApiAdminWorkspacesWorkspaceIdMembersGet: (
      workspaceId: string,
      params: RequestParams = {},
    ) =>
      this.request<OrganizationMemberOut[], HTTPValidationError>({
        path: `/api/admin/workspaces/${workspaceId}/members`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminInviteWorkspaceMemberApiAdminWorkspacesWorkspaceIdMembersPost
     * @summary Admin Invite Workspace Member
     * @request POST:/api/admin/workspaces/{workspace_id}/members
     * @secure
     */
    adminInviteWorkspaceMemberApiAdminWorkspacesWorkspaceIdMembersPost: (
      workspaceId: string,
      data: OrganizationMemberInvite,
      params: RequestParams = {},
    ) =>
      this.request<OrganizationMemberInviteOut, HTTPValidationError>({
        path: `/api/admin/workspaces/${workspaceId}/members`,
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
     * @name AdminUpdateWorkspaceMemberApiAdminWorkspacesWorkspaceIdMembersMemberUserIdPatch
     * @summary Admin Update Workspace Member
     * @request PATCH:/api/admin/workspaces/{workspace_id}/members/{member_user_id}
     * @secure
     */
    adminUpdateWorkspaceMemberApiAdminWorkspacesWorkspaceIdMembersMemberUserIdPatch:
      (
        workspaceId: string,
        memberUserId: string,
        data: OrganizationMemberUpdate,
        params: RequestParams = {},
      ) =>
        this.request<OrganizationMemberOut, HTTPValidationError>({
          path: `/api/admin/workspaces/${workspaceId}/members/${memberUserId}`,
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
     * @tags admin
     * @name AdminRemoveWorkspaceMemberApiAdminWorkspacesWorkspaceIdMembersMemberUserIdDelete
     * @summary Admin Remove Workspace Member
     * @request DELETE:/api/admin/workspaces/{workspace_id}/members/{member_user_id}
     * @secure
     */
    adminRemoveWorkspaceMemberApiAdminWorkspacesWorkspaceIdMembersMemberUserIdDelete:
      (workspaceId: string, memberUserId: string, params: RequestParams = {}) =>
        this.request<void, HTTPValidationError>({
          path: `/api/admin/workspaces/${workspaceId}/members/${memberUserId}`,
          method: "DELETE",
          secure: true,
          ...params,
        }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminRemoveWorkspaceAdminApiAdminWorkspacesWorkspaceIdAdminsAdminUserIdDelete
     * @summary Admin Remove Workspace Admin
     * @request DELETE:/api/admin/workspaces/{workspace_id}/admins/{admin_user_id}
     * @secure
     */
    adminRemoveWorkspaceAdminApiAdminWorkspacesWorkspaceIdAdminsAdminUserIdDelete:
      (workspaceId: string, adminUserId: string, params: RequestParams = {}) =>
        this.request<void, HTTPValidationError>({
          path: `/api/admin/workspaces/${workspaceId}/admins/${adminUserId}`,
          method: "DELETE",
          secure: true,
          ...params,
        }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminSuspendWorkspaceApiAdminWorkspacesWorkspaceIdSuspendPost
     * @summary Admin Suspend Workspace
     * @request POST:/api/admin/workspaces/{workspace_id}/suspend
     * @secure
     */
    adminSuspendWorkspaceApiAdminWorkspacesWorkspaceIdSuspendPost: (
      workspaceId: string,
      params: RequestParams = {},
    ) =>
      this.request<AdminWorkspaceOut, HTTPValidationError>({
        path: `/api/admin/workspaces/${workspaceId}/suspend`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminReactivateWorkspaceApiAdminWorkspacesWorkspaceIdReactivatePost
     * @summary Admin Reactivate Workspace
     * @request POST:/api/admin/workspaces/{workspace_id}/reactivate
     * @secure
     */
    adminReactivateWorkspaceApiAdminWorkspacesWorkspaceIdReactivatePost: (
      workspaceId: string,
      params: RequestParams = {},
    ) =>
      this.request<AdminWorkspaceOut, HTTPValidationError>({
        path: `/api/admin/workspaces/${workspaceId}/reactivate`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminArchiveWorkspaceApiAdminWorkspacesWorkspaceIdArchivePost
     * @summary Admin Archive Workspace
     * @request POST:/api/admin/workspaces/{workspace_id}/archive
     * @secure
     */
    adminArchiveWorkspaceApiAdminWorkspacesWorkspaceIdArchivePost: (
      workspaceId: string,
      params: RequestParams = {},
    ) =>
      this.request<AdminWorkspaceOut, HTTPValidationError>({
        path: `/api/admin/workspaces/${workspaceId}/archive`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminTransferWorkspaceOwnerApiAdminWorkspacesWorkspaceIdTransferOwnerPost
     * @summary Admin Transfer Workspace Owner
     * @request POST:/api/admin/workspaces/{workspace_id}/transfer-owner
     * @secure
     */
    adminTransferWorkspaceOwnerApiAdminWorkspacesWorkspaceIdTransferOwnerPost: (
      workspaceId: string,
      data: AdminWorkspaceTransferOwner,
      params: RequestParams = {},
    ) =>
      this.request<AdminWorkspaceOut, HTTPValidationError>({
        path: `/api/admin/workspaces/${workspaceId}/transfer-owner`,
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
     * @name AdminUpdateWorkspaceOwnerApiAdminWorkspacesWorkspaceIdOwnerPatch
     * @summary Admin Update Workspace Owner
     * @request PATCH:/api/admin/workspaces/{workspace_id}/owner
     * @secure
     */
    adminUpdateWorkspaceOwnerApiAdminWorkspacesWorkspaceIdOwnerPatch: (
      workspaceId: string,
      data: AdminOwnerUpdate,
      params: RequestParams = {},
    ) =>
      this.request<AdminOwnerOut, HTTPValidationError>({
        path: `/api/admin/workspaces/${workspaceId}/owner`,
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
     * @tags admin
     * @name AdminResetWorkspaceOwnerPasswordApiAdminWorkspacesWorkspaceIdOwnerResetPasswordPost
     * @summary Admin Reset Workspace Owner Password
     * @request POST:/api/admin/workspaces/{workspace_id}/owner/reset-password
     * @secure
     */
    adminResetWorkspaceOwnerPasswordApiAdminWorkspacesWorkspaceIdOwnerResetPasswordPost:
      (
        workspaceId: string,
        data: AdminOwnerPasswordReset,
        params: RequestParams = {},
      ) =>
        this.request<AdminOwnerPasswordResetOut, HTTPValidationError>({
          path: `/api/admin/workspaces/${workspaceId}/owner/reset-password`,
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
     * @name AdminListAgentActivationTokensApiAdminAgentActivationTokensGet
     * @summary Admin List Agent Activation Tokens
     * @request GET:/api/admin/agent-activation-tokens
     * @secure
     */
    adminListAgentActivationTokensApiAdminAgentActivationTokensGet: (
      query?: {
        /** Workspaceid */
        workspaceId?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<AdminAgentTokenOut[], HTTPValidationError>({
        path: `/api/admin/agent-activation-tokens`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminCreateAgentActivationTokenApiAdminAgentActivationTokensPost
     * @summary Admin Create Agent Activation Token
     * @request POST:/api/admin/agent-activation-tokens
     * @secure
     */
    adminCreateAgentActivationTokenApiAdminAgentActivationTokensPost: (
      data: AdminAgentTokenCreate,
      params: RequestParams = {},
    ) =>
      this.request<AdminAgentTokenCreated, HTTPValidationError>({
        path: `/api/admin/agent-activation-tokens`,
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
     * @name AdminRevokeAgentActivationTokenApiAdminAgentActivationTokensTokenIdDelete
     * @summary Admin Revoke Agent Activation Token
     * @request DELETE:/api/admin/agent-activation-tokens/{token_id}
     * @secure
     */
    adminRevokeAgentActivationTokenApiAdminAgentActivationTokensTokenIdDelete: (
      tokenId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/admin/agent-activation-tokens/${tokenId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminReplaceAgentActivationTokenApiAdminAgentActivationTokensTokenIdReplacePost
     * @summary Admin Replace Agent Activation Token
     * @request POST:/api/admin/agent-activation-tokens/{token_id}/replace
     * @secure
     */
    adminReplaceAgentActivationTokenApiAdminAgentActivationTokensTokenIdReplacePost:
      (tokenId: string, params: RequestParams = {}) =>
        this.request<AdminAgentTokenCreated, HTTPValidationError>({
          path: `/api/admin/agent-activation-tokens/${tokenId}/replace`,
          method: "POST",
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminListAgentsApiAdminAgentsGet
     * @summary Admin List Agents
     * @request GET:/api/admin/agents
     * @secure
     */
    adminListAgentsApiAdminAgentsGet: (
      query?: {
        /** Search */
        search?: string | null;
        /** Workspaceid */
        workspaceId?: string | null;
        /** Status */
        status?: string | null;
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
      },
      params: RequestParams = {},
    ) =>
      this.request<AdminAgentListOut, HTTPValidationError>({
        path: `/api/admin/agents`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminListAgentPhonesApiAdminAgentsRelayIdPhoneAllocationsGet
     * @summary Admin List Agent Phones
     * @request GET:/api/admin/agents/{relay_id}/phone-allocations
     * @secure
     */
    adminListAgentPhonesApiAdminAgentsRelayIdPhoneAllocationsGet: (
      relayId: string,
      query?: {
        /** Search */
        search?: string | null;
        /** Status */
        status?: string | null;
        /** Assignedworkspaceid */
        assignedWorkspaceId?: string | null;
        /**
         * Offset
         * @min 0
         * @default 0
         */
        offset?: number;
        /**
         * Limit
         * @min 1
         * @max 200
         * @default 100
         */
        limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<AdminAgentPhoneListOut, HTTPValidationError>({
        path: `/api/admin/agents/${relayId}/phone-allocations`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminAssignAgentPhonesApiAdminAgentsRelayIdPhoneAllocationsPost
     * @summary Admin Assign Agent Phones
     * @request POST:/api/admin/agents/{relay_id}/phone-allocations
     * @secure
     */
    adminAssignAgentPhonesApiAdminAgentsRelayIdPhoneAllocationsPost: (
      relayId: string,
      data: AdminAgentPhoneAssign,
      params: RequestParams = {},
    ) =>
      this.request<AdminAgentPhoneAssignOut, HTTPValidationError>({
        path: `/api/admin/agents/${relayId}/phone-allocations`,
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
     * @name AdminUnassignAgentPhonesApiAdminAgentsRelayIdPhoneAllocationsDelete
     * @summary Admin Unassign Agent Phones
     * @request DELETE:/api/admin/agents/{relay_id}/phone-allocations
     * @secure
     */
    adminUnassignAgentPhonesApiAdminAgentsRelayIdPhoneAllocationsDelete: (
      relayId: string,
      data: AdminAgentPhoneUnassign,
      params: RequestParams = {},
    ) =>
      this.request<AdminAgentPhoneAssignOut, HTTPValidationError>({
        path: `/api/admin/agents/${relayId}/phone-allocations`,
        method: "DELETE",
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
     * @name AdminUpdateAgentApiAdminAgentsRelayIdPatch
     * @summary Admin Update Agent
     * @request PATCH:/api/admin/agents/{relay_id}
     * @secure
     */
    adminUpdateAgentApiAdminAgentsRelayIdPatch: (
      relayId: string,
      data: AdminAgentUpdate,
      params: RequestParams = {},
    ) =>
      this.request<AdminAgentOut, HTTPValidationError>({
        path: `/api/admin/agents/${relayId}`,
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
     * @tags admin
     * @name AdminDeleteAgentApiAdminAgentsRelayIdDelete
     * @summary Admin Delete Agent
     * @request DELETE:/api/admin/agents/{relay_id}
     * @secure
     */
    adminDeleteAgentApiAdminAgentsRelayIdDelete: (
      relayId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/admin/agents/${relayId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminDisableAgentApiAdminAgentsRelayIdDisablePost
     * @summary Admin Disable Agent
     * @request POST:/api/admin/agents/{relay_id}/disable
     * @secure
     */
    adminDisableAgentApiAdminAgentsRelayIdDisablePost: (
      relayId: string,
      params: RequestParams = {},
    ) =>
      this.request<AdminAgentOut, HTTPValidationError>({
        path: `/api/admin/agents/${relayId}/disable`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminEnableAgentApiAdminAgentsRelayIdEnablePost
     * @summary Admin Enable Agent
     * @request POST:/api/admin/agents/{relay_id}/enable
     * @secure
     */
    adminEnableAgentApiAdminAgentsRelayIdEnablePost: (
      relayId: string,
      params: RequestParams = {},
    ) =>
      this.request<AdminAgentOut, HTTPValidationError>({
        path: `/api/admin/agents/${relayId}/enable`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminListDevicesApiAdminDevicesGet
     * @summary Admin List Devices
     * @request GET:/api/admin/devices
     * @secure
     */
    adminListDevicesApiAdminDevicesGet: (
      query?: {
        /** Search */
        search?: string | null;
        /** Workspaceid */
        workspaceId?: string | null;
        /** Status */
        status?: string | null;
        /** Assigned */
        assigned?: boolean | null;
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
      },
      params: RequestParams = {},
    ) =>
      this.request<AdminDeviceListOut, HTTPValidationError>({
        path: `/api/admin/devices`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminTransferDeviceWorkspaceApiAdminDevicesDeviceIdAssignmentPut
     * @summary Admin Transfer Device Workspace
     * @request PUT:/api/admin/devices/{device_id}/assignment
     * @secure
     */
    adminTransferDeviceWorkspaceApiAdminDevicesDeviceIdAssignmentPut: (
      deviceId: string,
      data: AdminDeviceTransfer,
      params: RequestParams = {},
    ) =>
      this.request<AdminDeviceOut, HTTPValidationError>({
        path: `/api/admin/devices/${deviceId}/assignment`,
        method: "PUT",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Drop a pool phone's row so its serial is free to register again. A serial is claimed globally (``services/device_registration.py``), so a row left behind by a retired pool agent blocks every other workspace from ever registering that physical phone. Only the pool workspace that manages the row can free it — the same rule the transfer endpoint enforces — and only while the phone is back in its pool, so this can never yank a phone out from under the tenant currently using it.
     *
     * @tags admin
     * @name AdminDeleteDeviceApiAdminDevicesDeviceIdDelete
     * @summary Admin Delete Device
     * @request DELETE:/api/admin/devices/{device_id}
     * @secure
     */
    adminDeleteDeviceApiAdminDevicesDeviceIdDelete: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/admin/devices/${deviceId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags admin
     * @name AdminAuditLogApiAdminAuditLogGet
     * @summary Admin Audit Log
     * @request GET:/api/admin/audit-log
     * @secure
     */
    adminAuditLogApiAdminAuditLogGet: (
      query?: {
        /** Action */
        action?: string | null;
        /** Resourcetype */
        resourceType?: string | null;
        /** Resourceid */
        resourceId?: string | null;
        /** Workspaceid */
        workspaceId?: string | null;
        /** Actor */
        actor?: string | null;
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
      },
      params: RequestParams = {},
    ) =>
      this.request<ActivityLogListOut, HTTPValidationError>({
        path: `/api/admin/audit-log`,
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
     * @description Serve the STFService.apk used by Android devices. The file is resolved from a small set of well-known locations: - backend/bundle/apks/STFService.apk                    (download_bundle.py output) - ../STFService.apk/app/build/outputs/apk/release/...   (local Gradle build)
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
     * No description
     *
     * @tags devices
     * @name ConnectLocalEmulatorApiDevicesConnectEmulatorPost
     * @summary Connect Local Emulator
     * @request POST:/api/devices/connect-emulator
     * @secure
     */
    connectLocalEmulatorApiDevicesConnectEmulatorPost: (
      data: ConnectLocalEmulatorBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/connect-emulator`,
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
     * @description List pool phones allocated to this workspace but not claimed by a user yet.
     *
     * @tags devices
     * @name ListAllocatedDevicesApiDevicesAllocatedGet
     * @summary List Allocated Devices
     * @request GET:/api/devices/allocated
     * @secure
     */
    listAllocatedDevicesApiDevicesAllocatedGet: (
      query?: {
        /** Q */
        q?: string | null;
        /**
         * Limit
         * @min 1
         * @max 100
         * @default 50
         */
        limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<DeviceOut[], HTTPValidationError>({
        path: `/api/devices/allocated`,
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
        /** Page */
        page?: number | null;
        /** Page Size */
        page_size?: number | null;
        /**
         * Connected Only
         * @default false
         */
        connected_only?: boolean;
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
     * @description List active logical sessions so fleet totals are operator-auditable.
     *
     * @tags devices
     * @name ListActiveFleetSessionsApiDevicesFleetSessionsGet
     * @summary List Active Fleet Sessions
     * @request GET:/api/devices/fleet/sessions
     * @secure
     */
    listActiveFleetSessionsApiDevicesFleetSessionsGet: (
      query?: {
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
      },
      params: RequestParams = {},
    ) =>
      this.request<ActiveFleetSessionListOut, HTTPValidationError>({
        path: `/api/devices/fleet/sessions`,
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
     * @name ClaimAllocatedDeviceRouteApiDevicesDeviceIdClaimAllocatedPost
     * @summary Claim Allocated Device Route
     * @request POST:/api/devices/{device_id}/claim-allocated
     * @secure
     */
    claimAllocatedDeviceRouteApiDevicesDeviceIdClaimAllocatedPost: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<DeviceOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}/claim-allocated`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name ConnectViaManagedAgentApiDevicesDeviceIdConnectViaManagedAgentPost
     * @summary Connect Via Managed Agent
     * @request POST:/api/devices/{device_id}/connect-via-managed-agent
     * @secure
     */
    connectViaManagedAgentApiDevicesDeviceIdConnectViaManagedAgentPost: (
      deviceId: string,
      data: ManagedAgentConnectBody,
      params: RequestParams = {},
    ) =>
      this.request<RelayCommandOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}/connect-via-managed-agent`,
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
     * @name UpdateNameApiDevicesDeviceIdNamePatch
     * @summary Update Name
     * @request PATCH:/api/devices/{device_id}/name
     * @secure
     */
    updateNameApiDevicesDeviceIdNamePatch: (
      deviceId: string,
      data: DeviceNameUpdate,
      params: RequestParams = {},
    ) =>
      this.request<DeviceOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}/name`,
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
     * @name ListCampaignsPageApiCampaignsPageGet
     * @summary List Campaigns Page
     * @request GET:/api/campaigns/page
     * @secure
     */
    listCampaignsPageApiCampaignsPageGet: (
      query?: {
        /** Search */
        search?: string | null;
        /**
         * Limit
         * @min 1
         * @max 100
         * @default 10
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
      this.request<CampaignPageOut, HTTPValidationError>({
        path: `/api/campaigns/page`,
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
        /** Search */
        search?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<(CampaignEntityOut | CampaignOut)[], HTTPValidationError>({
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
      this.request<CampaignEntityOut | CampaignOut, HTTPValidationError>({
        path: `/api/campaigns`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Unified campaign monitoring snapshot with phone/account/step context.
     *
     * @tags campaigns
     * @name GetCampaignMonitorApiCampaignsCampaignIdMonitorGet
     * @summary Get Campaign Monitor
     * @request GET:/api/campaigns/{campaign_id}/monitor
     * @secure
     */
    getCampaignMonitorApiCampaignsCampaignIdMonitorGet: (
      campaignId: string,
      query?: {
        /**
         * Limit
         * @min 1
         * @max 500
         * @default 200
         */
        limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<CampaignMonitorOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/monitor`,
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
     * @name GetCampaignApiCampaignsCampaignIdGet
     * @summary Get Campaign
     * @request GET:/api/campaigns/{campaign_id}
     * @secure
     */
    getCampaignApiCampaignsCampaignIdGet: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<CampaignOut | CampaignEntityOut, HTTPValidationError>({
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
     * @description Resolve devices and sources without creating executions or claims.
     *
     * @tags campaigns
     * @name PreviewCampaignDispatchRouteApiCampaignsCampaignIdDispatchPreviewPost
     * @summary Preview Campaign Dispatch Route
     * @request POST:/api/campaigns/{campaign_id}/dispatch-preview
     * @secure
     */
    previewCampaignDispatchRouteApiCampaignsCampaignIdDispatchPreviewPost: (
      campaignId: string,
      data: CampaignDispatchIn,
      params: RequestParams = {},
    ) =>
      this.request<CampaignDispatchPreviewOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/dispatch-preview`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
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
     * @description Return cumulative campaign-run counts (passed/failed/…) across all dispatches.
     *
     * @tags campaigns
     * @name CampaignRunStatsEndpointApiCampaignsCampaignIdRunStatsGet
     * @summary Campaign Run Stats Endpoint
     * @request GET:/api/campaigns/{campaign_id}/run-stats
     * @secure
     */
    campaignRunStatsEndpointApiCampaignsCampaignIdRunStatsGet: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/run-stats`,
        method: "GET",
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
     * @name ListScenarioTemplatesApiScenariosTemplatesGet
     * @summary List Scenario Templates
     * @request GET:/api/scenarios/templates
     * @secure
     */
    listScenarioTemplatesApiScenariosTemplatesGet: (
      query?: {
        /** Platform */
        platform?: string | null;
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
     * @description Replace steps on an existing scenario from a portable export file.
     *
     * @tags scenarios
     * @name ImportScenarioBodyIntoExistingRouteApiScenariosScenarioIdImportBodyPost
     * @summary Import Scenario Body Into Existing Route
     * @request POST:/api/scenarios/{scenario_id}/import-body
     * @secure
     */
    importScenarioBodyIntoExistingRouteApiScenariosScenarioIdImportBodyPost: (
      scenarioId: string,
      data: BodyImportScenarioBodyIntoExistingRouteApiScenariosScenarioIdImportBodyPost,
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
        path: `/api/scenarios/${scenarioId}/import-body`,
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
     * @name EnsureAccountLoginScenarioRouteApiScenariosAccountLoginEffectivePost
     * @summary Ensure Account Login Scenario Route
     * @request POST:/api/scenarios/account-login/effective
     * @secure
     */
    ensureAccountLoginScenarioRouteApiScenariosAccountLoginEffectivePost: (
      data: AccountLoginScenarioEnsureIn,
      params: RequestParams = {},
    ) =>
      this.request<OrgScenarioOut, HTTPValidationError>({
        path: `/api/scenarios/account-login/effective`,
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
     * @description Store a cropped template and report whether it is safe to match on. The ambiguity check is the point of doing this server-side: a crop of blank background scores 1.000 everywhere, so it would tap the wrong place while looking perfectly confident. Better to say so while the user is still looking at the crop than to debug it later in a run.
     *
     * @tags scenarios
     * @name UploadStepTemplateRouteApiScenariosScenarioIdImageTemplatesPost
     * @summary Upload Step Template Route
     * @request POST:/api/scenarios/{scenario_id}/image-templates
     * @secure
     */
    uploadStepTemplateRouteApiScenariosScenarioIdImageTemplatesPost: (
      scenarioId: string,
      data: BodyUploadStepTemplateRouteApiScenariosScenarioIdImageTemplatesPost,
      query?: {
        /**
         * Screen W
         * @min 0
         * @default 0
         */
        screen_w?: number;
        /**
         * Screen H
         * @min 0
         * @default 0
         */
        screen_h?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/scenarios/${scenarioId}/image-templates`,
        method: "POST",
        query: query,
        body: data,
        secure: true,
        type: ContentType.FormData,
        format: "json",
        ...params,
      }),

    /**
     * @description Presigned URL so the editor can show the template already attached.
     *
     * @tags scenarios
     * @name GetStepTemplateUrlRouteApiScenariosScenarioIdImageTemplatesUrlGet
     * @summary Get Step Template Url Route
     * @request GET:/api/scenarios/{scenario_id}/image-templates/url
     * @secure
     */
    getStepTemplateUrlRouteApiScenariosScenarioIdImageTemplatesUrlGet: (
      scenarioId: string,
      query: {
        /** Key */
        key: string;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/scenarios/${scenarioId}/image-templates/url`,
        method: "GET",
        query: query,
        secure: true,
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
     * @description List visible devices that can still be added to this group.
     *
     * @tags device-groups
     * @name ListAvailableDevicesForGroupApiDeviceGroupsGroupIdAvailableDevicesGet
     * @summary List Available Devices For Group
     * @request GET:/api/device-groups/{group_id}/available-devices
     * @secure
     */
    listAvailableDevicesForGroupApiDeviceGroupsGroupIdAvailableDevicesGet: (
      groupId: string,
      query?: {
        /** Q */
        q?: string | null;
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
         * @default 20
         */
        limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<DeviceGroupAvailableDevicesOut, HTTPValidationError>({
        path: `/api/device-groups/${groupId}/available-devices`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
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
         * Search
         * Substring match on username or display name
         */
        search?: string | null;
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
     * @description Stream-import accounts from a CSV file upload. Reads the upload in 64 KB chunks, parses CSV incrementally, and flushes batches of up to 500 rows to the DB via INSERT ON CONFLICT DO NOTHING — so memory usage stays flat regardless of file size. Expected CSV columns: platform, username, password, display_name, tags, notes, email, totp_secret, cookies, token
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
     * No description
     *
     * @tags accounts
     * @name ListAccountImportFormatsEndpointApiAccountsImportFormatsGet
     * @summary List Account Import Formats Endpoint
     * @request GET:/api/accounts/import-formats
     * @secure
     */
    listAccountImportFormatsEndpointApiAccountsImportFormatsGet: (
      query?: {
        /**
         * Include Inactive
         * @default false
         */
        include_inactive?: boolean;
      },
      params: RequestParams = {},
    ) =>
      this.request<AccountImportFormatListOut, HTTPValidationError>({
        path: `/api/accounts/import-formats`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags accounts
     * @name BulkImportTxtApiAccountsImportTxtPost
     * @summary Bulk Import Txt
     * @request POST:/api/accounts/import-txt
     * @secure
     */
    bulkImportTxtApiAccountsImportTxtPost: (
      data: BodyBulkImportTxtApiAccountsImportTxtPost,
      params: RequestParams = {},
    ) =>
      this.request<BulkImportResult, HTTPValidationError>({
        path: `/api/accounts/import-txt`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.FormData,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags accounts
     * @name AdminCreateAccountImportFormatApiAdminAccountImportFormatsPost
     * @summary Admin Create Account Import Format
     * @request POST:/api/admin/account-import-formats
     * @secure
     */
    adminCreateAccountImportFormatApiAdminAccountImportFormatsPost: (
      data: AccountImportFormatCreate,
      params: RequestParams = {},
    ) =>
      this.request<AccountImportFormatOut, HTTPValidationError>({
        path: `/api/admin/account-import-formats`,
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
     * @tags accounts
     * @name AdminUpdateAccountImportFormatApiAdminAccountImportFormatsFormatIdPatch
     * @summary Admin Update Account Import Format
     * @request PATCH:/api/admin/account-import-formats/{format_id}
     * @secure
     */
    adminUpdateAccountImportFormatApiAdminAccountImportFormatsFormatIdPatch: (
      formatId: string,
      data: AccountImportFormatUpdate,
      params: RequestParams = {},
    ) =>
      this.request<AccountImportFormatOut, HTTPValidationError>({
        path: `/api/admin/account-import-formats/${formatId}`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
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
     * @description List visible devices that are not yet linked to this account.
     *
     * @tags accounts
     * @name ListAccountAvailableDevicesEndpointApiAccountsAccountIdAvailableDevicesGet
     * @summary List Account Available Devices Endpoint
     * @request GET:/api/accounts/{account_id}/available-devices
     * @secure
     */
    listAccountAvailableDevicesEndpointApiAccountsAccountIdAvailableDevicesGet:
      (
        accountId: string,
        query?: {
          /** Q */
          q?: string | null;
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
           * @default 20
           */
          limit?: number;
        },
        params: RequestParams = {},
      ) =>
        this.request<AccountAvailableDevicesOut, HTTPValidationError>({
          path: `/api/accounts/${accountId}/available-devices`,
          method: "GET",
          query: query,
          secure: true,
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
     * No description
     *
     * @tags accounts
     * @name VerifyAccountOnDeviceEndpointApiDevicesDeviceIdAccountsAccountIdVerifyPost
     * @summary Verify Account On Device Endpoint
     * @request POST:/api/devices/{device_id}/accounts/{account_id}/verify
     * @secure
     */
    verifyAccountOnDeviceEndpointApiDevicesDeviceIdAccountsAccountIdVerifyPost:
      (deviceId: string, accountId: string, params: RequestParams = {}) =>
        this.request<AccountVerificationOut, HTTPValidationError>({
          path: `/api/devices/${deviceId}/accounts/${accountId}/verify`,
          method: "POST",
          secure: true,
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
     * @description List platform session provenance rows for a device.
     *
     * @tags accounts
     * @name ListDevicePlatformSessionsEndpointApiDevicesDeviceIdPlatformSessionsGet
     * @summary List Device Platform Sessions Endpoint
     * @request GET:/api/devices/{device_id}/platform-sessions
     * @secure
     */
    listDevicePlatformSessionsEndpointApiDevicesDeviceIdPlatformSessionsGet: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<DevicePlatformSessionOut[], HTTPValidationError>({
        path: `/api/devices/${deviceId}/platform-sessions`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags account-actions
     * @name ListAccountActionsApiAccountsAccountIdActionsGet
     * @summary List Account Actions
     * @request GET:/api/accounts/{account_id}/actions
     * @secure
     */
    listAccountActionsApiAccountsAccountIdActionsGet: (
      accountId: string,
      query?: {
        /**
         * Limit
         * @min 1
         * @max 200
         * @default 100
         */
        limit?: number;
        /** Cursor */
        cursor?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<AccountActionListOut, HTTPValidationError>({
        path: `/api/accounts/${accountId}/actions`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags account-actions
     * @name GetAccountActionSummaryApiAccountsAccountIdActionSummaryGet
     * @summary Get Account Action Summary
     * @request GET:/api/accounts/{account_id}/action-summary
     * @secure
     */
    getAccountActionSummaryApiAccountsAccountIdActionSummaryGet: (
      accountId: string,
      params: RequestParams = {},
    ) =>
      this.request<AccountActionSummaryOut, HTTPValidationError>({
        path: `/api/accounts/${accountId}/action-summary`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags account-discovery
     * @name GetAccountDiscoveryRouteApiAccountsAccountIdDiscoveryGet
     * @summary Get Account Discovery Route
     * @request GET:/api/accounts/{account_id}/discovery
     * @secure
     */
    getAccountDiscoveryRouteApiAccountsAccountIdDiscoveryGet: (
      accountId: string,
      query: {
        /**
         * Platform
         * @minLength 1
         * @maxLength 32
         */
        platform: string;
      },
      params: RequestParams = {},
    ) =>
      this.request<AccountDiscoveryStateOut, HTTPValidationError>({
        path: `/api/accounts/${accountId}/discovery`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags account-discovery
     * @name RequestAccountDiscoveryRouteApiAccountsAccountIdDiscoveryRequestPost
     * @summary Request Account Discovery Route
     * @request POST:/api/accounts/{account_id}/discovery/request
     * @secure
     */
    requestAccountDiscoveryRouteApiAccountsAccountIdDiscoveryRequestPost: (
      accountId: string,
      query: {
        /**
         * Platform
         * @minLength 1
         * @maxLength 32
         */
        platform: string;
      },
      params: RequestParams = {},
    ) =>
      this.request<AccountDiscoveryStateOut, HTTPValidationError>({
        path: `/api/accounts/${accountId}/discovery/request`,
        method: "POST",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags account-discovery
     * @name StartAccountDiscoveryRouteApiAccountsAccountIdDiscoveryStartPost
     * @summary Start Account Discovery Route
     * @request POST:/api/accounts/{account_id}/discovery/start
     * @secure
     */
    startAccountDiscoveryRouteApiAccountsAccountIdDiscoveryStartPost: (
      accountId: string,
      query: {
        /**
         * Platform
         * @minLength 1
         * @maxLength 32
         */
        platform: string;
      },
      params: RequestParams = {},
    ) =>
      this.request<AccountDiscoveryStateOut, HTTPValidationError>({
        path: `/api/accounts/${accountId}/discovery/start`,
        method: "POST",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags account-discovery
     * @name CompleteAccountDiscoveryRouteApiAccountsAccountIdDiscoveryCompletePost
     * @summary Complete Account Discovery Route
     * @request POST:/api/accounts/{account_id}/discovery/complete
     * @secure
     */
    completeAccountDiscoveryRouteApiAccountsAccountIdDiscoveryCompletePost: (
      accountId: string,
      query: {
        /**
         * Platform
         * @minLength 1
         * @maxLength 32
         */
        platform: string;
      },
      data: AccountDiscoveryCompleteIn,
      params: RequestParams = {},
    ) =>
      this.request<AccountDiscoveryStateOut, HTTPValidationError>({
        path: `/api/accounts/${accountId}/discovery/complete`,
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
     * @tags account-discovery
     * @name FailAccountDiscoveryRouteApiAccountsAccountIdDiscoveryFailPost
     * @summary Fail Account Discovery Route
     * @request POST:/api/accounts/{account_id}/discovery/fail
     * @secure
     */
    failAccountDiscoveryRouteApiAccountsAccountIdDiscoveryFailPost: (
      accountId: string,
      query: {
        /**
         * Platform
         * @minLength 1
         * @maxLength 32
         */
        platform: string;
      },
      data: AccountDiscoveryFailedIn,
      params: RequestParams = {},
    ) =>
      this.request<AccountDiscoveryStateOut, HTTPValidationError>({
        path: `/api/accounts/${accountId}/discovery/fail`,
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
     * @description Comments for a post — matches parent_id hash variants and parser post ids.
     *
     * @tags content
     * @name ListContentChildrenApiContentItemIdChildrenGet
     * @summary List Content Children
     * @request GET:/api/content/{item_id}/children
     * @secure
     */
    listContentChildrenApiContentItemIdChildrenGet: (
      itemId: string,
      query?: {
        /**
         * Limit
         * @min 1
         * @max 500
         * @default 100
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
        path: `/api/content/${itemId}/children`,
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
        /** Account Id */
        account_id?: string | null;
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
     * @description Unified trace for one execution: phone, account, steps, events, DLQ.
     *
     * @tags executions
     * @name GetExecutionTaskLogApiExecutionsExecutionIdTaskLogGet
     * @summary Get Execution Task Log
     * @request GET:/api/executions/{execution_id}/task-log
     * @secure
     */
    getExecutionTaskLogApiExecutionsExecutionIdTaskLogGet: (
      executionId: string,
      query?: {
        /** Since */
        since?: string | null;
        /**
         * Event Limit
         * @default 200
         */
        event_limit?: number;
        /**
         * Step Limit
         * @default 500
         */
        step_limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<ExecutionTaskLogOut, HTTPValidationError>({
        path: `/api/executions/${executionId}/task-log`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Alias for task-log while the frontend migrates naming.
     *
     * @tags executions
     * @name GetExecutionRunTraceApiExecutionsExecutionIdRunTraceGet
     * @summary Get Execution Run Trace
     * @request GET:/api/executions/{execution_id}/run-trace
     * @secure
     */
    getExecutionRunTraceApiExecutionsExecutionIdRunTraceGet: (
      executionId: string,
      query?: {
        /** Since */
        since?: string | null;
        /**
         * Event Limit
         * @default 200
         */
        event_limit?: number;
        /**
         * Step Limit
         * @default 500
         */
        step_limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<ExecutionTaskLogOut, HTTPValidationError>({
        path: `/api/executions/${executionId}/run-trace`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
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
     */
    streamExecutionEventsApiExecutionsExecutionIdEventsStreamGet: (
      executionId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/executions/${executionId}/events/stream`,
        method: "GET",
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
     * @description Register several reported serials in one call. Partial success by design (same shape as DLQ bulk retry): one bad serial must not sink the rest, so each is committed on its own and reported individually. An empty `serials` list means "everything this agent reports".
     *
     * @tags relay-agents
     * @name RegisterRelayDevicesBulkApiRelayAgentsRelayIdDevicesRegisterPost
     * @summary Register Relay Devices Bulk
     * @request POST:/api/relay-agents/{relay_id}/devices/register
     * @secure
     */
    registerRelayDevicesBulkApiRelayAgentsRelayIdDevicesRegisterPost: (
      relayId: string,
      data: RegisterRelayDevicesBody,
      params: RequestParams = {},
    ) =>
      this.request<RegisterRelayDevicesOut, HTTPValidationError>({
        path: `/api/relay-agents/${relayId}/devices/register`,
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
          /**
           * Ws Base Url
           * Phone-reachable ws(s) origin (same as dashboard QR). Overrides DEVICE_FARM_WS.
           */
          ws_base_url?: string | null;
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
     * @name ConnectRelayDeviceApiRelayAgentsRelayIdDevicesSerialConnectPost
     * @summary Connect Relay Device
     * @request POST:/api/relay-agents/{relay_id}/devices/{serial}/connect
     * @secure
     */
    connectRelayDeviceApiRelayAgentsRelayIdDevicesSerialConnectPost: (
      relayId: string,
      serial: string,
      query?: {
        /**
         * Device Id
         * Logical device id when DB serial is pending-* but ADB path serial is physical
         */
        device_id?: string | null;
        /**
         * Ws Base Url
         * Phone-reachable ws(s) origin (same as dashboard QR). Overrides DEVICE_FARM_WS.
         */
        ws_base_url?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<RelayCommandOut, HTTPValidationError>({
        path: `/api/relay-agents/${relayId}/devices/${serial}/connect`,
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
     * @name DisconnectRelayDeviceApiRelayAgentsRelayIdDevicesSerialDisconnectPost
     * @summary Disconnect Relay Device
     * @request POST:/api/relay-agents/{relay_id}/devices/{serial}/disconnect
     * @secure
     */
    disconnectRelayDeviceApiRelayAgentsRelayIdDevicesSerialDisconnectPost: (
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
        path: `/api/relay-agents/${relayId}/devices/${serial}/disconnect`,
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
     * @name TestChannelDraftApiNotificationChannelsTestDraftPost
     * @summary Test Channel Draft
     * @request POST:/api/notification-channels/test-draft
     * @secure
     */
    testChannelDraftApiNotificationChannelsTestDraftPost: (
      data: NotificationChannelTestRequest,
      params: RequestParams = {},
    ) =>
      this.request<TestNotificationOut, HTTPValidationError>({
        path: `/api/notification-channels/test-draft`,
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
        /** Account Id */
        account_id?: string | null;
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
     * @tags external-entities
     * @name ListExternalEntitiesRouteApiExternalEntitiesGet
     * @summary List External Entities Route
     * @request GET:/api/external-entities
     * @secure
     */
    listExternalEntitiesRouteApiExternalEntitiesGet: (
      query?: {
        /** Platform */
        platform?: string | null;
        /** Entity Type */
        entity_type?: string | null;
        /** Status */
        status?: string | null;
        /** Search */
        search?: string | null;
        /**
         * Limit
         * @min 1
         * @max 500
         * @default 100
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
      this.request<ExternalEntityListOut, HTTPValidationError>({
        path: `/api/external-entities`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags external-entities
     * @name ObserveExternalEntityRouteApiExternalEntitiesObservePost
     * @summary Observe External Entity Route
     * @request POST:/api/external-entities/observe
     * @secure
     */
    observeExternalEntityRouteApiExternalEntitiesObservePost: (
      data: ExternalEntityObserveIn,
      params: RequestParams = {},
    ) =>
      this.request<ExternalEntityObserveOut, HTTPValidationError>({
        path: `/api/external-entities/observe`,
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
     * @tags external-entities
     * @name BulkObserveExternalEntitiesRouteApiExternalEntitiesBulkObservePost
     * @summary Bulk Observe External Entities Route
     * @request POST:/api/external-entities/bulk-observe
     * @secure
     */
    bulkObserveExternalEntitiesRouteApiExternalEntitiesBulkObservePost: (
      data: ExternalEntityBulkObserveIn,
      params: RequestParams = {},
    ) =>
      this.request<ExternalEntityBulkObserveOut, HTTPValidationError>({
        path: `/api/external-entities/bulk-observe`,
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
     * @tags external-entities
     * @name GetExternalEntityRouteApiExternalEntitiesEntityIdGet
     * @summary Get External Entity Route
     * @request GET:/api/external-entities/{entity_id}
     * @secure
     */
    getExternalEntityRouteApiExternalEntitiesEntityIdGet: (
      entityId: string,
      params: RequestParams = {},
    ) =>
      this.request<ExternalEntityOut, HTTPValidationError>({
        path: `/api/external-entities/${entityId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags external-entities
     * @name ListDeviceTargetGroupsRouteApiDevicesDeviceIdTargetGroupsGet
     * @summary List Device Target Groups Route
     * @request GET:/api/devices/{device_id}/target-groups
     * @secure
     */
    listDeviceTargetGroupsRouteApiDevicesDeviceIdTargetGroupsGet: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<DeviceTargetGroupsOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}/target-groups`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags external-entities
     * @name ReplaceDeviceTargetGroupsRouteApiDevicesDeviceIdTargetGroupsPut
     * @summary Replace Device Target Groups Route
     * @request PUT:/api/devices/{device_id}/target-groups
     * @secure
     */
    replaceDeviceTargetGroupsRouteApiDevicesDeviceIdTargetGroupsPut: (
      deviceId: string,
      data: DeviceTargetGroupsReplaceIn,
      params: RequestParams = {},
    ) =>
      this.request<DeviceTargetGroupsOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}/target-groups`,
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
     * @tags ai-device-lab
     * @name StartWizardCheckoutRouteApiAiDeviceLabServiceCampaignsCampaignIdWizardPaymentCheckoutPost
     * @summary Start Wizard Checkout Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/wizard/payment/checkout
     * @secure
     */
    startWizardCheckoutRouteApiAiDeviceLabServiceCampaignsCampaignIdWizardPaymentCheckoutPost:
      (
        campaignId: string,
        data: StartWizardCheckoutIn,
        params: RequestParams = {},
      ) =>
        this.request<WizardCheckoutOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/wizard/payment/checkout`,
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
     * @tags ai-device-lab
     * @name RecordDeviceHygieneResultRouteApiAiDeviceLabDevicesDeviceIdHygieneResultsPost
     * @summary Record Device Hygiene Result Route
     * @request POST:/api/ai-device-lab/devices/{device_id}/hygiene-results
     * @secure
     */
    recordDeviceHygieneResultRouteApiAiDeviceLabDevicesDeviceIdHygieneResultsPost:
      (
        deviceId: string,
        data: DeviceHygieneResultIn,
        params: RequestParams = {},
      ) =>
        this.request<DeviceHygieneResultOut, HTTPValidationError>({
          path: `/api/ai-device-lab/devices/${deviceId}/hygiene-results`,
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
     * @tags ai-device-lab
     * @name CreateFarmRunRouteApiAiDeviceLabServiceCampaignsCampaignIdFarmRunsPost
     * @summary Create Farm Run Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/farm-runs
     * @secure
     */
    createFarmRunRouteApiAiDeviceLabServiceCampaignsCampaignIdFarmRunsPost: (
      campaignId: string,
      data: CreateFarmRunIn,
      params: RequestParams = {},
    ) =>
      this.request<FarmRunOut, HTTPValidationError>({
        path: `/api/ai-device-lab/service-campaigns/${campaignId}/farm-runs`,
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
     * @tags ai-device-lab
     * @name GetFarmJobRouteApiAiDeviceLabFarmJobsJobIdGet
     * @summary Get Farm Job Route
     * @request GET:/api/ai-device-lab/farm-jobs/{job_id}
     * @secure
     */
    getFarmJobRouteApiAiDeviceLabFarmJobsJobIdGet: (
      jobId: string,
      params: RequestParams = {},
    ) =>
      this.request<FarmRunOut, HTTPValidationError>({
        path: `/api/ai-device-lab/farm-jobs/${jobId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name RecordFarmEventRouteApiAiDeviceLabFarmJobsJobIdEventsPost
     * @summary Record Farm Event Route
     * @request POST:/api/ai-device-lab/farm-jobs/{job_id}/events
     * @secure
     */
    recordFarmEventRouteApiAiDeviceLabFarmJobsJobIdEventsPost: (
      jobId: string,
      data: FarmEventIn,
      params: RequestParams = {},
    ) =>
      this.request<FarmEventOut, HTTPValidationError>({
        path: `/api/ai-device-lab/farm-jobs/${jobId}/events`,
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
     * @tags ai-device-lab
     * @name CreateServiceCampaignRouteApiAiDeviceLabServiceCampaignsPost
     * @summary Create Service Campaign Route
     * @request POST:/api/ai-device-lab/service-campaigns
     * @secure
     */
    createServiceCampaignRouteApiAiDeviceLabServiceCampaignsPost: (
      data: ServiceCampaignCreateIn,
      params: RequestParams = {},
    ) =>
      this.request<ServiceCampaignOut, HTTPValidationError>({
        path: `/api/ai-device-lab/service-campaigns`,
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
     * @tags ai-device-lab
     * @name GetServiceCampaignRouteApiAiDeviceLabServiceCampaignsCampaignIdGet
     * @summary Get Service Campaign Route
     * @request GET:/api/ai-device-lab/service-campaigns/{campaign_id}
     * @secure
     */
    getServiceCampaignRouteApiAiDeviceLabServiceCampaignsCampaignIdGet: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<ServiceCampaignOut, HTTPValidationError>({
        path: `/api/ai-device-lab/service-campaigns/${campaignId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name GetCampaignFunnelRouteApiAiDeviceLabServiceCampaignsCampaignIdFunnelGet
     * @summary Get Campaign Funnel Route
     * @request GET:/api/ai-device-lab/service-campaigns/{campaign_id}/funnel
     * @secure
     */
    getCampaignFunnelRouteApiAiDeviceLabServiceCampaignsCampaignIdFunnelGet: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<CampaignFunnelOut, HTTPValidationError>({
        path: `/api/ai-device-lab/service-campaigns/${campaignId}/funnel`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name GetWizardStateRouteApiAiDeviceLabServiceCampaignsCampaignIdWizardGet
     * @summary Get Wizard State Route
     * @request GET:/api/ai-device-lab/service-campaigns/{campaign_id}/wizard
     * @secure
     */
    getWizardStateRouteApiAiDeviceLabServiceCampaignsCampaignIdWizardGet: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<WizardStateOut, HTTPValidationError>({
        path: `/api/ai-device-lab/service-campaigns/${campaignId}/wizard`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name ListPaymentReconciliationsRouteApiAiDeviceLabServiceCampaignsCampaignIdPaymentReconciliationsGet
     * @summary List Payment Reconciliations Route
     * @request GET:/api/ai-device-lab/service-campaigns/{campaign_id}/payment-reconciliations
     * @secure
     */
    listPaymentReconciliationsRouteApiAiDeviceLabServiceCampaignsCampaignIdPaymentReconciliationsGet:
      (
        campaignId: string,
        query?: {
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
        },
        params: RequestParams = {},
      ) =>
        this.request<PaymentReconciliationListOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/payment-reconciliations`,
          method: "GET",
          query: query,
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name SaveWizardDraftRouteApiAiDeviceLabServiceCampaignsCampaignIdWizardAppPut
     * @summary Save Wizard Draft Route
     * @request PUT:/api/ai-device-lab/service-campaigns/{campaign_id}/wizard/app
     * @secure
     */
    saveWizardDraftRouteApiAiDeviceLabServiceCampaignsCampaignIdWizardAppPut: (
      campaignId: string,
      data: SaveWizardDraftIn,
      params: RequestParams = {},
    ) =>
      this.request<WizardStateOut, HTTPValidationError>({
        path: `/api/ai-device-lab/service-campaigns/${campaignId}/wizard/app`,
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
     * @tags ai-device-lab
     * @name GenerateWizardScenarioRouteApiAiDeviceLabServiceCampaignsCampaignIdWizardScenarioGeneratePost
     * @summary Generate Wizard Scenario Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/wizard/scenario/generate
     * @secure
     */
    generateWizardScenarioRouteApiAiDeviceLabServiceCampaignsCampaignIdWizardScenarioGeneratePost:
      (
        campaignId: string,
        data: StartWizardGenerationIn,
        params: RequestParams = {},
      ) =>
        this.request<WizardStateOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/wizard/scenario/generate`,
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
     * @tags ai-device-lab
     * @name ApproveWizardScenarioRouteApiAiDeviceLabServiceCampaignsCampaignIdWizardScenarioApprovePost
     * @summary Approve Wizard Scenario Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/wizard/scenario/approve
     * @secure
     */
    approveWizardScenarioRouteApiAiDeviceLabServiceCampaignsCampaignIdWizardScenarioApprovePost:
      (
        campaignId: string,
        data: ApproveWizardScenarioIn,
        params: RequestParams = {},
      ) =>
        this.request<WizardStateOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/wizard/scenario/approve`,
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
     * @tags ai-device-lab
     * @name StartServiceCampaignRouteApiAiDeviceLabServiceCampaignsCampaignIdStartPost
     * @summary Start Service Campaign Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/start
     * @secure
     */
    startServiceCampaignRouteApiAiDeviceLabServiceCampaignsCampaignIdStartPost:
      (campaignId: string, data: StartCampaignIn, params: RequestParams = {}) =>
        this.request<StartCampaignOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/start`,
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
     * @tags ai-device-lab
     * @name MaterializeSlotsRouteApiAiDeviceLabServiceCampaignsCampaignIdSlotsMaterializePost
     * @summary Materialize Slots Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/slots/materialize
     * @secure
     */
    materializeSlotsRouteApiAiDeviceLabServiceCampaignsCampaignIdSlotsMaterializePost:
      (campaignId: string, params: RequestParams = {}) =>
        this.request<MaterializeSlotsOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/slots/materialize`,
          method: "POST",
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name ServiceProgressRouteApiAiDeviceLabServiceCampaignsCampaignIdProgressGet
     * @summary Service Progress Route
     * @request GET:/api/ai-device-lab/service-campaigns/{campaign_id}/progress
     * @secure
     */
    serviceProgressRouteApiAiDeviceLabServiceCampaignsCampaignIdProgressGet: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<ServiceProgressOut, HTTPValidationError>({
        path: `/api/ai-device-lab/service-campaigns/${campaignId}/progress`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name ListServiceLanesRouteApiAiDeviceLabServiceCampaignsCampaignIdLanesGet
     * @summary List Service Lanes Route
     * @request GET:/api/ai-device-lab/service-campaigns/{campaign_id}/lanes
     * @secure
     */
    listServiceLanesRouteApiAiDeviceLabServiceCampaignsCampaignIdLanesGet: (
      campaignId: string,
      query?: {
        /**
         * Offset
         * @min 0
         * @default 0
         */
        offset?: number;
        /**
         * Limit
         * @min 1
         * @max 50
         * @default 12
         */
        limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<ServiceLaneListOut, HTTPValidationError>({
        path: `/api/ai-device-lab/service-campaigns/${campaignId}/lanes`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name GetServiceLaneDetailRouteApiAiDeviceLabServiceCampaignsCampaignIdLanesLaneIdGet
     * @summary Get Service Lane Detail Route
     * @request GET:/api/ai-device-lab/service-campaigns/{campaign_id}/lanes/{lane_id}
     * @secure
     */
    getServiceLaneDetailRouteApiAiDeviceLabServiceCampaignsCampaignIdLanesLaneIdGet:
      (
        campaignId: string,
        laneId: string,
        query?: {
          /**
           * Slot Offset
           * @min 0
           * @default 0
           */
          slot_offset?: number;
          /**
           * Slot Limit
           * @min 1
           * @max 50
           * @default 14
           */
          slot_limit?: number;
        },
        params: RequestParams = {},
      ) =>
        this.request<ServiceLaneDetailOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/lanes/${laneId}`,
          method: "GET",
          query: query,
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name CreateEvidenceDownloadUrlRouteApiAiDeviceLabServiceCampaignsCampaignIdEvidenceEvidenceIdDownloadUrlPost
     * @summary Create Evidence Download Url Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/evidence/{evidence_id}/download-url
     * @secure
     */
    createEvidenceDownloadUrlRouteApiAiDeviceLabServiceCampaignsCampaignIdEvidenceEvidenceIdDownloadUrlPost:
      (campaignId: string, evidenceId: string, params: RequestParams = {}) =>
        this.request<EvidenceDownloadOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/evidence/${evidenceId}/download-url`,
          method: "POST",
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name ListCampaignParticipationRouteApiAiDeviceLabServiceCampaignsCampaignIdParticipationGet
     * @summary List Campaign Participation Route
     * @request GET:/api/ai-device-lab/service-campaigns/{campaign_id}/participation
     * @secure
     */
    listCampaignParticipationRouteApiAiDeviceLabServiceCampaignsCampaignIdParticipationGet:
      (
        campaignId: string,
        query?: {
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
           * @default 25
           */
          limit?: number;
        },
        params: RequestParams = {},
      ) =>
        this.request<ParticipationListOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/participation`,
          method: "GET",
          query: query,
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name RecordCampaignParticipationRouteApiAiDeviceLabServiceCampaignsCampaignIdParticipationPost
     * @summary Record Campaign Participation Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/participation
     * @secure
     */
    recordCampaignParticipationRouteApiAiDeviceLabServiceCampaignsCampaignIdParticipationPost:
      (
        campaignId: string,
        data: RecordParticipationIn,
        params: RequestParams = {},
      ) =>
        this.request<ParticipationRecordOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/participation`,
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
     * @tags ai-device-lab
     * @name ListCampaignIssuesRouteApiAiDeviceLabServiceCampaignsCampaignIdIssuesGet
     * @summary List Campaign Issues Route
     * @request GET:/api/ai-device-lab/service-campaigns/{campaign_id}/issues
     * @secure
     */
    listCampaignIssuesRouteApiAiDeviceLabServiceCampaignsCampaignIdIssuesGet: (
      campaignId: string,
      query?: {
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
         * @default 25
         */
        limit?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<IssueListOut, HTTPValidationError>({
        path: `/api/ai-device-lab/service-campaigns/${campaignId}/issues`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name CreateCampaignIssueRouteApiAiDeviceLabServiceCampaignsCampaignIdIssuesPost
     * @summary Create Campaign Issue Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/issues
     * @secure
     */
    createCampaignIssueRouteApiAiDeviceLabServiceCampaignsCampaignIdIssuesPost:
      (campaignId: string, data: CreateIssueIn, params: RequestParams = {}) =>
        this.request<IssueSummaryOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/issues`,
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
     * @tags ai-device-lab
     * @name RequestCampaignRetestRouteApiAiDeviceLabServiceCampaignsCampaignIdIssuesIssueIdRetestsPost
     * @summary Request Campaign Retest Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/issues/{issue_id}/retests
     * @secure
     */
    requestCampaignRetestRouteApiAiDeviceLabServiceCampaignsCampaignIdIssuesIssueIdRetestsPost:
      (
        campaignId: string,
        issueId: string,
        data: RequestRetestIn,
        params: RequestParams = {},
      ) =>
        this.request<RetestRequestOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/issues/${issueId}/retests`,
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
     * @tags ai-device-lab
     * @name ListCampaignReportsRouteApiAiDeviceLabServiceCampaignsCampaignIdReportsGet
     * @summary List Campaign Reports Route
     * @request GET:/api/ai-device-lab/service-campaigns/{campaign_id}/reports
     * @secure
     */
    listCampaignReportsRouteApiAiDeviceLabServiceCampaignsCampaignIdReportsGet:
      (
        campaignId: string,
        query?: {
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
           * @default 20
           */
          limit?: number;
        },
        params: RequestParams = {},
      ) =>
        this.request<ReportListOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/reports`,
          method: "GET",
          query: query,
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name PublishCampaignReportRouteApiAiDeviceLabServiceCampaignsCampaignIdReportsReportIdPublishPost
     * @summary Publish Campaign Report Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/reports/{report_id}/publish
     * @secure
     */
    publishCampaignReportRouteApiAiDeviceLabServiceCampaignsCampaignIdReportsReportIdPublishPost:
      (campaignId: string, reportId: string, params: RequestParams = {}) =>
        this.request<ReportSummaryOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/reports/${reportId}/publish`,
          method: "POST",
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name CreateReportDownloadUrlRouteApiAiDeviceLabServiceCampaignsCampaignIdReportsReportIdDownloadUrlPost
     * @summary Create Report Download Url Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/reports/{report_id}/download-url
     * @secure
     */
    createReportDownloadUrlRouteApiAiDeviceLabServiceCampaignsCampaignIdReportsReportIdDownloadUrlPost:
      (campaignId: string, reportId: string, params: RequestParams = {}) =>
        this.request<ReportDownloadOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/reports/${reportId}/download-url`,
          method: "POST",
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name ReplaceLaneDeviceRouteApiAiDeviceLabServiceCampaignsCampaignIdLanesLaneIdReplacePost
     * @summary Replace Lane Device Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/lanes/{lane_id}/replace
     * @secure
     */
    replaceLaneDeviceRouteApiAiDeviceLabServiceCampaignsCampaignIdLanesLaneIdReplacePost:
      (
        campaignId: string,
        laneId: string,
        data: ReplaceLaneDeviceIn,
        params: RequestParams = {},
      ) =>
        this.request<FleetLifecycleOperationOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/lanes/${laneId}/replace`,
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
     * @tags ai-device-lab
     * @name CompleteReplacementRouteApiAiDeviceLabServiceCampaignsCampaignIdOperationsOperationIdCompleteReplacementPost
     * @summary Complete Replacement Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/operations/{operation_id}/complete-replacement
     * @secure
     */
    completeReplacementRouteApiAiDeviceLabServiceCampaignsCampaignIdOperationsOperationIdCompleteReplacementPost:
      (campaignId: string, operationId: string, params: RequestParams = {}) =>
        this.request<FleetLifecycleOperationOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/operations/${operationId}/complete-replacement`,
          method: "POST",
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name ExtendServiceCampaignRouteApiAiDeviceLabServiceCampaignsCampaignIdExtendPost
     * @summary Extend Service Campaign Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/extend
     * @secure
     */
    extendServiceCampaignRouteApiAiDeviceLabServiceCampaignsCampaignIdExtendPost:
      (
        campaignId: string,
        data: ExtendServiceCampaignIn,
        params: RequestParams = {},
      ) =>
        this.request<ServiceExtensionOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/extend`,
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
     * @tags ai-device-lab
     * @name CancelServiceCampaignRouteApiAiDeviceLabServiceCampaignsCampaignIdCancelPost
     * @summary Cancel Service Campaign Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/cancel
     * @secure
     */
    cancelServiceCampaignRouteApiAiDeviceLabServiceCampaignsCampaignIdCancelPost:
      (
        campaignId: string,
        data: CancelServiceCampaignIn,
        params: RequestParams = {},
      ) =>
        this.request<FleetLifecycleOperationOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/cancel`,
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
     * @tags ai-device-lab
     * @name ExpireServiceCampaignRouteApiAiDeviceLabServiceCampaignsCampaignIdExpirePost
     * @summary Expire Service Campaign Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/expire
     * @secure
     */
    expireServiceCampaignRouteApiAiDeviceLabServiceCampaignsCampaignIdExpirePost:
      (
        campaignId: string,
        data: CancelServiceCampaignIn,
        params: RequestParams = {},
      ) =>
        this.request<FleetLifecycleOperationOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/expire`,
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
     * @tags ai-device-lab
     * @name CompleteCancellationRouteApiAiDeviceLabServiceCampaignsCampaignIdOperationsOperationIdCompleteCancellationPost
     * @summary Complete Cancellation Route
     * @request POST:/api/ai-device-lab/service-campaigns/{campaign_id}/operations/{operation_id}/complete-cancellation
     * @secure
     */
    completeCancellationRouteApiAiDeviceLabServiceCampaignsCampaignIdOperationsOperationIdCompleteCancellationPost:
      (campaignId: string, operationId: string, params: RequestParams = {}) =>
        this.request<FleetLifecycleOperationOut, HTTPValidationError>({
          path: `/api/ai-device-lab/service-campaigns/${campaignId}/operations/${operationId}/complete-cancellation`,
          method: "POST",
          secure: true,
          format: "json",
          ...params,
        }),

    /**
     * No description
     *
     * @tags ai-device-lab
     * @name SignKpiDefinitionRouteApiAiDeviceLabKpiDefinitionsPost
     * @summary Sign Kpi Definition Route
     * @request POST:/api/ai-device-lab/kpi/definitions
     * @secure
     */
    signKpiDefinitionRouteApiAiDeviceLabKpiDefinitionsPost: (
      data: SignKpiDefinitionIn,
      params: RequestParams = {},
    ) =>
      this.request<KpiDefinitionOut, HTTPValidationError>({
        path: `/api/ai-device-lab/kpi/definitions`,
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
     * @tags ai-device-lab
     * @name FreezeKpiCohortRouteApiAiDeviceLabKpiCohortsPost
     * @summary Freeze Kpi Cohort Route
     * @request POST:/api/ai-device-lab/kpi/cohorts
     * @secure
     */
    freezeKpiCohortRouteApiAiDeviceLabKpiCohortsPost: (
      data: FreezeKpiCohortIn,
      params: RequestParams = {},
    ) =>
      this.request<KpiCohortOut, HTTPValidationError>({
        path: `/api/ai-device-lab/kpi/cohorts`,
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
     * @tags ai-device-lab
     * @name RecordKpiAssistanceRouteApiAiDeviceLabKpiAssistanceEventsPost
     * @summary Record Kpi Assistance Route
     * @request POST:/api/ai-device-lab/kpi/assistance-events
     * @secure
     */
    recordKpiAssistanceRouteApiAiDeviceLabKpiAssistanceEventsPost: (
      data: RecordKpiAssistanceIn,
      params: RequestParams = {},
    ) =>
      this.request<KpiAssistanceOut, HTTPValidationError>({
        path: `/api/ai-device-lab/kpi/assistance-events`,
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
     * @tags ai-device-lab
     * @name ComputeKpiSnapshotRouteApiAiDeviceLabKpiCohortsCohortIdSnapshotsPost
     * @summary Compute Kpi Snapshot Route
     * @request POST:/api/ai-device-lab/kpi/cohorts/{cohort_id}/snapshots
     * @secure
     */
    computeKpiSnapshotRouteApiAiDeviceLabKpiCohortsCohortIdSnapshotsPost: (
      cohortId: string,
      data: ComputeKpiSnapshotIn,
      params: RequestParams = {},
    ) =>
      this.request<KpiSnapshotOut, HTTPValidationError>({
        path: `/api/ai-device-lab/kpi/cohorts/${cohortId}/snapshots`,
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
     * @tags ai-device-lab
     * @name BuildAcceptanceCandidateRouteApiAiDeviceLabAcceptanceCandidatesPost
     * @summary Build Acceptance Candidate Route
     * @request POST:/api/ai-device-lab/acceptance/candidates
     * @secure
     */
    buildAcceptanceCandidateRouteApiAiDeviceLabAcceptanceCandidatesPost: (
      data: BuildAcceptanceCandidateIn,
      params: RequestParams = {},
    ) =>
      this.request<AcceptanceCandidateOut, HTTPValidationError>({
        path: `/api/ai-device-lab/acceptance/candidates`,
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
     * @tags ai-device-lab
     * @name EvaluateAcceptanceCandidateRouteApiAiDeviceLabAcceptanceCandidatesCandidateIdEvaluatePost
     * @summary Evaluate Acceptance Candidate Route
     * @request POST:/api/ai-device-lab/acceptance/candidates/{candidate_id}/evaluate
     * @secure
     */
    evaluateAcceptanceCandidateRouteApiAiDeviceLabAcceptanceCandidatesCandidateIdEvaluatePost:
      (
        candidateId: string,
        data: EvaluateAcceptanceCandidateIn,
        params: RequestParams = {},
      ) =>
        this.request<AcceptanceDecisionOut, HTTPValidationError>({
          path: `/api/ai-device-lab/acceptance/candidates/${candidateId}/evaluate`,
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
     * @name ApiScenarioDeviceCapabilitiesApiScenarioDeviceCapabilitiesSerialGet
     * @summary Api Scenario Device Capabilities
     * @request GET:/api/scenario/device-capabilities/{serial}
     * @secure
     */
    apiScenarioDeviceCapabilitiesApiScenarioDeviceCapabilitiesSerialGet: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/scenario/device-capabilities/${serial}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiScenarioPreflightApiScenarioPreflightSerialPost
     * @summary Api Scenario Preflight
     * @request POST:/api/scenario/preflight/{serial}
     * @secure
     */
    apiScenarioPreflightApiScenarioPreflightSerialPost: (
      serial: string,
      data: Record<string, any>,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/scenario/preflight/${serial}`,
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
     * @name ApiScrcpyHeartbeatApiDevicesSerialScrcpyHeartbeatPost
     * @summary Api Scrcpy Heartbeat
     * @request POST:/api/devices/{serial}/scrcpy/heartbeat
     * @secure
     */
    apiScrcpyHeartbeatApiDevicesSerialScrcpyHeartbeatPost: (
      serial: string,
      data: ScrcpyDetachRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/scrcpy/heartbeat`,
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
      data: ScrcpyDetachRequest | null,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/scrcpy/detach`,
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
        /**
         * Priority
         * @default "background"
         */
        priority?: string;
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
     * @name ApiScenarioPreviewStreamInputApiDevicesSerialScenarioPreviewStreamTraceIdInputPost
     * @summary Api Scenario Preview Stream Input
     * @request POST:/api/devices/{serial}/scenario/preview-stream/{trace_id}/input
     * @secure
     */
    apiScenarioPreviewStreamInputApiDevicesSerialScenarioPreviewStreamTraceIdInputPost:
      (
        serial: string,
        traceId: string,
        data: InputTextRequest,
        params: RequestParams = {},
      ) =>
        this.request<any, HTTPValidationError>({
          path: `/api/devices/${serial}/scenario/preview-stream/${traceId}/input`,
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
     * @description Pause running scenarios on a device and allow manual input takeover.
     *
     * @tags device-control
     * @name ApiDeviceTakeoverApiDevicesSerialTakeoverPost
     * @summary Api Device Takeover
     * @request POST:/api/devices/{serial}/takeover
     * @secure
     */
    apiDeviceTakeoverApiDevicesSerialTakeoverPost: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/takeover`,
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

    /**
     * No description
     *
     * @name MjpegStreamApiStreamSerialGet
     * @summary Mjpeg Stream
     * @request GET:/api/stream/{serial}
     * @secure
     */
    mjpegStreamApiStreamSerialGet: (
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
        path: `/api/stream/${serial}`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @name ScreenshotApiScreenshotSerialGet
     * @summary Screenshot
     * @request GET:/api/screenshot/{serial}
     * @secure
     */
    screenshotApiScreenshotSerialGet: (
      serial: string,
      query?: {
        /**
         * Fresh
         * @default false
         */
        fresh?: boolean;
        /** Max Age Ms */
        max_age_ms?: number | null;
        /** Max Width */
        max_width?: number | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/screenshot/${serial}`,
        method: "GET",
        query: query,
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Screenshot as base64 JPEG. Cropping is done client-side.
     *
     * @name ScreenshotB64ApiScreenshotB64SerialGet
     * @summary Screenshot B64
     * @request GET:/api/screenshot-b64/{serial}
     * @secure
     */
    screenshotB64ApiScreenshotB64SerialGet: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/screenshot-b64/${serial}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @name CreateSessionApiMediaWebrtcSessionsPost
     * @summary Create Session
     * @request POST:/api/media/webrtc/sessions
     * @secure
     */
    createSessionApiMediaWebrtcSessionsPost: (
      data: WebRTCSessionCreate,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/media/webrtc/sessions`,
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
     * @name AnswerSessionApiMediaWebrtcSessionsSessionIdAnswerPost
     * @summary Answer Session
     * @request POST:/api/media/webrtc/sessions/{session_id}/answer
     * @secure
     */
    answerSessionApiMediaWebrtcSessionsSessionIdAnswerPost: (
      sessionId: string,
      data: SessionDescription,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/media/webrtc/sessions/${sessionId}/answer`,
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
     * @name HeartbeatSessionApiMediaWebrtcSessionsSessionIdHeartbeatPost
     * @summary Heartbeat Session
     * @request POST:/api/media/webrtc/sessions/{session_id}/heartbeat
     * @secure
     */
    heartbeatSessionApiMediaWebrtcSessionsSessionIdHeartbeatPost: (
      sessionId: string,
      data: WebRTCSessionHeartbeat,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/media/webrtc/sessions/${sessionId}/heartbeat`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description The cheap rung of the viewer's stall ladder. A decoder that stalls while bytes keep arriving has a broken reference chain; one IDR repairs it in about 100ms with the PeerConnection intact, where the next rung rebuilds the session and flashes the picture black. Only the gRPC control plane carries this. The direct-HTTP adapter has no such endpoint, and inventing a 404 round trip to find that out would just add latency to a caller that already escalates on failure.
     *
     * @name RequestKeyframeApiMediaWebrtcSessionsSessionIdKeyframePost
     * @summary Request Keyframe
     * @request POST:/api/media/webrtc/sessions/{session_id}/keyframe
     * @secure
     */
    requestKeyframeApiMediaWebrtcSessionsSessionIdKeyframePost: (
      sessionId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/media/webrtc/sessions/${sessionId}/keyframe`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @name CloseSessionApiMediaWebrtcSessionsSessionIdDelete
     * @summary Close Session
     * @request DELETE:/api/media/webrtc/sessions/{session_id}
     * @secure
     */
    closeSessionApiMediaWebrtcSessionsSessionIdDelete: (
      sessionId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/media/webrtc/sessions/${sessionId}`,
        method: "DELETE",
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
