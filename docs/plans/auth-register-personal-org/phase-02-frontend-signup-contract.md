# Phase 2: Frontend Signup Contract

## Context Links

- `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/app/[locale]/auth/sign-up/page.tsx`
- `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/features/auth/services/api.ts`
- `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/features/auth/hooks/use-register.ts`
- `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/features/organization/providers/organization-provider.tsx`
- `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/features/organization/services/farm-org-api.ts`

## Overview

Priority: P2  
Status: Completed  
Effort: 1h

Keep signup UI unchanged for phase 1 unless product wants a user-entered organization name. Backend auto-provisioning means frontend does not need to make a second API call.

## Key Insights

- Sign-up currently posts `name`, `email`, `password`.
- After success, it redirects to sign-in.
- The organization provider fetches organizations only after auth token exists.
- A frontend second call to `/organizations` would require login/token and is not atomic.

## Requirements

- Do not call `/organizations` from unauthenticated sign-up.
- Do not auto-login as part of this plan unless separately requested.
- Keep existing redirect to sign-in.
- If adding `organizationName`, make it a backend-accepted optional field and keep old clients compatible.

## Architecture

Recommended default:

```text
SignUpPage -> authApi.register({ name, email, password })
           -> backend creates user + default org
           -> redirect sign-in
           -> user logs in
           -> OrganizationProvider loads org list
           -> currentOrg = first org
```

Optional product variant:

```typescript
type RegisterPayload = {
  email: string;
  name: string;
  password: string;
  role?: string;
  organizationName?: string;
};
```

Only use the optional variant if the user explicitly wants business name at signup.

## Related Code Files

Default plan modify:

- None required in frontend.

Optional modify:

- `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/app/[locale]/auth/sign-up/page.tsx`
- `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/features/auth/services/api.ts`
- `/Users/hoanglcpila.vn/deviceFarmer/front-end/messages/en.json`
- `/Users/hoanglcpila.vn/deviceFarmer/front-end/messages/vi.json`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/schemas/auth.py`

## Implementation Steps

1. Default path: no frontend changes.
2. Verify after login that `OrganizationProvider` receives one organization.
3. If product asks for org name:
   - add field to signup form.
   - add validation min length.
   - add payload type.
   - backend uses `organizationName` over generated default.
   - preserve fallback generation if omitted.

## Todo List

- [x] Confirm product choice: generated personal org vs required business name.
- [x] If generated org is accepted, leave sign-up UI unchanged.
- [x] Leave org-name signup field unimplemented because generated personal org path was selected.

## Success Criteria

- Existing signup form still works.
- New user sees an organization after login.
- No unauthenticated organization creation call exists in frontend.

## Risk Assessment

- Risk: users expect to name their company during signup.
  Mitigation: optional `organizationName` can be added without changing backend transaction model.
- Risk: org provider silently swallows fetch errors.
  Mitigation: runtime verification should inspect network response and DB state.

## Security Considerations

- Do not store org choice in localStorage as authority.
- Do not let frontend decide membership role.

## Next Steps

Run backend and frontend validation in phase 3.
