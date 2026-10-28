import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import activation


class ActivationTests(unittest.TestCase):
    @patch("activation.ButtonActivation")
    def test_second_button_press_signals_existing_instance(self, factory):
        instance = factory.return_value
        instance.claim.return_value = False
        main = Mock()
        self.assertEqual(activation.launch(main, Path.cwd(), ["--listen-now"]), 0)
        main.assert_not_called()
        instance.signal.assert_called_once()
        instance.close.assert_called_once()

    @patch("activation.ButtonActivation")
    def test_first_button_launch_passes_activation_and_closes_handles(self, factory):
        instance = factory.return_value
        instance.claim.return_value = True
        main = Mock(return_value=0)
        self.assertEqual(activation.launch(main, Path.cwd(), ["--listen-now"]), 0)
        main.assert_called_once_with(["--listen-now"], activation=instance)
        instance.close.assert_called_once()

    @patch("activation.ButtonActivation")
    def test_normal_cli_checks_do_not_create_a_running_instance(self, factory):
        main = Mock(return_value=0)
        activation.launch(main, Path.cwd(), ["--check"])
        factory.assert_not_called()
        main.assert_called_once_with(["--check"])

    @unittest.skipUnless(os.environ.get("RUN_WINDOWS_ACTIVATION_TESTS") == "1", "Native desktop access required")
    def test_native_cross_process_activation_busy_handling_and_restart(self):
        work = Path(__file__).resolve().parents[1] / "work"
        temporary = tempfile.TemporaryDirectory(dir=work)
        root = Path(temporary.name)
        owner = activation.ButtonActivation(root)
        try:
            self.assertTrue(owner.claim())
            owner.prepare_wait()
            child = "from activation import ButtonActivation; import sys; a=ButtonActivation(sys.argv[1]); print(a.claim(), a.signal()); a.close()"
            result = subprocess.run([sys.executable, "-B", "-c", child, str(root)],
                                    capture_output=True, text=True, timeout=10, cwd=work.parent)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "False True")
            self.assertTrue(owner.consume())
            self.assertFalse(owner.consume())
            owner.finish_wait()
            result = subprocess.run([sys.executable, "-B", "-c", child, str(root)],
                                    capture_output=True, text=True, timeout=10, cwd=work.parent)
            self.assertEqual(result.stdout.strip(), "False False")
            owner.prepare_wait()
            self.assertFalse(owner.consume())
            owner.close()
            replacement = activation.ButtonActivation(root)
            try:
                self.assertTrue(replacement.claim())
            finally:
                replacement.close()
        finally:
            owner.close()
            self.assertTrue(root.resolve().is_relative_to(work.resolve()))
            temporary.cleanup()
