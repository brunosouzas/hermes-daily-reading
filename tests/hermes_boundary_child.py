"""Run inside Hermes' own Python: mount Hermes' dashboard app for one profile home and probe the plugin routes.

    python hermes_boundary_child.py HERMES_HOME HERMES_AGENT_DIR

Prints one JSON object: status codes for a request without the session token and with it.
Used by tests/test_api.py::test_unauthenticated_disabled_or_other_profile.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> None:
    home, hermes_dir = sys.argv[1], sys.argv[2]
    os.environ["HERMES_HOME"] = home
    os.environ["HERMES_DASHBOARD_SESSION_TOKEN"] = "boundary-test-token"
    sys.path.insert(0, hermes_dir)
    from fastapi.testclient import TestClient

    from hermes_cli import web_server

    client = TestClient(web_server.app, base_url="http://127.0.0.1:9119")
    path = "/api/plugins/daily-reading/digests"
    anonymous = client.get(path)
    authed = client.get(path, headers={"X-Hermes-Session-Token": "boundary-test-token"})
    wrong = client.get(path, headers={"X-Hermes-Session-Token": "not-the-token"})
    print(json.dumps({"anonymous": anonymous.status_code, "wrong_token": wrong.status_code,
                      "authed": authed.status_code,
                      "latest": authed.json().get("latest") if authed.status_code == 200 else None}))


if __name__ == "__main__":
    main()
