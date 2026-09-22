"""Collect generated XML for semantic assertions without changing the writer."""

import io

import kml_io.geometry


class MemoryKmlWriter(kml_io.geometry.KmlWriter):
    """Give tests an inspectable stream while exercising the production serializer."""

    def __init__(self) -> None:
        """Retain XML fragments for document assertions."""
        self.buffer = io.StringIO()
        super().__init__(self.buffer)

    def text(self) -> str:
        """Expose generated XML for parsing.

        Returns:
            All text written so far.
        """
        return self.buffer.getvalue()
