"""
Mints or propagates `trace_id` for every request (spec §11.2). A single
trace_id follows a ticket: Next.js → Django → Celery → ai-engine →
tracing backend, and `audit_log.trace_id` is how a business-log row is
connected back to the full LLM trace.
"""

import uuid

_HEADER = "X-Trace-Id"


class TraceIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        trace_id = request.headers.get(_HEADER) or uuid.uuid4().hex
        request.trace_id = trace_id
        response = self.get_response(request)
        response[_HEADER] = trace_id
        return response
