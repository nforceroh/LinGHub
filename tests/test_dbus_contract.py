"""The contract module must agree with the daemon's real interface.

The daemon's signatures live in `@method` annotations, which dbus-fast
introspects; they cannot read from a table. So the contract declares the truth
and this test compares it against introspection. Drift fails here rather than
at runtime on a user's machine.
"""

import unittest

from linghub import dbus_contract
from linghub.daemon.dbus_service import ManagerInterface


class _Stub:
    """Answers every collaborator call with a harmless value."""

    def __getattr__(self, _name):
        return lambda *args, **kwargs: True


def make_interface():
    return ManagerInterface(
        profiles=_Stub(),
        bindings=_Stub(),
        settings=_Stub(),
        get_view=lambda profile: None,
    )


class ContractMatchesDaemonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.introspected = {
            m.name: m for m in make_interface().introspect().methods
        }

    def test_every_contract_member_exists_on_the_daemon(self):
        missing = sorted(
            name for name in dbus_contract.BY_NAME
            if name not in self.introspected
        )
        self.assertEqual(missing, [], f"declared but not implemented: {missing}")

    def test_every_daemon_method_is_in_the_contract(self):
        """A new method must be added to the contract, or the client cannot call it."""
        undeclared = sorted(
            name for name in self.introspected
            if name not in dbus_contract.BY_NAME
        )
        self.assertEqual(undeclared, [], f"implemented but not declared: {undeclared}")

    def test_input_signatures_match(self):
        for name, member in dbus_contract.BY_NAME.items():
            with self.subTest(member=name):
                actual = "".join(a.signature for a in self.introspected[name].in_args)
                self.assertEqual(member.input, actual)

    def test_output_signatures_match(self):
        for name, member in dbus_contract.BY_NAME.items():
            with self.subTest(member=name):
                actual = "".join(a.signature for a in self.introspected[name].out_args)
                self.assertEqual(member.output, actual)


class VersionPropertyTests(unittest.TestCase):
    """The daemon's version is a property, not part of GetView (ADR-0009).

    A client reads it separately, so a daemon too old to have it answers
    "no such property" instead of breaking every other read.
    """

    def test_the_contract_property_exists_on_the_daemon_with_its_signature(self):
        properties = {p.name: p for p in make_interface().introspect().properties}
        self.assertIn(dbus_contract.VERSION.name, properties)
        self.assertEqual(
            properties[dbus_contract.VERSION.name].signature,
            dbus_contract.VERSION.signature,
        )

    def test_the_property_reports_the_version_it_was_given(self):
        interface = ManagerInterface(
            profiles=_Stub(), bindings=_Stub(), settings=_Stub(),
            get_view=lambda profile: None, app_version="0.1.0+3.g5c27eef",
        )
        self.assertEqual(interface.Version, "0.1.0+3.g5c27eef")

    def test_by_default_the_property_reports_this_process_version(self):
        from linghub import version

        self.assertEqual(make_interface().Version, version.current())


class CallBodyTests(unittest.TestCase):
    def test_accepts_the_declared_arity(self):
        self.assertEqual(
            dbus_contract.SET_RESOLUTION.call_body("p", 0, 800, False, False),
            ["p", 0, 800, False, False],
        )

    def test_rejects_too_few_arguments(self):
        with self.assertRaisesRegex(TypeError, "takes 5"):
            dbus_contract.SET_RESOLUTION.call_body("p", 0)

    def test_rejects_too_many_arguments(self):
        with self.assertRaisesRegex(TypeError, "takes 5"):
            dbus_contract.SET_RESOLUTION.call_body("p", 0, 800, False, False, "extra")

    def test_a_no_argument_member_takes_nothing(self):
        self.assertEqual(dbus_contract.RELOAD.call_body(), [])


if __name__ == "__main__":
    unittest.main()
