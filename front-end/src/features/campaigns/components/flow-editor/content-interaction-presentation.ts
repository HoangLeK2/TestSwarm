import type { FlowStep } from '../scenario-steps/types';
import type { VariablePreviewValues } from './variable-preview';

/** Presentation-only state; the step payload and runtime variable names stay intact. */
export function contentInteractionPresentation(
  step: FlowStep,
  variables?: VariablePreviewValues | null
) {
  const isPost =
    step.type === 'social_select_target' && step.target_type === 'post';
  const isLike = step.type === 'content_interaction' && step.action === 'like';
  const isComment =
    step.type === 'content_interaction' && step.action === 'comment';
  const identity = String(step.display_text || step.search || '').trim();
  const comment = String(step.comment_text || '').trim();
  const variableMatch = /^\$\{([A-Za-z][A-Za-z0-9_]*)\}$/.exec(comment);
  const resolvedComment = variableMatch
    ? variables?.[variableMatch[1]]
    : comment;
  const commentReady =
    typeof resolvedComment === 'string' && resolvedComment.trim().length > 0;

  return {
    isPost,
    isLike,
    isComment,
    identity,
    commentReady,
    commentVariable: variableMatch?.[1] ?? null,
    commentPreview: commentReady ? String(resolvedComment).trim() : ''
  };
}
