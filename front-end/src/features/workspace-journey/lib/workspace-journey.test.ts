import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildWorkspaceJourney,
  completedWorkspaceJourneySteps
} from './workspace-journey.ts';

test('keeps later seed data behind the first missing prerequisite', () => {
  const steps = buildWorkspaceJourney({
    deviceCount: 0,
    linkedAccountCount: 3,
    runnableScenarioCount: 8,
    readyCampaignCount: 2,
    campaignRunCount: 4,
    activeScheduleCount: 1
  });

  assert.deepEqual(
    steps.map((step) => step.state),
    ['current', 'upcoming', 'upcoming', 'upcoming', 'upcoming']
  );
  assert.equal(completedWorkspaceJourneySteps(steps), 0);
});

test('moves the next action forward as the workspace becomes ready', () => {
  const steps = buildWorkspaceJourney({
    deviceCount: 2,
    linkedAccountCount: 1,
    runnableScenarioCount: 1,
    readyCampaignCount: 1,
    campaignRunCount: 0,
    activeScheduleCount: 0
  });

  assert.deepEqual(
    steps.map((step) => step.state),
    ['complete', 'complete', 'complete', 'complete', 'current']
  );
  assert.equal(completedWorkspaceJourneySteps(steps), 4);
});

test('requires both a campaign run and an active schedule to finish', () => {
  const base = {
    deviceCount: 1,
    linkedAccountCount: 1,
    runnableScenarioCount: 1,
    readyCampaignCount: 1,
    campaignRunCount: 1
  };

  assert.equal(
    buildWorkspaceJourney({ ...base, activeScheduleCount: 0 }).at(-1)?.state,
    'current'
  );
  assert.equal(
    buildWorkspaceJourney({ ...base, activeScheduleCount: 1 }).at(-1)?.state,
    'complete'
  );
});
