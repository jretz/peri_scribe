"""HTTP request settings shared by every source fetcher.

They live in their own module because both the low-level feed metadata reader and the
download machinery need them, and the download machinery reaches the feed reader through
its imports.
"""

from __future__ import annotations


# How long a request may wait for a response before it is abandoned. Archive downloads
# transfer many megabytes, so this is generous enough to cover them as well.
REQUEST_TIMEOUT_SECONDS = 60


# The number of response bytes read at a time while streaming a download.
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
