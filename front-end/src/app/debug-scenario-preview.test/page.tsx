'use client';

import { useEffect, useState } from 'react';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle
} from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ScenarioBodyPreview } from '@/features/org-scenarios/components/scenario-body-preview';

const leafSteps = [
  { type: 'tap_selector', by: 'text', value: 'Continue', timeout: 4 },
  { type: 'wait_stable', timeout: 4, stable_duration: 0.5 },
  { type: 'input_text', text: '${USERNAME}', via: 'u2' },
  { type: 'tap_selector', by: 'text', value: 'Next', timeout: 4 }
];

const body = {
  variables: { USERNAME: 'debug@example.com' },
  steps: [
    {
      type: 'launch_app',
      package: 'com.facebook.katana',
      title: 'Mở Facebook'
    },
    { type: 'wait_stable', timeout: 5, stable_duration: 0.5 },
    {
      type: 'if_element',
      by: 'text',
      value: 'Bạn đang nghĩ gì?',
      timeout: 4,
      then: [],
      else: [
        {
          type: 'if_element',
          by: 'text',
          value: 'Trang chủ',
          timeout: 2,
          then: [],
          else: [
            {
              type: 'if_variable',
              name: 'LOGIN_METHOD',
              equals: 'native',
              then: leafSteps,
              else: [
                {
                  type: 'if_element',
                  by: 'text',
                  value: 'Tiếp tục với Google',
                  timeout: 3,
                  then: leafSteps,
                  else: leafSteps
                }
              ]
            }
          ]
        }
      ]
    },
    { type: 'login_if_needed', profile: { package: 'com.facebook.katana' } },
    {
      type: 'assert_app_state',
      profile: { package: 'com.facebook.katana' },
      any_text: ['Trang chủ', 'Tìm kiếm']
    }
  ]
};

export default function DebugScenarioPreviewHarnessPage() {
  const [renderTick, setRenderTick] = useState(0);
  const [tab, setTab] = useState('info');

  useEffect(() => {
    const timer = window.setInterval(() => {
      setRenderTick((value) => value + 1);
    }, 100);
    const tabTimer = window.setTimeout(() => setTab('body'), 150);
    return () => {
      window.clearInterval(timer);
      window.clearTimeout(tabTimer);
    };
  }, []);

  const renderedBody = {
    ...body,
    steps: structuredClone(body.steps)
  };

  return (
    <Sheet open>
      <SheetContent
        data-debug-render-tick={renderTick}
        className='flex w-full flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl'
      >
        <SheetHeader className='shrink-0 border-b px-6 py-4'>
          <SheetTitle>Đăng nhập Facebook</SheetTitle>
        </SheetHeader>
        <Tabs
          value={tab}
          onValueChange={setTab}
          className='flex min-h-0 flex-1 flex-col gap-0'
        >
          <div className='shrink-0 border-b px-6 py-3'>
            <TabsList className='grid h-9 w-full grid-cols-2'>
              <TabsTrigger value='info'>Thông tin</TabsTrigger>
              <TabsTrigger value='body'>Nội dung</TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value='info' className='mt-0 min-h-0 flex-1 px-6 py-4'>
            Thông tin
          </TabsContent>
          <TabsContent
            value='body'
            className='mt-0 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-6 py-4'
          >
            <ScenarioBodyPreview body={renderedBody} kind='sequence' />
          </TabsContent>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}
