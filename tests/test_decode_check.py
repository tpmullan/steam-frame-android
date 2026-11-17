import importlib.util
import pathlib
import sys
import unittest

PATH = pathlib.Path(__file__).resolve().parent.parent / "tools/decode-check.py"
spec = importlib.util.spec_from_file_location("decode_check", PATH)
dc = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = dc  # dataclasses (Python 3.12) look the module up by name
spec.loader.exec_module(dc)

DUMP = """
Decoder infos by media types:
=============================

Media type 'video/x-vnd.on2.vp9':
  Decoder "c2.android.vp9.decoder" supports
    attributes: 0x4: [
      encoder: 0,
      vendor: 0,
      software-only: 1,
      hw-accelerated: 0 ]
    details: AMessage(what = 0x00000000) = {
        string size-range = "2x2-2048x2048"
      }
  Decoder "c2.v4l2.vp9.decoder" supports
    attributes: 0x0: [
      encoder: 0,
      vendor: 1,
      software-only: 0,
      hw-accelerated: 1 ]
    details: AMessage(what = 0x00000000) = {
        string size-range = "64x64-8192x8192"
      }

Media type 'video/avc':
  Decoder "c2.android.avc.decoder" supports
    attributes: 0x4: [
      software-only: 1,
      hw-accelerated: 0 ]
    details: AMessage(what = 0x00000000) = {
        string size-range = "2x2-4080x4080"
      }

Encoder infos by media types:
=============================

Media type 'video/x-vnd.on2.vp9':
  Encoder "c2.android.vp9.encoder" supports
    attributes: 0x5: [
      software-only: 1,
      hw-accelerated: 0 ]
    details: AMessage(what = 0x00000000) = {
        string size-range = "2x2-2048x2048"
      }
"""


class DecodeCheckTests(unittest.TestCase):
    def test_parse_reads_decoders_and_ignores_encoders(self):
        decoders = dc.parse_decoders(DUMP)
        self.assertEqual(
            [d.name for d in decoders],
            ["c2.android.vp9.decoder", "c2.v4l2.vp9.decoder", "c2.android.avc.decoder"],
        )
        software, hardware, avc = decoders
        self.assertTrue(software.software_only and not software.hardware)
        self.assertEqual((software.max_width, software.max_height), (2048, 2048))
        self.assertTrue(hardware.hardware)
        self.assertEqual((hardware.max_width, hardware.max_height), (8192, 8192))
        self.assertFalse(avc.hardware)

    def test_only_a_hardware_decoder_big_enough_counts_for_4k(self):
        decoders = dc.parse_decoders(DUMP)
        names = [d.name for d in dc.hardware_decoders(decoders, "video/x-vnd.on2.vp9", 3840, 2160)]
        self.assertEqual(names, ["c2.v4l2.vp9.decoder"])
        self.assertEqual(dc.hardware_decoders(decoders[:1], "video/x-vnd.on2.vp9", 3840, 2160), [])
        self.assertEqual(dc.hardware_decoders(decoders, "video/avc", 3840, 2160), [])

    def test_describe_says_what_is_there_when_nothing_qualifies(self):
        text = dc.describe(dc.parse_decoders(DUMP)[:1], "video/x-vnd.on2.vp9")
        self.assertIn("c2.android.vp9.decoder (software, up to 2048x2048)", text)
        self.assertEqual(dc.describe([], "video/avc"), "none")

    def test_decode_result_needs_every_frame_at_real_time_speed(self):
        out = "frame=   60 fps=0.0 q=-0.0 size=N/A time=00:00:02.00 speed=3.94x"
        self.assertEqual(
            dc.decode_result(out, 60), (True, "decoded 60 frames (needs 60) at 3.9x real time")
        )
        self.assertFalse(dc.decode_result(out.replace("60", "30", 1), 60)[0])
        self.assertFalse(dc.decode_result(out.replace("3.94", "0.40"), 60)[0])
        self.assertFalse(dc.decode_result("Error opening input", 60)[0])

    def test_iris_interrupts_are_summed_over_cpus(self):
        text = (
            "           CPU0       CPU1       CPU2\n"
            " 10:       1000        200          3     GICv3  23 Level     arch_timer\n"
            "315:       8900         50         20     GICv3 206 Level     iris\n"
        )
        self.assertEqual(dc.iris_interrupts(text), 8970)
        self.assertIsNone(dc.iris_interrupts(" 10:  1 2 3  timer\n"))
        self.assertIsNone(dc.iris_interrupts(""))

    def test_the_codec_chosen_is_read_from_chromes_media_bridge_log(self):
        log = (
            "11-16 18:13:30.1 7217 7330 I cr_MediaCodecBridge: create MediaCodec video decoder, "
            "mime video/x-vnd.on2.vp9, decoder name c2.v4l2.vp9.decoder, block_model=false"
        )
        self.assertTrue(dc.codec_chosen(log))
        self.assertFalse(dc.codec_chosen(log.replace("c2.v4l2", "c2.android")))
        self.assertFalse(dc.codec_chosen("nothing"))

    def test_a_dead_codec_service_is_recognised_in_the_log(self):
        self.assertTrue(
            dc.component_died('E CCodec  : Codec2 component "c2.v4l2.vp9.decoder" died.')
        )
        self.assertTrue(dc.component_died("F libc    : Fatal signal 11 (SIGSEGV)"))
        self.assertFalse(dc.component_died("I V4L2Decoder: Set state Idle => Decoding"))


if __name__ == "__main__":
    unittest.main()
