"""Concurrent retries and worker phases on one ticket, in real transactions, end in refusals."""

from __future__ import annotations

import threading

import pytest
from django.db import OperationalError, connection

from apps.lifecycle.request_schema import TransitionPatch
from apps.lifecycle.tests.conftest import actions, put_in
from apps.lifecycle.utils.config import workflow_config
from apps.lifecycle.utils.engine import lifecycle
from apps.lifecycle.utils.errors import LifecycleError
from apps.lifecycle.utils.vocabulary import Phase, Trigger


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_parallel_retries_and_worker_phases_end_in_refusals_not_errors(
    ticket, strict, celery, webhooks, technician_user
):
    workflow_config.update_transition(
        strict.working.outgoing.get(to_status=strict.done),
        TransitionPatch(
            actions=actions(
                {
                    "action": "call_webhook",
                    "params": {"url": "http://localhost/x"},
                    "position": "before",
                }
            )
        ),
    )
    webhooks.status = 400
    put_in(ticket, strict.working)
    transfer = lifecycle.request_move(ticket.id, strict.done.id, actor=None, trigger=Trigger.MANUAL)
    assert transfer is not None
    celery.drain()

    errors: list[BaseException] = []
    start = threading.Barrier(8)

    def retry() -> None:
        try:
            start.wait()
            lifecycle.retry(ticket.id, technician_user)
        except LifecycleError:
            pass
        except BaseException as e:  # noqa: BLE001 — collected for the assertion
            errors.append(e)
        finally:
            connection.close()

    def work() -> None:
        try:
            start.wait()
            lifecycle.run_phase(transfer.id, Phase.BEFORE)
        except BaseException as e:  # noqa: BLE001 — collected for the assertion
            errors.append(e)
        finally:
            connection.close()

    threads = [threading.Thread(target=retry) for _ in range(4)]
    threads += [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not [e for e in errors if isinstance(e, OperationalError)], errors
    assert errors == []
    assert ticket.transfers.open().count() <= 1
