'use client';

import { useCallback, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import dynamic from 'next/dynamic';
import { ArrowLeft, Save, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import {
  useScenarioTemplate,
  useUpdateScenarioTemplate
} from '../../hooks/use-scenario-templates';
import { ROUTES } from '@/config/routes';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';

// ─── Dynamically import the actual canvas to avoid SSR / InversifyJS issues ───

const DynamicCanvas = dynamic(
  () => import('./canvas').then((m) => m.FlowgramCanvas),
  {
    ssr: false,
    loading: () => (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flex: 1
        }}
      >
        <Loader2
          size={24}
          style={{ animation: 'spin 1s linear infinite', color: '#9ca3af' }}
        />
      </div>
    )
  }
);

// ─── ScenarioFlowEditor ───────────────────────────────────────────────────────

interface Props {
  templateId: string;
}

export function ScenarioFlowEditor({ templateId }: Props) {
  const router = useRouter();
  const { data: template, isLoading } = useScenarioTemplate(templateId);
  const updateMutation = useUpdateScenarioTemplate();
  const { canUpdate } = useResourcePermissions('scenario-templates');
  const [isSaving, setIsSaving] = useState(false);
  // Track latest steps from canvas changes
  const latestStepsRef = useRef<Record<string, any>[]>([]);

  const handleBack = useCallback(() => {
    router.push(ROUTES.SCENARIO_TEMPLATES.ROOT);
  }, [router]);

  const handleSave = useCallback(async () => {
    setIsSaving(true);
    try {
      await updateMutation.mutateAsync({
        templateId,
        data: { steps: latestStepsRef.current }
      });
      toast.success('Đã lưu kịch bản');
    } catch {
      toast.error('Lưu thất bại');
    } finally {
      setIsSaving(false);
    }
  }, [templateId, updateMutation]);

  if (isLoading) {
    return (
      <div style={centeredStyle}>
        <Loader2
          size={32}
          style={{ animation: 'spin 1s linear infinite', color: '#6b7280' }}
        />
      </div>
    );
  }

  if (!template) {
    return (
      <div style={{ ...centeredStyle, flexDirection: 'column', gap: 16 }}>
        <p style={{ color: '#6b7280', fontSize: 14 }}>
          Không tìm thấy template
        </p>
        <button onClick={handleBack} style={iconBtn}>
          Quay lại
        </button>
      </div>
    );
  }

  // Initialize latestStepsRef with template steps on first render
  if (
    latestStepsRef.current.length === 0 &&
    (template.steps?.length ?? 0) > 0
  ) {
    latestStepsRef.current = template.steps ?? [];
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        width: '100vw',
        height: '100vh',
        overflow: 'hidden'
      }}
    >
      {/* Toolbar */}
      <div style={topBarStyle}>
        <button onClick={handleBack} style={iconBtn} title='Quay lại'>
          <ArrowLeft size={15} />
        </button>
        <div
          style={{
            width: 1,
            height: 22,
            background: '#e5e7eb',
            margin: '0 4px'
          }}
        />
        <span style={nameStyle}>{template.name}</span>
        {canUpdate ? (
          <button onClick={handleSave} disabled={isSaving} style={saveBtn}>
            {isSaving ? (
              <Loader2
                size={14}
                style={{ animation: 'spin 1s linear infinite' }}
              />
            ) : (
              <Save size={14} />
            )}
            Lưu
          </button>
        ) : null}
      </div>

      {/* Canvas */}
      <div style={{ flex: 1, overflow: 'hidden' }}>
        <DynamicCanvas
          key={template.id}
          steps={(template.steps ?? []) as any}
          onStepsChange={(steps) => {
            latestStepsRef.current = steps as any;
          }}
        />
      </div>
    </div>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const centeredStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  height: '100vh'
};

const topBarStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '0 12px',
  height: 52,
  flexShrink: 0,
  background: 'white',
  borderBottom: '1px solid #e5e7eb',
  boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
  fontFamily: 'system-ui, -apple-system, sans-serif'
};

const nameStyle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
  color: '#111827',
  flex: 1,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap'
};

const iconBtn: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 4,
  background: 'transparent',
  border: '1px solid #e5e7eb',
  borderRadius: 6,
  padding: '5px 8px',
  cursor: 'pointer',
  color: '#374151',
  fontSize: 13
};

const saveBtn: React.CSSProperties = {
  ...iconBtn,
  background: '#2563eb',
  borderColor: '#2563eb',
  color: 'white',
  padding: '6px 14px',
  fontWeight: 600,
  gap: 6
};
