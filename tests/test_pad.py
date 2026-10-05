import os
import tempfile
import unittest

from helpers import load

pad = load("wgapps-pad")

BTN_SOUTH, BTN_EAST, BTN_NORTH = 0x130, 0x131, 0x133


class TranslateTests(unittest.TestCase):
    def test_face_buttons_map_to_remote_keys(self):
        hat = {}
        self.assertEqual(pad.translate(pad.EV_KEY, BTN_SOUTH, 1, hat), [(pad.KEY_SELECT, 1)])
        self.assertEqual(pad.translate(pad.EV_KEY, BTN_SOUTH, 0, hat), [(pad.KEY_SELECT, 0)])
        self.assertEqual(pad.translate(pad.EV_KEY, BTN_EAST, 1, hat), [(pad.KEY_BACK, 1)])
        self.assertEqual(pad.translate(pad.EV_KEY, BTN_NORTH, 1, hat), [(pad.KEY_PLAYPAUSE, 1)])

    def test_autorepeat_and_unmapped_buttons_are_ignored(self):
        self.assertEqual(pad.translate(pad.EV_KEY, BTN_SOUTH, 2, {}), [])
        self.assertEqual(pad.translate(pad.EV_KEY, 0x134, 1, {}), [])

    def test_dpad_press_release_and_direct_reversal(self):
        hat = {}
        x = pad.ABS_HAT0X
        self.assertEqual(pad.translate(pad.EV_ABS, x, 1, hat), [(pad.KEY_RIGHT, 1)])
        self.assertEqual(pad.translate(pad.EV_ABS, x, 1, hat), [])
        self.assertEqual(
            pad.translate(pad.EV_ABS, x, -1, hat), [(pad.KEY_RIGHT, 0), (pad.KEY_LEFT, 1)]
        )
        self.assertEqual(pad.translate(pad.EV_ABS, x, 0, hat), [(pad.KEY_LEFT, 0)])

    def test_other_axes_are_ignored(self):
        self.assertEqual(pad.translate(pad.EV_ABS, 0x05, 255, {}), [])


class SinkTests(unittest.TestCase):
    def test_writes_key_and_syn_events_to_the_fifo(self):
        with tempfile.TemporaryDirectory() as tmp:
            fifo = os.path.join(tmp, "wl_keyboard_events")
            os.mkfifo(fifo)
            reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
            try:
                pad.Sink(fifo).key(pad.KEY_BACK, 1)
                data = os.read(reader, 4096)
            finally:
                os.close(reader)
        self.assertEqual(len(data), 2 * pad.EVENT.size)
        _, _, t1, c1, v1 = pad.EVENT.unpack_from(data, 0)
        _, _, t2, _, _ = pad.EVENT.unpack_from(data, pad.EVENT.size)
        self.assertEqual((t1, c1, v1, t2), (pad.EV_KEY, pad.KEY_BACK, 1, pad.EV_SYN))

    def test_no_reader_drops_the_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            fifo = os.path.join(tmp, "wl_keyboard_events")
            os.mkfifo(fifo)
            sink = pad.Sink(fifo)
            sink.key(pad.KEY_BACK, 1)
            self.assertIsNone(sink.fd)


if __name__ == "__main__":
    unittest.main()
