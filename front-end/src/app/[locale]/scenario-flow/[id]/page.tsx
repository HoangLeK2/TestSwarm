'use client';

import { use } from 'react';
import { ScenarioFlowEditor } from '@/features/scenario-templates/components/scenario-flow-editor';

export default function ScenarioFlowPage({
  params
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return <ScenarioFlowEditor templateId={id} />;
}
