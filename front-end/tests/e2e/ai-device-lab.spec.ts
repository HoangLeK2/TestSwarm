import { expect, test } from '@playwright/test';

test('08-T1: API-backed workspace keeps three authoritative denominators separate', async ({
  page
}) => {
  let terminal = 84;
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-1',
    async (route) => {
      await route.fulfill({
        json: {
          id: 'svc-1',
          runtime_campaign_id: 'runtime-1',
          package_name: 'com.example.production',
          timezone: 'UTC',
          plan_version: 'adl-14d-v1',
          status: 'active',
          lane_count: 12,
          started_at: '2026-10-04T00:00:00Z',
          end_at: '2026-10-18T00:00:00Z'
        }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-1/progress',
    async (route) => {
      await route.fulfill({
        json: {
          service: { planned: 168, attempted: 96, terminal, missed: 2 },
          app_quality: { evaluated: 80, pass: 68, fail: 8, inconclusive: 4 },
          play_participation: {
            identities: 12,
            opted_in: 10,
            lost: 1,
            unknown: 1
          }
        }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-1/lanes?*',
    async (route) => {
      await route.fulfill({
        json: { items: [], total: 0, offset: 0, limit: 12 }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-1/participation?*',
    async (route) => {
      await route.fulfill({
        json: { items: [], total: 0, offset: 0, limit: 100 }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-1/reports?*',
    async (route) => {
      await route.fulfill({
        json: { items: [], total: 0, offset: 0, limit: 20 }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-1/issues?*',
    async (route) => {
      await route.fulfill({
        json: { items: [], total: 0, offset: 0, limit: 100 }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-1/payment-reconciliations?*',
    async (route) => {
      await route.fulfill({
        json: { items: [], total: 0, offset: 0, limit: 50 }
      });
    }
  );

  await page.goto('/en/ai-device-lab/workspace/svc-1');
  await expect(
    page.getByRole('heading', { name: 'Campaign workspace' })
  ).toBeVisible();
  await expect(page.getByText('com.example.production')).toBeVisible();
  await expect(page.getByText('12 logical lanes')).toBeVisible();
  await expect(
    page.getByTestId('workspace-service').getByText('84 / 168')
  ).toBeVisible();
  await expect(
    page.getByTestId('workspace-quality').getByText('68 / 80')
  ).toBeVisible();
  await expect(
    page.getByTestId('workspace-participation').getByText('10 / 12')
  ).toBeVisible();

  terminal = 85;
  await page.getByRole('button', { name: 'Refresh sources' }).click();
  await expect(
    page.getByTestId('workspace-service').getByText('85 / 168')
  ).toBeVisible();
  await expect(page.getByText(/Google approved/i)).toHaveCount(0);
});

test('08-T3/11-T5/19b-T6: workspace drills into evidence and submits guarded lifecycle operations', async ({
  page,
  context
}) => {
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail',
    async (route) => {
      await route.fulfill({
        json: {
          id: 'svc-detail',
          runtime_campaign_id: 'runtime-detail',
          package_name: 'com.example.detail',
          timezone: 'UTC',
          plan_version: 'adl-14d-v1',
          status: 'active',
          lane_count: 12,
          started_at: '2026-10-04T00:00:00Z',
          end_at: '2026-10-18T00:00:00Z'
        }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail/progress',
    async (route) => {
      await route.fulfill({
        json: {
          service: { planned: 168, attempted: 1, terminal: 1, missed: 0 },
          app_quality: { evaluated: 1, pass: 0, fail: 0, inconclusive: 1 },
          play_participation: {
            identities: 1,
            opted_in: 0,
            lost: 0,
            unknown: 1
          }
        }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail/lanes?*',
    async (route) => {
      await route.fulfill({
        json: {
          total: 12,
          offset: 0,
          limit: 12,
          items: [
            {
              id: 'lane-03',
              ordinal: 3,
              tester_label: 'Tester 03',
              planned_slots: 14,
              terminal_slots: 1,
              active_reservation_count: 1
            }
          ]
        }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail/participation?*',
    async (route) => {
      await route.fulfill({
        json: {
          total: 1,
          offset: 0,
          limit: 100,
          items: [
            {
              id: 'participant-1',
              masked_label: 'te***03',
              track_name: 'closed',
              current_status: 'unknown',
              evidence_grade: 'none',
              active_segment_no: 0,
              last_observed_at: null,
              gap_reason: 'participation_unknown'
            }
          ]
        }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail/reports?*',
    async (route) => {
      await route.fulfill({
        json: {
          total: 1,
          offset: 0,
          limit: 20,
          items: [
            {
              id: 'report-1',
              version: 1,
              schema_version: 'adl-report-v1',
              cutoff_at: '2026-10-18T00:00:00Z',
              builder_version: 'backend-test',
              summary: {
                service: { planned_slots: 168, terminal_slots: 1 },
                evidence: { available: 0, missing: 1, unsupported: 1 }
              },
              manifest_sha256: 'a'.repeat(64),
              status: 'published',
              download_available: true,
              pdf_sha256: 'b'.repeat(64),
              created_at: '2026-10-18T00:01:00Z'
            }
          ]
        }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail/issues?*',
    async (route) => {
      await route.fulfill({
        json: {
          total: 1,
          offset: 0,
          limit: 100,
          items: [
            {
              id: 'issue-existing',
              source_attempt_id: 'attempt-1',
              source_build_id: 'build-v1',
              source_scenario_version_id: 'scenario-v1',
              severity: 'major',
              assertion_key: 'home-title-visible',
              expected: 'Home title',
              actual: 'Blank screen',
              reproduction: { step_path: 'steps[4]' },
              fingerprint: 'c'.repeat(64),
              status: 'open',
              retest_count: 0,
              created_at: '2026-10-04T00:01:00Z'
            }
          ]
        }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail/payment-reconciliations?*',
    async (route) => {
      await route.fulfill({
        json: {
          total: 1,
          offset: 0,
          limit: 50,
          items: [
            {
              id: 'reconcile-1',
              order_id: 'order-private',
              provider: 'sandbox',
              reason_code: 'PROVIDER_TIMEOUT',
              status: 'blocked',
              attempts: 1,
              last_error_code: 'PROVIDER_ADAPTER_UNAVAILABLE',
              available_at: '2026-10-04T00:00:00Z',
              resolved_at: null,
              created_at: '2026-10-04T00:00:00Z'
            }
          ]
        }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail/lanes/lane-03?*',
    async (route) => {
      await route.fulfill({
        json: {
          id: 'lane-03',
          ordinal: 3,
          tester_label: 'Tester 03',
          reservations: [
            {
              id: 'reservation-1',
              state: 'active',
              starts_at: '2026-10-04T00:00:00Z',
              ends_at: '2026-10-18T00:00:00Z',
              released_at: null
            }
          ],
          slot_total: 14,
          slot_offset: 0,
          slot_limit: 50,
          slots: [
            {
              id: 'slot-1',
              service_day: 1,
              planned_at: '2026-10-04T00:00:00Z',
              execution_status: 'blocked',
              app_verdict: 'inconclusive',
              play_participation_state: 'unknown',
              attempts: [
                {
                  id: 'attempt-1',
                  attempt_no: 1,
                  status: 'terminal',
                  outcome: 'blocked',
                  observed_build: { version_code: '42' },
                  failure_reason: 'DEVICE_OFFLINE',
                  started_at: '2026-10-04T00:00:00Z',
                  finished_at: '2026-10-04T00:01:00Z',
                  evidence: [
                    {
                      id: 'evidence-available',
                      step_path: 'steps.0',
                      step_attempt_index: 1,
                      kind: 'screenshot',
                      status: 'available',
                      captured_at: '2026-10-04T00:00:20Z',
                      capture_error_code: null
                    },
                    {
                      id: 'evidence-1',
                      step_path: 'steps.0',
                      step_attempt_index: 1,
                      kind: 'screenshot',
                      status: 'missing',
                      captured_at: '2026-10-04T00:00:30Z',
                      capture_error_code: 'STORAGE_UNAVAILABLE'
                    },
                    {
                      id: 'evidence-2',
                      step_path: 'steps.1',
                      step_attempt_index: 1,
                      kind: 'video',
                      status: 'unsupported',
                      captured_at: '2026-10-04T00:00:40Z',
                      capture_error_code: 'VIDEO_NOT_COMMITTED'
                    }
                  ]
                }
              ]
            }
          ]
        }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail/evidence/evidence-available/download-url',
    async (route) => {
      await route.fulfill({
        json: {
          url: 'https://storage.invalid/private-evidence.png',
          expires_at: '2026-10-18T00:06:00Z',
          content_type: 'image/png'
        }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail/reports/report-1/download-url',
    async (route) => {
      await route.fulfill({
        json: {
          url: 'https://storage.invalid/private-report.pdf',
          expires_at: '2026-10-18T00:06:00Z',
          content_type: 'application/pdf'
        }
      });
    }
  );
  const lifecyclePayloads: Record<string, unknown>[] = [];
  const lifecycleOperation = (
    operationType: string,
    status: string,
    checkpoint: string
  ) => ({
    id: `operation-${operationType}`,
    service_campaign_id: 'svc-detail',
    lane_id: operationType === 'replace_device' ? 'lane-03' : null,
    operation_type: operationType,
    status,
    checkpoint,
    old_reservation_id:
      operationType === 'replace_device' ? 'reservation-1' : null,
    new_reservation_id: null,
    reason: 'operator requested',
    error_code: null,
    created_at: '2026-10-04T00:00:00Z',
    updated_at: '2026-10-04T00:00:00Z'
  });
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail/lanes/lane-03/replace',
    async (route) => {
      lifecyclePayloads.push(route.request().postDataJSON());
      await route.fulfill({
        json: lifecycleOperation(
          'replace_device',
          'draining',
          'old_device_draining'
        )
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail/operations/operation-replace_device/complete-replacement',
    async (route) => {
      await route.fulfill({
        json: lifecycleOperation(
          'replace_device',
          'completed',
          'replacement_active'
        )
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail/extend',
    async (route) => {
      lifecyclePayloads.push(route.request().postDataJSON());
      await route.fulfill({
        json: {
          id: 'extension-1',
          service_campaign_id: 'svc-detail',
          previous_end_at: '2026-10-18T00:00:00Z',
          new_end_at: '2026-10-20T00:00:00Z',
          added_service_days: 2,
          order_id: 'order-verified-1',
          entitlement_id: 'entitlement-1',
          created_at: '2026-10-04T00:00:00Z'
        }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail/cancel',
    async (route) => {
      lifecyclePayloads.push(route.request().postDataJSON());
      await route.fulfill({
        json: lifecycleOperation(
          'cancel_campaign',
          'draining',
          'campaign_draining'
        )
      });
    }
  );
  const qualityPayloads: Record<string, unknown>[] = [];
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail/participation',
    async (route) => {
      qualityPayloads.push(route.request().postDataJSON());
      await route.fulfill({
        status: 201,
        json: {
          participation: {
            id: 'participant-2',
            masked_label: 'te***04',
            track_name: 'closed',
            current_status: 'opted_in',
            evidence_grade: 'operator_attested',
            active_segment_no: 1,
            last_observed_at: '2026-10-04T00:02:00Z',
            gap_reason: null
          },
          event_id: 'participation-event-2',
          event_type: 'opted_in',
          review_state: 'approved',
          observed_at: '2026-10-04T00:02:00Z'
        }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail/issues',
    async (route) => {
      qualityPayloads.push(route.request().postDataJSON());
      await route.fulfill({
        status: 201,
        json: {
          id: 'issue-created',
          source_attempt_id: 'attempt-1',
          source_build_id: 'build-v1',
          source_scenario_version_id: 'scenario-v1',
          severity: 'critical',
          assertion_key: 'checkout-total',
          expected: 'Correct total',
          actual: 'Incorrect total',
          reproduction: { step_path: 'steps[7]' },
          fingerprint: 'd'.repeat(64),
          status: 'open',
          retest_count: 0,
          created_at: '2026-10-04T00:03:00Z'
        }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-detail/issues/issue-existing/retests',
    async (route) => {
      qualityPayloads.push(route.request().postDataJSON());
      await route.fulfill({
        status: 201,
        json: {
          id: 'retest-1',
          issue_id: 'issue-existing',
          source_attempt_id: 'attempt-1',
          target_build_id: 'build-v2',
          target_scenario_version_id: 'scenario-v2',
          lane_scope: ['lane-03'],
          status: 'requested',
          new_attempt_id: null,
          verdict: null,
          verdict_reason: null,
          created_at: '2026-10-04T00:04:00Z'
        }
      });
    }
  );

  const opened: string[] = [];
  await context.route('https://storage.invalid/**', async (route) => {
    opened.push(route.request().url());
    await route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.4' });
  });
  await page.goto('/en/ai-device-lab/workspace/svc-detail');
  await page.getByRole('tab', { name: 'Payment review' }).click();
  await expect(page.getByText('Payment reconciliation queue')).toBeVisible();
  await expect(page.getByText('Provider adapter unavailable')).toBeVisible();
  await expect(page.getByText('provider-private-reference')).toHaveCount(0);
  await page.getByRole('tab', { name: 'Lanes' }).click();
  await page.getByRole('tab', { name: 'Lanes' }).click();
  await page.getByRole('button', { name: 'Open Tester 03' }).click();
  await expect(
    page.getByRole('heading', { name: 'Tester 03 history' })
  ).toBeVisible();
  await expect(page.getByText(/Missing · STORAGE_UNAVAILABLE/)).toBeVisible();
  await expect(
    page.getByText(/Unsupported · VIDEO_NOT_COMMITTED/)
  ).toBeVisible();
  await page.getByRole('button', { name: 'Open evidence screenshot' }).click();
  await expect.poll(() => opened.length).toBe(1);

  await page.getByRole('tab', { name: 'Participation' }).click();
  await expect(page.getByText('te***03', { exact: true })).toBeVisible();
  await expect(page.getByText('private-stable-account-ref')).toHaveCount(0);
  await page
    .getByLabel('Pseudonymous account reference')
    .fill('private-ref-04');
  await page.getByLabel('Masked label').fill('te***04');
  await page
    .getByLabel('Private evidence reference')
    .fill('private://participation/evidence-4');
  await page.getByRole('button', { name: 'Record evidence' }).click();
  await expect(page.getByTestId('participation-record-result')).toContainText(
    'te***04: opted_in · approved'
  );
  await expect(page.getByText('private-ref-04')).toHaveCount(0);

  await page.getByRole('tab', { name: 'Issues & retests' }).click();
  await page.getByLabel('Target build ID').fill('build-v2');
  await page.getByLabel('Target scenario version ID').fill('scenario-v2');
  await page.getByLabel('Amount in minor units').fill('0');
  await page.getByLabel('I approve the stated retest quota/cost.').check();
  await page.getByRole('button', { name: 'Request retest' }).click();
  await expect(page.getByTestId('quality-operation-result')).toContainText(
    'Request retest: requested'
  );

  await page.getByLabel('Failed attempt ID').fill('attempt-1');
  await page.getByLabel('Severity').selectOption('critical');
  await page.getByLabel('Assertion key').fill('checkout-total');
  await page.getByLabel('Expected').fill('Correct total');
  await page.getByLabel('Actual').fill('Incorrect total');
  await page.getByLabel('Reproduction step/path').fill('steps[7]');
  await page.getByRole('button', { name: 'Create issue' }).click();
  await expect(page.getByTestId('quality-operation-result')).toContainText(
    'checkout-total: open'
  );

  await page.getByRole('tab', { name: 'Reports' }).click();
  await page.getByRole('button', { name: 'Download report v1' }).click();
  await expect.poll(() => opened.length).toBe(2);

  await page.getByRole('tab', { name: 'Operations' }).click();
  await page.getByLabel('New device ID').fill('device-replacement-9');
  await page.getByLabel('Reason').first().fill('Battery health below policy');
  await page.getByRole('button', { name: 'Request replacement' }).click();
  await expect(page.getByTestId('operation-result')).toContainText(
    'replace_device: draining'
  );
  await page
    .getByRole('button', { name: 'Complete drained operation' })
    .click();
  await expect(page.getByTestId('operation-result')).toContainText(
    'replace_device: completed'
  );

  await page.getByLabel('Added service days').fill('2');
  await page.getByLabel('Verified order ID').fill('order-verified-1');
  await page.getByLabel('Entitlement ID').fill('entitlement-1');
  await page.getByLabel('Amount in minor units').fill('1500');
  await page
    .getByLabel('I confirm the approved price and extension consent.')
    .check();
  await page.getByRole('button', { name: 'Request extension' }).click();
  await expect(page.getByTestId('operation-result')).toContainText(
    'Extend campaign'
  );

  await page.getByLabel('Reason').last().fill('Customer requested termination');
  await page.getByLabel('Type CANCEL to confirm').fill('CANCEL');
  await page.getByRole('button', { name: 'Request cancellation' }).click();
  await expect(page.getByTestId('operation-result')).toContainText(
    'cancel_campaign: draining'
  );

  expect(lifecyclePayloads).toHaveLength(3);
  expect(lifecyclePayloads[0]).toMatchObject({
    new_device_id: 'device-replacement-9',
    reason: 'Battery health below policy'
  });
  expect(lifecyclePayloads[1]).toMatchObject({
    order_id: 'order-verified-1',
    entitlement_id: 'entitlement-1',
    added_service_days: 2,
    consent: { accepted: true, amount_minor: 1500, currency: 'USD' }
  });
  expect(lifecyclePayloads[2]).toMatchObject({
    reason: 'Customer requested termination'
  });
  expect(qualityPayloads).toHaveLength(3);
  expect(qualityPayloads[0]).toMatchObject({
    pseudonymous_account_ref: 'private-ref-04',
    masked_label: 'te***04',
    approve: true
  });
  expect(qualityPayloads[1]).toMatchObject({
    target_build_id: 'build-v2',
    target_scenario_version_id: 'scenario-v2',
    lane_scope: ['lane-03'],
    consent: { accepted: true, price_minor: 0 }
  });
  expect(qualityPayloads[2]).toMatchObject({
    source_attempt_id: 'attempt-1',
    assertion_key: 'checkout-total',
    reproduction: { step_path: 'steps[7]' }
  });
});

test('13a-T3: draft retry reuses one opaque creation intent and opens persisted workspace', async ({
  page
}) => {
  const intentKeys: string[] = [];
  const acquisitionEvents: Array<
    Array<{
      event_id: string;
      event_name: string;
      occurred_at: string;
      attribution: Record<string, string>;
    }>
  > = [];
  let attempts = 0;
  await page.route('**/api/ai-device-lab/service-campaigns', async (route) => {
    attempts += 1;
    const payload = route.request().postDataJSON() as {
      creation_intent_key: string;
      runtime_campaign_id: string;
      package_name: string;
      acquisition_events: Array<{
        event_id: string;
        event_name: string;
        occurred_at: string;
        attribution: Record<string, string>;
      }>;
    };
    intentKeys.push(payload.creation_intent_key);
    acquisitionEvents.push(payload.acquisition_events);
    expect(payload.runtime_campaign_id).toBe('runtime-existing-1');
    expect(payload.package_name).toBe('com.example.production');
    if (attempts === 1) {
      await route.fulfill({
        status: 503,
        json: { detail: 'Draft service is temporarily unavailable' }
      });
      return;
    }
    await route.fulfill({
      status: 201,
      json: {
        id: 'svc-created-1',
        runtime_campaign_id: payload.runtime_campaign_id,
        package_name: payload.package_name,
        timezone: 'UTC',
        plan_version: 'adl-14d-v1',
        status: 'draft',
        lane_count: 12,
        started_at: null,
        end_at: null
      }
    });
  });
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-created-1/wizard',
    async (route) => {
      await route.fulfill({
        json: {
          campaign: {
            id: 'svc-created-1',
            runtime_campaign_id: 'runtime-existing-1',
            package_name: 'com.example.production',
            timezone: 'UTC',
            plan_version: 'adl-14d-v1',
            status: 'draft',
            lane_count: 12,
            started_at: null,
            end_at: null
          },
          current_step: 'app',
          intake: null,
          generation: null,
          approval: null,
          payment: {
            provider_configured: false,
            provider: null,
            amount_minor: null,
            currency: null,
            pricing_version: null,
            policy_version: 'adl-billing-unconfigured-v1',
            quota: { device_minutes: 2520, slots: 168 },
            blocker_code: 'APPROVED_SCENARIO_REQUIRED',
            order: null,
            checkout_status: null,
            checkout_expires_at: null,
            checkout_error_code: null,
            entitlement: null
          }
        }
      });
    }
  );

  await page.goto('/en/ai-device-lab/start');
  await page.getByLabel('Runtime campaign ID').fill('runtime-existing-1');
  await page.getByLabel('Android package name').fill('com.example.production');
  await page.getByRole('button', { name: 'Create 12-lane draft' }).click();
  await expect(
    page.getByText('Draft service is temporarily unavailable', { exact: true })
  ).toBeVisible();
  await page.getByRole('button', { name: 'Create 12-lane draft' }).click();

  await expect(page).toHaveURL(/\/en\/ai-device-lab\/wizard\/svc-created-1$/);
  await expect(
    page.getByRole('heading', { name: 'Set up AI Device Lab' })
  ).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'App details' })
  ).toBeVisible();
  expect(intentKeys).toHaveLength(2);
  expect(intentKeys[0]).toBe(intentKeys[1]);
  expect(intentKeys[0]).not.toContain('runtime-existing-1');
  expect(intentKeys[0]).not.toContain('com.example.production');
  expect(acquisitionEvents).toHaveLength(2);
  expect(acquisitionEvents[0]).toEqual(acquisitionEvents[1]);
  expect(acquisitionEvents[0].map((event) => event.event_name)).toEqual([
    'landing_view',
    'start_click'
  ]);
  expect(
    acquisitionEvents[0].every(
      (event) =>
        Boolean(event.event_id) &&
        Boolean(Date.parse(event.occurred_at)) &&
        !JSON.stringify(event).toLowerCase().includes('email') &&
        !JSON.stringify(event).toLowerCase().includes('token')
    )
  ).toBe(true);
});

test('14-T1/T2/T4/T6: production wizard persists, retries AI, approves exact snapshot and blocks unconfigured payment', async ({
  page
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const campaign = {
    id: 'svc-wizard-1',
    runtime_campaign_id: 'runtime-wizard-1',
    package_name: 'com.example.production',
    timezone: 'UTC',
    plan_version: 'adl-14d-v1',
    status: 'draft',
    lane_count: 12,
    started_at: null,
    end_at: null
  };
  const payment = {
    provider_configured: false,
    provider: null,
    amount_minor: null,
    currency: null,
    pricing_version: null,
    policy_version: 'adl-billing-unconfigured-v1',
    quota: { device_minutes: 2520, slots: 168 },
    blocker_code: 'APPROVED_SCENARIO_REQUIRED',
    order: null,
    checkout_status: null,
    checkout_expires_at: null,
    checkout_error_code: null,
    entitlement: null
  };
  const intake = {
    id: 'intake-1',
    revision: 0,
    input_version: 1,
    package_name: campaign.package_name,
    closed_track_link:
      'https://play.google.com/store/apps/details?id=com.example.production',
    test_goal: 'Open the app and verify Home',
    test_environment: { locale: 'en-US', network: 'wifi' },
    status: 'draft',
    build: {
      id: 'build-1',
      version_name: '1.0.0',
      version_code: '100',
      source_kind: 'closed_track',
      source_ref: 'play-closed-track',
      checksum_sha256: null
    }
  };
  let serverState: Record<string, unknown> = {
    campaign,
    current_step: 'app',
    intake: null,
    generation: null,
    approval: null,
    payment
  };
  const operationIds: string[] = [];
  let generateAttempts = 0;

  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-wizard-1/wizard',
    async (route) => {
      await route.fulfill({ json: serverState });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-wizard-1/wizard/app',
    async (route) => {
      const body = route.request().postDataJSON() as {
        expected_revision: number;
        test_goal: string;
      };
      expect(body.expected_revision).toBe(0);
      expect(body.test_goal).toBe('Open the app and verify Home');
      serverState = { ...serverState, current_step: 'scenario', intake };
      await route.fulfill({ json: serverState });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-wizard-1/wizard/scenario/generate',
    async (route) => {
      generateAttempts += 1;
      const body = route.request().postDataJSON() as { operation_id: string };
      operationIds.push(body.operation_id);
      const generation =
        generateAttempts === 1
          ? {
              operation_id: body.operation_id,
              status: 'failed',
              error_code: 'AI_PROVIDER_UNAVAILABLE',
              scenario_version_id: null,
              content_hash: null,
              scenario: null
            }
          : {
              operation_id: body.operation_id,
              status: 'succeeded',
              error_code: null,
              scenario_version_id: 'scenario-version-1',
              content_hash: 'a'.repeat(64),
              scenario: {
                steps: [
                  { type: 'launch_app', package: campaign.package_name },
                  {
                    type: 'assert_element',
                    by: 'text',
                    value: 'Home',
                    timeout: 5
                  }
                ]
              }
            };
      serverState = { ...serverState, generation };
      await route.fulfill({ json: serverState });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-wizard-1/wizard/scenario/approve',
    async (route) => {
      const body = route.request().postDataJSON() as {
        operation_id: string;
        scenario_version_id: string;
        expected_content_hash: string;
      };
      expect(body).toEqual({
        operation_id: operationIds[1],
        scenario_version_id: 'scenario-version-1',
        expected_content_hash: 'a'.repeat(64)
      });
      serverState = {
        ...serverState,
        current_step: 'payment',
        approval: {
          id: 'approval-1',
          scenario_version_id: 'scenario-version-1',
          content_hash: 'a'.repeat(64),
          policy_version: 'adl-operations-v1',
          assertions: [{ type: 'assert_element', value: 'Home' }],
          allowed_operations: ['navigation.open'],
          approved_at: '2026-10-04T00:00:00Z'
        },
        payment: { ...payment, blocker_code: 'PAYMENT_PROVIDER_UNAVAILABLE' }
      };
      await route.fulfill({ json: serverState });
    }
  );

  await page.goto('/en/ai-device-lab/wizard/svc-wizard-1');
  await page
    .getByLabel('Play closed-track link')
    .fill(intake.closed_track_link);
  await page.getByLabel('Version name').fill('1.0.0');
  await page.getByLabel('Version code').fill('100');
  await page.getByLabel('Test goal').fill(intake.test_goal);
  const save = page.getByRole('button', { name: 'Save and continue' });
  await save.focus();
  await expect(save).toBeFocused();
  await page.keyboard.press('Enter');

  await page.getByRole('button', { name: 'Generate scenario with AI' }).click();
  await expect(
    page.getByText('AI_PROVIDER_UNAVAILABLE', { exact: true })
  ).toBeVisible();
  await page.getByRole('button', { name: 'Retry generation' }).click();
  await expect(page.getByText(/assert_element/)).toBeVisible();
  expect(operationIds).toHaveLength(2);
  expect(operationIds[0]).not.toBe(operationIds[1]);

  await page.getByRole('button', { name: 'Approve this snapshot' }).click();
  await expect(
    page.getByRole('heading', { name: 'Review service package' })
  ).toBeFocused();
  await expect(page.getByText('168 slots', { exact: true })).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole('heading', { name: 'Review service package' })
  ).toBeVisible();
  await page.getByRole('button', { name: 'Continue to payment' }).click();
  await expect(
    page.getByRole('heading', { name: 'Payment verification' })
  ).toBeFocused();
  await expect(
    page.getByText(
      'The payment provider is not configured. No service entitlement has been granted.',
      { exact: true }
    )
  ).toBeVisible();
  await expect(page.getByRole('button', { name: /Readiness/ })).toBeDisabled();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth
    )
  ).toBe(true);
});

test('09-T1/T5 and 14-T1: checkout return polls server truth and never trusts redirect', async ({
  page
}) => {
  const campaign = {
    id: 'svc-checkout-1',
    runtime_campaign_id: 'runtime-checkout-1',
    package_name: 'com.example.checkout',
    timezone: 'UTC',
    plan_version: 'adl-14d-v1',
    status: 'draft',
    lane_count: 12,
    started_at: null,
    end_at: null
  };
  const approval = {
    id: 'approval-checkout-1',
    scenario_version_id: 'scenario-checkout-1',
    content_hash: 'b'.repeat(64),
    policy_version: 'adl-operations-v1',
    assertions: [{ type: 'assert_element', value: 'Home' }],
    allowed_operations: ['navigation.open'],
    approved_at: '2026-10-04T00:00:00Z'
  };
  const basePayment = {
    provider_configured: true,
    provider: 'sandbox',
    amount_minor: 129900,
    currency: 'USD',
    pricing_version: 'pricing-v1',
    policy_version: 'refund-v1',
    quota: { device_minutes: 2520, slots: 168 },
    blocker_code: null,
    order: null,
    checkout_status: null,
    checkout_expires_at: null,
    checkout_error_code: null,
    entitlement: null
  };
  let checkoutStarted = false;
  let returnPolls = 0;
  const checkoutKeys: string[] = [];

  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-checkout-1/wizard',
    async (route) => {
      if (checkoutStarted && page.url().includes('/payment-return'))
        returnPolls += 1;
      const paid = returnPolls >= 2;
      await route.fulfill({
        json: {
          campaign,
          current_step: paid ? 'readiness' : 'payment',
          intake: {
            id: 'intake-checkout-1',
            revision: 0,
            input_version: 1,
            package_name: campaign.package_name,
            closed_track_link:
              'https://play.google.com/store/apps/details?id=com.example.checkout',
            test_goal: 'Verify checkout',
            test_environment: { locale: 'en-US' },
            status: 'draft',
            build: {
              id: 'build-checkout-1',
              version_name: '1.0.0',
              version_code: '100',
              source_kind: 'closed_track',
              source_ref: 'play-closed-track',
              checksum_sha256: null
            }
          },
          generation: {
            operation_id: 'generation-checkout-1',
            status: 'succeeded',
            error_code: null,
            scenario_version_id: approval.scenario_version_id,
            content_hash: approval.content_hash,
            scenario: { steps: [] }
          },
          approval,
          payment: {
            ...basePayment,
            blocker_code: paid ? null : 'PAYMENT_PENDING',
            order: checkoutStarted
              ? {
                  id: 'order-checkout-1',
                  status: paid ? 'paid' : 'pending',
                  amount_minor: 129900,
                  currency: 'USD',
                  pricing_version: 'pricing-v1',
                  policy_version: 'refund-v1'
                }
              : null,
            checkout_status: checkoutStarted
              ? paid
                ? 'paid'
                : 'awaiting_payment'
              : null,
            checkout_expires_at: checkoutStarted
              ? '2026-10-04T00:30:00Z'
              : null,
            entitlement: paid ? { id: 'entitlement-1', state: 'active' } : null
          }
        }
      });
    }
  );
  await page.route(
    '**/api/ai-device-lab/service-campaigns/svc-checkout-1/wizard/payment/checkout',
    async (route) => {
      const body = route.request().postDataJSON() as {
        approval_id: string;
        idempotency_key: string;
      };
      expect(body.approval_id).toBe(approval.id);
      checkoutKeys.push(body.idempotency_key);
      checkoutStarted = true;
      await route.fulfill({
        json: {
          order_id: 'order-checkout-1',
          intent_id: 'intent-checkout-1',
          status: 'awaiting_payment',
          checkout_url: new URL(
            '/en/ai-device-lab/payment-return?campaign_id=svc-checkout-1',
            page.url()
          ).toString(),
          expires_at: '2026-10-04T00:30:00Z',
          blocker_code: null
        }
      });
    }
  );

  await page.goto('/en/ai-device-lab/wizard/svc-checkout-1');
  await page.getByRole('button', { name: 'Continue to payment' }).click();
  await page.getByRole('button', { name: 'Open secure checkout' }).click();
  await expect(page).toHaveURL(/payment-return\?campaign_id=svc-checkout-1/);
  await expect(
    page.getByRole('heading', { name: 'Payment status' })
  ).toBeVisible();
  await expect(
    page.getByText('Payment is verified and the service entitlement is active.')
  ).toBeVisible({ timeout: 7000 });
  expect(checkoutKeys).toHaveLength(1);
  expect(checkoutKeys[0]).toMatch(/^[0-9a-f-]{36}$/i);
  await expect(page.getByText(/provider-reference/i)).toHaveCount(0);
});

test('20a-T1: landing and App → Scenario → Review → Payment → Readiness', async ({
  page
}) => {
  await page.goto('/en/ai-device-lab', { waitUntil: 'networkidle' });

  await expect(
    page.getByRole('heading', {
      name: '12 AI testing lanes. 14 service days.'
    })
  ).toBeVisible();
  await expect(
    page.getByText('One-time service package', { exact: true })
  ).toBeVisible();
  await expect(
    page.getByText('Price awaiting product approval', { exact: true })
  ).toBeVisible();
  await expect(
    page.getByText(
      'The server-priced amount, currency and refund policy will appear before checkout.',
      { exact: true }
    )
  ).toBeVisible();
  await expect(page).toHaveURL(/\/en\/ai-device-lab$/);

  await page.getByRole('button', { name: 'CTA error' }).click();
  await expect(
    page.getByText(
      'The draft service did not create a campaign. No payment or reservation was made.',
      { exact: true }
    )
  ).toBeVisible();
  await page.getByRole('button', { name: 'Retry draft creation' }).click();

  await page.getByRole('button', { name: 'Start campaign' }).click();
  await expect(
    page.getByRole('heading', { name: 'App details' })
  ).toBeVisible();
  await page.getByRole('button', { name: 'Continue to scenario' }).click();
  await page.getByRole('button', { name: 'Continue to review' }).click();
  await expect(
    page.getByRole('heading', { name: 'Review service package' })
  ).toBeVisible();
  await expect(
    page.getByText('12 lanes · 14 days · 168 scheduled slots', { exact: true })
  ).toBeVisible();
  await page.getByRole('button', { name: 'Continue to payment' }).click();
  await expect(
    page.getByRole('heading', { name: 'Payment verification' })
  ).toBeVisible();
  await page.getByRole('button', { name: 'Show failed state' }).click();
  await expect(
    page.getByText('Payment failed · service clock not started', {
      exact: true
    })
  ).toBeVisible();
  await page.getByRole('button', { name: 'Show paid state' }).click();
  await page.getByRole('button', { name: 'Open readiness' }).click();
  await expect(
    page.getByRole('heading', { name: '2 items need attention' })
  ).toBeVisible();
});

test('20a-T2: denied scenario and blocked readiness stay distinct from app failure', async ({
  page
}) => {
  await page.goto('/en/ai-device-lab', { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: 'Start campaign' }).click();
  await page.getByRole('button', { name: 'Continue to scenario' }).click();
  await page.getByRole('button', { name: 'Show AI error state' }).click();
  await expect(
    page.getByRole('heading', { name: 'AI scenario generation failed' })
  ).toBeVisible();
  await page.getByRole('button', { name: 'Retry generation' }).click();
  await expect(
    page.getByRole('heading', { name: 'Generating scenario' })
  ).toBeVisible();
  await page.getByRole('button', { name: 'Show stale approval' }).click();
  await expect(
    page.getByRole('heading', { name: 'Approval is stale' })
  ).toBeVisible();
  await page.getByRole('button', { name: 'Show denied state' }).click();

  await expect(
    page.getByRole('heading', { name: 'Scenario needs changes' })
  ).toBeVisible();
  await expect(
    page.getByText('This is not an app test failure.', { exact: true })
  ).toBeVisible();
  await expect(
    page.getByText('Owner: Developer', { exact: true })
  ).toBeVisible();
  await expect(
    page.getByText(
      'Checkout uses a real purchase, which is outside the permitted test policy.',
      { exact: true }
    )
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Edit test goal' })
  ).toBeVisible();

  await page.getByRole('button', { name: 'Readiness' }).click();
  await expect(
    page.getByRole('heading', { name: '2 items need attention' })
  ).toBeVisible();
  await expect(
    page.getByText('Blocked does not mean the app failed.', { exact: true })
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Start service' })
  ).toBeDisabled();
  await expect(
    page.getByText('Developer · provide permitted build', { exact: true })
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Recheck readiness' })
  ).toBeVisible();
  await page.getByRole('button', { name: 'Recheck readiness' }).click();
  await expect(
    page.getByText(
      'Fresh checks completed · blockers remain assigned. Start stays disabled.',
      { exact: true }
    )
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Start service' })
  ).toBeDisabled();

  await page.getByRole('button', { name: 'Unknown', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Readiness is unknown' })
  ).toBeVisible();
  await page.getByRole('button', { name: 'Recheck readiness' }).click();
  await expect(
    page.getByText(
      'Fresh observations are still unavailable. Readiness remains Unknown.',
      { exact: true }
    )
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Start service' })
  ).toBeDisabled();

  await page.getByRole('button', { name: 'Ready', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Ready to start' })
  ).toBeVisible();
  await expect(
    page.getByText('Account evidence · fresh and verified', { exact: true })
  ).toBeVisible();
  await expect(
    page.getByText('Build preflight · permitted build passed', { exact: true })
  ).toBeVisible();
  await expect(
    page.getByText('Operator · recheck account evidence', { exact: true })
  ).toHaveCount(0);
  await expect(
    page.getByText('Developer · provide permitted build', { exact: true })
  ).toHaveCount(0);

  const start = page.getByRole('button', { name: 'Start service' });
  await start.focus();
  await expect(start).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(
    page.getByRole('heading', { name: 'Service is running' })
  ).toBeFocused();
  await expect(
    page.getByText('Account evidence · fresh and verified', { exact: true })
  ).toBeVisible();
  await expect(
    page.getByText('Build preflight · permitted build passed', { exact: true })
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Recheck readiness' })
  ).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Start service' })).toHaveCount(
    0
  );
  await page.getByRole('button', { name: 'Open dashboard' }).click();
  await expect(
    page.getByRole('heading', { name: 'Testing stays explainable' })
  ).toBeFocused();
});

test('20a-T3: dashboard keeps service, quality and Play participation separate', async ({
  page
}) => {
  await page.goto('/en/ai-device-lab', { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: 'Dashboard' }).click();

  const service = page.getByTestId('progress-service');
  const quality = page.getByTestId('progress-quality');
  const participation = page.getByTestId('progress-participation');
  await expect(service.getByText('7 / 14 days', { exact: true })).toBeVisible();
  await expect(
    quality.getByText('120 / 168 scheduled', { exact: true })
  ).toBeVisible();
  await expect(
    participation.getByText('Unknown', { exact: true })
  ).toBeVisible();
  await expect(
    participation.getByText('No account-specific opt-in evidence', {
      exact: true
    })
  ).toBeVisible();
  await expect(page.getByText(/Google approved/i)).toHaveCount(0);
});

test('20a-T4: lane, report and operator views preserve history', async ({
  page
}, testInfo) => {
  await page.goto('/en/ai-device-lab', { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: 'Dashboard' }).click();
  await page.getByRole('button', { name: 'Open Tester 03 details' }).click();

  await expect(
    page.getByRole('heading', { name: 'Tester 03 · blocked run' })
  ).toBeVisible();
  await expect(
    page.getByText('Attempt 1 · build 42 · previous', { exact: true })
  ).toBeVisible();
  await expect(
    page.getByText('Evidence unavailable · retention expired', { exact: true })
  ).toBeVisible();
  await expect(
    page.getByText(
      'Logical lane 03 · device changed once · account continuity unknown',
      { exact: true }
    )
  ).toBeVisible();
  await page.getByRole('button', { name: 'Preview run retry' }).click();
  await expect(
    page.getByText(
      'A new run attempt uses build 43 and preserves attempts 1 and 2. Scheduled remains 168.',
      { exact: true }
    )
  ).toBeVisible();
  await page.getByRole('button', { name: 'Preview step retry' }).click();
  await expect(
    page.getByText(
      'A new step attempt stays inside run attempt 2 and preserves expected versus observed evidence.',
      { exact: true }
    )
  ).toBeVisible();

  await page.getByRole('button', { name: 'Operator' }).click();
  await page.getByRole('button', { name: 'Replace device' }).click();
  await expect(
    page.getByText(
      'Tester 03 keeps its lane identity. Earlier attempts and artifacts remain unchanged.',
      { exact: true }
    )
  ).toBeVisible();
  await page.getByRole('button', { name: 'Cancel campaign' }).click();
  await expect(
    page.getByText(
      'Future jobs stop; active work drains before reservation release and hygiene verification.',
      { exact: true }
    )
  ).toBeVisible();

  await page.getByRole('button', { name: 'Report' }).click();
  await expect(
    page.getByText('Frozen source snapshot', { exact: true })
  ).toBeVisible();
  await expect(
    page.getByText('Missing evidence remains explicit', { exact: true })
  ).toBeVisible();
  await page.getByRole('button', { name: 'Failed', exact: true }).click();
  await expect(
    page.getByText(
      'Report generation failed. Retry from the same cutoff without changing source results.',
      { exact: true }
    )
  ).toBeVisible();
  await page.getByRole('button', { name: 'Retry from same cutoff' }).click();
  await expect(
    page.getByText(
      'The report job is building an immutable snapshot at the recorded cutoff.',
      { exact: true }
    )
  ).toBeVisible();
  await page.getByRole('button', { name: 'Corrected', exact: true }).click();
  await expect(
    page.getByText(
      'Corrected version references version 2; original checksum remains available.',
      { exact: true }
    )
  ).toBeVisible();
  await testInfo.attach('report-view', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png'
  });
});

test('20a-T5: mobile EN/VI UI is keyboard reachable and meets the performance budget', async ({
  page
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });

  const expectNoOverflow = async () => {
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth
      )
    ).toBe(true);
  };
  const activateWithKeyboard = async (name: string | RegExp) => {
    const button = page.getByRole('button', { name }).first();
    await button.focus();
    await expect(button).toBeFocused();
    await page.keyboard.press('Enter');
  };
  const activateByTab = async (
    name: string | RegExp,
    verifyReverseOrder = false
  ) => {
    const target = page.getByRole('button', { name }).first();
    for (let index = 0; index < 40; index += 1) {
      await page.keyboard.press('Tab');
      if (
        await target.evaluate((element) => element === document.activeElement)
      ) {
        if (verifyReverseOrder) {
          await page.keyboard.press('Shift+Tab');
          await expect(target).not.toBeFocused();
          await page.keyboard.press('Tab');
          await expect(target).toBeFocused();
        }
        await page.keyboard.press('Enter');
        return;
      }
    }
    throw new Error(`Keyboard target not reached: ${String(name)}`);
  };

  const journeys = [
    {
      locale: 'vi',
      landing: '12 lane kiểm thử AI. 14 ngày dịch vụ.',
      start: 'Bắt đầu campaign',
      app: 'Thông tin app',
      toScenario: 'Tiếp tục tới kịch bản',
      scenario: 'Duyệt kịch bản AI',
      toReview: 'Tiếp tục tới duyệt gói',
      review: 'Duyệt gói dịch vụ',
      toPayment: 'Tiếp tục tới thanh toán',
      payment: 'Xác minh thanh toán',
      paid: 'Xem trạng thái đã thanh toán',
      openReadiness: 'Mở readiness',
      readiness: '2 mục cần xử lý',
      dashboardNav: 'Dashboard',
      dashboard: 'Tiến độ có thể giải thích',
      openLane: 'Mở chi tiết Tester 03',
      lane: 'Tester 03 · run bị chặn',
      backDashboard: /Quay lại dashboard/,
      reportNav: 'Báo cáo',
      report: 'Evidence có thể hành động',
      operatorNav: 'Vận hành',
      operator: 'Thao tác fleet an toàn với hệ quả rõ ràng',
      statesNav: 'Bản đồ trạng thái',
      states: 'Mỗi trạng thái đều có owner, nguồn và hành động tiếp theo',
      overviewNav: 'Tổng quan'
    },
    {
      locale: 'en',
      landing: '12 AI testing lanes. 14 service days.',
      start: 'Start campaign',
      app: 'App details',
      toScenario: 'Continue to scenario',
      scenario: 'Review AI scenario',
      toReview: 'Continue to review',
      review: 'Review service package',
      toPayment: 'Continue to payment',
      payment: 'Payment verification',
      paid: 'Show paid state',
      openReadiness: 'Open readiness',
      readiness: '2 items need attention',
      dashboardNav: 'Dashboard',
      dashboard: 'Testing stays explainable',
      openLane: 'Open Tester 03 details',
      lane: 'Tester 03 · blocked run',
      backDashboard: /Back to dashboard/,
      reportNav: 'Report',
      report: 'Evidence that stays actionable',
      operatorNav: 'Operator',
      operator: 'Safe fleet actions with visible consequences',
      statesNav: 'State map',
      states: 'Every state has an owner, source and next action',
      overviewNav: 'Overview'
    }
  ] as const;
  const performanceSamples: Array<{
    navigationMs: number;
    transferBytes: number;
  }> = [];

  for (const journey of journeys) {
    await page.goto(`/${journey.locale}/ai-device-lab`, {
      waitUntil: 'networkidle'
    });
    performanceSamples.push(
      await page.evaluate(() => {
        const navigation = performance.getEntriesByType(
          'navigation'
        )[0] as PerformanceNavigationTiming;
        return {
          navigationMs: navigation.domContentLoadedEventEnd,
          transferBytes: performance
            .getEntriesByType('resource')
            .reduce(
              (total, entry) =>
                total + (entry as PerformanceResourceTiming).transferSize,
              0
            )
        };
      })
    );
    await expect(page.getByTestId('ai-device-lab-prototype')).toBeVisible();
    const landingHeading = page.getByRole('heading', {
      name: journey.landing
    });
    await expect(landingHeading).toBeFocused();
    await expectNoOverflow();

    await activateByTab(journey.start);
    await expect(
      page.getByRole('heading', { name: journey.app })
    ).toBeFocused();
    await expectNoOverflow();
    await activateByTab(journey.toScenario, true);
    await expect(
      page.getByRole('heading', { name: journey.scenario })
    ).toBeFocused();
    await expectNoOverflow();
    await activateByTab(journey.toReview);
    await expect(
      page.getByRole('heading', { name: journey.review })
    ).toBeFocused();
    await expectNoOverflow();
    await activateByTab(journey.toPayment);
    await expect(
      page.getByRole('heading', { name: journey.payment })
    ).toBeFocused();
    await expectNoOverflow();
    await activateByTab(journey.paid);
    await activateByTab(journey.openReadiness);
    await expect(
      page.getByRole('heading', { name: journey.readiness })
    ).toBeFocused();
    await expectNoOverflow();

    await activateWithKeyboard(journey.dashboardNav);
    await expect(
      page.getByRole('heading', { name: journey.dashboard })
    ).toBeFocused();
    await expectNoOverflow();
    await activateWithKeyboard(journey.openLane);
    await expect(
      page.getByRole('heading', { name: journey.lane })
    ).toBeFocused();
    await expectNoOverflow();
    await activateWithKeyboard(journey.backDashboard);
    await expect(
      page.getByRole('heading', { name: journey.dashboard })
    ).toBeFocused();
    await activateWithKeyboard(journey.reportNav);
    await expect(
      page.getByRole('heading', { name: journey.report })
    ).toBeFocused();
    await expectNoOverflow();
    await activateWithKeyboard(journey.operatorNav);
    await expect(
      page.getByRole('heading', { name: journey.operator })
    ).toBeFocused();
    await expectNoOverflow();
    await activateWithKeyboard(journey.statesNav);
    await expect(
      page.getByRole('heading', { name: journey.states })
    ).toBeFocused();
    await expectNoOverflow();
    await activateWithKeyboard(journey.overviewNav);
    await expect(landingHeading).toBeFocused();
    await expectNoOverflow();
  }

  const metrics = await page.evaluate(() => {
    return {
      domNodes: document.querySelectorAll('*').length,
      hasHorizontalOverflow:
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth
    };
  });
  const navigationMs = Math.max(
    ...performanceSamples.map((sample) => sample.navigationMs)
  );
  const transferBytes = Math.max(
    ...performanceSamples.map((sample) => sample.transferBytes)
  );
  const performanceMetrics = { ...metrics, navigationMs, transferBytes };
  expect(metrics.hasHorizontalOverflow).toBe(false);
  expect(metrics.domNodes).toBeLessThan(500);
  expect(navigationMs).toBeLessThan(10_000);
  expect(transferBytes).toBeLessThan(8_000_000);
  console.info(`ADL_20A_PERF ${JSON.stringify(performanceMetrics)}`);
  await testInfo.attach('mobile-performance.json', {
    body: Buffer.from(JSON.stringify(performanceMetrics, null, 2)),
    contentType: 'application/json'
  });
});

test('20a-AC1: state map covers roles, sources and next actions', async ({
  page
}) => {
  await page.goto('/en/ai-device-lab', { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: 'State map' }).click();

  const rows = page.getByTestId('state-spec');
  expect(await rows.count()).toBe(31);
  for (const requiredState of [
    'Guest',
    'Signed in',
    'CTA error',
    'Draft',
    'Generating scenario',
    'AI generation error',
    'Denied scenario',
    'Approved scenario',
    'Stale approval',
    'Pending checkout',
    'Paid checkout',
    'Failed checkout',
    'Unknown readiness',
    'Blocked readiness',
    'Ready to start',
    'Running service',
    'Needs attention',
    'Device changed',
    'Account changed',
    'Run retry',
    'Step retry',
    'Missing media',
    'Expired media',
    'Generating report',
    'Failed report',
    'Frozen report',
    'Corrected report',
    'Replacement requested',
    'Extension preview',
    'Cancellation requested',
    'Quarantined device'
  ]) {
    await expect(
      page.getByRole('heading', { name: requiredState, exact: true })
    ).toBeVisible();
  }

  const invalidRows = await rows.evaluateAll(
    (items) =>
      items.filter(
        (item) =>
          !item.getAttribute('data-role') ||
          !item.getAttribute('data-source') ||
          !item.getAttribute('data-source')?.startsWith('server.') ||
          !item.getAttribute('data-primary-action') ||
          !item.getAttribute('data-secondary-action') ||
          !item.getAttribute('data-loading-copy') ||
          !item.getAttribute('data-error-copy')
      ).length
  );
  expect(invalidRows).toBe(0);

  const previewButtons = page.getByRole('button', {
    name: /^Open interactive state:/
  });
  await expect(previewButtons).toHaveCount(31);
  for (let index = 0; index < 31; index += 1) {
    await previewButtons.nth(index).click();
    await expect(previewButtons.nth(index)).toHaveAttribute(
      'aria-pressed',
      'true'
    );
    await expect(page.locator('#adl-state-preview')).toBeFocused();
  }
  await page.getByRole('button', { name: 'Loading', exact: true }).click();
  await expect(
    page.getByRole('status').filter({ hasText: 'Verifying the clean result.' })
  ).toBeVisible();
  await page.getByRole('button', { name: 'Error', exact: true }).click();
  await expect(
    page.getByRole('status').filter({
      hasText: 'Hygiene verification failed. Keep the device ineligible.'
    })
  ).toBeVisible();
});
