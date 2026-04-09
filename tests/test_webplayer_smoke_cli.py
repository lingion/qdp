import json
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_webplayer_smoke_cli_json_mode():
    repo = REPO_ROOT
    proc = None
    for attempt in range(2):
        proc = subprocess.run(
            [sys.executable, 'scripts/webplayer_smoke.py', '--json'],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            break
        if attempt == 0:
            time.sleep(1.0)
    assert proc is not None
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout)
    assert payload['ok'] is True
    assert payload['expected_version']
    labels = [item['label'] for item in payload['results']]
    assert '/app/' in labels
    assert '/__version' in labels
    assert '/api/meta' in labels
    assert '/api/discover-random-albums' in labels
    assert '/api/me' in labels
    indexed = {item['label']: item for item in payload['results']}
    assert indexed['/api/discover-random-albums']['ok'] is True
    assert indexed['/api/me']['ok'] is True
