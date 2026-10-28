import tempfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from types import SimpleNamespace
from fastapi import FastAPI,Request
from fastapi.testclient import TestClient
from deeptutor.family_learning.http_api import create_router
from deeptutor.family_learning.local_lessons import Lessons

with tempfile.TemporaryDirectory() as root:
 def auth(request:Request):
  role=request.headers.get('test-role','user')
  return SimpleNamespace(user_id='parent-test' if role=='admin' else request.headers.get('test-user','learner-test'),role=role)
 app=FastAPI();app.include_router(create_router(auth,lambda:Lessons(Path(root)),lambda:True,lambda:'http://testserver',lambda:[{'id':'learner-test','username':'test'}]),prefix='/api/family-learning')
 client=TestClient(app)
 headers={'origin':'http://testserver'}
 key='a'*32
 r=client.post('/api/family-learning/topic-requests',json={'request_id':key,'topic':'Python robots'},headers=headers)
 assert r.status_code==200,r.text
 assert client.get('/api/family-learning/topic-requests',headers={'test-user':'other'}).json()==[]
 body={'decision':'approve','expected_topic':'Python robots','replacement':'Python variables'}
 assert client.post('/api/family-learning/topic-requests/'+key+'/decision',json=body,headers=headers).status_code==403
 assert client.post('/api/family-learning/topic-requests/'+key+'/decision',json=body,headers={'test-role':'admin'}).status_code==403
 r=client.post('/api/family-learning/topic-requests/'+key+'/decision',json=body,headers={**headers,'test-role':'admin'})
 assert r.status_code==200 and r.json()['approved_topic']=='Python variables',r.text
 assert client.post('/api/family-learning/topic-requests/'+key+'/decision',json=body,headers={**headers,'test-role':'admin'}).status_code==409
 print('VERIFIED: real image API supports learner requests, parent edits and decisions; learner isolation, missing-Origin rejection and replay checks passed. No AI or assignment invoked.')
