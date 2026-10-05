import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen


@unittest.skipUnless(sys.platform == 'win32', 'Windows-only release')
class CliTests(unittest.TestCase):
    def test_startup_and_duplicate_instance(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
        with tempfile.TemporaryDirectory() as temp:
            command = [sys.executable, '-m', 'maibot_chatgpt_plan', '--port', str(port), '--data-dir', temp]
            child = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                ready = False
                for _ in range(50):
                    try:
                        with urlopen(f'http://127.0.0.1:{port}/health', timeout=1) as response:
                            self.assertFalse(json.load(response)['authorized'])
                        ready = True
                        break
                    except Exception:
                        if child.poll() is not None:
                            self.fail('Service exited before startup')
                        time.sleep(.2)
                self.assertTrue(ready)
                duplicate = subprocess.run(command, env=env, capture_output=True, text=True,
                    timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertNotEqual(duplicate.returncode, 0)
                self.assertIn('Another instance', duplicate.stderr)
            finally:
                child.terminate()
                child.communicate(timeout=10)
