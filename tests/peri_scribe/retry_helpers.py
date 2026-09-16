"""Provide data builders and stand-ins for retry tests."""

import enum
import json

import hypothesis.strategies
import requests
import tenacity

import tests.conftest


RETRY_AFTER_HEADER_IN_SECONDS = 7


RATE_LIMIT_ERROR_STRING = json.dumps(tests.conftest.RATE_LIMIT_ERROR_PAYLOAD)


LOOSE_429_ERROR_STRING = json.dumps(tests.conftest.LOOSE_429_ERROR_PAYLOAD)


class AttemptOutcome(enum.Enum):
    """Distinguish outcomes that stop a query from failures that allow another try."""

    SUCCESS = "success"
    CONNECTION_ERROR = "connection_error"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    FATAL_ERROR = "fatal_error"


def query_effects(outcomes: list[AttemptOutcome], result: object) -> list[object]:
    """Make each attempted query observable without performing network requests.

    Args:
        outcomes: The sequence of successful and failed attempts to simulate.
        result: The value returned by a successful attempt.

    Returns:
        Mock side effects, with a successful terminal attempt after the sequence.
    """
    effects: dict[AttemptOutcome, object] = {
        AttemptOutcome.SUCCESS: result,
        AttemptOutcome.CONNECTION_ERROR: requests.exceptions.ConnectionError("Offline"),
        AttemptOutcome.TIMEOUT: requests.exceptions.Timeout("Timed out"),
        AttemptOutcome.RATE_LIMIT: ValueError({
            "error": {"code": 429, "details": ["Retry after 7 sec"]},
        }),
        AttemptOutcome.FATAL_ERROR: ValueError("Invalid query"),
    }
    return [effects[outcome] for outcome in outcomes] + [result]


@hypothesis.strategies.composite
def rate_limit_representations(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[dict[str, object], str]:
    """Vary JSON layout and key order without changing the server's retry instruction.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        An ArcGIS error payload and its equivalent JSON text.
    """
    delays = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.integers(0, 3600),
            max_size=4,
        ),
    )
    fields: list[tuple[str, object]] = [
        ("code", 429),
        ("message", "Too many requests"),
        ("details", ["Server busy", *[f"Retry after {delay} sec" for delay in delays]]),
    ]
    payload: dict[str, object] = {
        "error": dict(draw(hypothesis.strategies.permutations(fields))),
    }
    indent = draw(
        hypothesis.strategies.one_of(
            hypothesis.strategies.none(),
            hypothesis.strategies.integers(0, 4),
        ),
    )
    return payload, json.dumps(payload, indent=indent)


def http_error(
    status_code: int,
    *,
    retry_after: str | None = None,
) -> requests.exceptions.HTTPError:
    """Build an HTTPError whose response has the given status and header.

    Args:
        status_code: The response status code.
        retry_after: The Retry-After header value, if any.

    Returns:
        The HTTPError.
    """
    response = requests.Response()
    response.status_code = status_code
    if retry_after is not None:
        response.headers["Retry-After"] = retry_after
    return requests.exceptions.HTTPError("boom", response=response)


def failed_retry_state(error: Exception) -> tenacity.RetryCallState:
    """Build the retry state of a single failed attempt raising *error*.

    Args:
        error: Exception supplied for the selected failure case.

    Returns:
        A retry state whose latest attempt raised *error*.
    """
    retry_state = tenacity.RetryCallState(
        retry_object=tenacity.Retrying(),
        fn=None,
        args=(),
        kwargs={},
    )
    retry_state.set_exception((type(error), error, error.__traceback__))
    return retry_state


def raise_disconnected_query() -> None:
    """Simulate a disconnected query after retries are exhausted.

    Raises:
        requests.exceptions.ConnectionError: Always, to exercise serializable failure
            logging.
    """
    message = "Disconnected"
    raise requests.exceptions.ConnectionError(message)
