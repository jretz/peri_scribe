"""Replace retry dependencies with controlled test doubles."""

import requests


def raise_disconnected_query() -> None:
    """Simulate a disconnected query that exhausts the retry policy.

    Raises:
        requests.exceptions.ConnectionError: Always, to exercise serializable failure
            logging.
    """
    message = "Disconnected"
    raise requests.exceptions.ConnectionError(message)
