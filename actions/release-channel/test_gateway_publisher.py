"""Exercise the Gateway publisher's actual preflight before any registry work."""
from pathlib import Path
import subprocess
from textwrap import dedent
import unittest


class GatewayPublisherIdentityTest(unittest.TestCase):
    def test_only_the_original_gateway_repository_can_publish_from_main(self):
        action = Path(__file__).resolve().parents[1] / 'publish-gateway-runtime/action.yml'
        first_step = action.read_text().split('    - name: Require the trusted gateway main push\n', 1)[1]
        guard = dedent(first_step.split('      run: |\n', 1)[1].split('\n    - ', 1)[0])
        valid = {
            'GITHUB_REPOSITORY_ID': '1439103692',
            'GITHUB_WORKFLOW_REF': 'hyperme-sh/gateway/.github/workflows/package.yml@refs/heads/main',
            'GITHUB_EVENT_NAME': 'push',
            'GITHUB_REF': 'refs/heads/main',
        }
        for override in (
            {},
            {'GITHUB_REPOSITORY_ID': '42'},
            {'GITHUB_WORKFLOW_REF': 'hyperme-sh/hypermesh-gateway/.github/workflows/package.yml@refs/heads/main'},
            {'GITHUB_WORKFLOW_REF': 'hyperme-sh/gateway/.github/workflows/other.yml@refs/heads/main'},
            {'GITHUB_EVENT_NAME': 'pull_request'},
            {'GITHUB_REF': 'refs/heads/other'},
        ):
            with self.subTest(override=override):
                result = subprocess.run(
                    ['/bin/bash', '-e', '-c', guard], env=valid | override, check=False,
                )
                self.assertEqual(result.returncode == 0, not override)
