"""Compare bundled policy with its independently checked-out immutable source."""
import json
from pathlib import Path
import sys


def verify(source, destination):
    source,destination=Path(source),Path(destination)
    record=json.loads((destination/'SOURCE.json').read_text())
    if record['repository']!='hyperme-sh/spanopticon' or record['revision']!='60e605ff39923c61bccc6c732181f82e557be35a':
        raise ValueError('Unexpected policy source')
    if (destination/'__init__.py').read_bytes()!=b'':raise ValueError('Policy initializer must not execute code')
    for original,bundled in [('release/policy.py','policy.py'),('release/accepted.py','accepted.py'),('scripts/component_release.py','component_release.py')]:
        expected=(source/original).read_text().replace('from release.policy import','from stable_policy.policy import').replace('from release.accepted import','from stable_policy.accepted import')
        if (destination/bundled).read_text()!=expected:raise ValueError('Bundled policy differs: '+bundled)


if __name__=='__main__':
    verify(sys.argv[1],Path(__file__).resolve().parent/'stable_policy')
    print('Bundled policy matches the immutable reviewed source')
