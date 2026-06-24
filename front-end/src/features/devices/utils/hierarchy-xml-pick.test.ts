import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  findSelectorInXml,
  listSelectorCandidatesInXml
} from './hierarchy-xml-pick.ts';

class TestElement {
  tagName = 'node';
  children: TestElement[] = [];
  parentElement: TestElement | null = null;
  private readonly attrs: Record<string, string>;

  constructor(attrs: Record<string, string>) {
    this.attrs = attrs;
  }

  getAttribute(name: string): string | null {
    return this.attrs[name] ?? null;
  }
}

class TestDocument {
  private readonly nodes: TestElement[];

  constructor(nodes: TestElement[]) {
    this.nodes = nodes;
  }

  getElementsByTagName(tagName: string): TestElement[] {
    return tagName === 'node' ? this.nodes : [];
  }
}

function parseAttrs(raw: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  const attrRe = /([\w:-]+)="([^"]*)"/g;
  let match: RegExpExecArray | null;
  while ((match = attrRe.exec(raw)) != null) {
    attrs[match[1]] = match[2];
  }
  return attrs;
}

class TestDOMParser {
  parseFromString(xml: string): TestDocument {
    const nodes: TestElement[] = [];
    const stack: TestElement[] = [];
    const tagRe = /<\/node>|<node\b([^>]*?)(\/?)>/g;
    let match: RegExpExecArray | null;

    while ((match = tagRe.exec(xml)) != null) {
      if (match[0] === '</node>') {
        stack.pop();
        continue;
      }

      const node = new TestElement(parseAttrs(match[1] ?? ''));
      const parent = stack.at(-1) ?? null;
      node.parentElement = parent;
      if (parent) parent.children.push(node);
      nodes.push(node);

      if (match[2] !== '/') {
        stack.push(node);
      }
    }

    return new TestDocument(nodes);
  }
}

(globalThis as unknown as { DOMParser: typeof TestDOMParser }).DOMParser =
  TestDOMParser;

function fixture(name: string): string {
  return readFileSync(`../device_farm/tests/fixtures/element_finding/${name}`, {
    encoding: 'utf-8'
  });
}

test('listSelectorCandidatesInXml keeps tapped action ahead of row sibling text', () => {
  const xml = fixture('facebook_row_action.xml');
  const picks = listSelectorCandidatesInXml(xml, 930 / 1080, 154 / 1920, {
    targetPackage: 'com.facebook.katana',
    screenDims: { dw: 1080, dh: 1920 }
  });

  assert.equal(picks[0]?.by, 'xpath');
  assert.equal(picks[0]?.value, '//*[@bounds="[820,118][1040,190]"]');
  assert.equal(picks[0]?.selectorVolatile, true);
});

test('listSelectorCandidatesInXml still uses row semantic text when tapping blank row area', () => {
  const xml = fixture('facebook_row_action.xml');
  const picks = listSelectorCandidatesInXml(xml, 760 / 1080, 154 / 1920, {
    targetPackage: 'com.facebook.katana',
    screenDims: { dw: 1080, dh: 1920 }
  });

  assert.equal(picks[0]?.by, 'description');
  assert.equal(picks[0]?.value, 'Group Alpha, 42K members');
});

test('findSelectorInXml keeps exact group description instead of broad startsWith prefix', () => {
  const xml = fixture('facebook_row_action.xml');
  const pick = findSelectorInXml(xml, 760 / 1080, 154 / 1920, {
    targetPackage: 'com.facebook.katana',
    screenDims: { dw: 1080, dh: 1920 }
  });

  assert.equal(pick?.by, 'description');
  assert.equal(pick?.value, 'Group Alpha, 42K members');
  assert.equal(pick?.selector.by, 'description');
  assert.equal(pick?.selector.value, 'Group Alpha, 42K members');
});

test('findSelectorInXml pins duplicate comment button instead of group header shell', () => {
  const xml = fixture('facebook_group_feed.xml');
  const pick = findSelectorInXml(xml, 200 / 1080, 650 / 1920, {
    targetPackage: 'com.facebook.katana',
    screenDims: { dw: 1080, dh: 1920 }
  });

  assert.equal(pick?.by, 'xpath');
  assert.equal(pick?.value, '//*[@bounds="[100,620][300,680]"]');
  assert.notEqual(pick?.value, 'Codex VN, Công khai · 11K thành viên');
});

test('findSelectorInXml prefers comment author over group header when names are unique', () => {
  const xml = fixture('facebook_group_feed.xml');
  const pick = findSelectorInXml(xml, 320 / 1080, 750 / 1920, {
    targetPackage: 'com.facebook.katana',
    screenDims: { dw: 1080, dh: 1920 }
  });

  assert.equal(pick?.by, 'text');
  assert.equal(pick?.value, 'Anonymous Member 175');
});

// Live dump from MCP df_hierarchy (Codex VN group feed, V2352A 1260×2737).
test('live Codex VN: post comment button is Bình luận not group header', () => {
  const xml = fixture('facebook_codex_vn_live.xml');
  const opts = {
    targetPackage: 'com.facebook.katana',
    screenDims: { dw: 1260, dh: 2737 }
  };
  const pick = findSelectorInXml(xml, 310 / 1260, 1069 / 2737, opts);

  assert.equal(pick?.by, 'description');
  assert.equal(pick?.value, 'Bình luận');
  assert.notEqual(pick?.value, 'Codex VN');
});

test('live Codex VN: group header tap only when touching title chrome', () => {
  const xml = fixture('facebook_codex_vn_live.xml');
  const pick = findSelectorInXml(xml, 356 / 1260, 212 / 2737, {
    targetPackage: 'com.facebook.katana',
    screenDims: { dw: 1260, dh: 2737 }
  });

  assert.equal(pick?.by, 'description');
  assert.equal(pick?.value, 'Codex VN');
});

test('live Codex VN: author row maps to member name not profile shell xpath', () => {
  const xml = fixture('facebook_codex_vn_live.xml');
  const pick = findSelectorInXml(xml, 486 / 1260, 1467 / 2737, {
    targetPackage: 'com.facebook.katana',
    screenDims: { dw: 1260, dh: 2737 }
  });

  assert.equal(pick?.by, 'description');
  assert.equal(pick?.value, 'Người tham gia ẩn danh 175');
});
