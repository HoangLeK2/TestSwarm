export type VariableDisplayCategory =
  | 'runtimeState'
  | 'gate'
  | 'profileResult'
  | 'targetData'
  | 'stepOutput'
  | 'builtIn'
  | 'content'
  | 'crawlConfig'
  | 'account'
  | 'custom';

export type VariableDisplayMetadata = {
  category: VariableDisplayCategory;
  labelKey?: string;
  descriptionKey?: string;
  originKey?: string;
  fallbackLabel: string;
};

const KNOWN_VARIABLES: Record<
  string,
  Omit<VariableDisplayMetadata, 'fallbackLabel'>
> = {
  PLATFORM_SESSION_READY: {
    category: 'runtimeState',
    labelKey: 'variableInfo.labels.platformSessionReady',
    descriptionKey: 'variableInfo.descriptions.platformSessionReady',
    originKey: 'variableInfo.origins.platformSessionReady'
  },
  ENABLE_CONNECTION_REQUEST: {
    category: 'gate',
    labelKey: 'variableInfo.labels.enableConnectionRequest',
    descriptionKey: 'variableInfo.descriptions.enableConnectionRequest',
    originKey: 'variableInfo.origins.enableConnectionRequest'
  },
  PEOPLE_PROFILE_SELECTED: {
    category: 'profileResult',
    labelKey: 'variableInfo.labels.peopleProfileSelected',
    descriptionKey: 'variableInfo.descriptions.peopleProfileSelected',
    originKey: 'variableInfo.origins.peopleProfileSelected'
  },
  AUTHOR_PROFILE_OPENED: {
    category: 'profileResult',
    labelKey: 'variableInfo.labels.authorProfileOpened',
    descriptionKey: 'variableInfo.descriptions.authorProfileOpened',
    originKey: 'variableInfo.origins.authorProfileOpened'
  },
  COMMENTER_PROFILE_OPENED: {
    category: 'profileResult',
    labelKey: 'variableInfo.labels.commenterProfileOpened',
    descriptionKey: 'variableInfo.descriptions.commenterProfileOpened',
    originKey: 'variableInfo.origins.commenterProfileOpened'
  },
  COMMENT_SHEET_OPENED: {
    category: 'runtimeState',
    labelKey: 'variableInfo.labels.commentSheetOpened',
    descriptionKey: 'variableInfo.descriptions.commentSheetOpened',
    originKey: 'variableInfo.origins.commentSheetOpened'
  },
  CANDIDATE_AVAILABLE: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.candidateAvailable',
    descriptionKey: 'variableInfo.descriptions.candidateAvailable',
    originKey: 'variableInfo.origins.candidateLease'
  },
  CANDIDATE_ID: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.candidateId',
    descriptionKey: 'variableInfo.descriptions.candidateId',
    originKey: 'variableInfo.origins.candidateLease'
  },
  CANDIDATE_ENTITY_ID: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.candidateEntityId',
    descriptionKey: 'variableInfo.descriptions.candidateEntityId',
    originKey: 'variableInfo.origins.candidateLease'
  },
  CANDIDATE_EXTERNAL_ID: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.candidateExternalId',
    descriptionKey: 'variableInfo.descriptions.candidateExternalId',
    originKey: 'variableInfo.origins.candidateLease'
  },
  CANDIDATE_NAME: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.candidateName',
    descriptionKey: 'variableInfo.descriptions.candidateName',
    originKey: 'variableInfo.origins.candidateLease'
  },
  CANDIDATE_URL: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.candidateUrl',
    descriptionKey: 'variableInfo.descriptions.candidateUrl',
    originKey: 'variableInfo.origins.candidateLease'
  },
  CANDIDATE_LEASE_TOKEN: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.candidateLeaseToken',
    descriptionKey: 'variableInfo.descriptions.candidateLeaseToken',
    originKey: 'variableInfo.origins.candidateLease'
  },
  TARGET_AVAILABLE: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.targetAvailable',
    descriptionKey: 'variableInfo.descriptions.targetAvailable',
    originKey: 'variableInfo.origins.targetLease'
  },
  TARGET_ACTION_ID: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.targetActionId',
    descriptionKey: 'variableInfo.descriptions.targetActionId',
    originKey: 'variableInfo.origins.targetLease'
  },
  TARGET_ENTITY_ID: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.targetEntityId',
    descriptionKey: 'variableInfo.descriptions.targetEntityId',
    originKey: 'variableInfo.origins.targetAssignment'
  },
  TARGET_EXTERNAL_ID: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.targetExternalId',
    descriptionKey: 'variableInfo.descriptions.targetExternalId',
    originKey: 'variableInfo.origins.targetAssignment'
  },
  TARGET_NAME: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.targetName',
    descriptionKey: 'variableInfo.descriptions.targetName',
    originKey: 'variableInfo.origins.targetAssignment'
  },
  TARGET_URL: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.targetUrl',
    descriptionKey: 'variableInfo.descriptions.targetUrl',
    originKey: 'variableInfo.origins.targetAssignment'
  },
  TARGET_SEARCH_TEXT: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.targetSearchText',
    descriptionKey: 'variableInfo.descriptions.targetSearchText',
    originKey: 'variableInfo.origins.targetLease'
  },
  TARGET_SEARCH_QUERY: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.targetSearchQuery',
    descriptionKey: 'variableInfo.descriptions.targetSearchQuery',
    originKey: 'variableInfo.origins.targetAssignment'
  },
  TARGET_SELECTOR_BY: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.targetSelectorBy',
    descriptionKey: 'variableInfo.descriptions.targetSelectorBy',
    originKey: 'variableInfo.origins.targetAssignment'
  },
  TARGET_SELECTOR_VALUE: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.targetSelectorValue',
    descriptionKey: 'variableInfo.descriptions.targetSelectorValue',
    originKey: 'variableInfo.origins.targetAssignment'
  },
  TARGET_FALLBACK_SELECTOR_BY: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.targetFallbackSelectorBy',
    descriptionKey: 'variableInfo.descriptions.targetFallbackSelectorBy',
    originKey: 'variableInfo.origins.targetAssignment'
  },
  TARGET_FALLBACK_SELECTOR_VALUE: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.targetFallbackSelectorValue',
    descriptionKey: 'variableInfo.descriptions.targetFallbackSelectorValue',
    originKey: 'variableInfo.origins.targetAssignment'
  },
  TARGET_GROUP_NAME: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.targetGroupName',
    descriptionKey: 'variableInfo.descriptions.targetGroupName',
    originKey: 'variableInfo.origins.targetAssignment'
  },
  TARGET_LOCATOR: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.targetLocator',
    descriptionKey: 'variableInfo.descriptions.targetLocator',
    originKey: 'variableInfo.origins.targetAssignment'
  },
  GROUP_COUNT: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.groupCount',
    descriptionKey: 'variableInfo.descriptions.groupCount',
    originKey: 'variableInfo.origins.groupTargets'
  },
  GROUP_SEARCHES: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.groupSearches',
    descriptionKey: 'variableInfo.descriptions.groupSearches',
    originKey: 'variableInfo.origins.groupTargets'
  },
  GROUP_ROW_TEXTS: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.groupRowTexts',
    descriptionKey: 'variableInfo.descriptions.groupRowTexts',
    originKey: 'variableInfo.origins.groupTargets'
  },
  GROUP_SEARCH_CURRENT: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.groupSearchCurrent',
    descriptionKey: 'variableInfo.descriptions.groupSearchCurrent',
    originKey: 'variableInfo.origins.loopFromList'
  },
  GROUP_ROW_TEXT_CURRENT: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.groupRowTextCurrent',
    descriptionKey: 'variableInfo.descriptions.groupRowTextCurrent',
    originKey: 'variableInfo.origins.loopFromList'
  },
  GROUP_SCAN_SECONDS: {
    category: 'crawlConfig',
    labelKey: 'variableInfo.labels.groupScanSeconds',
    descriptionKey: 'variableInfo.descriptions.groupScanSeconds',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  PAGE_COUNT: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.pageCount',
    descriptionKey: 'variableInfo.descriptions.pageCount',
    originKey: 'variableInfo.origins.pageTargets'
  },
  PAGE_TARGETS: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.pageTargets',
    descriptionKey: 'variableInfo.descriptions.pageTargets',
    originKey: 'variableInfo.origins.pageTargets'
  },
  PAGE_ROW_TEXTS: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.pageRowTexts',
    descriptionKey: 'variableInfo.descriptions.pageRowTexts',
    originKey: 'variableInfo.origins.pageTargets'
  },
  PAGE_SEARCH_CURRENT: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.pageSearchCurrent',
    descriptionKey: 'variableInfo.descriptions.pageSearchCurrent',
    originKey: 'variableInfo.origins.loopFromList'
  },
  PAGE_ROW_TEXT_CURRENT: {
    category: 'targetData',
    labelKey: 'variableInfo.labels.pageRowTextCurrent',
    descriptionKey: 'variableInfo.descriptions.pageRowTextCurrent',
    originKey: 'variableInfo.origins.loopFromList'
  },
  COMMENT_TEXT: {
    category: 'content',
    labelKey: 'variableInfo.labels.commentText',
    descriptionKey: 'variableInfo.descriptions.commentText',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  COMMENT_INPUT_LABEL: {
    category: 'content',
    labelKey: 'variableInfo.labels.commentInputLabel',
    descriptionKey: 'variableInfo.descriptions.commentInputLabel',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  COMMENT_SUBMIT_LABEL: {
    category: 'content',
    labelKey: 'variableInfo.labels.commentSubmitLabel',
    descriptionKey: 'variableInfo.descriptions.commentSubmitLabel',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  POST_KEYWORDS: {
    category: 'content',
    labelKey: 'variableInfo.labels.postKeywords',
    descriptionKey: 'variableInfo.descriptions.postKeywords',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  POST_TARGET_COUNT: {
    category: 'crawlConfig',
    labelKey: 'variableInfo.labels.postTargetCount',
    descriptionKey: 'variableInfo.descriptions.postTargetCount',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  POST_RUN_SECONDS: {
    category: 'crawlConfig',
    labelKey: 'variableInfo.labels.postRunSeconds',
    descriptionKey: 'variableInfo.descriptions.postRunSeconds',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  SEARCH_QUERY: {
    category: 'crawlConfig',
    labelKey: 'variableInfo.labels.searchQuery',
    descriptionKey: 'variableInfo.descriptions.searchQuery',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  MAX_PAGES: {
    category: 'crawlConfig',
    labelKey: 'variableInfo.labels.maxPages',
    descriptionKey: 'variableInfo.descriptions.maxPages',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  PAGE_KEYWORDS: {
    category: 'crawlConfig',
    labelKey: 'variableInfo.labels.pageKeywords',
    descriptionKey: 'variableInfo.descriptions.pageKeywords',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  PAGE_KEYWORD_COUNT: {
    category: 'crawlConfig',
    labelKey: 'variableInfo.labels.pageKeywordCount',
    descriptionKey: 'variableInfo.descriptions.pageKeywordCount',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  MAX_ITEMS_PER_KEYWORD: {
    category: 'crawlConfig',
    labelKey: 'variableInfo.labels.maxItemsPerKeyword',
    descriptionKey: 'variableInfo.descriptions.maxItemsPerKeyword',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  PROFILE_REQUIRED_KEYWORDS: {
    category: 'profileResult',
    labelKey: 'variableInfo.labels.profileRequiredKeywords',
    descriptionKey: 'variableInfo.descriptions.profileRequiredKeywords',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  PROFILE_BONUS_KEYWORDS: {
    category: 'profileResult',
    labelKey: 'variableInfo.labels.profileBonusKeywords',
    descriptionKey: 'variableInfo.descriptions.profileBonusKeywords',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  PROFILE_OPTIONAL_KEYWORDS: {
    category: 'profileResult',
    labelKey: 'variableInfo.labels.profileOptionalKeywords',
    descriptionKey: 'variableInfo.descriptions.profileOptionalKeywords',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  PROFILE_BLOCKED_KEYWORDS: {
    category: 'profileResult',
    labelKey: 'variableInfo.labels.profileBlockedKeywords',
    descriptionKey: 'variableInfo.descriptions.profileBlockedKeywords',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  PROFILE_FORBIDDEN_KEYWORDS: {
    category: 'profileResult',
    labelKey: 'variableInfo.labels.profileForbiddenKeywords',
    descriptionKey: 'variableInfo.descriptions.profileForbiddenKeywords',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  PROFILE_MIN_SCORE: {
    category: 'profileResult',
    labelKey: 'variableInfo.labels.profileMinScore',
    descriptionKey: 'variableInfo.descriptions.profileMinScore',
    originKey: 'variableInfo.origins.manualOrCampaign'
  },
  _post_scan: {
    category: 'stepOutput',
    labelKey: 'variableInfo.labels.postScanResult',
    descriptionKey: 'variableInfo.descriptions.postScanResult',
    originKey: 'variableInfo.origins.postScan'
  },
  _group_post_scan: {
    category: 'stepOutput',
    labelKey: 'variableInfo.labels.groupPostScanResult',
    descriptionKey: 'variableInfo.descriptions.groupPostScanResult',
    originKey: 'variableInfo.origins.postScan'
  },
  _people_target: {
    category: 'stepOutput',
    labelKey: 'variableInfo.labels.peopleTarget',
    descriptionKey: 'variableInfo.descriptions.peopleTarget',
    originKey: 'variableInfo.origins.peopleTarget'
  },
  _post_target: {
    category: 'stepOutput',
    labelKey: 'variableInfo.labels.postTarget',
    descriptionKey: 'variableInfo.descriptions.postTarget',
    originKey: 'variableInfo.origins.previousStepSaveAs'
  },
  _visible_connection_action: {
    category: 'stepOutput',
    labelKey: 'variableInfo.labels.visibleConnectionAction',
    descriptionKey: 'variableInfo.descriptions.visibleConnectionAction',
    originKey: 'variableInfo.origins.connectionAction'
  },
  _people_connection_action: {
    category: 'stepOutput',
    labelKey: 'variableInfo.labels.peopleConnectionAction',
    descriptionKey: 'variableInfo.descriptions.peopleConnectionAction',
    originKey: 'variableInfo.origins.connectionAction'
  },
  _group_join_action: {
    category: 'stepOutput',
    labelKey: 'variableInfo.labels.groupJoinAction',
    descriptionKey: 'variableInfo.descriptions.groupJoinAction',
    originKey: 'variableInfo.origins.groupJoinAction'
  }
};

const BUILTIN_VARIABLES: Record<
  string,
  Omit<VariableDisplayMetadata, 'fallbackLabel'>
> = {
  __NOW__: {
    category: 'builtIn',
    labelKey: 'variableInfo.labels.now',
    descriptionKey: 'variableInfo.descriptions.now',
    originKey: 'variableInfo.origins.systemBuiltin'
  },
  __DATE__: {
    category: 'builtIn',
    labelKey: 'variableInfo.labels.date',
    descriptionKey: 'variableInfo.descriptions.date',
    originKey: 'variableInfo.origins.systemBuiltin'
  },
  __TIME__: {
    category: 'builtIn',
    labelKey: 'variableInfo.labels.time',
    descriptionKey: 'variableInfo.descriptions.time',
    originKey: 'variableInfo.origins.systemBuiltin'
  },
  __DEVICE_SERIAL__: {
    category: 'builtIn',
    labelKey: 'variableInfo.labels.deviceSerial',
    descriptionKey: 'variableInfo.descriptions.deviceSerial',
    originKey: 'variableInfo.origins.deviceRuntime'
  },
  __DEVICE_MODEL__: {
    category: 'builtIn',
    labelKey: 'variableInfo.labels.deviceModel',
    descriptionKey: 'variableInfo.descriptions.deviceModel',
    originKey: 'variableInfo.origins.deviceRuntime'
  },
  __RANDOM_INT_1_100__: {
    category: 'builtIn',
    labelKey: 'variableInfo.labels.randomInt',
    descriptionKey: 'variableInfo.descriptions.randomInt',
    originKey: 'variableInfo.origins.systemBuiltin'
  },
  __RANDOM_UUID__: {
    category: 'builtIn',
    labelKey: 'variableInfo.labels.randomUuid',
    descriptionKey: 'variableInfo.descriptions.randomUuid',
    originKey: 'variableInfo.origins.systemBuiltin'
  },
  __STEP_INDEX__: {
    category: 'builtIn',
    labelKey: 'variableInfo.labels.stepIndex',
    descriptionKey: 'variableInfo.descriptions.stepIndex',
    originKey: 'variableInfo.origins.stepRuntime'
  },
  __LOOP_INDEX__: {
    category: 'builtIn',
    labelKey: 'variableInfo.labels.loopIndex',
    descriptionKey: 'variableInfo.descriptions.loopIndex',
    originKey: 'variableInfo.origins.loopRuntime'
  },
  __ACCOUNT_ID__: {
    category: 'account',
    labelKey: 'variableInfo.labels.accountId',
    descriptionKey: 'variableInfo.descriptions.accountId',
    originKey: 'variableInfo.origins.accountBinding'
  },
  __ACCOUNT_USERNAME__: {
    category: 'account',
    labelKey: 'variableInfo.labels.accountUsername',
    descriptionKey: 'variableInfo.descriptions.accountUsername',
    originKey: 'variableInfo.origins.accountBinding'
  },
  __ACCOUNT_PASSWORD__: {
    category: 'account',
    labelKey: 'variableInfo.labels.accountPassword',
    descriptionKey: 'variableInfo.descriptions.accountPassword',
    originKey: 'variableInfo.origins.accountSecret'
  },
  __ACCOUNT_EMAIL__: {
    category: 'account',
    labelKey: 'variableInfo.labels.accountEmail',
    descriptionKey: 'variableInfo.descriptions.accountEmail',
    originKey: 'variableInfo.origins.accountSecret'
  },
  __ACCOUNT_TOTP_CODE__: {
    category: 'account',
    labelKey: 'variableInfo.labels.accountTotpCode',
    descriptionKey: 'variableInfo.descriptions.accountTotpCode',
    originKey: 'variableInfo.origins.accountSecret'
  },
  __ACCOUNT_TOTP_SECRET__: {
    category: 'account',
    labelKey: 'variableInfo.labels.accountTotpSecret',
    descriptionKey: 'variableInfo.descriptions.accountTotpSecret',
    originKey: 'variableInfo.origins.accountSecret'
  },
  __ACCOUNT_DISPLAY_NAME__: {
    category: 'account',
    labelKey: 'variableInfo.labels.accountDisplayName',
    descriptionKey: 'variableInfo.descriptions.accountDisplayName',
    originKey: 'variableInfo.origins.accountBinding'
  },
  __ACCOUNT_PLATFORM__: {
    category: 'account',
    labelKey: 'variableInfo.labels.accountPlatform',
    descriptionKey: 'variableInfo.descriptions.accountPlatform',
    originKey: 'variableInfo.origins.accountBinding'
  }
};

export function humanizeVariableName(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export function getVariableDisplayMetadata(
  name: string
): VariableDisplayMetadata {
  const normalized = name.trim();
  const known = KNOWN_VARIABLES[normalized] ?? BUILTIN_VARIABLES[normalized];
  if (known) {
    return {
      ...known,
      fallbackLabel: humanizeVariableName(normalized.replace(/^__|__$/g, ''))
    };
  }
  if (normalized.startsWith('__ACCOUNT_')) {
    return {
      category: 'account',
      descriptionKey: 'variableInfo.descriptions.genericAccount',
      originKey: 'variableInfo.origins.accountBinding',
      fallbackLabel: humanizeVariableName(normalized.replace(/^__|__$/g, ''))
    };
  }
  if (normalized.startsWith('__') && normalized.endsWith('__')) {
    return {
      category: 'builtIn',
      descriptionKey: 'variableInfo.descriptions.genericBuiltin',
      originKey: 'variableInfo.origins.systemBuiltin',
      fallbackLabel: humanizeVariableName(normalized.replace(/^__|__$/g, ''))
    };
  }
  if (normalized.startsWith('_')) {
    return {
      category: 'stepOutput',
      descriptionKey: 'variableInfo.descriptions.genericStepOutput',
      originKey: 'variableInfo.origins.previousStepSaveAs',
      fallbackLabel: humanizeVariableName(normalized)
    };
  }
  if (normalized.startsWith('ENABLE_')) {
    return {
      category: 'gate',
      descriptionKey: 'variableInfo.descriptions.genericGate',
      originKey: 'variableInfo.origins.manualOrCampaign',
      fallbackLabel: humanizeVariableName(normalized)
    };
  }
  if (
    normalized.endsWith('_READY') ||
    normalized.endsWith('_OPENED') ||
    normalized.endsWith('_SHEET_OPENED')
  ) {
    return {
      category: 'runtimeState',
      descriptionKey: 'variableInfo.descriptions.genericRuntimeState',
      originKey: 'variableInfo.origins.previousStepRuntime',
      fallbackLabel: humanizeVariableName(normalized)
    };
  }
  if (normalized.endsWith('_SELECTED')) {
    return {
      category: 'profileResult',
      descriptionKey: 'variableInfo.descriptions.genericProfileResult',
      originKey: 'variableInfo.origins.previousStepRuntime',
      fallbackLabel: humanizeVariableName(normalized)
    };
  }
  if (normalized.startsWith('CANDIDATE_')) {
    return {
      category: 'targetData',
      descriptionKey: 'variableInfo.descriptions.genericTargetData',
      originKey: 'variableInfo.origins.candidateLease',
      fallbackLabel: humanizeVariableName(normalized)
    };
  }
  if (/^PROFILE_\d+_(SEARCH|ROW_TEXT)$/.test(normalized)) {
    return {
      category: 'targetData',
      descriptionKey: 'variableInfo.descriptions.genericProfileTarget',
      originKey: 'variableInfo.origins.manualOrCampaign',
      fallbackLabel: humanizeVariableName(normalized)
    };
  }
  if (normalized.startsWith('PROFILE_')) {
    return {
      category: 'profileResult',
      descriptionKey: 'variableInfo.descriptions.genericProfileConfig',
      originKey: 'variableInfo.origins.manualOrCampaign',
      fallbackLabel: humanizeVariableName(normalized)
    };
  }
  if (normalized.endsWith('_INDEX')) {
    return {
      category: 'runtimeState',
      descriptionKey: 'variableInfo.descriptions.genericLoopIndex',
      originKey: 'variableInfo.origins.loopRuntime',
      fallbackLabel: humanizeVariableName(normalized)
    };
  }
  if (
    normalized.startsWith('GROUP_') ||
    normalized.startsWith('PAGE_') ||
    normalized.startsWith('TARGET_')
  ) {
    return {
      category: 'targetData',
      descriptionKey: normalized.startsWith('TARGET_')
        ? 'variableInfo.descriptions.genericTargetData'
        : normalized.startsWith('GROUP_')
          ? 'variableInfo.descriptions.genericGroupData'
          : 'variableInfo.descriptions.genericPageData',
      originKey: normalized.startsWith('TARGET_')
        ? 'variableInfo.origins.targetAssignment'
        : normalized.startsWith('GROUP_')
          ? 'variableInfo.origins.groupTargets'
          : 'variableInfo.origins.pageTargets',
      fallbackLabel: humanizeVariableName(normalized)
    };
  }
  if (
    normalized.startsWith('POST_') ||
    normalized.startsWith('PEOPLE_') ||
    normalized.startsWith('FANPAGE_')
  ) {
    return {
      category: 'targetData',
      descriptionKey: 'variableInfo.descriptions.genericSearchTarget',
      originKey: 'variableInfo.origins.manualOrCampaign',
      fallbackLabel: humanizeVariableName(normalized)
    };
  }
  if (
    normalized.includes('KEYWORD') ||
    normalized.endsWith('_TEXT') ||
    normalized.endsWith('_MESSAGE')
  ) {
    return {
      category: 'content',
      descriptionKey: 'variableInfo.descriptions.genericContent',
      originKey: 'variableInfo.origins.manualOrCampaign',
      fallbackLabel: humanizeVariableName(normalized)
    };
  }
  if (
    normalized.includes('MAX_') ||
    normalized.endsWith('_SECONDS') ||
    normalized.endsWith('_LIMIT') ||
    normalized.endsWith('_COUNT')
  ) {
    return {
      category: 'crawlConfig',
      descriptionKey: 'variableInfo.descriptions.genericRunConfig',
      originKey: 'variableInfo.origins.manualOrCampaign',
      fallbackLabel: humanizeVariableName(normalized)
    };
  }
  if (normalized.startsWith('ACCOUNT_')) {
    return {
      category: 'account',
      descriptionKey: 'variableInfo.descriptions.genericAccount',
      originKey: 'variableInfo.origins.accountBinding',
      fallbackLabel: humanizeVariableName(normalized.replace(/^__|__$/g, ''))
    };
  }
  return {
    category: 'custom',
    descriptionKey: 'variableInfo.descriptions.genericCustom',
    originKey: 'variableInfo.origins.custom',
    fallbackLabel: humanizeVariableName(normalized)
  };
}
