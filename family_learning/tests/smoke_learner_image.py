"""Disposable learner-image acceptance; never mounts household data."""

import json
import os
from pathlib import Path
import subprocess
import time
import uuid


def run(*args):
    return subprocess.check_output(list(args), text=True).strip()


def main():
    name = "family-learner-smoke-" + uuid.uuid4().hex[:10]
    image = os.environ.get("FAMILY_LEARNER_TEST_IMAGE", "family-deeptutor:acceptance")
    volume = name + "-data"
    run("docker", "volume", "create", "--label", "family-learning.test=learner-smoke", volume)
    try:
        seed = """import os,json
from pathlib import Path
root=Path('/app/data');root.mkdir(exist_ok=True);os.chown(root,950,950)
for item in root.rglob('*'):os.chown(item,950,950)
os.setgid(950);os.setuid(950)
settings=root/'user/settings';settings.mkdir(parents=True,exist_ok=True)
(settings/'auth.json').write_text(json.dumps({'enabled':True,'username':'','password_hash':''}))
(settings/'model_catalog.json').write_text(json.dumps({'version':1,'services':{}}))
from deeptutor.services.auth import add_user
add_user('test-parent','synthetic-test-password',role='admin')
add_user('test-learner','synthetic-test-password',role='user',preset='learner')
"""
        run(
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            volume + ":/app/data",
            "--entrypoint",
            "python",
            image,
            "-c",
            seed,
        )
        bootstrap = Path(__file__).resolve().parents[1] / "learner_bootstrap.py"
        output = run(
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "950:950",
            "-v",
            volume + ":/app/data",
            "-v",
            str(bootstrap) + ":/tmp/bootstrap.py:ro",
            "--entrypoint",
            "python",
            image,
            "/tmp/bootstrap.py",
            "--learner",
            "test-learner",
        )
        assert "accounts preserved" in output
        print("PASS: exact mounted bootstrap launch imports DeepTutor and preserves accounts")
        run(
            "docker",
            "network",
            "create",
            "--internal",
            "--label",
            "family-learning.test=learner-smoke",
            name,
        )
        args = [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--network",
            name,
            "--memory",
            "2g",
            "--cpus",
            "1.5",
            "--pids-limit",
            "512",
            "-v",
            volume + ":/app/data",
        ]
        for env in [
            "PUID=950",
            "PGID=950",
            "FAMILY_LEARNING_ENABLED=1",
            "FAMILY_LEARNING_LOCAL_ONLY=1",
            "FAMILY_LEARNER_HOST=1",
            "FAMILY_LEARNING_ORIGIN=http://localhost:3785",
        ]:
            args += ["-e", env]
        run(*args, image)
        probe = """import json,urllib.request,urllib.error,http.cookiejar
base='http://127.0.0.1:3782'
jar=http.cookiejar.CookieJar();client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def call(path,body=None):
 req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','Origin':'http://localhost:3785'})
 try:
  with client.open(req,timeout=5) as r:return r.status,json.loads(r.read())
 except urllib.error.HTTPError as e:return e.code,None
assert call('/api/auth/status')[0]==200
assert call('/api/auth/login',{'username':'test-parent','password':'synthetic-test-password'})[0]==200
assert call('/api/family-learning')[1]['learner_host'] is True
assert call('/api/settings')[0]==200
assert call('/api/family-learning/authoring/models')[0]==200
course={'title':'Test','subject':'Math','objectives':['Count'],'lessons':[{'id':'one','title':'One','explanation':'One item','question':'How many?','kind':'number','answer':'1','hints':['Count one'],'success':'Yes'}]}
status,saved=call('/api/family-learning/imports/publish',{'format':'family-learning-course','version':1,'course':course})
assert status==200,(status,saved)
assert call('/api/family-learning/courses/'+saved['id']+'/export')[1]['course']==course
assert call('/api/auth/login',{'username':'test-learner','password':'synthetic-test-password'})[0]==200
assert call('/api/family-learning/courses/'+saved['id']+'/export')[0]==403
assert call('/api/settings')[0]==403
assert call('/api/family-learning')[1]['courses']==[]
print('PASS: remapped service UID; parent import/export; no automatic assignment; parent dashboard allowed; learner AI routes blocked')
"""
        for attempt in range(90):
            check = subprocess.run(
                ["docker", "exec", name, "python", "-c", probe], capture_output=True, text=True
            )
            if check.returncode == 0:
                print(check.stdout.strip())
                break
            time.sleep(1)
        else:
            raise RuntimeError("Fresh learner-image acceptance failed: " + check.stderr[-1200:])
        details = json.loads(run("docker", "inspect", name))[0]
        assert not details["HostConfig"]["PortBindings"]
        assert not any(
            mount.get("Destination") == "/var/run/docker.sock" for mount in details["Mounts"]
        )
        assert json.loads(run("docker", "network", "inspect", name))[0]["Internal"]
        print(
            "PASS: internal network, no published ports, no Docker socket or household data mounted"
        )
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        subprocess.run(["docker", "network", "rm", name], capture_output=True)
        subprocess.run(["docker", "volume", "rm", volume], capture_output=True)


if __name__ == "__main__":
    if os.environ.get("FAMILY_LEARNER_IMAGE_TEST") != "1":
        raise SystemExit("Set FAMILY_LEARNER_IMAGE_TEST=1 to run the disposable image acceptance")
    main()
