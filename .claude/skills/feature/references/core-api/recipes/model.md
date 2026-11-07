# Recipe: add or change a core-api model

Exemplars: `apps/teams/models.py`, `apps/kb/models.py` (querysets and one-row
rules), `apps/core/models.py` (`BaseModel`).

1. **Name.** Check the spec DDL (`requirement.md`, the phase-2 spec) for the table
   and column names; set `db_table` to match. `infra/migrations/sql/` is written
   against those names.
2. **Base.** Inherit `apps.core.models.BaseModel` (UUID primary key, ADR-0011).
3. **Fields.** Choices as a `TextChoices`/`StrEnum` in the app. A new column on an
   existing table needs a default or `null=True` so old rows survive. A JSON
   column read through a Pydantic schema gives each new field a default.
4. **Behaviour.** One-row rules as model methods, which-rows filters as queryset
   methods (`objects = XQuerySet.as_manager()`). Model methods don't touch
   `request`, write to other models, call external systems, or query in a
   `@property` (`where-logic-goes.md` rule 5). Cross-model writes go in a service
   class in `utils/`.
5. **Migration.** `make makemigrations`, read the file, `make migrate`. A CHECK,
   trigger, grant or index the ORM can't express goes in `infra/migrations/sql/`,
   applied by `RunSQL` in `apps/dbextras/migrations/`. A grant to the ai-engine
   role stays `SELECT` (ADR-0004).
6. **Tests.** A DB-level guard (CHECK, trigger) gets a test that the database
   refuses the bad row, not only that the code never writes it.
7. **Admin and types.** If a response schema changed, `make types`.
