import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from deeptutor.family_learning.python_runner import PythonRunner, validate_code


class SyntaxTests(unittest.TestCase):
    def test_lesson_programs(self):
        for code in ['stars = 5\nprint(stars + 2)', 'for number in range(1, 6):\n print(number)', 'count = 0\nwhile count < 3:\n count += 1\nprint(count)']:
            validate_code(code)

    def test_out_of_scope_and_malformed_programs(self):
        for code in ['import os', 'open("/etc/passwd")', 'print.__globals__', '__import__("os")', 'print = 3', 'eval("1")', 'for x in :', 'print("x")' * 3000]:
            with self.assertRaises(ValueError, msg=code[:40]):
                validate_code(code)


@unittest.skipUnless(os.environ.get('FAMILY_PYTHON_LIVE_TEST') == '1', 'requires explicit disposable Docker acceptance')
class ContainerTests(unittest.TestCase):
    def setUp(self):
        self.runner = PythonRunner()

    def test_correct_loop_output(self):
        result = self.runner.run('for number in range(1, 6):\n print(number)')
        self.assertEqual(result.state, 'finished', result.output)
        self.assertEqual(result.output, '1\n2\n3\n4\n5\n')

    def test_isolation_without_relying_on_syntax_validation(self):
        result = self.runner._isolated('''import os, socket
print(os.getuid())
print(os.path.exists('/var/run/docker.sock'))
print(os.path.exists('/home/byron/.ssh'))
try:
 open('/etc/family-test', 'w').write('blocked')
 print('WRITE_ALLOWED')
except OSError:
 print('WRITE_BLOCKED')
s = socket.socket()
s.settimeout(1)
try:
 s.connect(('1.1.1.1', 443))
 print('NETWORK_ALLOWED')
except OSError:
 print('NETWORK_BLOCKED')
''')
        self.assertEqual(result.state, 'finished', result.output)
        self.assertEqual(result.output, '65534\nFalse\nFalse\nWRITE_BLOCKED\nNETWORK_BLOCKED\n')

    def test_output_exhaustion_is_bounded(self):
        result = self.runner.run('while True:\n print("x" * 1000)')
        self.assertEqual(result.state, 'output_limit')
        self.assertLessEqual(len(result.output.encode()), 16384)

    def test_infinite_loop_is_stopped(self):
        result = self.runner.run('while True:\n pass')
        self.assertIn(result.state, {'error', 'time_limit'})

    def test_memory_exhaustion_is_stopped(self):
        result = self.runner.run('text = "x" * 268435456\nprint(text)')
        self.assertEqual(result.state, 'error')

    def test_scratch_is_discarded_and_containers_removed(self):
        self.runner._isolated('open("/tmp/marker", "w").write("temporary")')
        result = self.runner._isolated('import os\nprint(os.path.exists("/tmp/marker"))')
        self.assertEqual(result.output, 'False\n')
        names = subprocess.check_output([self.runner.docker, 'ps', '-a', '--filter', 'name=family-python-', '--format', '{{.Names}}'], text=True)
        self.assertEqual(names.strip(), '')


if __name__ == '__main__':
    unittest.main()
