import { z } from 'zod';

export const deviceSchema = z.object({
  serial: z.string(),
  brand: z.string(),
  model: z.string(),
  state: z.string(),
  battery: z.number(),
  current_app: z.string().optional(),
  screen_width: z.number().optional(),
  screen_height: z.number().optional()
});

export const taskSchema = z.object({
  id: z.string(),
  name: z.string(),
  status: z.string(),
  target: z.string().optional(),
  retry_count: z.number(),
  max_retries: z.number(),
  error: z.string().optional()
});

export type DeviceSchema = z.infer<typeof deviceSchema>;
export type TaskSchema = z.infer<typeof taskSchema>;
