import type { QueryClient } from '@tanstack/react-query';
import type { CampaignPage } from '../services/api';
import type { CampaignOut } from '../types';

const LIST_KEY = ['campaigns'] as const;
const pageQueryPrefix = ['campaigns', 'page'] as const;

function detailKey(id: string) {
  return ['campaigns', id] as const;
}

function campaignMatchesSearch(row: CampaignOut, normalizedSearch: string) {
  if (!normalizedSearch) return true;
  const haystack =
    `${row.name ?? ''} ${row.description ?? ''}`.toLocaleLowerCase();
  return haystack.includes(normalizedSearch);
}

function isCampaignPageQueryKey(
  queryKey: readonly unknown[]
): queryKey is readonly ['campaigns', 'page', string, number, number] {
  return (
    queryKey[0] === 'campaigns' &&
    queryKey[1] === 'page' &&
    typeof queryKey[2] === 'string' &&
    typeof queryKey[3] === 'number' &&
    typeof queryKey[4] === 'number'
  );
}

export function syncCreatedCampaignCaches(qc: QueryClient, row: CampaignOut) {
  qc.setQueryData(detailKey(row.id), row);
  qc.setQueryData<CampaignOut[]>(LIST_KEY, (prev) => {
    const list = prev ?? [];
    if (list.some((campaign) => campaign.id === row.id)) {
      return list.map((campaign) => (campaign.id === row.id ? row : campaign));
    }
    return [row, ...list];
  });

  for (const query of qc
    .getQueryCache()
    .findAll({ queryKey: pageQueryPrefix })) {
    const queryKey = query.queryKey;
    if (!isCampaignPageQueryKey(queryKey)) continue;
    const [, , normalizedSearch, page, pageSize] = queryKey;
    const shouldInclude = campaignMatchesSearch(row, normalizedSearch);
    qc.setQueryData<CampaignPage>(queryKey, (old) => {
      if (!old) return old;
      if (old.items.some((campaign) => campaign.id === row.id)) {
        return {
          ...old,
          items: old.items.map((campaign) =>
            campaign.id === row.id ? row : campaign
          )
        };
      }
      if (!shouldInclude) return old;
      if (page !== 1) return { ...old, total: old.total + 1 };
      return {
        ...old,
        total: old.total + 1,
        items: [row, ...old.items].slice(0, pageSize)
      };
    });
  }

  void qc.invalidateQueries({ queryKey: LIST_KEY, exact: true });
  void qc.invalidateQueries({ queryKey: pageQueryPrefix });
}
