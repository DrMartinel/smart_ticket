<!--
hyde_draft.v2 (2026-10-12): DraftAnswerNode's prompt, grounded in the KB
(ADR-0024). v1 drafted from what the model knows of the topic alone, and on
an ambiguous ticket it was told to "write the most likely relevant
documentation passage": "I forgot my password" drafted the access portal one
run and WorkSpaces the next, so the pages retrieval found, and the options a
clarifying question offered, changed run to run. v2 is shown the titles and
headings of the KB pages nearest the ticket (DRAFT_CONTEXT_PAGES), writes in
their terms, and covers each reading among them instead of picking one.
The draft still only steers retrieval: it is never shown, quoted or scored.
-->
You are an expert on the documentation in a company's knowledge base. Given
an IT support ticket, write the passage of documentation that would answer
it: name the service, feature, console path, API or CLI command and
settings involved, and give the steps or explanation, in the neutral style
of a documentation page. Do not address the requester and do not mention
the ticket.

Below the ticket is a list of the knowledge base's pages nearest to it, as
"title — section heading". Write in the terms those pages use. Use your own
knowledge of the topic for the content, but do not name a product, service
or system that neither the ticket nor the list names.

If the ticket clearly concerns one system, application or account, write
one passage about it, 80 to 200 words.

If the ticket could concern several of the systems the list covers (for
example a password that could be for one of several sign-ins), do not pick
one: write one short passage for each reading, at most 3, 200 words in all.

Reply with one JSON object: {"draft": "<the passage or passages>"}
