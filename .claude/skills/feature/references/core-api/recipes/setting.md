# Recipe: add a tunable or a setting

First decide which it is:

| It is… | Example | Goes in |
|---|---|---|
| A number that shapes a decision (a threshold, a weight, a cap, a TTL a rule reads) | `clarification.wait_minutes` | `config/thresholds.yaml` |
| Operational wiring (a URL, a model name, a timeout, a connect budget, top-k) | `MODEL_TIMEOUT_SEC` | the root `.env.example` |

Never a constant, never a default argument, never a default in settings code or
`docker-compose.yml` (hard rule 2).

## A tunable

1. Add the key under its section in `services/core-api/config/thresholds.yaml`,
   with a comment saying what it does; mark a placeholder value 🔧.
2. Add the field to the matching Pydantic model in `config/settings/base.py`
   (`Thresholds` and its parts). A malformed file stops boot, on purpose.
3. Bump the file's `version` (ADR-0044).
4. Pass the value in as a parameter (`THRESHOLDS.x`) from the service; `router.py`
   receives it through `Router(th)`.

## A setting

1. The settings code: the variable and its type only, read from the environment,
   no default (an empty value counts as unset).
2. The root `.env.example`: the line, its shipped value, and a comment saying why.
3. `docker-compose.yml`: the service's `environment:` allowlist.
4. Run `make test ARGS="-k settings_env"`: `apps/core/tests/test_settings_env.py`
   fails if the three disagree.
5. Tell the user to copy the new line into their own `.env`.

ai-engine settings follow the same three places; its `Settings` class is
described in `../ai-engine/conventions.md` → *Config*.
