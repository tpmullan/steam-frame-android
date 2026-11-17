import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock

PATH = pathlib.Path(__file__).resolve().parent.parent / "tools/gpu-trial.py"
spec = importlib.util.spec_from_file_location("gpu_trial", PATH)
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class GpuTrialTests(unittest.TestCase):
    def test_remote_steam_script_is_valid_python(self):
        compile(trial.REMOTE_STEAM, "remote", "exec")

    def test_every_config_names_an_egl_wgapps_accepts_and_plain_properties(self):
        for name, config in trial.CONFIGS.items():
            self.assertIn(config["egl"], ("mesa", "angle"), name)
            for prop in config["device_prop"]:
                self.assertRegex(prop, r"^[a-z][a-z0-9._]+=[A-Za-z0-9._-]+$")

    def test_baseline_changes_nothing(self):
        self.assertEqual(trial.CONFIGS["baseline"], {"device_prop": [], "egl": "mesa"})

    def test_toggle_script_writes_each_hand_to_its_sim_file_and_waits(self):
        sent = []
        frame = mock.Mock()
        frame.run.side_effect = sent.append
        steps = [
            {"right": [0.1, -0.1, -0.2, 0, 35, 1, 0, 0, 0], "wait": 0.5},
            {
                "left": [-0.1, -0.1, -0.2, 0, 35, 0, 1, 0, 0],
                "right": [0.1, -0.1, -0.2, 0, 35, 0, 0, 0, 0],
            },
        ]
        with mock.patch.object(trial.time, "sleep") as sleep:
            trial.play_toggle_script(frame, steps)
        self.assertEqual(len(sent), 3)
        self.assertIn("0.1 -0.1 -0.2 0 35 1 0 0 0' > /tmp/xr-sim-input;", sent[0])
        self.assertIn("> /tmp/xr-sim-input-left;", sent[2])
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [0.5, 1.0])

    def test_toggle_script_sends_key_events_to_android(self):
        frame = mock.Mock()
        with mock.patch.object(trial.time, "sleep"):
            trial.play_toggle_script(frame, [{"keys": ["KEYCODE_F"], "wait": 0}])
        frame.android.assert_called_once_with("input keyevent KEYCODE_F")

    def test_max_gap_counts_silence_from_the_start_and_up_to_the_end(self):
        self.assertEqual(trial.max_gap([11.0, 12.0, 13.0], 10.0, 14.0), 1.0)
        self.assertEqual(trial.max_gap([11.0, 16.0], 10.0, 17.0), 5.0)
        self.assertEqual(trial.max_gap([], 10.0, 14.0), 4.0)
        self.assertEqual(trial.max_gap([5.0, 11.0], 10.0, 11.5), 1.0)

    def test_epochs_picks_the_timestamps_of_lines_with_the_marker(self):
        log = (
            "  100.250 D VRB: Average Frame Rate: 72Hz\n"
            "  101.5 D x: other\n"
            "  102.0 D VRB: Average Frame Rate: 72Hz"
        )
        self.assertEqual(trial.epochs(log, "Average Frame Rate"), [100.25, 102.0])

    def test_pose_moved_ignores_noise_and_catches_a_tilt_or_a_missing_reading(self):
        base = (0.0, 0.0, 0.0, 0.3, 0.0, 3.06)
        self.assertFalse(trial.pose_moved(base, (0.001, 0.0, 0.0, 0.301, 0.0, 3.061)))
        self.assertTrue(trial.pose_moved(base, (0.0, 0.0, 0.0, 0.5, 0.0, 3.06)))
        self.assertTrue(trial.pose_moved(base, (0.05, 0.0, 0.0, 0.3, 0.0, 3.06)))
        self.assertTrue(trial.pose_moved(base, None))
        self.assertFalse(
            trial.pose_moved((0, 0, 0, 0, 0, 3.14), (0, 0, 0, 0, 0, -3.14))
        )  # wraps around

    def test_wait_for_returns_true_as_soon_as_the_predicate_holds_and_false_on_timeout(self):
        calls = []
        self.assertTrue(trial.wait_for(lambda: calls.append(1) or len(calls) >= 3, 5, 0.01))
        self.assertFalse(trial.wait_for(lambda: False, 0.05, 0.01))

    def test_pids_changed_names_missing_and_restarted_services_only(self):
        before = {"surfaceflinger": "134", "composer": "93"}
        self.assertEqual(trial.pids_changed(before, dict(before)), [])
        self.assertEqual(
            trial.pids_changed(before, {"surfaceflinger": "134", "composer": "201"}), ["composer"]
        )
        self.assertEqual(
            trial.pids_changed(before, {"surfaceflinger": "", "composer": "93"}), ["surfaceflinger"]
        )
        self.assertEqual(trial.pids_changed(before, {}), ["surfaceflinger", "composer"])

    def test_pointer_check_fails_when_the_composer_restarts(self):
        class Fake:
            def __init__(self, pids):
                self.pids, self.calls = list(pids), 0

            def android(self, command, timeout=60):
                if command.startswith("pidof"):
                    name = command.split()[1]
                    return self.pids[self.calls][name]
                if command.startswith("ls -t"):
                    return "tombstone_1"
                self.calls = min(self.calls + 1, len(self.pids) - 1)
                return ""

        up = {n: "1" for n in trial.SYSTEM_SERVICES}
        restarted = {**up, trial.SYSTEM_SERVICES[1]: "2"}
        with mock.patch.object(trial.time, "sleep"):
            self.assertTrue(trial.pointer(Fake([up, up])).ok)
            self.assertFalse(trial.pointer(Fake([up, restarted])).ok)

    def test_a_freeze_leaves_a_file_with_the_stacks_and_the_end_of_the_log(self):
        frame = mock.Mock()
        frame.android.side_effect = lambda command, timeout=60: (
            "STACK: eglQuerySurface" if "debuggerd" in command else "LOG: last lines"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(trial.dump_freeze(frame, pathlib.Path(tmp)))
            text = path.read_text()
            self.assertEqual(path.parent, pathlib.Path(tmp))
        self.assertIn("STACK: eglQuerySurface", text)
        self.assertIn("LOG: last lines", text)
        self.assertIn("debuggerd -b $(pidof ", frame.android.call_args_list[0].args[0])


if __name__ == "__main__":
    unittest.main()
