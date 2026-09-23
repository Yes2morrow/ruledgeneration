"""Explicit local WebUI HTTP smoke check; not run by unittest discovery."""
import argparse
import json
import time
import urllib.request


def check_api(base_url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path, payload=None):
        data = json.dumps(payload).encode('utf-8') if payload is not None else None
        req = urllib.request.Request(base_url.rstrip('/') + path, data=data,
                                     headers={'Content-Type': 'application/json'})
        with opener.open(req, timeout=60) as response:
            return json.load(response)

    catalog = request('/api/modules/catalog')
    assert {m['code'] for m in catalog} == set('ABCDEFG')
    cases = [
        ({'mode': 'generate', 'evacuees': 36, 'selectedModules': {'A': 4, 'C': 8}}, 36),
        ({'mode': 'recommend', 'evacuees': 60, 'strategy': 'balanced'}, 60),
    ]
    for selection, expected_beds in cases:
        submitted = request('/api/layout', dict(length=48, width=14, days=3, **selection))
        assert submitted.get('runId') and submitted.get('statusUrl')
        deadline = time.monotonic() + 60
        while True:
            job = request(submitted['statusUrl'])
            if job['done']:
                assert not job.get('error'), job.get('error')
                layout = job['result']['layout']
                assert layout['success'] and len(layout['beds']) >= expected_beds
                assert layout['metrics']['road_connected']
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Layout job timed out: {submitted['runId']}")
            time.sleep(.1)
    print('Catalog, generate and recommend HTTP checks passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:3000')
    check_api(parser.parse_args().base_url)
