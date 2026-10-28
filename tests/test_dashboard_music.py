import threading
import unittest
from unittest.mock import Mock, patch
import requests
from personal_api_client import PersonalAPIError, desktop_device, _launch_spotify

def response(devices):
    item=Mock();item.status_code=200;item.json.return_value={'devices':devices};return item

LOCAL={'id':'native','name':'ADI','type':'Computer','is_restricted':False}

@patch.dict('os.environ',{'COMPUTERNAME':'ADI','SPOTIFY_DESKTOP_DEVICE_NAME':''})
class DesktopMusicTests(unittest.TestCase):
    @patch('personal_api_client.webbrowser.open')
    @patch('personal_api_client._launch_spotify')
    def test_opens_native_app_and_chooses_local_computer(self, launch, browser):
        session=Mock();session.get.return_value=response([
            {'id':'web','name':'PAPI · This browser','type':'Computer'},
            {'id':'phone','name':'ADI','type':'Smartphone'},LOCAL])
        self.assertEqual(desktop_device(session,'http://127.0.0.1:8000'),'native')
        launch.assert_called_once();browser.assert_not_called()
        self.assertTrue(session.get.call_args.args[0].endswith('/spotify/devices'))

    @patch('personal_api_client.time.sleep')
    @patch('personal_api_client._start_personal_api')
    @patch('personal_api_client._launch_spotify')
    def test_starts_api_when_unavailable_then_waits_for_local_app(self, launch, start, sleep):
        session=Mock();session.get.side_effect=[requests.ConnectionError(),response([]),response([LOCAL])]
        self.assertEqual(desktop_device(session,'http://127.0.0.1:8000'),'native')
        start.assert_called_once();launch.assert_called_once()

    @patch('personal_api_client.time.monotonic',side_effect=[0,31])
    @patch('personal_api_client._launch_spotify')
    def test_wrong_computer_and_restricted_devices_never_get_selected(self, launch, clock):
        session=Mock();session.get.return_value=response([{**LOCAL,'is_restricted':True},{**LOCAL,'name':'Other PC'}])
        with self.assertRaisesRegex(PersonalAPIError,'not available yet'):
            desktop_device(session,'http://127.0.0.1:8000')

    @patch('personal_api_client._launch_spotify')
    def test_cancellation_stops_before_launch(self, launch):
        event=threading.Event();event.set();session=Mock()
        with self.assertRaisesRegex(PersonalAPIError,'cancelled'):
            desktop_device(session,'http://127.0.0.1:8000',event)
        launch.assert_not_called();session.get.assert_not_called()

    @patch.dict('os.environ',{'SPOTIFY_DESKTOP_DEVICE_NAME':'My Spotify'})
    @patch('personal_api_client._launch_spotify')
    def test_custom_desktop_device_name(self, launch):
        session=Mock();session.get.return_value=response([{**LOCAL,'name':'My Spotify'}])
        self.assertEqual(desktop_device(session,'http://127.0.0.1:8000'),'native')

    @patch('personal_api_client.os.startfile')
    def test_launch_uses_spotify_protocol_not_browser(self, launch):
        _launch_spotify();launch.assert_called_once_with('spotify:')

    @patch('personal_api_client.os.startfile',side_effect=OSError())
    def test_missing_app_is_reported_without_browser_fallback(self, launch):
        with self.assertRaisesRegex(PersonalAPIError,'desktop app'):_launch_spotify()

    @patch("personal_api_client.os.startfile")
    def test_untrusted_native_uri_is_rejected(self, launch):
        for uri in ("https://evil.example", "spotify:track:bad", "file:///private", "spotify:track:"+"a"*22+"?extra=yes"):
            with self.assertRaises(PersonalAPIError): _launch_spotify(uri)
        launch.assert_not_called()
