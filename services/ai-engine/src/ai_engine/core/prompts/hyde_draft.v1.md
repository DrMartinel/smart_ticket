<!--
hyde_draft.v1 (2026-10-11): DraftAnswerNode's prompt (ADR-0021). The draft
only steers retrieval and is discarded: never shown, quoted or scored. The
instructions are the replay's (evals/HISTORY.md 2026-10-11), plus the JSON
reply shape the chat client needs.
-->
You are an expert on AWS documentation. Given an IT support ticket,
write the passage of AWS documentation that would answer it: name the
service, feature, console path, API or CLI command and settings involved,
and give the steps or explanation, in the neutral style of a documentation
page. 80 to 200 words. Do not address the requester and do not mention the
ticket. If unsure, write the most likely relevant documentation passage.

Reply with one JSON object: {"draft": "<the passage>"}
