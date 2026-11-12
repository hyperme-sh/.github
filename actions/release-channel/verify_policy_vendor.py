"""Compare bundled policy with its independently checked-out immutable source."""
import json
from pathlib import Path
import sys


def verify(source, destination):
    source,destination=Path(source),Path(destination)
    record=json.loads((destination/'SOURCE.json').read_text())
    if record['repository']!='hyperme-sh/spanopticon' or record['revision']!='43225361d5f421d3bbda2836b2911421da6d366a':
        raise ValueError('Unexpected policy source')
    if (destination/'__init__.py').read_bytes()!=b'':raise ValueError('Policy initializer must not execute code')
    for original,bundled in [('release/policy.py','policy.py'),('release/accepted.py','accepted.py'),('scripts/component_release.py','component_release.py'),
            ('release/preparation.py','preparation.py'),('release/installer.py','installer.py'),
            ('release/preparation_contract.py','preparation_contract.py'),
            ('release/preparation-vectors.json','preparation-vectors.json')]:
        expected=(source/original).read_text().replace('from release.policy import','from stable_policy.policy import').replace('from release.accepted import','from stable_policy.accepted import').replace('from release.preparation import','from stable_policy.preparation import').replace('from release.installer import','from stable_policy.installer import')
        if (destination/bundled).read_text()!=expected:raise ValueError('Bundled policy differs: '+bundled)


if __name__=='__main__':
    verify(sys.argv[1],Path(__file__).resolve().parent/'stable_policy')
    print('Bundled policy matches the immutable reviewed source')
