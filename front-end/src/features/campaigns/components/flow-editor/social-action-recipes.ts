import { createDefaultStep, type FlowStep } from '../scenario-steps/types';

export const CONTENT_LIKE_COMMENT_RECIPE = 'social_content_like_comment_flow';

export function createContentLikeCommentFlow(): FlowStep[] {
  const target: FlowStep = {
    ...createDefaultStep('social_select_target'),
    platform: 'facebook',
    target_type: 'post',
    save_as: '_post_target'
  };
  const like: FlowStep = {
    ...createDefaultStep('content_interaction', target.order, null),
    platform: 'facebook',
    action: 'like',
    require_verified_target: '_post_target',
    save_as: 'CONTENT_LIKE_RESULT'
  };
  const comment: FlowStep = {
    ...createDefaultStep('content_interaction', like.order, null),
    platform: 'facebook',
    action: 'comment',
    comment_text: '${COMMENT_TEXT}',
    require_verified_target: '_post_target',
    save_as: 'CONTENT_COMMENT_RESULT'
  };
  return [target, like, comment];
}
