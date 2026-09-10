import assert from 'node:assert/strict';
import test from 'node:test';
import { createTranslator } from 'next-intl';
import { readFileSync } from 'node:fs';
import {
  getStepDisplay,
  getStepTypeName,
  getVariableDisplayName
} from './constants.ts';
import { resolveVariablePreviewText } from './variable-preview.ts';

const labels: Record<string, string> = {
  'typeName.platform_session_gate': 'KIỂM TRA PHIÊN NỀN TẢNG',
  'display.platformSessionPreflight': 'Kiểm tra trước khi tiếp tục',
  'systemVariable.platformSessionReady': 'Phiên nền tảng sẵn sàng'
};

const t = (key: string) => labels[key] ?? `campaignsFeature.flowStep.${key}`;

test('localizes post scan cards with keyword arrays and empty keywords', () => {
  for (const locale of ['vi', 'en']) {
    const messages = JSON.parse(
      readFileSync(
        new URL(`../../../../../messages/${locale}.json`, import.meta.url),
        'utf8'
      )
    );
    const translate = createTranslator({
      locale,
      messages,
      namespace: 'campaignsFeature.flowStep',
      onError(error) {
        throw error;
      }
    });
    for (const keywords of [
      ['coffee', 'tea'],
      'coffee, tea',
      [],
      '',
      undefined
    ]) {
      const keywordLabel = Array.isArray(keywords)
        ? keywords.join(', ')
        : keywords;
      const expectedLabel =
        keywordLabel || translate('display.socialScanPostsAnyKeyword');
      assert.equal(
        getStepDisplay(
          { type: 'social_scan_posts_interact', keywords, target_count: 3 },
          translate
        ).target,
        `${expectedLabel} · 3 ${locale === 'vi' ? 'bài' : 'items'}`
      );
    }
  }
});

test('localizes the platform session node without exposing Facebook internals', () => {
  assert.equal(
    getStepTypeName('platform_session_gate', t),
    'KIỂM TRA PHIÊN NỀN TẢNG'
  );
  assert.deepEqual(
    getStepDisplay({ type: 'platform_session_gate', phase: 'preflight' }, t),
    { target: 'Kiểm tra trước khi tiếp tục' }
  );
  assert.equal(
    getVariableDisplayName('PLATFORM_SESSION_READY', t),
    'Phiên nền tảng sẵn sàng'
  );
});

test('keeps user-authored variable names unchanged', () => {
  assert.equal(
    getVariableDisplayName('MY_CUSTOM_VARIABLE', t),
    'MY_CUSTOM_VARIABLE'
  );
});

test('resolves variable references for node display previews', () => {
  assert.equal(
    resolveVariablePreviewText('${SEARCH_QUERY}', {
      SEARCH_QUERY: 'openclaw'
    }),
    'openclaw'
  );
  assert.equal(
    resolveVariablePreviewText('"${SEARCH_QUERY}"', {
      SEARCH_QUERY: 'openclaw'
    }),
    '"openclaw"'
  );
  assert.equal(
    resolveVariablePreviewText('${MAX_PAGES}', {
      MAX_PAGES: { type: 'number', default: 20 }
    }),
    '20'
  );
  assert.equal(
    resolveVariablePreviewText('${MISSING}', { SEARCH_QUERY: 'openclaw' }),
    '${MISSING}'
  );
});
