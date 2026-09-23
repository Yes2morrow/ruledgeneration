import concurrent.futures
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'cloudrun_app')]
from cloudrun_app import main
from job_queue import JobQueue, _MySQLConnection
from storage import LocalStorage, build_storage
from tenant import owner_key
from deployment import deployment_errors
from fastapi.testclient import TestClient


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.queue = JobQueue(Path(self.temp.name) / 'queue.sqlite3', max_pending=2)

    def submit(self, run_id='run1', fp='f1', owner='owner1'):
        return self.queue.submit(run_id, fp, owner, 'plan', {}, {'appid': 'app'})

    def test_concurrent_identical_submissions_admit_once(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            ids = list(executor.map(lambda i: self.submit('run'+str(i)), range(20)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(self.queue.pending_count(), 1)

    def test_concurrent_fresh_queue_initialization(self):
        target = Path(self.temp.name) / 'fresh.sqlite3'
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            queues = list(executor.map(lambda _: JobQueue(target), range(8)))
        self.assertTrue(all(queue.pending_count() == 0 for queue in queues))

    def test_capacity_is_shared_by_connections(self):
        self.submit()
        self.submit('run2', 'f2')
        with self.assertRaises(OverflowError):
            self.submit('run3', 'f3')

    def test_identity_is_required_for_retrieval_and_deduplication(self):
        self.submit()
        self.assertIsNone(self.queue.get('run1', 'owner2'))
        self.assertEqual(self.submit('run2', owner='owner2'), 'run2')

    def test_reopen_recovers_expired_lease_and_rejects_stale_completion(self):
        self.submit()
        first = self.queue.claim()
        reopened = JobQueue(Path(self.temp.name) / 'queue.sqlite3')
        self.assertIsNone(reopened.claim())
        with patch('job_queue.time.time', return_value=time.time()+61):
            second = reopened.claim()
            self.assertEqual(second['id'], first['id'])
            self.assertFalse(reopened.finish(first, result={'old': True}))
            self.assertTrue(reopened.finish(second, result={'new': True}))
        self.assertEqual(reopened.get('run1', 'owner1')['result'], {'new': True})

    def test_repeated_worker_crashes_become_explicit_failure(self):
        self.submit()
        now = time.time()
        for offset in (0, 61, 122):
            with patch('job_queue.time.time', return_value=now+offset):
                self.assertIsNotNone(self.queue.claim())
        with patch('job_queue.time.time', return_value=now+183):
            self.assertIsNone(self.queue.claim())
        self.assertEqual(self.queue.get('run1', 'owner1')['status'], 'failed')

    def test_mysql_sql_translation_covers_multiline_insert_and_parameters(self):
        from unittest.mock import Mock
        connection = Mock()
        adapter = _MySQLConnection(connection)
        adapter.execute('INSERT INTO jobs\n (id,status) VALUES (?,?)', ('x','queued'))
        connection.cursor().execute.assert_called_with(
            'INSERT INTO layout_jobs\n (id,status) VALUES (%s,%s)', ('x','queued'))


class APIBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = LocalStorage(self.root, 'http://testserver')
        self.queue = JobQueue(self.root / 'jobs.sqlite3')
        for name, value in [('_storage', self.storage), ('_jobs', self.queue), ('LOCAL_ROOT', self.root)]:
            p = patch.object(main, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.a = {'X-WX-APPID': 'app1', 'X-WX-OPENID': 'user1'}
        self.b = {'X-WX-APPID': 'app1', 'X-WX-OPENID': 'user2'}
        self.owner = owner_key({'appid': 'app1', 'userKey': 'app1:user1'})
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        self.payload = dict(evacuees=8, length=12, width=12, days=2, selectedModules={'B': 4})
        # Tests own isolated quotas and an explicit test allowlist.
        p = patch('tenant._ALLOWED_APPIDS', frozenset({'app1'}))
        p.start()
        self.addCleanup(p.stop)
        from ratelimit import SlidingWindowLimiter
        for name in ('_limiter', '_query_limiter', '_validation_limiter'):
            p = patch.object(main, name, SlidingWindowLimiter(1000, 60))
            p.start()
            self.addCleanup(p.stop)

    def test_missing_user_identity_is_denied(self):
        response = self.client.post('/api/jobs', json=self.payload, headers={'X-WX-APPID':'app1'})
        self.assertEqual(response.status_code, 403)

    def test_job_query_and_result_replay_are_owner_scoped(self):
        submitted = self.client.post('/api/jobs', json=self.payload, headers=self.a)
        self.assertEqual(submitted.status_code, 202)
        run_id = submitted.json()['runId']
        self.assertEqual(self.client.get('/api/jobs/'+run_id, headers=self.b).status_code, 404)
        self.assertEqual(self.client.get('/api/jobs/'+run_id, headers=self.a).status_code, 200)
        self.storage.put_json(f'results/{run_id}.json', {'owner': self.owner, 'result': {'runId': run_id}})
        self.assertEqual(self.client.get('/api/runs/'+run_id, headers=self.b).status_code, 404)
        self.assertEqual(self.client.get('/api/runs/'+run_id, headers=self.a).status_code, 200)

    def test_client_run_id_cannot_overwrite_another_task(self):
        first = self.client.post('/api/jobs', json=dict(self.payload, runId='chosen'), headers=self.a).json()
        second = self.client.post('/api/jobs', json=dict(self.payload, runId='chosen'), headers=self.b).json()
        self.assertNotEqual(first['runId'], second['runId'])
        repeated = self.client.post('/api/jobs', json=self.payload, headers=self.a).json()
        self.assertEqual(first['runId'], repeated['runId'])

    def test_invalid_or_excessive_modules_are_rejected_before_queuing(self):
        for selected in ({'B': True}, {'B': 1.5}, {'B': 2001}, {'A':3}, {'X':1}):
            response = self.client.post('/api/jobs', json=dict(self.payload, selectedModules=selected), headers=self.a)
            self.assertEqual(response.status_code, 422, selected)
        self.assertEqual(self.queue.pending_count(), 0)

    def test_large_request_body_is_rejected(self):
        response = self.client.post('/api/jobs', content=b' '*65537, headers=self.a)
        self.assertEqual(response.status_code, 413)

    def test_budget_stops_computation_instead_of_holding_cpu_indefinitely(self):
        from compute_budget import start_budget, reset_budget, check_budget
        with patch.dict(os.environ, {'COMPUTE_TIMEOUT_SECONDS': '1'}), patch('compute_budget.time.monotonic', return_value=100):
            token = start_budget()
        try:
            with patch('compute_budget.time.monotonic', return_value=102), self.assertRaises(TimeoutError):
                check_budget()
        finally:
            reset_budget(token)
        check_budget()

    def test_unsigned_files_internal_records_and_sibling_paths_are_inaccessible(self):
        self.storage.put_json('results/secret.json', {'secret': True})
        url = self.storage.put_bytes(b'PNG', 'plans/2026/09/app1/test.png')['url']
        parsed = urlsplit(url)
        self.assertEqual(self.client.get(parsed.path+'?'+parsed.query).status_code, 200)
        self.assertEqual(self.client.get(parsed.path).status_code, 404)
        self.assertEqual(self.client.get('/api/runs/files/results/secret.json').status_code, 404)
        self.assertEqual(self.client.get('/api/runs/files/jobs.sqlite3').status_code, 404)
        key = 'plans/../../outside.png'
        expires = int(time.time())+60
        signature = self.storage._signature(key, expires)
        self.assertEqual(self.client.get('/api/runs/files/plans/%2e%2e/%2e%2e/outside.png',
                         params={'expires':expires, 'signature':signature}).status_code, 404)

    def test_expired_image_url_is_refreshed_on_replay(self):
        old_url = self.storage.put_bytes(b'PNG', 'plans/test.png')['url']
        self.storage.put_json('results/owned.json', {'owner':self.owner, 'result':{'outputFiles':{'textureOnly':old_url}}})
        with patch('storage.time.time', return_value=time.time()+8000):
            replay = self.client.get('/api/runs/owned', headers=self.a).json()
            renewed = replay['outputFiles']['textureOnly']
            self.assertNotEqual(old_url, renewed)
            self.assertEqual(self.client.get(renewed).status_code, 200)
            self.assertEqual(self.client.get(old_url).status_code, 404)

    def test_replay_prefers_committed_queue_result_over_an_old_archive(self):
        self.queue.submit('winner', 'fp', self.owner, 'plan', {}, {'appid':'app1'})
        claimed = self.queue.claim()
        self.queue.finish(claimed, result={'winner': True})
        self.storage.put_json('results/winner.json', {'owner': self.owner, 'result': {'winner': False}})
        self.assertTrue(self.client.get('/api/runs/winner', headers=self.a).json()['winner'])

    def test_incomplete_cos_configuration_does_not_silently_use_local_disk(self):
        with patch.dict(os.environ, {'COS_BUCKET': 'configured-bucket'}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'COS'):
                build_storage(self.root)

    def test_production_configuration_fails_closed(self):
        self.assertGreater(len(deployment_errors({})), 0)

    def test_real_async_plan_produces_owned_result_and_signed_image(self):
        with TestClient(main.app) as client:
            run_id = client.post('/api/jobs', json=self.payload, headers=self.a).json()['runId']
            deadline = time.monotonic()+20
            while time.monotonic() < deadline:
                info = client.get('/api/jobs/'+run_id, headers=self.a).json()
                if info['status'] in ('succeeded', 'failed'):
                    break
                time.sleep(.05)
            self.assertEqual(info['status'], 'succeeded', info)
            self.assertEqual(len(info['result']['layout']['beds']), 8)
            self.assertTrue(info['result']['layout']['metrics']['route_access_valid'])
            image = client.get(info['result']['outputFiles']['textureOnly'])
            self.assertEqual(image.status_code, 200)
            self.assertTrue(image.content.startswith(b'\x89PNG'))


if __name__ == '__main__':
    unittest.main()
