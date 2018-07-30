"""Tests for Idle Controller."""
import time

from os import path

from RTagsComplete.plugin import vc
from RTagsComplete.plugin import idle
from RTagsComplete.tests.gui_wrapper import GuiTestWrapper

class TestIdleController(GuiTestWrapper):
    """Test Idle Controller."""

    def setUp(self):
        """Test that setup view correctly sets up the view."""
        self.set_up()
        file_name = path.join(path.dirname(__file__),
                              'test_files',
                              'test.cpp')
        self.set_up_view(file_name)

        self.assertIsNotNone(self.view)

    def tearDown(self):
        self.tear_down()

    def test_init(self):
        vc_manager = vc.VCManager()
        controller = vc_manager.view_controller(self.view)

        self.assertIsNotNone(controller)
        self.assertIsNotNone(controller.idle)

    def idle_callback():
        self.idle_callback_hit = True

    def test_idle(self):
        self.idle_callback_hit = True

        #idle_controller = idle.Controller(self.view, True, 10.0, threshold, self.idle_callback)
        #idle_controller.sleep()
        #time.sleep()

