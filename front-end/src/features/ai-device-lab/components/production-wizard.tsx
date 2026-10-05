'use client';

import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from 'react';
import { CheckCircle2, Loader2, RefreshCw, ShieldAlert } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

import {
  approveWizardScenario,
  checkWizardReadiness,
  generateWizardScenario,
  loadWizardState,
  saveWizardDraft,
  startWizardCheckout,
  type WizardState
} from '../services/ai-device-lab-api';

type Locale = 'en' | 'vi';
type Step = 'app' | 'scenario' | 'review' | 'payment' | 'readiness';

const steps: Step[] = ['app', 'scenario', 'review', 'payment', 'readiness'];

function storedIntent(campaignId: string, kind: string): string {
  const key = `ai-device-lab:${campaignId}:${kind}`;
  const existing = window.sessionStorage.getItem(key);
  if (existing) return existing;
  const created = crypto.randomUUID();
  window.sessionStorage.setItem(key, created);
  return created;
}

function clearIntent(campaignId: string, kind: string) {
  window.sessionStorage.removeItem(`ai-device-lab:${campaignId}:${kind}`);
}

export function ProductionWizard({
  campaignId,
  locale
}: {
  campaignId: string;
  locale: Locale;
}) {
  const [state, setState] = useState<WizardState | null>(null);
  const [view, setView] = useState<Step>('app');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<Awaited<
    ReturnType<typeof checkWizardReadiness>
  > | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [form, setForm] = useState({
    packageName: '',
    closedTrackLink: '',
    testGoal: '',
    versionName: '',
    versionCode: '',
    locale: locale === 'vi' ? 'vi-VN' : 'en-US',
    network: 'wifi'
  });
  const copy = useMemo(
    () =>
      locale === 'vi'
        ? {
            title: 'Thiết lập AI Device Lab',
            loading: 'Đang tải draft từ máy chủ…',
            loadError: 'Không tải được trạng thái wizard.',
            steps: {
              app: 'App',
              scenario: 'Kịch bản',
              review: 'Duyệt gói',
              payment: 'Thanh toán',
              readiness: 'Sẵn sàng'
            },
            appTitle: 'Thông tin app',
            package: 'Android package name',
            track: 'Link Play closed track',
            goal: 'Mục tiêu kiểm thử',
            versionName: 'Version name',
            versionCode: 'Version code',
            appSave: 'Lưu và tiếp tục',
            saving: 'Đang lưu…',
            scenarioTitle: 'Kịch bản AI',
            generate: 'Tạo kịch bản bằng AI',
            retry: 'Thử tạo lại',
            approve: 'Duyệt snapshot này',
            generating: 'AI đang tạo và kiểm tra kịch bản…',
            reviewTitle: 'Duyệt gói dịch vụ',
            reviewNext: 'Tiếp tục tới thanh toán',
            paymentTitle: 'Xác minh thanh toán',
            providerBlocked:
              'Nhà cung cấp thanh toán chưa được cấu hình. Không có quyền dịch vụ nào được cấp.',
            pending: 'Máy chủ vẫn đang chờ payment event đã xác minh.',
            checkout: 'Mở trang thanh toán an toàn',
            checkoutStarting: 'Đang tạo phiên thanh toán…',
            checkoutUncertain:
              'Kết quả checkout chưa chắc chắn. Máy chủ đang đối soát cùng intent; không tạo thanh toán mới.',
            readinessTitle: 'Readiness do máy chủ kiểm tra',
            recheck: 'Kiểm tra readiness',
            refresh: 'Tải lại từ máy chủ',
            conflict:
              'Draft đã thay đổi ở tab khác. Trạng thái mới đã được tải lại.',
            denied:
              'Kịch bản bị từ chối bởi policy hoặc validation. Đây không phải app test failed.',
            approved: 'Snapshot đã được duyệt bất biến.'
          }
        : {
            title: 'Set up AI Device Lab',
            loading: 'Loading the server draft…',
            loadError: 'The wizard state could not be loaded.',
            steps: {
              app: 'App',
              scenario: 'Scenario',
              review: 'Review',
              payment: 'Payment',
              readiness: 'Readiness'
            },
            appTitle: 'App details',
            package: 'Android package name',
            track: 'Play closed-track link',
            goal: 'Test goal',
            versionName: 'Version name',
            versionCode: 'Version code',
            appSave: 'Save and continue',
            saving: 'Saving…',
            scenarioTitle: 'AI scenario',
            generate: 'Generate scenario with AI',
            retry: 'Retry generation',
            approve: 'Approve this snapshot',
            generating: 'AI is generating and validating the scenario…',
            reviewTitle: 'Review service package',
            reviewNext: 'Continue to payment',
            paymentTitle: 'Payment verification',
            providerBlocked:
              'The payment provider is not configured. No service entitlement has been granted.',
            pending:
              'The server is still waiting for a verified payment event.',
            checkout: 'Open secure checkout',
            checkoutStarting: 'Creating the checkout session…',
            checkoutUncertain:
              'The checkout result is uncertain. The server is reconciling the same intent and will not create a new payment.',
            readinessTitle: 'Server-checked readiness',
            recheck: 'Check readiness',
            refresh: 'Reload from server',
            conflict:
              'The draft changed in another tab. The latest server state has been loaded.',
            denied:
              'Policy or validation rejected the scenario. This is not an app test failure.',
            approved: 'The immutable snapshot is approved.'
          },
    [locale]
  );

  const applyState = useCallback((next: WizardState, preferred?: Step) => {
    setState(next);
    if (next.intake) {
      const build = next.intake.build as Record<string, unknown>;
      setForm({
        packageName: next.intake.package_name,
        closedTrackLink: next.intake.closed_track_link,
        testGoal: next.intake.test_goal,
        versionName: String(build.version_name ?? ''),
        versionCode: String(build.version_code ?? ''),
        locale: String(next.intake.test_environment.locale ?? 'en-US'),
        network: String(next.intake.test_environment.network ?? 'wifi')
      });
    } else {
      setForm((current) => ({
        ...current,
        packageName: next.campaign.package_name
      }));
    }
    if (preferred) setView(preferred);
    else if (next.current_step === 'payment' && next.approval)
      setView('review');
    else setView(next.current_step as Step);
  }, []);

  const reload = useCallback(async () => {
    setError(null);
    try {
      applyState(await loadWizardState(campaignId));
    } catch (reason) {
      setError(formatFarmApiError(reason, copy.loadError));
    } finally {
      setLoading(false);
    }
  }, [applyState, campaignId, copy.loadError]);

  useEffect(() => {
    const controller = new AbortController();
    loadWizardState(campaignId, controller.signal)
      .then((next) => applyState(next))
      .catch((reason) => {
        if (!controller.signal.aborted)
          setError(formatFarmApiError(reason, copy.loadError));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [applyState, campaignId, copy.loadError]);

  useEffect(() => {
    headingRef.current?.focus();
  }, [view]);

  async function submitApp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!state || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const next = await saveWizardDraft(campaignId, {
        expected_revision: state.intake?.revision ?? 0,
        package_name: form.packageName.trim(),
        closed_track_link: form.closedTrackLink.trim(),
        test_goal: form.testGoal.trim(),
        test_environment: {
          locale: form.locale.trim(),
          network: form.network.trim()
        },
        build: {
          version_name: form.versionName.trim(),
          version_code: form.versionCode.trim(),
          source_kind: 'closed_track',
          source_ref: 'play-closed-track',
          checksum_sha256: null
        }
      });
      applyState(next, 'scenario');
    } catch (reason) {
      const response = reason as {
        response?: { data?: { detail?: { code?: string } } };
      };
      if (
        response.response?.data?.detail?.code === 'WIZARD_REVISION_CONFLICT'
      ) {
        await reload();
        setError(copy.conflict);
      } else {
        setError(formatFarmApiError(reason, copy.loadError));
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function generate() {
    if (!state || submitting) return;
    setSubmitting(true);
    setError(null);
    const operationId = storedIntent(
      campaignId,
      `generation:${state.intake?.input_version ?? 0}`
    );
    try {
      const next = await generateWizardScenario(campaignId, {
        operation_id: operationId
      });
      if (next.generation?.status !== 'running') {
        clearIntent(
          campaignId,
          `generation:${state.intake?.input_version ?? 0}`
        );
      }
      applyState(next, 'scenario');
    } catch (reason) {
      setError(formatFarmApiError(reason, copy.loadError));
    } finally {
      setSubmitting(false);
    }
  }

  async function approve() {
    const generation = state?.generation;
    if (
      !generation?.scenario_version_id ||
      !generation.content_hash ||
      submitting
    )
      return;
    setSubmitting(true);
    setError(null);
    try {
      const next = await approveWizardScenario(campaignId, {
        operation_id: generation.operation_id,
        scenario_version_id: generation.scenario_version_id,
        expected_content_hash: generation.content_hash
      });
      applyState(next, 'review');
    } catch (reason) {
      setError(formatFarmApiError(reason, copy.denied));
    } finally {
      setSubmitting(false);
    }
  }

  async function recheckReadiness() {
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await checkWizardReadiness(
        campaignId,
        storedIntent(campaignId, 'readiness')
      );
      setReadiness(result);
      clearIntent(campaignId, 'readiness');
    } catch (reason) {
      setError(formatFarmApiError(reason, copy.loadError));
    } finally {
      setSubmitting(false);
    }
  }

  async function beginCheckout() {
    const approvalId = state?.approval?.id;
    if (!approvalId || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await startWizardCheckout(campaignId, {
        approval_id: approvalId,
        idempotency_key: storedIntent(campaignId, 'checkout')
      });
      if (result.checkout_url) {
        window.location.assign(result.checkout_url);
        return;
      }
      await reload();
      setView('payment');
      if (result.status === 'uncertain') setError(copy.checkoutUncertain);
    } catch (reason) {
      setError(formatFarmApiError(reason, copy.loadError));
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <main
        className='flex min-h-screen items-center justify-center'
        aria-live='polite'
      >
        <Loader2 className='mr-2 size-5 animate-spin' />
        {copy.loading}
      </main>
    );
  }
  if (!state) {
    return (
      <main className='mx-auto max-w-2xl p-6'>
        <p role='alert'>{error ?? copy.loadError}</p>
        <Button className='mt-4' onClick={reload}>
          {copy.refresh}
        </Button>
      </main>
    );
  }

  const canOpen: Record<Step, boolean> = {
    app: true,
    scenario: Boolean(state.intake),
    review: Boolean(state.approval),
    payment: Boolean(state.approval),
    readiness: Boolean(state.payment.entitlement)
  };
  const generationFailed = state.generation?.status === 'failed';

  return (
    <main className='min-h-screen bg-slate-50 px-4 py-8 text-slate-950 sm:px-8'>
      <div className='mx-auto max-w-4xl space-y-5'>
        <div>
          <p className='text-sm font-medium text-emerald-700'>
            AI Device Lab · {state.campaign.package_name}
          </p>
          <h1 className='mt-1 text-3xl font-semibold'>{copy.title}</h1>
        </div>
        <nav aria-label='Wizard progress' className='flex flex-wrap gap-2'>
          {steps.map((step, index) => (
            <Button
              key={step}
              type='button'
              variant={view === step ? 'default' : 'outline'}
              disabled={!canOpen[step]}
              aria-current={view === step ? 'step' : undefined}
              onClick={() => setView(step)}
            >
              {index + 1}. {copy.steps[step]}
            </Button>
          ))}
        </nav>
        {error && (
          <p
            role='alert'
            className='rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900'
          >
            {error}
          </p>
        )}

        {view === 'app' && (
          <Card>
            <CardHeader>
              <h2
                ref={headingRef}
                tabIndex={-1}
                className='text-2xl font-semibold'
              >
                {copy.appTitle}
              </h2>
            </CardHeader>
            <CardContent>
              <form className='grid gap-5 sm:grid-cols-2' onSubmit={submitApp}>
                <Field label={copy.package} id='wizard-package'>
                  <Input
                    id='wizard-package'
                    value={form.packageName}
                    readOnly
                    aria-readonly='true'
                  />
                </Field>
                <Field label={copy.track} id='wizard-track'>
                  <Input
                    id='wizard-track'
                    type='url'
                    value={form.closedTrackLink}
                    onChange={(event) =>
                      setForm({ ...form, closedTrackLink: event.target.value })
                    }
                    required
                  />
                </Field>
                <Field label={copy.versionName} id='wizard-version-name'>
                  <Input
                    id='wizard-version-name'
                    value={form.versionName}
                    onChange={(event) =>
                      setForm({ ...form, versionName: event.target.value })
                    }
                    required
                  />
                </Field>
                <Field label={copy.versionCode} id='wizard-version-code'>
                  <Input
                    id='wizard-version-code'
                    value={form.versionCode}
                    onChange={(event) =>
                      setForm({ ...form, versionCode: event.target.value })
                    }
                    required
                  />
                </Field>
                <div className='space-y-2 sm:col-span-2'>
                  <Label htmlFor='wizard-goal'>{copy.goal}</Label>
                  <Textarea
                    id='wizard-goal'
                    value={form.testGoal}
                    onChange={(event) =>
                      setForm({ ...form, testGoal: event.target.value })
                    }
                    required
                    rows={5}
                  />
                </div>
                <Button
                  className='sm:col-span-2 sm:w-fit'
                  type='submit'
                  disabled={submitting}
                >
                  {submitting ? copy.saving : copy.appSave}
                </Button>
              </form>
            </CardContent>
          </Card>
        )}

        {view === 'scenario' && (
          <Card>
            <CardHeader>
              <h2
                ref={headingRef}
                tabIndex={-1}
                className='text-2xl font-semibold'
              >
                {copy.scenarioTitle}
              </h2>
            </CardHeader>
            <CardContent className='space-y-4'>
              {state.generation?.status === 'running' && (
                <p aria-live='polite'>{copy.generating}</p>
              )}
              {generationFailed && (
                <div className='rounded-lg bg-amber-50 p-4 text-amber-950'>
                  <ShieldAlert className='mb-2 size-5' aria-hidden='true' />
                  <p>{copy.denied}</p>
                  <code className='text-xs'>
                    {state.generation?.error_code}
                  </code>
                </div>
              )}
              {state.generation?.scenario && (
                <pre className='max-h-80 overflow-auto rounded-lg bg-slate-950 p-4 text-xs text-slate-50'>
                  {JSON.stringify(state.generation.scenario, null, 2)}
                </pre>
              )}
              {state.approval && (
                <p className='flex items-center gap-2 text-emerald-800'>
                  <CheckCircle2 className='size-5' />
                  {copy.approved}
                </p>
              )}
              {!state.generation?.scenario && (
                <Button onClick={generate} disabled={submitting}>
                  {generationFailed ? copy.retry : copy.generate}
                </Button>
              )}
              {state.generation?.scenario && !state.approval && (
                <Button onClick={approve} disabled={submitting}>
                  {copy.approve}
                </Button>
              )}
            </CardContent>
          </Card>
        )}

        {view === 'review' && state.approval && (
          <Card>
            <CardHeader>
              <h2
                ref={headingRef}
                tabIndex={-1}
                className='text-2xl font-semibold'
              >
                {copy.reviewTitle}
              </h2>
            </CardHeader>
            <CardContent className='space-y-4'>
              <dl className='grid gap-3 sm:grid-cols-2'>
                <Summary label='Package' value={state.campaign.package_name} />
                <Summary label='Plan' value={state.campaign.plan_version} />
                <Summary
                  label='Scenario hash'
                  value={state.approval.content_hash}
                />
                <Summary label='Policy' value={state.approval.policy_version} />
                <Summary
                  label='Quota'
                  value={`${state.payment.quota.slots ?? 0} slots`}
                />
                <Summary
                  label='Price'
                  value={
                    state.payment.amount_minor == null
                      ? (state.payment.blocker_code ?? 'Unavailable')
                      : `${state.payment.amount_minor} ${state.payment.currency}`
                  }
                />
              </dl>
              <Button onClick={() => setView('payment')}>
                {copy.reviewNext}
              </Button>
            </CardContent>
          </Card>
        )}

        {view === 'payment' && (
          <Card>
            <CardHeader>
              <h2
                ref={headingRef}
                tabIndex={-1}
                className='text-2xl font-semibold'
              >
                {copy.paymentTitle}
              </h2>
            </CardHeader>
            <CardContent className='space-y-4'>
              <p className='rounded-lg bg-amber-50 p-4 text-amber-950'>
                {!state.payment.provider_configured
                  ? copy.providerBlocked
                  : state.payment.checkout_status === 'uncertain'
                    ? copy.checkoutUncertain
                    : copy.pending}
              </p>
              <code className='block text-xs'>
                {state.payment.blocker_code}
              </code>
              {state.payment.checkout_status && (
                <p className='text-sm text-slate-600' aria-live='polite'>
                  Checkout: {state.payment.checkout_status}
                  {state.payment.checkout_error_code
                    ? ` · ${state.payment.checkout_error_code}`
                    : ''}
                </p>
              )}
              {state.payment.provider_configured &&
                !state.payment.entitlement && (
                  <Button onClick={beginCheckout} disabled={submitting}>
                    {submitting ? copy.checkoutStarting : copy.checkout}
                  </Button>
                )}
              <Button variant='outline' onClick={reload}>
                {copy.refresh}
              </Button>
            </CardContent>
          </Card>
        )}

        {view === 'readiness' && (
          <Card>
            <CardHeader>
              <h2
                ref={headingRef}
                tabIndex={-1}
                className='text-2xl font-semibold'
              >
                {copy.readinessTitle}
              </h2>
            </CardHeader>
            <CardContent className='space-y-4'>
              {readiness?.checks.map((check) => (
                <div key={check.key} className='rounded-lg border p-3'>
                  <strong>{check.key}</strong>
                  <p>
                    {check.status} · {check.reason_code}
                  </p>
                  {check.next_action && (
                    <p className='text-sm text-slate-600'>
                      {check.owner} · {check.next_action}
                    </p>
                  )}
                </div>
              ))}
              <Button
                onClick={recheckReadiness}
                disabled={submitting || !state.payment.entitlement}
              >
                <RefreshCw className='mr-2 size-4' />
                {copy.recheck}
              </Button>
            </CardContent>
          </Card>
        )}
      </div>
    </main>
  );
}

function Field({
  label,
  id,
  children
}: {
  label: string;
  id: string;
  children: React.ReactNode;
}) {
  return (
    <div className='space-y-2'>
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  );
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className='min-w-0 rounded-lg border p-3'>
      <dt className='text-xs uppercase text-slate-500'>{label}</dt>
      <dd className='mt-1 break-words font-medium'>{value}</dd>
    </div>
  );
}
