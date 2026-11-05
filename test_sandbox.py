import json
from pathlib import Path
import re
import unittest

from grader import grade

TEST_CASE = {"id": "1.1", "cases": [[[], "Привет, Python!"]]}
ATTACKS = {
    "file": "open('secret.txt').read()",
    "network bridge": "from js import fetch\nfetch('https://example.com')",
    "worker bridge": "import pyodide",
    "dynamic eval": "eval('40 + 2')",
    "dynamic exec": "exec('print(42)')",
    "reflection": "print((1).__class__.__mro__)",
    "format traversal": "print('{0.__class__}'.format(1))",
    "class body": "class X:\n    pass",
    "decorator": "@print\ndef x():\n    pass",
    "cycle": "x = []\nx.append(x)",
    "infinite loop": "while True:\n    pass",
    "recursion": "def f():\n    return f()\nf()",
    "large range": "list(range(1000000000))",
    "large string": "print('x' * 1000000000)",
    "large list": "print([0] * 1000000000)",
    "large power": "print(2 ** 1000000000)",
    "large format": "print(f'{42:999999999d}')",
    "large join": "print(('x' * 2000).join(['a'] * 200))",
    "large output": "for x in range(10):\n    print('x' * 2000)",
    "long source": "# " + "x" * 16000,
}


class SandboxTests(unittest.TestCase):
    def test_hostile_submissions(self):
        for name, code in ATTACKS.items():
            with self.subTest(name=name):
                self.assertEqual(grade(TEST_CASE | {"code": code})["status"], "blocked")

    def test_basic_alternative_solutions(self):
        examples = [
            ("3.1", "x = 12\nprint(type(x).__name__)", [[[], "int"]]),
            ("5.2", "n = int(input())\nprint(f'Итого {1500 * n:.0f}')", [[["3"], "4500"], [["5"], "7500"]]),
            ("7.1", "films = ['А', 'Б']\nfilms.append('В')\nprint(films)", [[[], None]]),
            ("8.3", "total = 0\nfor price in [1500, 900, 2000]:\n    total += price\nprint(total)", [[[], "4400"]]),
        ]
        for number, code, cases in examples:
            with self.subTest(number=number):
                self.assertEqual(grade({"id": number, "code": code, "cases": cases})["status"], "ok")

    def test_browser_bundle_uses_the_same_sandbox(self):
        html = (Path(__file__).parent / "dist/index.html").read_text(encoding="utf-8")
        source = json.loads(re.search(r"^const GRADER = (.*);$", html, re.MULTILINE)[1])
        namespace = {"__name__": "bundled_grader"}
        exec(compile(source, "bundled_grader", "exec"), namespace)
        for code, status in [(ATTACKS["network bridge"], "blocked"), ('print("Привет, Python!")', "ok")]:
            result = json.loads(namespace["grade_json"](json.dumps(TEST_CASE | {"code": code})))
            self.assertEqual(result["status"], status)


if __name__ == "__main__":
    unittest.main()
