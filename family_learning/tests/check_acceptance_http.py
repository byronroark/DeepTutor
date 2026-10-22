"""Explicit opt-in tests against disposable source-built acceptance accounts."""
import json
import os
from pathlib import Path
import sys
import unittest
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor, Request
from http.cookiejar import CookieJar
import uuid

BASE = 'http://127.0.0.1:3783'


class Client:
    def __init__(self, username, password):
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self.call('/api/auth/login', {'username':username,'password':password})

    def call(self, path, body=None, origin=BASE):
        request = Request(BASE+path, data=None if body is None else json.dumps(body).encode(),
                          headers={'Content-Type':'application/json','Origin':origin})
        with self.opener.open(request,timeout=15) as response:
            return json.load(response)


@unittest.skipUnless(os.environ.get('FAMILY_HTTP_LIVE_TEST') == '1', 'explicit disposable acceptance only')
class AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        password=Path('/tmp/family-learning-acceptance-runtime/fixture-password').read_text()
        cls.parent=Client('test-parent',password)
        cls.child=Client('test-learner',password)
        cls.learner=cls.parent.call('/api/family-learning/learners')[0]['id']
        cls.samples=cls.parent.call('/api/family-learning/starters')

    def course(self,index):
        course=json.loads(json.dumps(self.samples[index]))
        course['title'] += ' acceptance ' + uuid.uuid4().hex[:8]
        key=self.parent.call('/api/family-learning/courses',course)['id']
        self.parent.call(f'/api/family-learning/courses/{key}/assignment',{'learner':self.learner})
        return key

    def answer(self,key,lesson,text):
        return self.child.call(f'/api/family-learning/courses/{key}/lessons/{lesson}/answer',{'answer':text,'request_id':uuid.uuid4().hex})

    def test_prepared_feedback_unlock_and_durable_marker(self):
        key=self.course(0)
        self.assertEqual(self.answer(key,'name-a-value','1')['state'],'retry')
        self.assertEqual(self.answer(key,'name-a-value','0')['state'],'passed')
        view=self.child.call(f'/api/family-learning/courses/{key}')
        self.assertTrue(view['lessons'][1]['unlocked'])
        self.assertNotIn('answer',view['lessons'][0])
        marker=Path('/tmp/family-learning-acceptance-runtime/persistence-check.json')
        marker.write_text(json.dumps({'course':key,'learner':self.learner}))
        marker.chmod(0o600)

    def test_writing_revise_and_approve(self):
        key=self.course(2)
        self.child.call(f'/api/family-learning/courses/{key}/lessons/book-report/draft',{'text':'A saved local draft.'})
        first=self.answer(key,'book-report','My first report.')
        self.parent.call(f"/api/family-learning/submissions/{first['submission']}/review",{'approve':False,'feedback':'Add an example from the story.'})
        second=self.answer(key,'book-report','My revised report has an example.')
        self.parent.call(f"/api/family-learning/submissions/{second['submission']}/review",{'approve':True,'feedback':'Your example supports your opinion.'})
        self.assertEqual(self.child.call(f'/api/family-learning/courses/{key}')['lessons'][0]['state'],'passed')
        versions=self.parent.call(f'/api/family-learning/courses/{key}')['submissions']
        self.assertEqual(len(versions),2)

    def test_revocation_and_parent_surface_denied(self):
        key=self.course(0)
        self.parent.call(f'/api/family-learning/courses/{key}/assignment',{'learner':self.learner,'active':False})
        for path in [f'/api/family-learning/courses/{key}','/api/family-learning/starters','/api/family-learning/learners']:
            with self.assertRaises(HTTPError) as raised:
                self.child.call(path)
            self.assertEqual(raised.exception.code,403)
            raised.exception.close()

    def test_cross_origin_write_denied_through_real_proxy(self):
        with self.assertRaises(HTTPError) as raised:
            self.parent.call('/api/family-learning/courses',self.samples[0],origin='http://evil.example')
        self.assertEqual(raised.exception.code,403)
        raised.exception.close()

    def test_local_only_blocks_learner_settings_api(self):
        with self.assertRaises(HTTPError) as raised:
            self.child.call('/api/settings')
        self.assertEqual(raised.exception.code,403)
        raised.exception.close()


if __name__ == '__main__':
    unittest.main()
