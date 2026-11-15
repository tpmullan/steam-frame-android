import importlib.util
import pathlib
import unittest

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

    def test_wait_for_returns_true_as_soon_as_the_predicate_holds_and_false_on_timeout(self):
        calls = []
        self.assertTrue(trial.wait_for(lambda: calls.append(1) or len(calls) >= 3, 5, 0.01))
        self.assertFalse(trial.wait_for(lambda: False, 0.05, 0.01))


if __name__ == "__main__":
    unittest.main()
