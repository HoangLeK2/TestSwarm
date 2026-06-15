import assert from 'node:assert/strict';
import test from 'node:test';

import {
  inferForegroundPackage,
  isGenericHierarchyResourceId,
  isSystemUiPackage,
  scoreHierarchyHit
} from './hierarchy-hit-test.ts';

function mockNode(attrs: Record<string, string>): Element {
  return {
    getAttribute: (k: string) => (k in attrs ? attrs[k] : null)
  } as unknown as Element;
}

test('isGenericHierarchyResourceId flags FB obfuscated ids', () => {
  assert.equal(
    isGenericHierarchyResourceId('com.facebook.katana:id/(name removed)'),
    true
  );
  assert.equal(isGenericHierarchyResourceId('android:id/list'), true);
  assert.equal(
    isGenericHierarchyResourceId('com.facebook.katana:id/primary_button'),
    false
  );
});

test('isSystemUiPackage flags platform chrome but not app packages', () => {
  assert.equal(isSystemUiPackage('com.android.systemui'), true);
  assert.equal(isSystemUiPackage('android'), true);
  assert.equal(isSystemUiPackage(''), true);
  assert.equal(isSystemUiPackage('com.facebook.katana'), false);
});

test('inferForegroundPackage ignores system UI chrome and picks largest app', () => {
  const nodes = [
    mockNode({ package: 'com.android.systemui', bounds: '[0,0][1080,80]' }),
    mockNode({ package: 'android', bounds: '[0,0][1080,1920]' }),
    mockNode({ package: 'com.facebook.katana', bounds: '[0,80][1080,1800]' }),
    mockNode({ package: 'com.facebook.katana', bounds: '[0,80][540,400]' })
  ];
  assert.equal(inferForegroundPackage(nodes), 'com.facebook.katana');
});

test('inferForegroundPackage returns empty when only system UI present', () => {
  const nodes = [
    mockNode({ package: 'com.android.systemui', bounds: '[0,0][1080,80]' }),
    mockNode({ package: 'android', bounds: '[0,0][1080,1920]' })
  ];
  assert.equal(inferForegroundPackage(nodes), '');
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
    resourceId: 'com.facebook.katana:id/(name removed)',
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
