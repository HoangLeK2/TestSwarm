'use client';

import {
  MousePointerClick,
  MoveRight,
  ArrowDownToLine,
  Keyboard,
  Smartphone,
  Globe,
  Timer,
  Search,
  CheckCircle,
  XCircle,
  Variable,
  Repeat,
  Repeat1,
  GitBranch,
  Dice5,
  Package,
  Hand,
  CircleDot,
  type LucideProps
} from 'lucide-react';
import { cn } from '@/lib/utils';

const ICON_MAP: Record<string, React.ComponentType<LucideProps>> = {
  tap: MousePointerClick,
  tap_ratio: CircleDot,
  tap_position: CircleDot,
  tap_selector: MousePointerClick,
  long_tap_selector: Hand,
  swipe_ratio: MoveRight,
  input_text: Keyboard,
  input_selector: Keyboard,
  key: Keyboard,
  launch_app: Smartphone,
  open_url: Globe,
  scroll_down: ArrowDownToLine,
  scroll_to: ArrowDownToLine,
  wait: Timer,
  wait_element: Search,
  wait_stable: Timer,
  assert_element: CheckCircle,
  dismiss_popup: XCircle,
  set_variable: Variable,
  repeat: Repeat,
  repeat_until: Repeat1,
  if_element: GitBranch,
  if_variable: GitBranch,
  random_pick: Dice5,
  run_scenario: Package,
};

const COLOR_MAP: Record<string, string> = {
  tap: 'text-blue-500', tap_ratio: 'text-blue-500', tap_position: 'text-blue-500',
  tap_selector: 'text-blue-500', long_tap_selector: 'text-blue-500', swipe_ratio: 'text-blue-500',
  input_text: 'text-cyan-500', input_selector: 'text-cyan-500', key: 'text-cyan-500',
  launch_app: 'text-indigo-500', open_url: 'text-indigo-500',
  scroll_down: 'text-indigo-400', scroll_to: 'text-indigo-400',
  wait: 'text-green-500', wait_element: 'text-green-500', wait_stable: 'text-green-500',
  assert_element: 'text-green-600', dismiss_popup: 'text-red-400',
  set_variable: 'text-purple-500',
  repeat: 'text-orange-500', repeat_until: 'text-orange-500',
  if_element: 'text-amber-500', if_variable: 'text-amber-500',
  random_pick: 'text-rose-500', run_scenario: 'text-pink-500',
};

interface Props {
  type: string;
  size?: number;
  className?: string;
}

export function StepIcon({ type, size = 12, className }: Props) {
  const Icon = ICON_MAP[type] ?? MousePointerClick;
  const color = COLOR_MAP[type] ?? 'text-muted-foreground';
  return <Icon size={size} className={cn(color, className)} />;
}
