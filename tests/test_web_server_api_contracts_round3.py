import io
import json
import unittest
from unittest.mock import patch

from qdp.web import server


class WebServerApiContractsRound3Tests(unittest.TestCase):
    def _make_handler(self, path, accept='application/json'):
        handler = server._QDPWebHandler.__new__(server._QDPWebHandler)
        handler.headers = {'Accept': accept}
        handler.rfile = io.BytesIO()
        handler.wfile = io.BytesIO()
        handler.path = path
        response = {'status': None, 'headers': []}
        handler.send_response = lambda code, message=None: response.__setitem__('status', code)
        handler.send_header = lambda key, value: response['headers'].append((key, value))
        handler.end_headers = lambda: None
        handler._trace = server._QDPWebHandler._trace.__get__(handler, server._QDPWebHandler)
        handler.client_address = ('127.0.0.1', 12345)
        return handler, response

    def test_trace_forbidden_returns_wrapped_json(self):
        handler, response = self._make_handler('/__trace')
        handler.client_address = ('192.168.1.5', 12345)
        handler._handle_trace()
        payload = json.loads(handler.wfile.getvalue().decode('utf-8'))
        self.assertEqual(response['status'], 403)
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['error']['code'], 'debug_endpoint_forbidden')

    def test_shutdown_success_returns_wrapped_json(self):
        handler, response = self._make_handler('/__shutdown')
        handler.server = type('Srv', (), {'shutdown': lambda self: None})()
        with patch('qdp.web.server.threading.Thread') as thread_cls:
            thread = thread_cls.return_value
            thread.start.return_value = None
            handler._handle_shutdown()
        payload = json.loads(handler.wfile.getvalue().decode('utf-8'))
        self.assertEqual(response['status'], 200)
        self.assertTrue(payload['ok'])
        self.assertTrue(payload['data']['shutdown'])

    def test_static_bad_path_returns_wrapped_json_error(self):
        handler, response = self._make_handler('/app/../../secret')
        parsed = server.urllib.parse.urlparse(handler.path)
        handler._handle_app_static(parsed)
        payload = json.loads(handler.wfile.getvalue().decode('utf-8'))
        self.assertEqual(response['status'], 400)
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['error']['code'], 'bad_path')


if __name__ == '__main__':
    unittest.main()
