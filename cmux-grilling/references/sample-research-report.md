## Q1
### Result
ANSWERED

### Answer
The Nuxt frontend talks to TYPO3 through `nuxtjs/services/ApiService.js`, which wraps the
HTTP client with the `API_URL` base URL from the environment; content elements receive their
JSON via the nuxt-typo3 module.

### Sources
- nuxtjs/services/ApiService.js
- nuxtjs/.env.example

### Method
- `grep -r "API_URL" nuxtjs/services nuxtjs/.env.example`: located the HTTP layer and its config
- Read `nuxtjs/services/ApiService.js`: confirmed the wrapper role

### Blockers
- None

### Plan Drift
- None

### Notes
- Shipped clean-report fixture for the smoke test; content is illustrative.
