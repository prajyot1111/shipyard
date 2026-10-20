"""Voice at its own address, `harbor.<tailnet>` (2026-09-26).

On a phone, Chrome installs one app per part of a site: the deck's scope is `/`, so Voice
under `/segments/voice/app/` could only ever be added as a shortcut beside it. A Tailscale
Service gives this same server a second name, and on that name `/` is Voice, so each installs
as its own app. The deck's own pages asked for on that name (Voice's back link,
`/?view=now`) go back to the deck's address, and the deck opens Voice at its own address.
"""

import http.client
import json
import unittest

from keel import serve
from tests.test_serve import ServerCase

HARBOR = "https://harbor.example.ts.net"
DECK = "https://keel.example.ts.net"


class HarborHostTest(ServerCase):
    def setUp(self):
        super().setUp()
        self.cfg.voice_app_url = HARBOR
        self.cfg.voice_deck_url = DECK

    def get(self, path, host):
        port = self.server.server_address[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        self.addCleanup(conn.close)
        conn.request("GET", path, headers={"Host": host})
        response = conn.getresponse()
        response.read()
        return response.status, response.getheader("Location")

    def test_the_harbor_name_opens_voice(self):
        self.assertEqual(self.get("/", "harbor.example.ts.net"), (302, serve.VOICE_APP_PATH))

    def test_the_deck_s_pages_on_the_harbor_name_go_to_the_deck(self):
        self.assertEqual(self.get("/?view=now", "harbor.example.ts.net"), (302, DECK + "/?view=now"))


    def test_voice_itself_is_served_on_the_harbor_name(self):
        status, _ = self.get(serve.VOICE_APP_PATH + "manifest.webmanifest", "harbor.example.ts.net")
        self.assertNotEqual(status, 302)

    def test_the_deck_opens_voice_at_its_own_address(self):
        self.assertEqual(serve.voice_url(self.cfg), HARBOR + serve.VOICE_APP_PATH)
        state = self.get_json("/api/state")
        self.assertEqual(state["config"]["voice_url"], HARBOR + serve.VOICE_APP_PATH)



if __name__ == "__main__":
    unittest.main()
