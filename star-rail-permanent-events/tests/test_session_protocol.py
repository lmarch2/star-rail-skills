import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
worker = SCRIPTS / 'event_session.py'
# Load protocol-only definitions; the controller's executable body must not activate the game.
namespace = {'__file__': str(worker)}
exec(compile(worker.read_text(encoding='utf-8').split('parser = argparse.ArgumentParser', 1)[0], str(worker), 'exec'), namespace)
check_control = namespace['check_control']
ControlRequestError = namespace['ControlRequestError']


def test_claim_and_same_owner_input():
    assert check_control({'action': 'claim', 'owner': 'a'}, None) == 'a'
    assert check_control({'action': 'key', 'key': 'w', 'owner': 'a'}, 'a') == 'a'
    assert check_control({'action': 'release', 'owner': 'a'}, 'a') == 'a'


@pytest.mark.parametrize('payload', [
    {'action': 'claim', 'owner': 'b'},
    {'action': 'key', 'owner': 'b'},
    {'action': 'stop'},
    {'action': 'plot', 'enabled': False},
])
def test_competitor_or_legacy_input_cannot_control_owner(payload):
    with pytest.raises(PermissionError):
        check_control(payload, 'a')


def test_readonly_status_remains_accessible():
    assert check_control({'action': 'status'}, 'a') == 'a'
    assert check_control({'action': 'map_locate'}, 'a') == 'a'


def test_preflight_rejects_unknown_action_before_first_input():
    with pytest.raises(ControlRequestError):
        check_control({'actions': [{'action': 'key'}, {'action': 'unknown'}], 'owner': 'a'}, 'a')


def test_claim_cannot_smuggle_a_batch():
    with pytest.raises(ControlRequestError):
        check_control({'actions': [{'action': 'claim'}, {'action': 'key'}], 'owner': 'b'}, None)


def test_concurrent_clients_keep_all_requests(tmp_path):
    payload = tmp_path / 'request.json'
    payload.write_text('{"action":"status"}', encoding='utf-8')
    def submit(index):
        command = [sys.executable, str(SCRIPTS / 'session_request.py'), '--session', str(tmp_path),
                   '--file', str(payload), '--owner', f'client-{index}', '--timeout', '0']
        return json.loads(subprocess.check_output(command, text=True))
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(submit, range(12)))
    ids = [result['request'] for result in results]
    assert len(set(ids)) == 12
    requests = [json.loads(p.read_text(encoding='utf-8')) for p in (tmp_path / 'requests').glob('*.json')]
    assert {r['owner'] for r in requests} == {f'client-{i}' for i in range(12)}
