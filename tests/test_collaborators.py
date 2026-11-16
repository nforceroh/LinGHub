"""The collaborators must actually satisfy their Protocols.

`collaborators.py` declares what the D-Bus adapter needs; `writes.py` provides
it. Nothing tied the two together, so a method could be renamed on one side and
only fail at runtime, on a user's machine, the first time the UI asked for it.

`runtime_checkable` is not enough on its own: it compares method *names*, so
dropping a parameter or changing its type would still pass. These tests compare
signatures through `inspect`, which is the same shape a caller sees.
"""

import inspect
import unittest
from typing import Protocol

from linghub.daemon import collaborators, writes


def _signature(fn) -> inspect.Signature:
    """The signature without `self`: that is what a caller supplies."""
    return inspect.Signature(
        [
            parameter
            for name, parameter in inspect.signature(fn).parameters.items()
            if name != "self"
        ]
    )


def _protocol_methods(proto: type[Protocol]) -> dict[str, inspect.Signature]:
    return {
        name: _signature(member)
        for name, member in vars(proto).items()
        if not name.startswith("_") and callable(member)
    }


def _implementation_methods(cls: type) -> dict[str, inspect.Signature]:
    return {
        name: _signature(member)
        for name, member in vars(cls).items()
        if not name.startswith("_") and callable(member)
    }


PAIRS = (
    (collaborators.ProfileLifecycle, writes.ProfileLifecycle),
    (collaborators.Bindings, writes.Bindings),
    (collaborators.DeviceSettings, writes.DeviceSettings),
)


class ConformanceTests(unittest.TestCase):
    def test_every_protocol_method_is_implemented(self):
        for proto, impl in PAIRS:
            for name in _protocol_methods(proto):
                with self.subTest(protocol=proto.__name__, method=name):
                    self.assertIn(
                        name, _implementation_methods(impl),
                        f"{impl.__name__} does not implement {name}",
                    )

    def test_the_implementations_add_nothing_to_their_protocol(self):
        """An extra public method is a member the adapter cannot reach.

        It would also mean the Protocol understates the collaborator, so a test
        fake written from the Protocol would not match the real thing.
        """
        for proto, impl in PAIRS:
            with self.subTest(protocol=proto.__name__):
                extra = sorted(
                    set(_implementation_methods(impl)) - set(_protocol_methods(proto))
                )
                self.assertEqual(extra, [], f"{impl.__name__} has unstated members")

    def test_signatures_match(self):
        """A drifted parameter list is the failure a name check misses."""
        for proto, impl in PAIRS:
            for name, wanted in _protocol_methods(proto).items():
                with self.subTest(protocol=proto.__name__, method=name):
                    actual = _implementation_methods(impl)[name]
                    self.assertEqual(
                        list(actual.parameters), list(wanted.parameters),
                        f"{impl.__name__}.{name} takes different arguments",
                    )

    def test_return_annotations_match(self):
        for proto, impl in PAIRS:
            for name, wanted in _protocol_methods(proto).items():
                with self.subTest(protocol=proto.__name__, method=name):
                    actual = _implementation_methods(impl)[name]
                    self.assertEqual(
                        actual.return_annotation, wanted.return_annotation,
                        f"{impl.__name__}.{name} returns a different type",
                    )


if __name__ == "__main__":
    unittest.main()