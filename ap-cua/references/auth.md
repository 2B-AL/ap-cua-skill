# Auth

This AgentPlan CUA skill uses the caller's Volcengine Ark AgentPlan API key as
the bearer credential. The gateway validates that key with Ark acquire, resolves
an AgentPlan-only user principal, allocates the user's cloud desktop, and passes
the same API key to CUA runtime model calls.

## Login

1. A business command (or `auth status`) returns `AUTH_REQUIRED` when there is no
   configured API key. Run its `error.retry_command` (which is `auth login`).
2. `auth login` asks the user to enter their AgentPlan API key through a secure
   prompt, then calls `/v1/auth/me` to validate it.
3. On success it returns `status: "logged_in"` and caches the API key locally.

For non-interactive use, set `AP_CUA_AGENTPLAN_API_KEY`. `AGENTPLAN_API_KEY` and
`ARK_API_KEY` are accepted as compatibility aliases. Never print or log the key.

## Local Cache

- Location: `~/.openclaw/ap-cua-skill/auth.json` (override with
  `AP_CUA_SKILL_AUTH_FILE`).
- Permissions: `0600`; the script attempts to repair unsafe permissions and
  refuses to continue if it cannot.
- `auth.json` holds the API base URL, the API key, last verified user summary,
  and desktop binding flag. It is never printed.

## Auth Errors

| Error | Meaning | Action |
| --- | --- | --- |
| `AUTH_REQUIRED` | no API key, or the API key is invalid | run `error.retry_command` (`auth login`), enter the correct API key, then retry |
| `TOKEN_EXPIRED` | gateway rejected the bearer credential | run `auth login` again |
| `REFRESH_FAILED` | legacy alias for re-login needed | run `auth login` again |
| `FORBIDDEN` | API key is valid but not allowed for this operation | do not retry with the same key |

## Logout

`auth logout` clears the local cache. There is no server-side refresh token to
revoke in this AgentPlan variant.
