'use client';

import { useTranslations } from 'next-intl';
import {
  getInsertMenuForUi,
  getStepDisplay,
  getStepTypeName,
  type FlowStepTranslator,
} from './constants';

/** Campaign flow editor + step list i18n helpers. */
export function useCampaignFlowI18n() {
  const tInsert = useTranslations('campaignsFeature.flowInsert');
  const tStep = useTranslations('campaignsFeature.flowStep');
  const tEditor = useTranslations('campaignsFeature.stepEditor');
  const tValidation = useTranslations('campaignsFeature.scenarioValidation');

  const stepT: FlowStepTranslator = (key, values) =>
    tStep(key as Parameters<typeof tStep>[0], values as Record<string, string | number>);

  return {
    tInsert,
    tEditor,
    tValidation,
    getInsertMenu: () => getInsertMenuForUi(tInsert),
    getStepTypeName: (type: string) => getStepTypeName(type, stepT),
    getStepDisplay: (step: Parameters<typeof getStepDisplay>[0]) => getStepDisplay(step, stepT),
  };
}
