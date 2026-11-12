"""Scope the attribute overrides used by fresh crash interpreters."""

import contextlib
import types
import typing


class AttributePatch(typing.Protocol):
    """Share existing module and class overrides with pytest fixtures."""

    def setattr(
        self,
        target: types.ModuleType | type,
        name: str,
        value: object,
    ) -> None:
        """Override an existing attribute for the current test scope."""
        ...


class AttributeOverrides(contextlib.ExitStack):
    """Restore scoped module and class overrides in reverse order."""

    def setattr(
        self,
        target: types.ModuleType | type,
        name: str,
        value: object,
    ) -> None:
        """Keep raw descriptors and inherited attributes intact after cleanup.

        Args:
            target: The module or class exposing an observable production boundary.
            name: The existing attribute to override.
            value: The temporary replacement.
        """
        getattr(target, name)
        attributes = vars(target)
        owned = name in attributes
        original = attributes.get(name)
        setattr(target, name, value)
        if owned:
            self.callback(setattr, target, name, original)
        else:
            self.callback(delattr, target, name)
