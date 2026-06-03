'use client';

import { use, useEffect } from 'react';
import { ROUTES } from '@/config/routes';
import { useRouter } from '@/i18n/navigation';

/** Graph flow editor disabled — sequence-only org scenarios. */
export default function OrgScenarioFlowPage({
  params
}: {
  params: Promise<{ scenarioId: string }>;
}) {
  const { scenarioId } = use(params);
  const router = useRouter();

  useEffect(() => {
    router.replace(ROUTES.ORG_SCENARIOS.DETAIL(scenarioId));
  }, [router, scenarioId]);

  return null;
}
