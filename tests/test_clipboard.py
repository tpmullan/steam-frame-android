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
