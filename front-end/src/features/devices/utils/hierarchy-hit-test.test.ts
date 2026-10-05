import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildBoundsXPath,
  hierarchyBoundsCenterRatio,
  hierarchyRatioToPoint,
  inferForegroundPackage,
  isGenericHierarchyResourceId,
  isSystemUiPackage,
  pickStableHierarchySelector,
  parseHierarchyScreenDims,
  scoreHierarchyHit
} from './hierarchy-hit-test.ts';

function mockNode(attrs: Record<string, string>): Element {
  return {
    getAttribute: (k: string) => (k in attrs ? attrs[k] : null)
  } as unknown as Element;
}

test('isGenericHierarchyResourceId flags FB obfuscated ids', () => {
  assert.equal(
    isGenericHierarchyResourceId('com.instagram.android:id/(name removed)'),
    true
  );
  assert.equal(isGenericHierarchyResourceId('android:id/list'), true);
  assert.equal(
    isGenericHierarchyResourceId('com.instagram.android:id/primary_button'),
    false
  );
});

test('isSystemUiPackage flags platform chrome but not app packages', () => {
  assert.equal(isSystemUiPackage('com.android.systemui'), true);
  assert.equal(isSystemUiPackage('android'), true);
  assert.equal(isSystemUiPackage(''), true);
  assert.equal(isSystemUiPackage('com.instagram.android'), false);
});

test('inferForegroundPackage ignores system UI chrome and picks largest app', () => {
  const nodes = [
    mockNode({ package: 'com.android.systemui', bounds: '[0,0][1080,80]' }),
    mockNode({ package: 'android', bounds: '[0,0][1080,1920]' }),
    mockNode({ package: 'com.instagram.android', bounds: '[0,80][1080,1800]' }),
    mockNode({ package: 'com.instagram.android', bounds: '[0,80][540,400]' })
  ];
  assert.equal(inferForegroundPackage(nodes), 'com.instagram.android');
});

test('inferForegroundPackage returns empty when only system UI present', () => {
  const nodes = [
    mockNode({ package: 'com.android.systemui', bounds: '[0,0][1080,80]' }),
    mockNode({ package: 'android', bounds: '[0,0][1080,1920]' })
  ];
  assert.equal(inferForegroundPackage(nodes), '');
});

test('parseHierarchyScreenDims ignores early status-bar bounds', () => {
  const nodes = [
    mockNode({ package: 'com.android.systemui', bounds: '[0,0][1080,80]' }),
    mockNode({ package: 'android', bounds: '[0,0][1080,1920]' }),
    mockNode({
      package: 'com.instagram.android',
      bounds: '[0,80][1080,1800]'
    })
  ];
  assert.deepEqual(parseHierarchyScreenDims(nodes), { dw: 1080, dh: 1920 });
});

test('parseHierarchyScreenDims falls back to max extents without a full root', () => {
  const nodes = [
    mockNode({ package: 'com.android.systemui', bounds: '[0,0][1260,133]' }),
    mockNode({
      package: 'com.instagram.android',
      bounds: '[0,133][1260,2737]'
    }),
    mockNode({ package: 'com.vivo.upslide', bounds: '[0,2737][1260,2800]' })
  ];
  assert.deepEqual(parseHierarchyScreenDims(nodes), { dw: 1260, dh: 2800 });
});

test('hierarchyRatioToPoint uses full screen dims, not the first zero-origin node', () => {
  const nodes = [
    mockNode({ package: 'com.android.systemui', bounds: '[0,0][1080,80]' }),
    mockNode({ package: 'android', bounds: '[0,0][1080,1920]' }),
    mockNode({ package: 'com.example', bounds: '[0,80][1080,1840]' })
  ];
  assert.deepEqual(hierarchyRatioToPoint(nodes, 0.5, 0.5), {
    px: 540,
    py: 960,
    dw: 1080,
    dh: 1920
  });
});

test('hierarchyRatioToPoint maps lower-screen taps below app content when nav bar exists', () => {
  const nodes = [
    mockNode({ package: 'com.android.systemui', bounds: '[0,0][1260,133]' }),
    mockNode({ package: 'com.example', bounds: '[0,133][1260,2737]' }),
    mockNode({ package: 'com.vivo.upslide', bounds: '[0,2737][1260,2800]' })
  ];
  assert.deepEqual(hierarchyRatioToPoint(nodes, 0.9, 0.98), {
    px: 1134,
    py: 2744,
    dw: 1260,
    dh: 2800
  });
});

test('hierarchyRatioToPoint prefers device screenDims over taller hierarchy bounds', () => {
  const nodes = [
    mockNode({ package: 'com.android.systemui', bounds: '[0,0][1260,133]' }),
    mockNode({
      package: 'com.instagram.android',
      bounds: '[0,133][1260,2737]'
    }),
    mockNode({ package: 'com.vivo.upslide', bounds: '[0,2737][1260,2800]' })
  ];
  assert.deepEqual(
    hierarchyRatioToPoint(nodes, 0.5, 0.5, {
      screenDims: { dw: 1260, dh: 2737 }
    }),
    { px: 630, py: 1368.5, dw: 1260, dh: 2737 }
  );
});

test('hierarchyBoundsCenterRatio uses device screenDims when provided', () => {
  const nodes = [
    mockNode({ package: 'com.android.systemui', bounds: '[0,0][1080,80]' }),
    mockNode({ package: 'android', bounds: '[0,0][1080,1920]' }),
    mockNode({
      package: 'com.example',
      bounds: '[100,500][500,700]'
    })
  ];
  assert.deepEqual(
    hierarchyBoundsCenterRatio(nodes, [100, 500, 500, 700], {
      screenDims: { dw: 1080, dh: 1920 }
    }),
    {
      rx: 300 / 1080,
      ry: 600 / 1920,
      dw: 1080,
      dh: 1920
    }
  );
});

test('hierarchyBoundsCenterRatio rejects empty and inverted bounds', () => {
  const nodes = [mockNode({ package: 'android', bounds: '[0,0][1080,1920]' })];
  assert.equal(hierarchyBoundsCenterRatio(nodes, null), null);
  assert.equal(hierarchyBoundsCenterRatio(nodes, [10, 10, 10, 20]), null);
  assert.equal(hierarchyBoundsCenterRatio(nodes, [20, 20, 10, 30]), null);
});

test('buildBoundsXPath builds a uiautomator XPath for exact hierarchy bounds', () => {
  assert.equal(
    buildBoundsXPath('[100,200][300,250]'),
    '//*[@bounds="[100,200][300,250]"]'
  );
  assert.equal(buildBoundsXPath('not-bounds'), null);
});

test('pickStableHierarchySelector uses unique resource-id', () => {
  assert.deepEqual(
    pickStableHierarchySelector(
      {
        resourceId: 'com.example:id/submit',
        bounds: '[10,20][30,40]'
      },
      { resourceIdCount: 1 },
      { allowBoundsXPath: true }
    ),
    {
      by: 'resource-id',
      value: 'com.example:id/submit',
      selectorReason: 'unique resource-id',
      selectorVolatile: false,
      resourceIdDuplicateCount: 1,
      textDuplicateCount: 0,
      descDuplicateCount: 0
    }
  );
});

test('pickStableHierarchySelector avoids duplicate resource-id and uses unique text', () => {
  assert.deepEqual(
    pickStableHierarchySelector(
      {
        resourceId: 'com.example:id/item',
        text: 'Target row',
        bounds: '[100,200][500,260]'
      },
      { resourceIdCount: 8, textCount: 1 },
      { allowBoundsXPath: true }
    ),
    {
      by: 'text',
      value: 'Target row',
      selectorReason: 'unique text',
      selectorVolatile: false,
      resourceIdDuplicateCount: 8,
      textDuplicateCount: 1,
      descDuplicateCount: 0
    }
  );
});

test('pickStableHierarchySelector avoids generic resource-id even when currently unique', () => {
  assert.deepEqual(
    pickStableHierarchySelector(
      {
        resourceId: 'com.instagram.android:id/(name removed)',
        text: 'Theo dõi',
        pkg: 'com.instagram.android',
        bounds: '[100,200][500,260]'
      },
      { resourceIdCount: 1, textCount: 1 },
      { allowBoundsXPath: true }
    ),
    {
      by: 'text',
      value: 'Theo dõi',
      selectorReason: 'unique text',
      selectorVolatile: false,
      resourceIdDuplicateCount: 1,
      textDuplicateCount: 1,
      descDuplicateCount: 0
    }
  );
});

test('pickStableHierarchySelector falls back to bounds XPath for duplicate selectors', () => {
  assert.deepEqual(
    pickStableHierarchySelector(
      {
        resourceId: 'com.example:id/item',
        text: 'Like',
        contentDesc: 'Like',
        bounds: '[100,200][500,260]'
      },
      { resourceIdCount: 8, textCount: 4, descCount: 4 },
      { allowBoundsXPath: true }
    ),
    {
      by: 'xpath',
      value: '//*[@bounds="[100,200][500,260]"]',
      selectorReason: 'bounds fallback',
      selectorVolatile: true,
      resourceIdDuplicateCount: 8,
      textDuplicateCount: 4,
      descDuplicateCount: 4
    }
  );
});

test('pickStableHierarchySelector never picks duplicate launcher icon resource-id', () => {
  assert.deepEqual(
    pickStableHierarchySelector(
      {
        resourceId: 'com.sec.android.app.launcher:id/icon',
        text: 'Instagram',
        pkg: 'com.sec.android.app.launcher',
        bounds: '[100,200][220,340]'
      },
      { resourceIdCount: 20, textCount: 1 },
      { allowBoundsXPath: true }
    ),
    {
      by: 'text',
      value: 'Instagram',
      selectorReason: 'unique text',
      selectorVolatile: false,
      resourceIdDuplicateCount: 20,
      textDuplicateCount: 1,
      descDuplicateCount: 0
    }
  );
});

test('scoreHierarchyHit prefers deep semantic node over outer FB container', () => {
  const outerRecycler = scoreHierarchyHit({
    depth: 4,
    area: 400 * 800,
    clickable: true,
    text: '',
    contentDesc: '',
    resourceId: 'android:id/list',
    className: 'androidx.recyclerview.widget.RecyclerView',
    resourceIdCount: 1
  });
  const storyButton = scoreHierarchyHit({
    depth: 8,
    area: 110 * 270,
    clickable: true,
    text: 'Tạo tin',
    contentDesc: 'Tạo tin',
    resourceId: '',
    className: 'android.widget.Button',
    resourceIdCount: 0
  });
  assert.ok(storyButton > outerRecycler);
});

test('scoreHierarchyHit prefers content-desc over duplicate generic resource-id shell', () => {
  const shell = scoreHierarchyHit({
    depth: 6,
    area: 360 * 360,
    clickable: true,
    text: '',
    contentDesc: '',
    resourceId: 'com.instagram.android:id/(name removed)',
    className: 'android.view.ViewGroup',
    resourceIdCount: 40
  });
  const profile = scoreHierarchyHit({
    depth: 9,
    area: 120 * 120,
    clickable: true,
    text: '',
    contentDesc: 'Đi tới trang cá nhân',
    resourceId: '',
    className: 'android.widget.Button',
    resourceIdCount: 0
  });
  assert.ok(profile > shell);
});
