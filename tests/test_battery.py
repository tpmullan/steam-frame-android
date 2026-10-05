import pathlib
import tempfile
import unittest

from helpers import load

bat = load("wgapps-battery")


def supply(root, name, **attrs):
    d = pathlib.Path(root, name)
    d.mkdir(parents=True)
    for key, value in attrs.items():
        (d / key).write_text(f"{value}\n")


class ReadHostTests(unittest.TestCase):
    def test_battery_and_usb_charger(self):
        with tempfile.TemporaryDirectory() as root:
            supply(
                root,
                "qcom-battmgr-bat",
                type="Battery",
                capacity=57,
                status="Charging",
                temp=312,
                charge_counter=2100000,
            )
            supply(root, "qcom-battmgr-usb", type="USB", online=1)
            supply(root, "qcom-battmgr-ac", type="Mains", online=0)
            state = bat.read_host(pathlib.Path(root))
        self.assertEqual(state["battery"]["level"], 57)
        self.assertEqual(state["battery"]["status"], "Charging")
        self.assertEqual(state["battery"]["temp"], 312)
        self.assertTrue(state["usb"])
        self.assertFalse(state["ac"])

    def test_usb_pd_type_counts_as_usb(self):
        with tempfile.TemporaryDirectory() as root:
            supply(root, "bat", type="Battery", capacity=80, status="Discharging")
            supply(root, "pd", type="USB_PD", online=1)
            self.assertTrue(bat.read_host(pathlib.Path(root))["usb"])

    def test_no_battery_and_missing_directory(self):
        with tempfile.TemporaryDirectory() as root:
            supply(root, "ac", type="Mains", online=1)
            self.assertIsNone(bat.read_host(pathlib.Path(root))["battery"])
            self.assertIsNone(bat.read_host(pathlib.Path(root, "missing"))["battery"])

    def test_capacity_is_clamped(self):
        with tempfile.TemporaryDirectory() as root:
            supply(root, "bat", type="Battery", capacity=104, status="Full")
            self.assertEqual(bat.read_host(pathlib.Path(root))["battery"]["level"], 100)


class MappingTests(unittest.TestCase):
    def state(self, **battery):
        b = {"level": 42, "status": "Discharging", "temp": None, "counter": None, **battery}
        return {"battery": b, "ac": False, "usb": False, "wireless": False}

    def test_discharging_on_battery(self):
        values = bat.to_android(self.state())
        self.assertEqual(values["level"], 42)
        self.assertEqual(values["status"], 3)
        self.assertEqual((values["ac"], values["usb"], values["wireless"]), (0, 0, 0))
        self.assertNotIn("temp", values)

    def test_status_names(self):
        for name, code in (("Charging", 2), ("Not charging", 4), ("Full", 5), ("Weird", 1)):
            self.assertEqual(bat.to_android(self.state(status=name))["status"], code)

    def test_temperature_and_counter_passed_through(self):
        values = bat.to_android(self.state(temp=305, counter=1500000))
        self.assertEqual((values["temp"], values["counter"]), (305, 1500000))

    def test_no_battery_sets_nothing(self):
        self.assertEqual(
            bat.to_android({"battery": None, "ac": True, "usb": False, "wireless": False}), {}
        )


class CommandTests(unittest.TestCase):
    def test_only_changes_are_pushed(self):
        self.assertEqual(bat.changes({"level": 50, "ac": 0}, {"level": 51, "ac": 0}), {"level": 51})
        self.assertEqual(bat.changes({}, {"level": 51}), {"level": 51})

    def test_level_is_set_last(self):
        line = bat.command({"level": 50, "status": 2, "usb": 1})
        self.assertEqual(
            line, "cmd battery set status 2; cmd battery set usb 1; cmd battery set level 50"
        )


if __name__ == "__main__":
    unittest.main()
