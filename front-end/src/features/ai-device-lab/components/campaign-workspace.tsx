'use client';

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState
} from 'react';
import {
  AlertTriangle,
  Download,
  ExternalLink,
  RefreshCw,
  ShieldCheck,
  Wrench
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

import {
  cancelServiceCampaign,
  completeCampaignCancellation,
  completeDeviceReplacement,
  createEvidenceDownloadUrl,
  createIssue,
  createReportDownloadUrl,
  extendServiceCampaign,
  loadIssues,
  loadPaymentReconciliations,
  loadParticipation,
  loadReports,
  loadServiceCampaignWorkspace,
  loadServiceLaneDetail,
  loadServiceLanes,
  recordParticipation,
  replaceLaneDevice,
  requestRetest,
  type FleetLifecycleOperation,
  type IssueList,
  type IssueSummary,
  type PaymentReconciliationList,
  type ParticipationList,
  type ReportList,
  type ServiceCampaignWorkspace,
  type ServiceLaneDetail,
  type ServiceLaneList
} from '../services/ai-device-lab-api';

type Locale = 'en' | 'vi';

const copy = {
  en: {
    title: 'Campaign workspace',
    loading: 'Loading authoritative campaign sources…',
    error: 'Campaign data could not be loaded.',
    retry: 'Retry',
    refresh: 'Refresh sources',
    lanes: 'logical lanes',
    lanesTab: 'Lanes',
    overview: 'Overview',
    participationTab: 'Participation',
    reportsTab: 'Reports',
    qualityTab: 'Issues & retests',
    operationsTab: 'Operations',
    billingTab: 'Payment review',
    service: 'Service progress',
    quality: 'App testing quality',
    participation: 'Play participation',
    terminal: 'terminal',
    planned: 'planned slots',
    evaluated: 'evaluated',
    passed: 'passed',
    identities: 'identities',
    optedIn: 'opted in',
    source: 'Tenant-scoped backend source',
    empty: 'No denominator is available yet.',
    noRows: 'No records are available for this campaign.',
    distinction:
      'Service delivery, app quality and Play participation are independent sources.',
    open: 'Open',
    history: 'history',
    day: 'Day',
    attempts: 'attempts',
    reservations: 'Reservation history',
    evidence: 'Evidence',
    openEvidence: 'Open evidence',
    noAttempts: 'No attempt has been recorded for this slot.',
    segment: 'continuity segment',
    lastObserved: 'Last observed',
    neverObserved: 'No reviewed observation',
    report: 'Report',
    cutoff: 'Cutoff',
    download: 'Download report',
    unavailable: 'PDF is not available.',
    privateDownload:
      'A short-lived private URL is created only when requested.',
    operations: 'Fleet lifecycle operations',
    operationsHelp:
      'Each request uses a fresh idempotency key. Completion remains separate until drain succeeds.',
    replaceDevice: 'Replace device',
    selectedLane: 'Lane',
    newDeviceId: 'New device ID',
    reason: 'Reason',
    requestReplacement: 'Request replacement',
    completeDrain: 'Complete drained operation',
    extendCampaign: 'Extend campaign',
    addedDays: 'Added service days',
    orderId: 'Verified order ID',
    entitlementId: 'Entitlement ID',
    amountMinor: 'Amount in minor units',
    currency: 'Currency',
    policyVersion: 'Policy version',
    pricingVersion: 'Pricing version',
    consent: 'I confirm the approved price and extension consent.',
    requestExtension: 'Request extension',
    cancelCampaign: 'Cancel campaign',
    cancelConfirm: 'Type CANCEL to confirm',
    requestCancellation: 'Request cancellation',
    operationResult: 'Latest operation',
    operationPending: 'Submitting operation…',
    recordEvidence: 'Record participation evidence',
    pseudonymousRef: 'Pseudonymous account reference',
    maskedLabel: 'Masked label',
    trackName: 'Track name',
    eventType: 'Observation',
    sourceType: 'Source type',
    evidenceRef: 'Private evidence reference',
    evidenceGrade: 'Evidence grade',
    approveEvidence: 'Approve this observation as the current reviewer.',
    submitEvidence: 'Record evidence',
    qualityIssues: 'App issues and retests',
    sourceAttempt: 'Failed attempt ID',
    severity: 'Severity',
    assertionKey: 'Assertion key',
    expected: 'Expected',
    actual: 'Actual',
    reproduction: 'Reproduction step/path',
    createIssue: 'Create issue',
    requestRetest: 'Request retest',
    targetBuild: 'Target build ID',
    targetScenario: 'Target scenario version ID',
    laneScope: 'Lane',
    retestConsent: 'I approve the stated retest quota/cost.',
    noIssue: 'No issue has been recorded.',
    paymentReconciliation: 'Payment reconciliation queue',
    paymentReconciliationHelp:
      'Only sanitized provider state is shown. Checkout references and provider error bodies remain private.',
    noPaymentReconciliation: 'No payment needs reconciliation.'
  },
  vi: {
    title: 'Không gian campaign',
    loading: 'Đang tải nguồn campaign có thẩm quyền…',
    error: 'Không tải được dữ liệu campaign.',
    retry: 'Thử lại',
    refresh: 'Làm mới nguồn',
    lanes: 'lane logic',
    lanesTab: 'Lane',
    overview: 'Tổng quan',
    participationTab: 'Tham gia',
    reportsTab: 'Báo cáo',
    qualityTab: 'Lỗi & retest',
    operationsTab: 'Vận hành',
    billingTab: 'Đối soát thanh toán',
    service: 'Tiến độ dịch vụ',
    quality: 'Chất lượng kiểm thử app',
    participation: 'Tham gia Google Play',
    terminal: 'đã kết thúc',
    planned: 'slot đã lên lịch',
    evaluated: 'đã đánh giá',
    passed: 'đạt',
    identities: 'định danh',
    optedIn: 'đã opt-in',
    source: 'Nguồn backend theo tenant',
    empty: 'Chưa có denominator để tính.',
    noRows: 'Campaign này chưa có dữ liệu.',
    distinction:
      'Dịch vụ, chất lượng app và tham gia Google Play là ba nguồn độc lập.',
    open: 'Mở',
    history: 'lịch sử',
    day: 'Ngày',
    attempts: 'lần chạy',
    reservations: 'Lịch sử giữ máy',
    evidence: 'Bằng chứng',
    openEvidence: 'Mở bằng chứng',
    noAttempts: 'Slot này chưa có lần chạy nào.',
    segment: 'đoạn liên tục',
    lastObserved: 'Quan sát gần nhất',
    neverObserved: 'Chưa có quan sát đã duyệt',
    report: 'Báo cáo',
    cutoff: 'Mốc dữ liệu',
    download: 'Tải báo cáo',
    unavailable: 'Chưa có PDF.',
    privateDownload: 'URL riêng tư, thời hạn ngắn chỉ được tạo khi yêu cầu.',
    operations: 'Vận hành vòng đời fleet',
    operationsHelp:
      'Mỗi yêu cầu dùng idempotency key mới. Bước hoàn tất tách riêng cho tới khi drain thành công.',
    replaceDevice: 'Thay thiết bị',
    selectedLane: 'Lane',
    newDeviceId: 'ID thiết bị mới',
    reason: 'Lý do',
    requestReplacement: 'Yêu cầu thay máy',
    completeDrain: 'Hoàn tất thao tác đã drain',
    extendCampaign: 'Gia hạn campaign',
    addedDays: 'Số ngày dịch vụ thêm',
    orderId: 'Order ID đã xác minh',
    entitlementId: 'Entitlement ID',
    amountMinor: 'Số tiền theo đơn vị nhỏ nhất',
    currency: 'Tiền tệ',
    policyVersion: 'Phiên bản chính sách',
    pricingVersion: 'Phiên bản giá',
    consent: 'Tôi xác nhận giá đã duyệt và đồng ý gia hạn.',
    requestExtension: 'Yêu cầu gia hạn',
    cancelCampaign: 'Hủy campaign',
    cancelConfirm: 'Nhập CANCEL để xác nhận',
    requestCancellation: 'Yêu cầu hủy',
    operationResult: 'Thao tác gần nhất',
    operationPending: 'Đang gửi thao tác…',
    recordEvidence: 'Ghi nhận bằng chứng tham gia',
    pseudonymousRef: 'Tham chiếu tài khoản giả danh',
    maskedLabel: 'Nhãn đã che',
    trackName: 'Tên track',
    eventType: 'Quan sát',
    sourceType: 'Loại nguồn',
    evidenceRef: 'Tham chiếu bằng chứng riêng tư',
    evidenceGrade: 'Cấp bằng chứng',
    approveEvidence: 'Duyệt quan sát này với tư cách reviewer hiện tại.',
    submitEvidence: 'Ghi nhận bằng chứng',
    qualityIssues: 'Lỗi ứng dụng và retest',
    sourceAttempt: 'ID lần chạy thất bại',
    severity: 'Mức độ',
    assertionKey: 'Khóa assertion',
    expected: 'Kỳ vọng',
    actual: 'Thực tế',
    reproduction: 'Bước/đường dẫn tái hiện',
    createIssue: 'Tạo lỗi',
    requestRetest: 'Yêu cầu retest',
    targetBuild: 'ID build đích',
    targetScenario: 'ID phiên bản scenario đích',
    laneScope: 'Lane',
    retestConsent: 'Tôi duyệt quota/chi phí retest đã nêu.',
    noIssue: 'Chưa ghi nhận lỗi.',
    paymentReconciliation: 'Hàng đợi đối soát thanh toán',
    paymentReconciliationHelp:
      'Chỉ hiển thị trạng thái provider đã làm sạch. Tham chiếu checkout và nội dung lỗi provider vẫn riêng tư.',
    noPaymentReconciliation: 'Không có thanh toán cần đối soát.'
  }
} satisfies Record<Locale, Record<string, string>>;

type WorkspaceDetails = {
  lanes: ServiceLaneList;
  participation: ParticipationList;
  reports: ReportList;
  issues: IssueList;
  paymentReconciliations: PaymentReconciliationList;
};

function percentage(numerator: number, denominator: number): number {
  if (denominator <= 0) return 0;
  return Math.min(100, Math.round((numerator / denominator) * 100));
}

function sentenceCase(value: string): string {
  if (!value) return value;
  const normalized = value.replaceAll('_', ' ');
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export function CampaignWorkspace({
  campaignId,
  locale
}: {
  campaignId: string;
  locale: Locale;
}) {
  const t = copy[locale];
  const [data, setData] = useState<ServiceCampaignWorkspace | null>(null);
  const [details, setDetails] = useState<WorkspaceDetails | null>(null);
  const [selectedLane, setSelectedLane] = useState<ServiceLaneDetail | null>(
    null
  );
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [laneLoading, setLaneLoading] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const laneHeadingRef = useRef<HTMLHeadingElement>(null);

  const reload = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all([
      loadServiceCampaignWorkspace(campaignId, controller.signal),
      loadServiceLanes(campaignId, controller.signal),
      loadParticipation(campaignId, controller.signal),
      loadReports(campaignId, controller.signal),
      loadIssues(campaignId, controller.signal),
      loadPaymentReconciliations(campaignId, controller.signal)
    ])
      .then(
        ([
          workspace,
          lanes,
          participation,
          reports,
          issues,
          paymentReconciliations
        ]) => {
          setData(workspace);
          setDetails({
            lanes,
            participation,
            reports,
            issues,
            paymentReconciliations
          });
          setSelectedLane(null);
        }
      )
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(formatFarmApiError(reason, t.error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [campaignId, revision, t.error]);

  const openLane = useCallback(
    async (laneId: string) => {
      setLaneLoading(true);
      setDetailError(null);
      try {
        const lane = await loadServiceLaneDetail(campaignId, laneId);
        setSelectedLane(lane);
        requestAnimationFrame(() => laneHeadingRef.current?.focus());
      } catch (reason) {
        setDetailError(formatFarmApiError(reason, t.error));
      } finally {
        setLaneLoading(false);
      }
    },
    [campaignId, t.error]
  );

  const downloadReport = useCallback(
    async (reportId: string) => {
      setDownloadingId(reportId);
      setDetailError(null);
      try {
        const download = await createReportDownloadUrl(campaignId, reportId);
        window.open(download.url, '_blank', 'noopener,noreferrer');
      } catch (reason) {
        setDetailError(formatFarmApiError(reason, t.error));
      } finally {
        setDownloadingId(null);
      }
    },
    [campaignId, t.error]
  );

  const downloadEvidence = useCallback(
    async (evidenceId: string) => {
      setDownloadingId(evidenceId);
      setDetailError(null);
      try {
        const download = await createEvidenceDownloadUrl(
          campaignId,
          evidenceId
        );
        window.open(download.url, '_blank', 'noopener,noreferrer');
      } catch (reason) {
        setDetailError(formatFarmApiError(reason, t.error));
      } finally {
        setDownloadingId(null);
      }
    },
    [campaignId, t.error]
  );

  return (
    <main className='min-h-screen bg-slate-50 px-5 py-8 text-slate-950 sm:px-8'>
      <section className='mx-auto max-w-6xl' aria-live='polite'>
        <header className='flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between'>
          <div>
            <div className='flex items-center gap-2 text-sm font-medium text-emerald-700'>
              <ShieldCheck className='size-4' aria-hidden='true' />
              AI Device Lab · {t.source}
            </div>
            <h1 className='mt-2 text-3xl font-semibold tracking-tight'>
              {t.title}
            </h1>
            <p className='mt-2 max-w-3xl text-sm leading-6 text-slate-600'>
              {t.distinction}
            </p>
          </div>
          <Button variant='outline' onClick={reload} disabled={loading}>
            <RefreshCw
              className={`mr-2 size-4 ${loading ? 'animate-spin' : ''}`}
              aria-hidden='true'
            />
            {t.refresh}
          </Button>
        </header>

        {loading && !data && (
          <div
            data-testid='workspace-loading'
            className='mt-10 rounded-xl border bg-white p-8 text-slate-600'
          >
            {t.loading}
          </div>
        )}
        {error && (
          <div
            role='alert'
            className='mt-10 rounded-xl border border-red-200 bg-red-50 p-5 text-red-900'
          >
            <div className='flex items-center gap-2 font-medium'>
              <AlertTriangle className='size-4' aria-hidden='true' />
              {error}
            </div>
            <Button className='mt-4' size='sm' onClick={reload}>
              {t.retry}
            </Button>
          </div>
        )}
        {detailError && (
          <div
            role='alert'
            className='mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-red-900'
          >
            {detailError}
          </div>
        )}
        {data && details && (
          <div className='mt-10'>
            <div className='flex flex-wrap items-center gap-3'>
              <h2 className='text-xl font-semibold'>
                {data.campaign.package_name}
              </h2>
              <Badge>{data.campaign.status}</Badge>
              <span className='text-sm text-slate-500'>
                {data.campaign.lane_count} {t.lanes}
              </span>
            </div>

            <Tabs defaultValue='overview' className='mt-6'>
              <TabsList className='h-auto max-w-full flex-wrap justify-start'>
                <TabsTrigger value='overview'>{t.overview}</TabsTrigger>
                <TabsTrigger value='lanes'>{t.lanesTab}</TabsTrigger>
                <TabsTrigger value='participation'>
                  {t.participationTab}
                </TabsTrigger>
                <TabsTrigger value='reports'>{t.reportsTab}</TabsTrigger>
                <TabsTrigger value='quality'>{t.qualityTab}</TabsTrigger>
                <TabsTrigger value='billing'>{t.billingTab}</TabsTrigger>
                <TabsTrigger value='operations'>{t.operationsTab}</TabsTrigger>
              </TabsList>

              <TabsContent value='overview'>
                <div className='mt-4 grid gap-4 lg:grid-cols-3'>
                  <MetricCard
                    testId='workspace-service'
                    title={t.service}
                    numerator={data.progress.service.terminal}
                    denominator={data.progress.service.planned}
                    numeratorLabel={t.terminal}
                    denominatorLabel={t.planned}
                    empty={t.empty}
                  />
                  <MetricCard
                    testId='workspace-quality'
                    title={t.quality}
                    numerator={data.progress.app_quality.pass}
                    denominator={data.progress.app_quality.evaluated}
                    numeratorLabel={t.passed}
                    denominatorLabel={t.evaluated}
                    empty={t.empty}
                  />
                  <MetricCard
                    testId='workspace-participation'
                    title={t.participation}
                    numerator={data.progress.play_participation.opted_in}
                    denominator={data.progress.play_participation.identities}
                    numeratorLabel={t.optedIn}
                    denominatorLabel={t.identities}
                    empty={t.empty}
                  />
                </div>
              </TabsContent>

              <TabsContent value='lanes'>
                <div className='mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-3'>
                  {details.lanes.items.map((lane) => (
                    <Card key={lane.id}>
                      <CardHeader>
                        <CardTitle className='text-base'>
                          {lane.tester_label}
                        </CardTitle>
                      </CardHeader>
                      <CardContent className='space-y-3 text-sm'>
                        <p>
                          {lane.terminal_slots} / {lane.planned_slots}{' '}
                          {t.terminal}
                        </p>
                        <p className='text-slate-600'>
                          {lane.active_reservation_count}{' '}
                          {t.reservations.toLowerCase()}
                        </p>
                        <Button
                          size='sm'
                          variant='outline'
                          disabled={laneLoading}
                          onClick={() => openLane(lane.id)}
                          aria-label={`${t.open} ${lane.tester_label}`}
                        >
                          <ExternalLink
                            className='mr-2 size-4'
                            aria-hidden='true'
                          />
                          {t.open}
                        </Button>
                      </CardContent>
                    </Card>
                  ))}
                </div>
                {details.lanes.items.length === 0 && <Empty text={t.noRows} />}
                {selectedLane && (
                  <LaneHistory
                    lane={selectedLane}
                    headingRef={laneHeadingRef}
                    copy={t}
                    downloadingId={downloadingId}
                    onDownloadEvidence={downloadEvidence}
                  />
                )}
              </TabsContent>

              <TabsContent value='participation'>
                <ParticipationEvidence
                  campaignId={campaignId}
                  copy={t}
                  onChanged={reload}
                />
                <div className='mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-3'>
                  {details.participation.items.map((participant) => (
                    <Card key={participant.id}>
                      <CardHeader>
                        <CardTitle className='text-base'>
                          {participant.masked_label}
                        </CardTitle>
                      </CardHeader>
                      <CardContent className='space-y-2 text-sm'>
                        <div className='flex flex-wrap gap-2'>
                          <Badge variant='outline'>
                            {participant.current_status}
                          </Badge>
                          <Badge variant='secondary'>
                            {participant.evidence_grade}
                          </Badge>
                        </div>
                        <p>{participant.track_name}</p>
                        <p className='text-slate-600'>
                          {t.segment} {participant.active_segment_no}
                        </p>
                        <p className='text-slate-600'>
                          {participant.last_observed_at
                            ? `${t.lastObserved}: ${new Date(
                                participant.last_observed_at
                              ).toLocaleString(locale)}`
                            : t.neverObserved}
                        </p>
                        {participant.gap_reason && (
                          <p className='text-amber-700'>
                            {participant.gap_reason}
                          </p>
                        )}
                      </CardContent>
                    </Card>
                  ))}
                </div>
                {details.participation.items.length === 0 && (
                  <Empty text={t.noRows} />
                )}
              </TabsContent>

              <TabsContent value='reports'>
                <p className='mt-4 text-sm text-slate-600'>
                  {t.privateDownload}
                </p>
                <div className='mt-4 grid gap-3 md:grid-cols-2'>
                  {details.reports.items.map((report) => (
                    <Card key={report.id}>
                      <CardHeader>
                        <CardTitle className='text-base'>
                          {t.report} v{report.version}
                        </CardTitle>
                      </CardHeader>
                      <CardContent className='space-y-3 text-sm'>
                        <div className='flex flex-wrap gap-2'>
                          <Badge>{report.status}</Badge>
                          <Badge variant='outline'>
                            {report.schema_version}
                          </Badge>
                        </div>
                        <p className='text-slate-600'>
                          {t.cutoff}:{' '}
                          {new Date(report.cutoff_at).toLocaleString(locale)}
                        </p>
                        <p className='break-all font-mono text-xs text-slate-500'>
                          SHA-256 {report.manifest_sha256}
                        </p>
                        <Button
                          size='sm'
                          disabled={
                            !report.download_available ||
                            downloadingId === report.id
                          }
                          onClick={() => downloadReport(report.id)}
                          aria-label={`${t.download} v${report.version}`}
                        >
                          <Download
                            className='mr-2 size-4'
                            aria-hidden='true'
                          />
                          {report.download_available
                            ? t.download
                            : t.unavailable}
                        </Button>
                      </CardContent>
                    </Card>
                  ))}
                </div>
                {details.reports.items.length === 0 && (
                  <Empty text={t.noRows} />
                )}
              </TabsContent>

              <TabsContent value='quality'>
                <QualityOperations
                  campaignId={campaignId}
                  lanes={details.lanes}
                  issues={details.issues}
                  copy={t}
                  onChanged={reload}
                />
              </TabsContent>

              <TabsContent value='billing'>
                <p className='mt-4 text-sm text-slate-600'>
                  {t.paymentReconciliationHelp}
                </p>
                <div className='mt-4 grid gap-3 md:grid-cols-2'>
                  {details.paymentReconciliations.items.map((job) => (
                    <Card key={job.id}>
                      <CardHeader>
                        <CardTitle className='text-base'>
                          {t.paymentReconciliation}
                        </CardTitle>
                      </CardHeader>
                      <CardContent className='space-y-2 text-sm'>
                        <div className='flex flex-wrap gap-2'>
                          <Badge>{job.status}</Badge>
                          <Badge variant='outline'>{job.provider}</Badge>
                        </div>
                        <p>{sentenceCase(job.reason_code)}</p>
                        {job.last_error_code && (
                          <p className='text-amber-700'>
                            {sentenceCase(job.last_error_code)}
                          </p>
                        )}
                        <p className='text-slate-600'>
                          {job.attempts} attempts ·{' '}
                          {new Date(job.created_at).toLocaleString(locale)}
                        </p>
                      </CardContent>
                    </Card>
                  ))}
                </div>
                {details.paymentReconciliations.items.length === 0 && (
                  <Empty text={t.noPaymentReconciliation} />
                )}
              </TabsContent>

              <TabsContent value='operations'>
                <LifecycleOperations
                  campaignId={campaignId}
                  lanes={details.lanes}
                  copy={t}
                  onChanged={reload}
                />
              </TabsContent>
            </Tabs>
          </div>
        )}
      </section>
    </main>
  );
}

function ParticipationEvidence({
  campaignId,
  copy: t,
  onChanged
}: {
  campaignId: string;
  copy: (typeof copy)[Locale];
  onChanged: () => void;
}) {
  const [accountRef, setAccountRef] = useState('');
  const [maskedLabel, setMaskedLabel] = useState('');
  const [trackName, setTrackName] = useState('closed');
  const [eventType, setEventType] = useState('opted_in');
  const [sourceType, setSourceType] = useState('operator_observation');
  const [evidenceRef, setEvidenceRef] = useState('');
  const [evidenceGrade, setEvidenceGrade] = useState('operator_attested');
  const [approve, setApprove] = useState(true);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPending(true);
    setMessage(null);
    setError(null);
    void recordParticipation(campaignId, {
      pseudonymous_account_ref: accountRef.trim(),
      masked_label: maskedLabel.trim(),
      track_name: trackName.trim(),
      event_type: eventType,
      source_type: sourceType.trim(),
      evidence_ref: evidenceRef.trim() || null,
      evidence_grade: evidenceGrade,
      observed_at: new Date().toISOString(),
      approve,
      source_ref: null,
      correction_of_id: null,
      limitations: null
    })
      .then((record) => {
        setMessage(
          `${record.participation.masked_label}: ${record.participation.current_status} · ${record.review_state}`
        );
        setAccountRef('');
        onChanged();
      })
      .catch((reason: unknown) => setError(formatFarmApiError(reason, t.error)))
      .finally(() => setPending(false));
  };

  return (
    <Card className='mt-4'>
      <CardHeader>
        <CardTitle className='text-base'>{t.recordEvidence}</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className='grid gap-3 md:grid-cols-2 lg:grid-cols-4'
          onSubmit={submit}
        >
          <label className='text-sm font-medium'>
            {t.pseudonymousRef}
            <Input
              className='mt-1'
              type='password'
              autoComplete='off'
              value={accountRef}
              onChange={(event) => setAccountRef(event.target.value)}
              required
            />
          </label>
          <label className='text-sm font-medium'>
            {t.maskedLabel}
            <Input
              className='mt-1'
              value={maskedLabel}
              onChange={(event) => setMaskedLabel(event.target.value)}
              required
            />
          </label>
          <label className='text-sm font-medium'>
            {t.trackName}
            <Input
              className='mt-1'
              value={trackName}
              onChange={(event) => setTrackName(event.target.value)}
              required
            />
          </label>
          <label className='text-sm font-medium'>
            {t.eventType}
            <select
              className='mt-1 h-10 w-full rounded-md border bg-white px-3'
              value={eventType}
              onChange={(event) => setEventType(event.target.value)}
            >
              <option value='opted_in'>opted_in</option>
              <option value='lost'>lost</option>
              <option value='rejoined'>rejoined</option>
              <option value='installed'>installed</option>
              <option value='opened'>opened</option>
              <option value='unknown'>unknown</option>
            </select>
          </label>
          <label className='text-sm font-medium'>
            {t.sourceType}
            <Input
              className='mt-1'
              value={sourceType}
              onChange={(event) => setSourceType(event.target.value)}
              required
            />
          </label>
          <label className='text-sm font-medium'>
            {t.evidenceRef}
            <Input
              className='mt-1'
              value={evidenceRef}
              onChange={(event) => setEvidenceRef(event.target.value)}
            />
          </label>
          <label className='text-sm font-medium'>
            {t.evidenceGrade}
            <select
              className='mt-1 h-10 w-full rounded-md border bg-white px-3'
              value={evidenceGrade}
              onChange={(event) => setEvidenceGrade(event.target.value)}
            >
              <option value='operator_attested'>operator_attested</option>
              <option value='provider_verified'>provider_verified</option>
              <option value='self_attested'>self_attested</option>
              <option value='none'>none</option>
            </select>
          </label>
          <div className='space-y-3'>
            <label className='flex items-start gap-2 text-sm'>
              <input
                className='mt-1'
                type='checkbox'
                checked={approve}
                onChange={(event) => setApprove(event.target.checked)}
              />
              {t.approveEvidence}
            </label>
            <Button type='submit' disabled={pending}>
              {t.submitEvidence}
            </Button>
          </div>
        </form>
        {message && (
          <p
            data-testid='participation-record-result'
            className='mt-3 text-sm text-emerald-700'
          >
            {message}
          </p>
        )}
        {error && (
          <p role='alert' className='mt-3 text-sm text-red-800'>
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function QualityOperations({
  campaignId,
  lanes,
  issues,
  copy: t,
  onChanged
}: {
  campaignId: string;
  lanes: ServiceLaneList;
  issues: IssueList;
  copy: (typeof copy)[Locale];
  onChanged: () => void;
}) {
  const [sourceAttemptId, setSourceAttemptId] = useState('');
  const [severity, setSeverity] = useState('major');
  const [assertionKey, setAssertionKey] = useState('');
  const [expected, setExpected] = useState('');
  const [actual, setActual] = useState('');
  const [reproduction, setReproduction] = useState('');
  const [issueId, setIssueId] = useState(issues.items[0]?.id ?? '');
  const [targetBuildId, setTargetBuildId] = useState('');
  const [targetScenarioId, setTargetScenarioId] = useState('');
  const [laneId, setLaneId] = useState(lanes.items[0]?.id ?? '');
  const [costMinor, setCostMinor] = useState('0');
  const [consent, setConsent] = useState(false);
  const [retestKey, setRetestKey] = useState(() => crypto.randomUUID());
  const [pending, setPending] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submitIssue = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPending('issue');
    setError(null);
    void createIssue(campaignId, {
      source_attempt_id: sourceAttemptId.trim(),
      severity,
      assertion_key: assertionKey.trim(),
      expected: expected.trim(),
      actual: actual.trim(),
      reproduction: { step_path: reproduction.trim() }
    })
      .then((issue) => {
        setIssueId(issue.id);
        setMessage(`${issue.assertion_key}: ${issue.status}`);
        onChanged();
      })
      .catch((reason: unknown) => setError(formatFarmApiError(reason, t.error)))
      .finally(() => setPending(null));
  };

  const submitRetest = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPending('retest');
    setError(null);
    void requestRetest(campaignId, issueId, {
      target_build_id: targetBuildId.trim(),
      target_scenario_version_id: targetScenarioId.trim(),
      lane_scope: [laneId],
      idempotency_key: retestKey,
      consent: {
        accepted: consent,
        price_minor: Number(costMinor),
        device_minutes: 15
      }
    })
      .then((retest) => {
        setMessage(`${t.requestRetest}: ${retest.status}`);
        setRetestKey(crypto.randomUUID());
        onChanged();
      })
      .catch((reason: unknown) => setError(formatFarmApiError(reason, t.error)))
      .finally(() => setPending(null));
  };

  return (
    <section className='mt-4 space-y-4'>
      <h3 className='text-lg font-semibold'>{t.qualityIssues}</h3>
      {error && (
        <p
          role='alert'
          className='rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800'
        >
          {error}
        </p>
      )}
      {message && (
        <p
          data-testid='quality-operation-result'
          className='rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800'
        >
          {message}
        </p>
      )}
      <div className='grid gap-4 lg:grid-cols-2'>
        <Card>
          <CardHeader>
            <CardTitle className='text-base'>{t.createIssue}</CardTitle>
          </CardHeader>
          <CardContent>
            <form className='space-y-3' onSubmit={submitIssue}>
              <label className='block text-sm font-medium'>
                {t.sourceAttempt}
                <Input
                  className='mt-1'
                  value={sourceAttemptId}
                  onChange={(event) => setSourceAttemptId(event.target.value)}
                  required
                />
              </label>
              <label className='block text-sm font-medium'>
                {t.severity}
                <select
                  className='mt-1 h-10 w-full rounded-md border bg-white px-3'
                  value={severity}
                  onChange={(event) => setSeverity(event.target.value)}
                >
                  <option value='minor'>minor</option>
                  <option value='major'>major</option>
                  <option value='critical'>critical</option>
                </select>
              </label>
              <label className='block text-sm font-medium'>
                {t.assertionKey}
                <Input
                  className='mt-1'
                  value={assertionKey}
                  onChange={(event) => setAssertionKey(event.target.value)}
                  required
                />
              </label>
              <label className='block text-sm font-medium'>
                {t.expected}
                <Textarea
                  className='mt-1'
                  value={expected}
                  onChange={(event) => setExpected(event.target.value)}
                  required
                />
              </label>
              <label className='block text-sm font-medium'>
                {t.actual}
                <Textarea
                  className='mt-1'
                  value={actual}
                  onChange={(event) => setActual(event.target.value)}
                  required
                />
              </label>
              <label className='block text-sm font-medium'>
                {t.reproduction}
                <Input
                  className='mt-1'
                  value={reproduction}
                  onChange={(event) => setReproduction(event.target.value)}
                  required
                />
              </label>
              <Button type='submit' disabled={pending !== null}>
                {t.createIssue}
              </Button>
            </form>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className='text-base'>{t.requestRetest}</CardTitle>
          </CardHeader>
          <CardContent>
            <form className='space-y-3' onSubmit={submitRetest}>
              <label className='block text-sm font-medium'>
                {t.qualityIssues}
                <select
                  className='mt-1 h-10 w-full rounded-md border bg-white px-3'
                  value={issueId}
                  onChange={(event) => setIssueId(event.target.value)}
                  required
                >
                  {issues.items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.assertion_key} · {item.status}
                    </option>
                  ))}
                </select>
              </label>
              <label className='block text-sm font-medium'>
                {t.targetBuild}
                <Input
                  className='mt-1'
                  value={targetBuildId}
                  onChange={(event) => setTargetBuildId(event.target.value)}
                  required
                />
              </label>
              <label className='block text-sm font-medium'>
                {t.targetScenario}
                <Input
                  className='mt-1'
                  value={targetScenarioId}
                  onChange={(event) => setTargetScenarioId(event.target.value)}
                  required
                />
              </label>
              <label className='block text-sm font-medium'>
                {t.laneScope}
                <select
                  className='mt-1 h-10 w-full rounded-md border bg-white px-3'
                  value={laneId}
                  onChange={(event) => setLaneId(event.target.value)}
                  required
                >
                  {lanes.items.map((lane) => (
                    <option key={lane.id} value={lane.id}>
                      {lane.tester_label}
                    </option>
                  ))}
                </select>
              </label>
              <label className='block text-sm font-medium'>
                {t.amountMinor}
                <Input
                  className='mt-1'
                  type='number'
                  min={0}
                  value={costMinor}
                  onChange={(event) => setCostMinor(event.target.value)}
                  required
                />
              </label>
              <label className='flex items-start gap-2 text-sm'>
                <input
                  className='mt-1'
                  type='checkbox'
                  checked={consent}
                  onChange={(event) => setConsent(event.target.checked)}
                  required
                />
                {t.retestConsent}
              </label>
              <Button
                type='submit'
                disabled={pending !== null || !issueId || !laneId || !consent}
              >
                {t.requestRetest}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
      <div className='grid gap-3 md:grid-cols-2'>
        {issues.items.map((issue: IssueSummary) => (
          <Card key={issue.id}>
            <CardContent className='pt-5 text-sm'>
              <div className='flex flex-wrap gap-2'>
                <Badge>{issue.severity}</Badge>
                <Badge variant='outline'>{issue.status}</Badge>
                <Badge variant='secondary'>{issue.retest_count} retest</Badge>
              </div>
              <p className='mt-3 font-medium'>{issue.assertion_key}</p>
              <p className='mt-1 text-slate-600'>
                {issue.expected} → {issue.actual}
              </p>
              <p className='mt-2 break-all font-mono text-xs text-slate-500'>
                {issue.fingerprint}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
      {issues.items.length === 0 && <Empty text={t.noIssue} />}
    </section>
  );
}

function LifecycleOperations({
  campaignId,
  lanes,
  copy: t,
  onChanged
}: {
  campaignId: string;
  lanes: ServiceLaneList;
  copy: (typeof copy)[Locale];
  onChanged: () => void;
}) {
  const [laneId, setLaneId] = useState(lanes.items[0]?.id ?? '');
  const [newDeviceId, setNewDeviceId] = useState('');
  const [replacementReason, setReplacementReason] = useState('');
  const [replacementKey, setReplacementKey] = useState(() =>
    crypto.randomUUID()
  );
  const [addedDays, setAddedDays] = useState('1');
  const [orderId, setOrderId] = useState('');
  const [entitlementId, setEntitlementId] = useState('');
  const [amountMinor, setAmountMinor] = useState('1');
  const [currency, setCurrency] = useState('USD');
  const [policyVersion, setPolicyVersion] = useState('v1');
  const [pricingVersion, setPricingVersion] = useState('v1');
  const [extensionConsent, setExtensionConsent] = useState(false);
  const [extensionKey, setExtensionKey] = useState(() => crypto.randomUUID());
  const [cancellationReason, setCancellationReason] = useState('');
  const [cancelConfirmation, setCancelConfirmation] = useState('');
  const [cancellationKey, setCancellationKey] = useState(() =>
    crypto.randomUUID()
  );
  const [lastOperation, setLastOperation] =
    useState<FleetLifecycleOperation | null>(null);
  const [resultMessage, setResultMessage] = useState<string | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const run = useCallback(
    async (kind: string, action: () => Promise<void>) => {
      setPending(kind);
      setOperationError(null);
      setResultMessage(null);
      try {
        await action();
        onChanged();
      } catch (reason) {
        setOperationError(formatFarmApiError(reason, t.error));
      } finally {
        setPending(null);
      }
    },
    [onChanged, t.error]
  );

  const submitReplacement = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void run('replace', async () => {
      const operation = await replaceLaneDevice(campaignId, laneId, {
        new_device_id: newDeviceId.trim(),
        idempotency_key: replacementKey,
        reason: replacementReason.trim()
      });
      setLastOperation(operation);
      setResultMessage(
        `${operation.operation_type}: ${operation.status} · ${operation.checkpoint}`
      );
      setReplacementKey(crypto.randomUUID());
    });
  };

  const submitExtension = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void run('extend', async () => {
      const extension = await extendServiceCampaign(campaignId, {
        order_id: orderId.trim(),
        entitlement_id: entitlementId.trim(),
        idempotency_key: extensionKey,
        added_service_days: Number(addedDays),
        consent: {
          accepted: extensionConsent,
          accepted_at: new Date().toISOString(),
          policy_version: policyVersion.trim(),
          pricing_version: pricingVersion.trim(),
          amount_minor: Number(amountMinor),
          currency: currency.trim().toUpperCase()
        }
      });
      setLastOperation(null);
      setResultMessage(
        `${t.extendCampaign}: ${new Date(extension.previous_end_at).toLocaleDateString()} → ${new Date(extension.new_end_at).toLocaleDateString()}`
      );
      setExtensionKey(crypto.randomUUID());
    });
  };

  const submitCancellation = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void run('cancel', async () => {
      const operation = await cancelServiceCampaign(campaignId, {
        idempotency_key: cancellationKey,
        reason: cancellationReason.trim()
      });
      setLastOperation(operation);
      setResultMessage(
        `${operation.operation_type}: ${operation.status} · ${operation.checkpoint}`
      );
      setCancellationKey(crypto.randomUUID());
    });
  };

  const completeDrain = () => {
    if (!lastOperation) return;
    void run('complete', async () => {
      const operation = lastOperation.operation_type.includes('replace')
        ? await completeDeviceReplacement(campaignId, lastOperation.id)
        : await completeCampaignCancellation(campaignId, lastOperation.id);
      setLastOperation(operation);
      setResultMessage(
        `${operation.operation_type}: ${operation.status} · ${operation.checkpoint}`
      );
    });
  };

  return (
    <section
      className='mt-4 space-y-5'
      aria-labelledby='lifecycle-operations-heading'
    >
      <div>
        <h3
          id='lifecycle-operations-heading'
          className='flex items-center gap-2 text-lg font-semibold'
        >
          <Wrench className='size-4' aria-hidden='true' />
          {t.operations}
        </h3>
        <p className='mt-1 text-sm text-slate-600'>{t.operationsHelp}</p>
      </div>

      {operationError && (
        <div
          role='alert'
          className='rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900'
        >
          {operationError}
        </div>
      )}
      {resultMessage && (
        <div
          data-testid='operation-result'
          className='rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900'
        >
          <strong>{t.operationResult}:</strong> {resultMessage}
          {lastOperation && lastOperation.status !== 'completed' && (
            <Button
              className='ml-3'
              size='sm'
              variant='outline'
              onClick={completeDrain}
              disabled={pending !== null}
            >
              {t.completeDrain}
            </Button>
          )}
        </div>
      )}
      {pending && (
        <p role='status' className='text-sm text-slate-600'>
          {t.operationPending}
        </p>
      )}

      <div className='grid gap-4 xl:grid-cols-3'>
        <Card>
          <CardHeader>
            <CardTitle className='text-base'>{t.replaceDevice}</CardTitle>
          </CardHeader>
          <CardContent>
            <form className='space-y-3' onSubmit={submitReplacement}>
              <label className='block text-sm font-medium'>
                {t.selectedLane}
                <select
                  className='mt-1 h-10 w-full rounded-md border bg-white px-3'
                  value={laneId}
                  onChange={(event) => setLaneId(event.target.value)}
                  required
                >
                  {lanes.items.map((lane) => (
                    <option key={lane.id} value={lane.id}>
                      {lane.tester_label}
                    </option>
                  ))}
                </select>
              </label>
              <label className='block text-sm font-medium'>
                {t.newDeviceId}
                <Input
                  className='mt-1'
                  value={newDeviceId}
                  onChange={(event) => setNewDeviceId(event.target.value)}
                  required
                />
              </label>
              <label className='block text-sm font-medium'>
                {t.reason}
                <Textarea
                  className='mt-1'
                  value={replacementReason}
                  onChange={(event) => setReplacementReason(event.target.value)}
                  minLength={3}
                  required
                />
              </label>
              <Button type='submit' disabled={pending !== null || !laneId}>
                {t.requestReplacement}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className='text-base'>{t.extendCampaign}</CardTitle>
          </CardHeader>
          <CardContent>
            <form className='space-y-3' onSubmit={submitExtension}>
              <label className='block text-sm font-medium'>
                {t.addedDays}
                <Input
                  className='mt-1'
                  type='number'
                  min={1}
                  max={365}
                  value={addedDays}
                  onChange={(event) => setAddedDays(event.target.value)}
                  required
                />
              </label>
              <label className='block text-sm font-medium'>
                {t.orderId}
                <Input
                  className='mt-1'
                  value={orderId}
                  onChange={(event) => setOrderId(event.target.value)}
                  required
                />
              </label>
              <label className='block text-sm font-medium'>
                {t.entitlementId}
                <Input
                  className='mt-1'
                  value={entitlementId}
                  onChange={(event) => setEntitlementId(event.target.value)}
                  required
                />
              </label>
              <div className='grid grid-cols-2 gap-2'>
                <label className='block text-sm font-medium'>
                  {t.amountMinor}
                  <Input
                    className='mt-1'
                    type='number'
                    min={1}
                    value={amountMinor}
                    onChange={(event) => setAmountMinor(event.target.value)}
                    required
                  />
                </label>
                <label className='block text-sm font-medium'>
                  {t.currency}
                  <Input
                    className='mt-1 uppercase'
                    minLength={3}
                    maxLength={3}
                    value={currency}
                    onChange={(event) => setCurrency(event.target.value)}
                    required
                  />
                </label>
                <label className='block text-sm font-medium'>
                  {t.policyVersion}
                  <Input
                    className='mt-1'
                    value={policyVersion}
                    onChange={(event) => setPolicyVersion(event.target.value)}
                    required
                  />
                </label>
                <label className='block text-sm font-medium'>
                  {t.pricingVersion}
                  <Input
                    className='mt-1'
                    value={pricingVersion}
                    onChange={(event) => setPricingVersion(event.target.value)}
                    required
                  />
                </label>
              </div>
              <label className='flex items-start gap-2 text-sm'>
                <input
                  className='mt-1'
                  type='checkbox'
                  checked={extensionConsent}
                  onChange={(event) =>
                    setExtensionConsent(event.target.checked)
                  }
                  required
                />
                {t.consent}
              </label>
              <Button
                type='submit'
                disabled={pending !== null || !extensionConsent}
              >
                {t.requestExtension}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card className='border-red-200'>
          <CardHeader>
            <CardTitle className='text-base text-red-900'>
              {t.cancelCampaign}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form className='space-y-3' onSubmit={submitCancellation}>
              <label className='block text-sm font-medium'>
                {t.reason}
                <Textarea
                  className='mt-1'
                  value={cancellationReason}
                  onChange={(event) =>
                    setCancellationReason(event.target.value)
                  }
                  minLength={3}
                  required
                />
              </label>
              <label className='block text-sm font-medium'>
                {t.cancelConfirm}
                <Input
                  className='mt-1'
                  value={cancelConfirmation}
                  onChange={(event) =>
                    setCancelConfirmation(event.target.value)
                  }
                  required
                />
              </label>
              <Button
                type='submit'
                variant='destructive'
                disabled={pending !== null || cancelConfirmation !== 'CANCEL'}
              >
                {t.requestCancellation}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}

function LaneHistory({
  lane,
  headingRef,
  copy: t,
  downloadingId,
  onDownloadEvidence
}: {
  lane: ServiceLaneDetail;
  headingRef: React.RefObject<HTMLHeadingElement | null>;
  copy: (typeof copy)[Locale];
  downloadingId: string | null;
  onDownloadEvidence: (evidenceId: string) => void;
}) {
  return (
    <section className='mt-8 rounded-xl border bg-white p-5'>
      <h3
        ref={headingRef}
        tabIndex={-1}
        className='text-lg font-semibold outline-none'
      >
        {lane.tester_label} {t.history}
      </h3>
      <p className='mt-2 text-sm text-slate-600'>
        {lane.slot_total} {t.planned} · {lane.reservations.length}{' '}
        {t.reservations.toLowerCase()}
      </p>
      <div className='mt-4 space-y-4'>
        {lane.slots.map((slot) => (
          <article key={slot.id} className='rounded-lg border p-4'>
            <div className='flex flex-wrap items-center gap-2'>
              <h4 className='font-medium'>
                {t.day} {slot.service_day}
              </h4>
              <Badge variant='outline'>{slot.execution_status}</Badge>
              {slot.app_verdict && (
                <Badge variant='secondary'>{slot.app_verdict}</Badge>
              )}
              <Badge variant='outline'>{slot.play_participation_state}</Badge>
            </div>
            {slot.attempts.length === 0 ? (
              <p className='mt-3 text-sm text-slate-600'>{t.noAttempts}</p>
            ) : (
              <div className='mt-3 space-y-3'>
                {slot.attempts.map((attempt) => (
                  <div
                    key={attempt.id}
                    className='rounded-md bg-slate-50 p-3 text-sm'
                  >
                    <div className='flex flex-wrap gap-2 font-medium'>
                      <span>
                        {t.attempts} {attempt.attempt_no}
                      </span>
                      <Badge>{attempt.outcome ?? attempt.status}</Badge>
                    </div>
                    {attempt.failure_reason && (
                      <p className='mt-2 text-amber-800'>
                        {attempt.failure_reason}
                      </p>
                    )}
                    {attempt.evidence.length > 0 && (
                      <div className='mt-3'>
                        <p className='font-medium'>{t.evidence}</p>
                        <ul className='mt-1 space-y-1 text-slate-600'>
                          {attempt.evidence.map((item) => (
                            <li
                              key={item.id}
                              className='flex flex-wrap items-center gap-2'
                            >
                              <span>
                                {item.kind} · {sentenceCase(item.status)}
                                {item.capture_error_code
                                  ? ` · ${item.capture_error_code}`
                                  : ''}
                              </span>
                              {item.status === 'available' && (
                                <Button
                                  type='button'
                                  variant='outline'
                                  size='sm'
                                  disabled={downloadingId === item.id}
                                  onClick={() => onDownloadEvidence(item.id)}
                                  aria-label={`${t.openEvidence} ${item.kind}`}
                                >
                                  <ExternalLink
                                    className='mr-1 size-3.5'
                                    aria-hidden='true'
                                  />
                                  {t.openEvidence}
                                </Button>
                              )}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className='mt-4 rounded-xl border bg-white p-6 text-sm text-slate-600'>
      {text}
    </div>
  );
}

function MetricCard({
  testId,
  title,
  numerator,
  denominator,
  numeratorLabel,
  denominatorLabel,
  empty
}: {
  testId: string;
  title: string;
  numerator: number;
  denominator: number;
  numeratorLabel: string;
  denominatorLabel: string;
  empty: string;
}) {
  const percent = percentage(numerator, denominator);
  return (
    <Card data-testid={testId}>
      <CardHeader>
        <CardTitle className='text-base'>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {denominator > 0 ? (
          <>
            <div className='text-2xl font-semibold'>
              {numerator} / {denominator}
            </div>
            <div className='mt-1 text-xs text-slate-500'>
              {numeratorLabel} · {denominatorLabel}
            </div>
            <Progress
              className='mt-4'
              value={percent}
              aria-label={`${title}: ${percent}%`}
            />
          </>
        ) : (
          <p className='text-sm text-slate-600'>{empty}</p>
        )}
      </CardContent>
    </Card>
  );
}
