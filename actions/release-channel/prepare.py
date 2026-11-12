#!/usr/bin/env python3
"""Offline preparation entry point; cannot publish or alter release history."""
import argparse
import json
from pathlib import Path
from stable_policy.preparation import prepare


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('candidate', 'provenance', 'source-root'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--baseline-root', type=Path)
    parser.add_argument('--repository')
    args = parser.parse_args()
    print(json.dumps(prepare(args.candidate, args.provenance, args.source_root,
                            baseline_root=args.baseline_root, repository=args.repository), sort_keys=True))
