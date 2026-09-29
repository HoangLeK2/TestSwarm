import assert from 'node:assert/strict';
import test from 'node:test';

import {
  contentInteractionPresentation
  // @ts-expect-error Node --experimental-strip-types imports TS sources by extension.
} from './content-interaction-presentation.ts';

test('post flow presentation distinguishes the verified post from its runtime variable', () => {
  const post = contentInteractionPresentation({
    type: 'social_select_target',
    target_type: 'post',
    save_as: '_post_target'
  });
  assert.equal(post.isPost, true);
  assert.equal(post.identity, '');

  const identified = contentInteractionPresentation({
    type: 'social_select_target',
    target_type: 'post',
    display_text: 'A distinctive headline',
    save_as: '_post_target'
  });
  assert.equal(identified.identity, 'A distinctive headline');
});

test('comment preview resolves only a supplied comment variable or literal text', () => {
  const comment = {
    type: 'content_interaction',
    action: 'comment',
    comment_text: '${COMMENT_TEXT}'
  };
  assert.equal(contentInteractionPresentation(comment).commentReady, false);
  assert.equal(
    contentInteractionPresentation(comment).commentVariable,
    'COMMENT_TEXT'
  );
  assert.equal(
    contentInteractionPresentation(comment, { COMMENT_TEXT: '  Hello!  ' })
      .commentPreview,
    'Hello!'
  );
  assert.equal(
    contentInteractionPresentation({
      ...comment,
      comment_text: 'A literal comment'
    }).commentPreview,
    'A literal comment'
  );
});
