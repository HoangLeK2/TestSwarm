/**
 * Đồng bộ mảng bước (FlowStep[]) ↔ document nội bộ của Flowgram (fixed-layout).
 *
 * Dùng khi sửa panel chi tiết / merge tọa độ / selector theo `_fgId`: cần ép lại JSON
 * document trên ctx để canvas re-render khớp state React, rồi đọc ngược ra steps có `_fgId`
 * ổn định (flowDocToSteps).
 *
 * Lưu ý: `fromJSON` thay toàn bộ cây — không dùng cho chỉnh sửa incremental nhẹ trên canvas.
 */
import type { FixedLayoutPluginContext } from '@flowgram.ai/fixed-layout-editor';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import { flowDocToSteps, stepsToFlowDoc } from './converters';

/** Ghi đè document trên ctx từ steps[]; trả về steps đã chuẩn hóa (có `_fgId` theo node id). */
export function applyStepsToFlowgramDocument(ctx: FixedLayoutPluginContext, steps: FlowStep[]): FlowStep[] {
  // Build FlowDocumentJSON (start / các node nội dung / end) rồi nạp vào editor
  ctx.document.fromJSON(stepsToFlowDoc(steps));
  // Serialize lại để mọi node nhận _fgId khớp id trên canvas
  return flowDocToSteps(ctx.document.toJSON());
}
