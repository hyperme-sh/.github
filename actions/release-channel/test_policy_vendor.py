import json
from pathlib import Path
import tempfile
import unittest
import shutil
from verify_policy_vendor import verify


class VendorTest(unittest.TestCase):
    def test_tampered_policy_and_vectors_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / 'vendor'
            shutil.copytree(Path(__file__).parent / 'stable_policy', destination)
            source = root / 'source'
            for name in ('policy.py', 'accepted.py', 'preparation.py', 'installer.py',
                         'preparation_contract.py', 'preparation-vectors.json', 'component_release.py'):
                target = source / ('scripts' if name == 'component_release.py' else 'release') / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text((destination / name).read_text().replace('from stable_policy.', 'from release.'))
            verify(source, destination)
            for name in ('policy.py', 'accepted.py', 'preparation.py', 'installer.py',
                         'preparation_contract.py', 'preparation-vectors.json', 'component_release.py', '__init__.py'):
                path = destination / name
                original = path.read_bytes()
                path.write_bytes(original + b'\n# tampered\n')
                with self.subTest(name=name), self.assertRaises(ValueError): verify(source, destination)
                path.write_bytes(original)
            record = json.loads((destination / 'SOURCE.json').read_text())
            record['revision'] = '0' * 40
            (destination / 'SOURCE.json').write_text(json.dumps(record))
            with self.assertRaises(ValueError): verify(source, destination)
