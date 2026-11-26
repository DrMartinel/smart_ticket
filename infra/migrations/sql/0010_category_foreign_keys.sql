-- infra/migrations/sql/0010_category_foreign_keys.sql
--
-- Every column that stores a ticket category references ticket_categories(slug) (ADR-0049).

ALTER TABLE tickets
    ADD CONSTRAINT fk_tickets_category
    FOREIGN KEY (category) REFERENCES ticket_categories (slug) ON DELETE RESTRICT;

ALTER TABLE incidents
    ADD CONSTRAINT fk_incidents_category
    FOREIGN KEY (category) REFERENCES ticket_categories (slug) ON DELETE RESTRICT;

ALTER TABLE kb_articles
    ADD CONSTRAINT fk_kb_articles_category
    FOREIGN KEY (category) REFERENCES ticket_categories (slug) ON DELETE RESTRICT;

ALTER TABLE kb_drafts
    ADD CONSTRAINT fk_kb_drafts_category
    FOREIGN KEY (category) REFERENCES ticket_categories (slug) ON DELETE RESTRICT;

ALTER TABLE sla_policies
    ADD CONSTRAINT fk_sla_policies_category
    FOREIGN KEY (category) REFERENCES ticket_categories (slug) ON DELETE RESTRICT;

ALTER TABLE fewshot_examples
    ADD CONSTRAINT fk_fewshot_examples_category
    FOREIGN KEY (category) REFERENCES ticket_categories (slug) ON DELETE RESTRICT;

ALTER TABLE team_categories
    ADD CONSTRAINT fk_team_categories_category
    FOREIGN KEY (category) REFERENCES ticket_categories (slug) ON DELETE RESTRICT;

ALTER TABLE review_decisions
    ADD CONSTRAINT fk_review_decisions_corrected_category
    FOREIGN KEY (corrected_category) REFERENCES ticket_categories (slug) ON DELETE RESTRICT;

ALTER TABLE team_reassignments
    ADD CONSTRAINT fk_team_reassignments_from_category
    FOREIGN KEY (from_category) REFERENCES ticket_categories (slug) ON DELETE RESTRICT;

ALTER TABLE team_reassignments
    ADD CONSTRAINT fk_team_reassignments_to_category
    FOREIGN KEY (to_category) REFERENCES ticket_categories (slug) ON DELETE RESTRICT;

ALTER TABLE report_ticket_facts
    ADD CONSTRAINT fk_report_ticket_facts_category
    FOREIGN KEY (category) REFERENCES ticket_categories (slug) ON DELETE RESTRICT;
