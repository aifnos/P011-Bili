"""Two necessary HOST-only continuation tests; never import a hardware API."""
import json
import pathlib
import tempfile
import unittest

import bsl_frames as bsl
import continue_autod_handshake as continuation
from early_mode_probe import MODE_FRAME, Refused, SYNC_FRAME
from test_early_mode_probe import World, node


def write_records(directory, records):
    raw = ''.join(json.dumps(item, sort_keys=True) + '\n' for item in records).encode()
    (directory / 'device-probe/events.jsonl').write_bytes(raw)
    (directory / 'host.stdout.raw').write_bytes(raw)


def fixture(root, fake_id=None):
    directory = root / 'prior-fixture'
    directory.mkdir()
    for name in continuation.PINS:
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((continuation.PRIOR / name).read_bytes())
    if fake_id:
        records = [json.loads(line) for line in (directory / 'device-probe/events.jsonl').read_text().splitlines()]
        for record in records:
            if record.get('event') == 'USB_STATE':
                for item in record.get('devices', []):
                    item['identity_sha256'] = continuation.sha(fake_id.encode())[:16]
        write_records(directory, records)
    return directory


def pins(directory):
    return {name: continuation.sha((directory / name).read_bytes()) for name in continuation.PINS}


def open433_case():
    """New targeted subcase, independently callable without rerunning successes."""
    with tempfile.TemporaryDirectory(prefix='p011-continuation-open-host-') as temp:
        root = pathlib.Path(temp)
        fake_node = node(port='COM9')
        directory = fixture(root, fake_node['id'])
        origin = continuation.load_origin(directory, required_path=directory, pins=pins(directory))
        continuation.claim_once(origin, root / 'output', claim_path=root / 'one-shot.claim.json')
        world = World()
        world.inventory_override = lambda: [dict(fake_node)]
        attempts = []
        def failing_opener(row):
            attempts.append(dict(row))
            error = OSError('HOST fixture: first fresh open fails')
            error.winerror = 433
            raise error
        try:
            continuation.continue_round(origin, world.inventory, failing_opener, world.sink,
                                        clock=world.clock.now, sleep=world.clock.sleep)
        except Refused as exc:
            assert 'winerror=433' in str(exc)
        else:
            raise AssertionError('open failure was not refused')
        assert len(attempts) == 1 and world.transmitted == []
        results = [value for kind, value in world.records if kind == 'result']
        assert len(results) == 1 and results[0]['status'] == 'STOPPED_UNCONFIRMED'
        assert results[0]['sync_attempted'] == 0 and results[0]['connect_attempted'] is False


class ContinuationHostTests(unittest.TestCase):
    def test_origin_rejects_tampering_used_budget_and_repeat_claim(self):
        with tempfile.TemporaryDirectory(prefix='p011-continuation-host-') as temp:
            root = pathlib.Path(temp)
            directory = fixture(root)
            original = pins(directory)
            origin = continuation.load_origin(directory, required_path=directory, pins=original)
            source_path = directory / 'sources/bsl_frames.py'
            source = source_path.read_bytes()
            source_path.write_bytes(source + b'\n# HOST tamper fixture\n')
            with self.assertRaisesRegex(Refused, 'SHA mismatch'):
                continuation.load_origin(directory, required_path=directory, pins=original)
            source_path.write_bytes(source)
            result_path = directory / 'device-probe/result.json'
            result_raw = result_path.read_bytes()
            result = json.loads(result_raw)
            result['sync_attempted'] = 1
            result_path.write_text(json.dumps(result), encoding='utf-8')
            records_raw = (directory / 'device-probe/events.jsonl').read_bytes()
            records = [json.loads(line) for line in records_raw.splitlines()]
            records[-1] = dict(result, record_type='result')
            write_records(directory, records)
            # Even a self-consistent alternate HOST pin set cannot authorize a
            # round that has already consumed part of the required zero budget.
            with self.assertRaisesRegex(Refused, 'prior budget is not unused'):
                continuation.load_origin(directory, required_path=directory, pins=pins(directory))
            result_path.write_bytes(result_raw)
            (directory / 'device-probe/events.jsonl').write_bytes(records_raw)
            (directory / 'host.stdout.raw').write_bytes(records_raw)
            claim = root / 'one-shot.claim.json'
            continuation.claim_once(origin, root / 'output', claim_path=claim)
            with self.assertRaisesRegex(Refused, 'already has a continuation claim'):
                continuation.claim_once(origin, root / 'another-output', claim_path=claim)
            self.assertTrue(json.loads(claim.read_text())['consumed'])

    def test_fake_continuation_succeeds_with_zero_mode_transmissions(self):
        with tempfile.TemporaryDirectory(prefix='p011-continuation-host-') as temp:
            root = pathlib.Path(temp)
            fake_node = node(port='COM9')
            directory = fixture(root, fake_node['id'])
            origin = continuation.load_origin(directory, required_path=directory, pins=pins(directory))
            continuation.claim_once(origin, root / 'output', claim_path=root / 'one-shot.claim.json')
            def setup(serial):
                def write(data):
                    if data == SYNC_FRAME:
                        serial.queue(.02, bsl.AUTOD_VERSION_FRAME[:9])
                        serial.queue(.06, bsl.AUTOD_VERSION_FRAME[9:])
                    elif data == bsl.CONNECT_FRAME:
                        serial.queue(.02, bsl.ACK_FRAME)
                    else:
                        self.fail('a forbidden packet reached the fake underlying transport')
                serial.on_write = write
            world = World(setup)
            world.inventory_override = lambda: [dict(fake_node)]
            result = continuation.continue_round(origin, world.inventory, world.opener, world.sink,
                                                 clock=world.clock.now, sleep=world.clock.sleep)
            self.assertEqual(world.transmitted, [(1, SYNC_FRAME), (1, bsl.CONNECT_FRAME)])
            self.assertEqual(world.writes(MODE_FRAME), [])
            self.assertEqual(result['cumulative_mode_attempted'], 1)
            self.assertEqual(result['cumulative_sync_attempted'], 1)
            self.assertEqual(result['cumulative_connect_attempted'], 1)
            self.assertTrue(result['connect_ack_verified'])
            self.assertTrue(result['host_handle_closed'])
            self.assertEqual(result['status'], 'AUTOD_HANDSHAKE_CONFIRMED_NO_STORAGE_ACCESS')
            self.assertTrue(all(not item.is_open for item in world.handles))
            # The continuation adapter rejects MODE even if called directly.
            adapter = continuation.NoModeTransport(world.handles[0], world.inventory, fake_node,
                                                  dict(sync=1, connect=1))
            with self.assertRaisesRegex(Refused, 'no MODE capability'):
                adapter.write(MODE_FRAME)
            self.assertEqual(world.transmitted, [(1, SYNC_FRAME), (1, bsl.CONNECT_FRAME)])
        open433_case()


if __name__ == '__main__':
    unittest.main(verbosity=2)
