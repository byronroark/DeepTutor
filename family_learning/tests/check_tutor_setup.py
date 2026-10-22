import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'learning'))
import setup_gateway


class SetupTests(unittest.TestCase):
    def test_repeat_setup_preserves_token_and_never_enables_traffic(self):
        with tempfile.TemporaryDirectory() as folder:
            home = pathlib.Path(folder)
            with patch.object(setup_gateway.Path, 'home', return_value=home), \
                    patch.object(sys, 'argv', ['setup_gateway.py']), \
                    patch.object(setup_gateway.subprocess, 'run') as command:
                setup_gateway.main()
                token = (home / '.config/family-tutor/gateway-token').read_text()
                setup_gateway.main()
                self.assertEqual((home / '.config/family-tutor/gateway-token').read_text(), token)
                self.assertFalse((home / '.config/family-tutor/child-api-ready').exists())
                self.assertFalse((home / '.config/family-tutor/openai-api-key').exists())
                for call in command.call_args_list:
                    self.assertEqual(call.args[0], ['/usr/bin/systemctl', '--user', 'daemon-reload'])
                self.assertEqual((home / '.config/family-tutor/gateway-token').stat().st_mode & 0o777, 0o600)

    def test_private_writer_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            target = root / 'untouched'
            target.write_text('keep')
            link = root / 'linked'
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                setup_gateway.save_private(link, 'replace')
            self.assertEqual(target.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
