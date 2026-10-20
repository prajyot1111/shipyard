"""`helpers.serve_in_background`: a test's server stops as soon as it is told to.

`socketserver`'s `serve_forever` looks for a shutdown request once per `poll_interval`, half a
second by default, and `shutdown()` blocks until it has looked. Every test that served a
deck, a door, a fake lavish or a fake gateway paid up to that half second in its teardown:
measured 2026-09-24 as 150 s against 69 s over the five modules that served then (test_serve
and test_housetier among them; the other three went with the two-machine code, c-622), run
serially on this Mac.
"""

import http.server
import time
import unittest

from tests.helpers import SERVE_POLL, serve_in_background


class QuickShutdownTest(unittest.TestCase):
    def test_shutdown_returns_well_inside_the_stdlib_half_second(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
        self.addCleanup(server.server_close)
        thread = serve_in_background(server)
        time.sleep(SERVE_POLL * 2)                # into the loop's wait, not before it
        started = time.monotonic()
        server.shutdown()
        took = time.monotonic() - started
        thread.join(1.0)
        self.assertFalse(thread.is_alive())
        self.assertLess(took, 0.25, f"shutdown took {took:.3f}s")

    def test_the_thread_is_a_daemon_so_a_failed_test_cannot_hang_the_run(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
        self.addCleanup(server.server_close)
        thread = serve_in_background(server)
        self.addCleanup(server.shutdown)
        self.assertTrue(thread.daemon)


if __name__ == "__main__":
    unittest.main()
