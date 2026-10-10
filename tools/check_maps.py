"""Verify the scraper's local UI and jobs API, without making an external search."""
import json
import urllib.request

from mvp import maps_request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open("http://127.0.0.1:8082/", timeout=30) as response:
    assert response.status == 200
    assert "Google Maps Scraper" in response.read().decode()
jobs = json.loads(maps_request("GET", "jobs"))
assert jobs is None or isinstance(jobs, list)
print("Maps UI and jobs API verified. External collection is checked separately.")
