import { farmApi } from '@/lib/farm-api';
import type {
  ApproveWizardScenarioIn,
  CampaignFunnelOut,
  CancelServiceCampaignIn,
  CreateIssueIn,
  EvidenceDownloadOut,
  ExtendServiceCampaignIn,
  FleetLifecycleOperationOut,
  IssueListOut,
  IssueSummaryOut,
  PaymentReconciliationListOut,
  ParticipationListOut,
  ParticipationRecordOut,
  RecordParticipationIn,
  ReplaceLaneDeviceIn,
  ReportDownloadOut,
  ReportListOut,
  RequestRetestIn,
  RetestRequestOut,
  SaveWizardDraftIn,
  ServiceCampaignOut,
  ServiceLaneDetailOut,
  ServiceLaneListOut,
  ServiceExtensionOut,
  StartCampaignOut,
  StartWizardCheckoutIn,
  StartWizardGenerationIn,
  WizardCheckoutOut,
  WizardStateOut
} from '@/features/device-farm/services/generated/DeviceFarmApi';

export type ServiceCampaign = ServiceCampaignOut;
export type WizardState = WizardStateOut;
export type WizardDraft = SaveWizardDraftIn;
export type ServiceLaneList = ServiceLaneListOut;
export type ServiceLaneDetail = ServiceLaneDetailOut;
export type ParticipationList = ParticipationListOut;
export type ReportList = ReportListOut;
export type IssueList = IssueListOut;
export type IssueSummary = IssueSummaryOut;
export type PaymentReconciliationList = PaymentReconciliationListOut;
export type FleetLifecycleOperation = FleetLifecycleOperationOut;
export type ServiceExtension = ServiceExtensionOut;
export type CampaignFunnel = CampaignFunnelOut;

export type ServiceProgress = {
  service: {
    planned: number;
    attempted: number;
    terminal: number;
    missed: number;
  };
  app_quality: {
    evaluated: number;
    pass: number;
    fail: number;
    inconclusive: number;
  };
  play_participation: {
    identities: number;
    opted_in: number;
    lost: number;
    unknown: number;
  };
};

export type ServiceCampaignWorkspace = {
  campaign: ServiceCampaign;
  progress: ServiceProgress;
};

export type CreateServiceCampaignInput = {
  creation_intent_key: string;
  runtime_campaign_id: string;
  package_name: string;
  timezone: string;
  plan_version: string;
  acquisition_events: Array<{
    event_id: string;
    event_name: 'landing_view' | 'start_click';
    occurred_at: string;
    attribution: Record<string, string>;
  }>;
};

export async function createServiceCampaign(
  input: CreateServiceCampaignInput
): Promise<ServiceCampaign> {
  const response = await farmApi.post<ServiceCampaign>(
    '/ai-device-lab/service-campaigns',
    input
  );
  return response.data;
}

export async function loadServiceCampaignWorkspace(
  campaignId: string,
  signal?: AbortSignal
): Promise<ServiceCampaignWorkspace> {
  const encoded = encodeURIComponent(campaignId);
  const [campaign, progress] = await Promise.all([
    farmApi.get<ServiceCampaign>(
      `/ai-device-lab/service-campaigns/${encoded}`,
      { signal }
    ),
    farmApi.get<ServiceProgress>(
      `/ai-device-lab/service-campaigns/${encoded}/progress`,
      { signal }
    )
  ]);
  return { campaign: campaign.data, progress: progress.data };
}

export async function loadCampaignFunnel(
  campaignId: string,
  signal?: AbortSignal
): Promise<CampaignFunnel> {
  const response = await farmApi.get<CampaignFunnel>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/funnel`,
    { signal }
  );
  return response.data;
}

export async function loadWizardState(
  campaignId: string,
  signal?: AbortSignal
): Promise<WizardState> {
  const response = await farmApi.get<WizardState>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/wizard`,
    { signal }
  );
  return response.data;
}

export async function saveWizardDraft(
  campaignId: string,
  input: WizardDraft
): Promise<WizardState> {
  const response = await farmApi.put<WizardState>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/wizard/app`,
    input
  );
  return response.data;
}

export async function generateWizardScenario(
  campaignId: string,
  input: StartWizardGenerationIn
): Promise<WizardState> {
  const response = await farmApi.post<WizardState>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/wizard/scenario/generate`,
    input
  );
  return response.data;
}

export async function approveWizardScenario(
  campaignId: string,
  input: ApproveWizardScenarioIn
): Promise<WizardState> {
  const response = await farmApi.post<WizardState>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/wizard/scenario/approve`,
    input
  );
  return response.data;
}

export async function startWizardCheckout(
  campaignId: string,
  input: StartWizardCheckoutIn
): Promise<WizardCheckoutOut> {
  const response = await farmApi.post<WizardCheckoutOut>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/wizard/payment/checkout`,
    input
  );
  return response.data;
}

export async function checkWizardReadiness(
  campaignId: string,
  idempotencyKey: string
): Promise<StartCampaignOut> {
  const response = await farmApi.post<StartCampaignOut>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/start`,
    { idempotency_key: idempotencyKey }
  );
  return response.data;
}

export async function loadServiceLanes(
  campaignId: string,
  signal?: AbortSignal
): Promise<ServiceLaneList> {
  const response = await farmApi.get<ServiceLaneList>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/lanes`,
    { params: { offset: 0, limit: 12 }, signal }
  );
  return response.data;
}

export async function loadServiceLaneDetail(
  campaignId: string,
  laneId: string,
  signal?: AbortSignal
): Promise<ServiceLaneDetail> {
  const response = await farmApi.get<ServiceLaneDetail>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/lanes/${encodeURIComponent(laneId)}`,
    { params: { slot_offset: 0, slot_limit: 50 }, signal }
  );
  return response.data;
}

export async function loadParticipation(
  campaignId: string,
  signal?: AbortSignal
): Promise<ParticipationList> {
  const response = await farmApi.get<ParticipationList>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/participation`,
    { params: { offset: 0, limit: 100 }, signal }
  );
  return response.data;
}

export async function recordParticipation(
  campaignId: string,
  input: RecordParticipationIn
): Promise<ParticipationRecordOut> {
  const response = await farmApi.post<ParticipationRecordOut>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/participation`,
    input
  );
  return response.data;
}

export async function loadIssues(
  campaignId: string,
  signal?: AbortSignal
): Promise<IssueList> {
  const response = await farmApi.get<IssueList>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/issues`,
    { params: { offset: 0, limit: 100 }, signal }
  );
  return response.data;
}

export async function loadPaymentReconciliations(
  campaignId: string,
  signal?: AbortSignal
): Promise<PaymentReconciliationList> {
  const response = await farmApi.get<PaymentReconciliationList>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/payment-reconciliations`,
    { params: { offset: 0, limit: 50 }, signal }
  );
  return response.data;
}

export async function createIssue(
  campaignId: string,
  input: CreateIssueIn
): Promise<IssueSummary> {
  const response = await farmApi.post<IssueSummary>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/issues`,
    input
  );
  return response.data;
}

export async function requestRetest(
  campaignId: string,
  issueId: string,
  input: RequestRetestIn
): Promise<RetestRequestOut> {
  const response = await farmApi.post<RetestRequestOut>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/issues/${encodeURIComponent(issueId)}/retests`,
    input
  );
  return response.data;
}

export async function loadReports(
  campaignId: string,
  signal?: AbortSignal
): Promise<ReportList> {
  const response = await farmApi.get<ReportList>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/reports`,
    { params: { offset: 0, limit: 20 }, signal }
  );
  return response.data;
}

export async function createReportDownloadUrl(
  campaignId: string,
  reportId: string
): Promise<ReportDownloadOut> {
  const response = await farmApi.post<ReportDownloadOut>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/reports/${encodeURIComponent(reportId)}/download-url`
  );
  return response.data;
}

export async function createEvidenceDownloadUrl(
  campaignId: string,
  evidenceId: string
): Promise<EvidenceDownloadOut> {
  const response = await farmApi.post<EvidenceDownloadOut>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/evidence/${encodeURIComponent(evidenceId)}/download-url`
  );
  return response.data;
}

export async function replaceLaneDevice(
  campaignId: string,
  laneId: string,
  input: ReplaceLaneDeviceIn
): Promise<FleetLifecycleOperation> {
  const response = await farmApi.post<FleetLifecycleOperation>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/lanes/${encodeURIComponent(laneId)}/replace`,
    input
  );
  return response.data;
}

export async function completeDeviceReplacement(
  campaignId: string,
  operationId: string
): Promise<FleetLifecycleOperation> {
  const response = await farmApi.post<FleetLifecycleOperation>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/operations/${encodeURIComponent(operationId)}/complete-replacement`
  );
  return response.data;
}

export async function extendServiceCampaign(
  campaignId: string,
  input: ExtendServiceCampaignIn
): Promise<ServiceExtension> {
  const response = await farmApi.post<ServiceExtension>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/extend`,
    input
  );
  return response.data;
}

export async function cancelServiceCampaign(
  campaignId: string,
  input: CancelServiceCampaignIn
): Promise<FleetLifecycleOperation> {
  const response = await farmApi.post<FleetLifecycleOperation>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/cancel`,
    input
  );
  return response.data;
}

export async function completeCampaignCancellation(
  campaignId: string,
  operationId: string
): Promise<FleetLifecycleOperation> {
  const response = await farmApi.post<FleetLifecycleOperation>(
    `/ai-device-lab/service-campaigns/${encodeURIComponent(campaignId)}/operations/${encodeURIComponent(operationId)}/complete-cancellation`
  );
  return response.data;
}
