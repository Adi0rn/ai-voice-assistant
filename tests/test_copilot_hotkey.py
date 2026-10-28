import unittest
from copilot_hotkey import CopilotGesture


class CopilotGestureTests(unittest.TestCase):
    def test_copilot_triggers_once_until_released(self):
        key = CopilotGesture()
        self.assertEqual(key.update(0x5B, True), (False, False))
        self.assertEqual(key.update(0xA0, True), (False, False))
        self.assertEqual(key.update(0x86, True), (True, True))
        self.assertEqual(key.update(0x86, True), (True, False))
        self.assertEqual(key.update(0x86, False), (True, False))
        self.assertEqual(key.update(0x86, True), (True, True))

    def test_other_keys_and_unmodified_f23_pass_through(self):
        key = CopilotGesture()
        self.assertEqual(key.update(0x41, True), (False, False))
        self.assertEqual(key.update(0x86, True), (False, False))
        key.update(0x5B, True)
        self.assertEqual(key.update(0x86, True), (False, False))

    def test_release_order_and_modifier_cleanup(self):
        key = CopilotGesture()
        key.update(0x5C, True)
        key.update(0xA1, True)
        self.assertEqual(key.update(0x86, True), (True, True))
        key.update(0x5C, False)
        key.update(0xA1, False)
        self.assertEqual(key.update(0x86, False), (True, False))
        self.assertEqual(key.update(0x86, True), (False, False))
