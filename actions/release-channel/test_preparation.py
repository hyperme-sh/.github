import json
from pathlib import Path
import unittest
from stable_policy.preparation_contract import exercise


class PreparationVectorsTest(unittest.TestCase):
    pass


def make_vector_test(vector):
    def run(self):
        if vector['accepted']:
            self.assertIs(exercise(vector['case'])['publication_authorized'], False)
        else:
            with self.assertRaises(ValueError): exercise(vector['case'])
    return run


for vector in json.loads((Path(__file__).parent / 'stable_policy/preparation-vectors.json').read_text()):
    setattr(PreparationVectorsTest, 'test_' + vector['case'].replace('-', '_'), make_vector_test(vector))
