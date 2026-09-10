'use client';

import { useTranslations } from 'next-intl';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { isIntlMissingMessage } from './constants';
import { CollapsibleBlock } from './extract-fields';
import {
  StepPanelField,
  StepPanelInput,
  StepPanelTextarea,
  StepPanelToggle
} from './step-panel-primitives';

/** An enum choice: a bare value, or one carrying its own label key. */
export type StepFieldValue = string | { value: string; label_key?: string };

/** One field of a node's config, as declared by the backend STEP_SCHEMA. */
export type StepFieldSpec = {
  type?: 'string' | 'number' | 'boolean' | 'enum' | 'json';
  values?: StepFieldValue[];
  default?: unknown;
  min?: number;
  max?: number;
  pattern?: string;
  label_key?: string;
  placeholder_key?: string;
  /** Safety valve / tuning knob: correct by default, hidden until asked for. */
  advanced?: boolean;
};

export type StepTypeSchema = {
  required?: string[];
  optional?: string[];
  required_any?: string[][];
  fields?: Record<string, StepFieldSpec>;
  description?: string;
};

export type StepSchemaMap = Record<string, StepTypeSchema>;

/** `wait_after` → `Wait after`. The fallback when a field declares no label_key. */
export function humanizeFieldName(name: string): string {
  const words = name.replace(/[_-]+/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

type StepEditorTranslator = ReturnType<
  typeof useTranslations<'campaignsFeature.stepEditor'>
>;

/**
 * Resolve a schema-declared key, falling back rather than printing it.
 *
 * The key is only known at run time, so the message type cannot check it and
 * scripts/check-i18n-keys.mjs cannot see it either — next-intl would render
 * "appLifecycle.packageLabel" straight into the UI. Same guard the step-type
 * labels already use; check-schema-field-i18n.mjs is what stops the fallback
 * from silently becoming the normal case.
 */
function resolveKey(
  t: StepEditorTranslator,
  key: string | undefined,
  fallback: string
): string {
  if (!key) return fallback;
  const label = t(key as 'stepFields.position');
  return isIntlMissingMessage(key, label) ? fallback : label;
}

/** Read the schema entry for a step type, or undefined when it has not migrated. */
export function schemaFieldsFor(
  schema: StepSchemaMap | undefined,
  stepType: string
): Record<string, StepFieldSpec> | undefined {
  const fields = schema?.[stepType]?.fields;
  return fields && Object.keys(fields).length > 0 ? fields : undefined;
}

type Props = {
  name: string;
  spec: StepFieldSpec;
  value: unknown;
  onChange: (value: unknown) => void;
};

/**
 * Renders one schema-declared field with the existing step-panel primitives.
 *
 * The point is not a new design system — it is that the field's type, bounds and
 * label live in one place (device_farm/common/scenario_schema.py) instead of
 * being restated by hand in a branch of the 3,900-line detail panel. Nodes that
 * declare no `fields` keep their hand-written form.
 */
export function SchemaField({ name, spec, value, onChange }: Props) {
  // Namespace, not stepFields: label_key is a dotted path so a field can reuse
  // any wording the editor already ships (appLifecycle.packageLabel, …).
  const t = useTranslations('campaignsFeature.stepEditor');
  const kind = spec.type ?? 'string';

  const label = resolveKey(t, spec.label_key, humanizeFieldName(name));
  const resolvedPlaceholder = resolveKey(t, spec.placeholder_key, '');
  const placeholder = resolvedPlaceholder || undefined;

  if (kind === 'boolean') {
    const checked =
      typeof value === 'boolean' ? value : Boolean(spec.default ?? false);
    return (
      <StepPanelToggle
        label={label}
        checked={checked}
        onCheckedChange={onChange}
      />
    );
  }

  if (kind === 'enum') {
    return (
      <StepPanelField label={label}>
        <Select
          value={typeof value === 'string' ? value : ''}
          onValueChange={onChange}
        >
          <SelectTrigger className='h-8 text-xs'>
            <SelectValue placeholder={placeholder} />
          </SelectTrigger>
          <SelectContent>
            {(spec.values ?? []).map((option) => {
              const choice =
                typeof option === 'string' ? { value: option } : option;
              return (
                <SelectItem
                  key={choice.value}
                  value={choice.value}
                  className='text-xs'
                >
                  {resolveKey(
                    t,
                    choice.label_key,
                    humanizeFieldName(choice.value)
                  )}
                </SelectItem>
              );
            })}
          </SelectContent>
        </Select>
      </StepPanelField>
    );
  }

  if (kind === 'json') {
    return (
      <StepPanelField label={label}>
        <StepPanelTextarea
          className='min-h-20 w-full rounded-md border border-input bg-background px-2 py-1.5 font-mono text-xs'
          value={value == null ? '' : JSON.stringify(value, null, 2)}
          placeholder={placeholder}
          onValueCommit={(next) => {
            const text = next.trim();
            if (!text) return onChange(undefined);
            try {
              onChange(JSON.parse(text));
            } catch {
              // Keep the last valid value: committing a half-typed object would
              // wipe the field while the user is still editing it.
            }
          }}
        />
      </StepPanelField>
    );
  }

  if (kind === 'number') {
    return (
      <StepPanelField label={label}>
        <StepPanelInput
          type='number'
          min={spec.min}
          max={spec.max}
          className='h-8 w-32 text-xs'
          value={value == null ? '' : String(value)}
          placeholder={placeholder ?? String(spec.default ?? '')}
          onValueCommit={(next) => {
            const text = next.trim();
            if (!text) return onChange(undefined);
            // ${VAR} is a legitimate value here — the backend resolves it at run
            // time and validate_step lets it through untyped.
            if (text.includes('${')) return onChange(text);
            const parsed = Number(text);
            onChange(Number.isFinite(parsed) ? parsed : text);
          }}
        />
      </StepPanelField>
    );
  }

  return (
    <StepPanelField label={label}>
      <StepPanelInput
        className='h-8 text-xs'
        value={typeof value === 'string' ? value : ''}
        placeholder={placeholder}
        onValueCommit={(next) => onChange(next || undefined)}
      />
    </StepPanelField>
  );
}

/**
 * Render every declared field of a node, in schema order.
 *
 * Fields marked `advanced` move into a collapsed block — the same progressive
 * disclosure `extract` already uses, reusing its CollapsibleBlock rather than a
 * second one. A node with a dozen tuning knobs stays readable, and the knobs
 * stay reachable.
 */
export function SchemaFields({
  fields,
  step,
  onChange
}: {
  fields: Record<string, StepFieldSpec>;
  step: Record<string, unknown>;
  onChange: (patch: Record<string, unknown>) => void;
}) {
  const t = useTranslations('campaignsFeature.stepEditor');
  const entries = Object.entries(fields);
  const primary = entries.filter(([, spec]) => !spec.advanced);
  const advanced = entries.filter(([, spec]) => spec.advanced);

  const render = ([name, spec]: [string, StepFieldSpec]) => (
    <SchemaField
      key={name}
      name={name}
      spec={spec}
      value={step[name]}
      onChange={(value) => onChange({ [name]: value })}
    />
  );

  return (
    <>
      {primary.map(render)}
      {advanced.length > 0 ? (
        <CollapsibleBlock
          title={t('advancedFieldsTitle')}
          badge={
            <span className='text-[10px] text-muted-foreground'>
              {t('advancedDefaultOk')}
            </span>
          }
        >
          {advanced.map(render)}
        </CollapsibleBlock>
      ) : null}
    </>
  );
}
