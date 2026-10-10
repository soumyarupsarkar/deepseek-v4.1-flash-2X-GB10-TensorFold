"""Exercise only a temporary synthetic loopback server; never the inference API."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import itertools
import json
import threading
import unittest

from pathlib import Path
import sys

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'tools/qualification'))
from native_decode_compaction import Reader, witnesses


@contextlib.contextmanager
def fixture(mode='normal'):
    entered = threading.Event()
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            entered.set()
            if mode == 'before_headers':
                release.wait(5)
            self.send_response(503 if mode == 'bad_status' else 200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            if mode == 'after_headers':
                release.wait(5)
            try:
                if mode == 'early_end':
                    self.wfile.write(b'data: [DONE]\n\n')
                else:
                    for i in range(256):
                        piece = json.dumps({'choices': [{'text': f'{i}.'}]})
                        self.wfile.write(('data: '+piece+'\n\n').encode())
                self.wfile.flush()
                release.wait(5)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', entered
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


class CompactionClientTests(unittest.TestCase):
    def test_witnesses_cover_every_possible_moved_subset(self):
        survivors = list(range(1, 16, 2))
        for count in range(1, 9):
            chosen = set(witnesses(survivors, count))
            self.assertEqual(len(chosen), 9-count)
            for moved in itertools.combinations(survivors, count):
                self.assertTrue(chosen.intersection(moved))

    def test_invalid_relocation_counts_fail(self):
        for value in (0, 9, -1, 1.0, True, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                witnesses(list(range(8)), value)

    def test_remote_endpoint_is_rejected_before_connect(self):
        with self.assertRaises(ValueError):
            Reader('http://192.0.2.1:8001', {})

    def test_paused_reader_counts_buffered_and_fresh_chunks(self):
        with fixture() as (base, _):
            probe = Reader(base, {}).start()
            try:
                self.assertTrue(probe.holding.wait(2))
                self.assertEqual(len(probe.parts), 24)
                self.assertFalse(probe.done.is_set())
                probe.goal = 160
                probe.release.set()
                self.assertTrue(probe.done.wait(2))
                probe.check()
                self.assertEqual(probe.summary()['chunks'], 160)
                self.assertEqual(''.join(probe.parts), ''.join(f'{i}.' for i in range(160)))
            finally:
                probe.cancel()
                probe.thread.join(2)
            self.assertFalse(probe.thread.is_alive())

    def test_solo_prefix_success_and_mismatch(self):
        with fixture() as (base, _):
            for expected, success in [('0.1.2.', True), ('wrong', False)]:
                probe = Reader(base, {}, expected=expected).start()
                try:
                    self.assertTrue(probe.done.wait(2))
                    if success:
                        probe.check()
                        self.assertEqual(probe.summary()['chunks'], 3)
                    else:
                        with self.assertRaisesRegex(AssertionError, 'differs from solo'):
                            probe.check()
                finally:
                    probe.cancel()
                    probe.thread.join(2)

    def test_bad_status_and_early_end_fail(self):
        for mode, expected in [('bad_status', RuntimeError), ('early_end', AssertionError)]:
            with self.subTest(mode=mode), fixture(mode) as (base, _):
                probe = Reader(base, {}).start()
                try:
                    self.assertTrue(probe.done.wait(2))
                    with self.assertRaises(expected):
                        probe.check()
                finally:
                    probe.cancel()
                    probe.thread.join(2)

    def test_cancel_interrupts_wait_for_headers_or_body(self):
        for mode in ('before_headers', 'after_headers'):
            with self.subTest(mode=mode), fixture(mode) as (base, entered):
                probe = Reader(base, {}).start()
                try:
                    self.assertTrue(entered.wait(2))
                    probe.cancel()
                    self.assertTrue(probe.done.wait(2))
                    probe.check()
                finally:
                    probe.cancel()
                    probe.thread.join(2)
                self.assertFalse(probe.thread.is_alive())

    def test_cancel_interrupts_paused_reader(self):
        with fixture() as (base, _):
            probe = Reader(base, {}).start()
            try:
                self.assertTrue(probe.holding.wait(2))
                probe.cancel()
                self.assertTrue(probe.done.wait(2))
                probe.check()
                self.assertEqual(len(probe.parts), 24)
            finally:
                probe.cancel()
                probe.thread.join(2)
            self.assertFalse(probe.thread.is_alive())


if __name__ == '__main__':
    unittest.main(verbosity=2)
