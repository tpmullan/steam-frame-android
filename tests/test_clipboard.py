import unittest

from helpers import load

clip = load("wgapps-clipboard")


class FakeHost:
    def __init__(self, text=None, error=None):
        self.text = text
        self.error = error
        self.set_calls = []

    def get(self):
        if self.error:
            raise self.error
        return self.text

    def set(self, text):
        self.set_calls.append(text)
        self.text = text


class BridgeTests(unittest.TestCase):
    def test_android_copy_sets_host_clipboard(self):
        host = FakeHost()
        clip.ClipboardBridge(host).android_copied("hello")
        self.assertEqual(host.set_calls, ["hello"])

    def test_empty_android_copy_is_ignored(self):
        host = FakeHost()
        bridge = clip.ClipboardBridge(host)
        bridge.android_copied("")
        bridge.android_copied(None)
        self.assertEqual(host.set_calls, [])

    def test_oversized_android_copy_is_not_shared(self):
        host = FakeHost()
        clip.ClipboardBridge(host, max_bytes=4).android_copied("hello")
        self.assertEqual(host.set_calls, [])

    def test_android_paste_reads_host(self):
        self.assertEqual(
            clip.ClipboardBridge(FakeHost("from steam")).android_pastes(), "from steam"
        )

    def test_unicode_size_is_measured_in_bytes(self):
        bridge = clip.ClipboardBridge(FakeHost("ééé"), max_bytes=5)
        self.assertEqual(bridge.android_pastes(), "")

    def test_empty_or_failing_host_gives_empty_string(self):
        self.assertEqual(clip.ClipboardBridge(FakeHost(None)).android_pastes(), "")
        failing = FakeHost(error=OSError("no display"))
        self.assertEqual(clip.ClipboardBridge(failing).android_pastes(), "")


class StructLayoutTests(unittest.TestCase):
    def test_xevent_is_the_size_of_xlibs_union(self):
        # XEvent is a union padded to 24 longs.
        self.assertEqual(
            clip.ctypes.sizeof(clip.XEvent), 24 * clip.ctypes.sizeof(clip.ctypes.c_long)
        )

    def test_gbinder_reader_and_writer_sizes_match_the_headers(self):
        ptr = clip.ctypes.sizeof(clip.ctypes.c_void_p)
        self.assertEqual(clip.ctypes.sizeof(clip.GBinderReader), 6 * ptr)
        self.assertEqual(clip.ctypes.sizeof(clip.GBinderWriter), 4 * ptr)


if __name__ == "__main__":
    unittest.main()


class DisplayDiscoveryTests(unittest.TestCase):
    def test_displays_come_from_x11_sockets(self):
        import pathlib
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            for name in ("X0", "X1", "X10", "Xfoo", "other"):
                pathlib.Path(d, name).touch()
            self.assertEqual(clip.gamescope_displays(pathlib.Path(d)), [":0", ":1", ":10"])
            self.assertEqual(clip.gamescope_displays(pathlib.Path(d, "missing")), [])


class FakeOwner:
    def __init__(self, display):
        self.display = display
        self.taken = 0

    def take_ownership(self):
        self.taken += 1


class HubTests(unittest.TestCase):
    def hub(self, displays):
        hub = clip.ClipboardHub.__new__(clip.ClipboardHub)  # no X libraries needed
        hub._lock = clip.threading.Lock()
        hub._text, hub._source = None, None
        hub._owners = {d: FakeOwner(d) for d in displays}
        return hub

    def test_android_copy_is_owned_on_every_display(self):
        hub = self.hub([":0", ":1"])
        hub.set("from android")
        self.assertEqual(hub.get(), "from android")
        self.assertEqual([o.taken for o in hub._owners.values()], [1, 1])

    def test_copy_on_one_display_is_owned_on_the_others(self):
        hub = self.hub([":0", ":1", ":2"])
        hub.copied_on(":1", b"from steam")
        self.assertEqual(hub.get(), "from steam")
        self.assertEqual({d: o.taken for d, o in hub._owners.items()}, {":0": 1, ":1": 0, ":2": 1})

    def test_oversized_display_copy_is_ignored(self):
        hub = self.hub([":0"])
        hub.set("keep")
        hub.copied_on(":0", b"x" * (clip.MAX_BYTES + 1))
        self.assertEqual(hub.get(), "keep")


class LshalTests(unittest.TestCase):
    OUT = (
        "android.hardware.graphics.composer@2.1::IComposer/default                 75\n"
        "vendor.waydroid.clipboard@1.0::IWaydroidClipboard/default                 N/A\n"
    )

    def test_our_server_shows_no_pid(self):
        self.assertEqual(clip.parse_server(self.OUT), clip.OURS)

    def test_hwcomposer_holding_it(self):
        out = self.OUT.replace(
            "IWaydroidClipboard/default                 N/A",
            "IWaydroidClipboard/default                 75",
        )
        self.assertEqual(clip.parse_server(out), "75")

    def test_not_registered_or_no_output(self):
        self.assertIsNone(clip.parse_server(self.OUT.splitlines()[0]))
        self.assertIsNone(clip.parse_server(None))
