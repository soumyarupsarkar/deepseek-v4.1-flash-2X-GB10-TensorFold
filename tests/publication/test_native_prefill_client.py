"""The qualification client's cancellation must wake either HTTP read state."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
from pathlib import Path
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('native_prefill', ROOT / 'tools/qualification/native_prefill.py')
prefill = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prefill)


class NativePrefillClient(unittest.TestCase):
    def check_cancel(self, send_headers):
        entered = threading.Event()
        release = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                if send_headers:
                    # HTTP/1.0 transfers ownership of the socket to HTTPResponse.
                    # The client must still be able to cancel its body read.
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', '100')
                    self.end_headers()
                    self.wfile.write(b'{')
                    self.wfile.flush()
                entered.set()
                release.wait(5)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        thread.start()
        probe = prefill.Probe('http://127.0.0.1:' + str(server.server_port), {'synthetic': True}).start()
        try:
            self.assertTrue(entered.wait(2), 'Synthetic request did not reach the test server')
            self.assertFalse(probe.done.is_set())
            started = time.monotonic()
            probe.close()
            self.assertLess(time.monotonic() - started, 2)
            self.assertTrue(probe.done.is_set())
            self.assertIsNotNone(probe.error)
            self.assertIsNone(probe.result)
        finally:
            release.set()
            probe.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_cancel_before_headers(self):
        self.check_cancel(False)

    def test_cancel_while_reading_response_body(self):
        self.check_cancel(True)


if __name__ == '__main__':
    unittest.main()
