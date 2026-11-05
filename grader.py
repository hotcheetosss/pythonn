import ast
import json
import math
import re

from sandbox import Sandbox, SandboxError, parse_submission

NUM = r"(?<![\w.])[+-]?\d+(?:[.,]\d+)?(?![\w.])"

def norm(value):
    return " ".join(value.split()).casefold().rstrip(".!")

def numbers(value):
    return [float(match.replace(",", ".")) for match in re.findall(NUM, value)]

def numeric(actual, expected):
    result = numbers(actual)
    return bool(result) and math.isclose(result[-1], float(expected))

def structure(tree, task):
    nodes = list(ast.walk(tree))
    calls = [n for n in nodes if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    if task == "1.4":
        prints = [n for n in calls if n.func.id == "print"]
        if len(prints) != 1 or len(prints[0].args) != 3:
            return "Передай три слова как три аргумента одной команды print()."
    if task.startswith("5.") or task.startswith("6."):
        if not any(n.func.id == "input" for n in calls):
            return "Используй input(), чтобы прочитать данные."
    if task.startswith("6.") and not any(isinstance(n, (ast.If, ast.IfExp)) for n in nodes):
        return "Добавь условие if."
    if task.startswith("8.") or task == "9.5":
        if not any(isinstance(n, ast.For) for n in nodes):
            return "Используй цикл for."
    if task == "7.4" and not any(n.func.id == "len" for n in calls):
        return "Используй len() для подсчёта элементов."
    if task == "7.3" and not any(isinstance(n, ast.Subscript) and
        isinstance(n.slice, ast.UnaryOp) and isinstance(n.slice.op, ast.USub) and
        isinstance(n.slice.operand, ast.Constant) and n.slice.operand.value == 1 for n in nodes):
        return "Обратись к последнему элементу через индекс -1."
    ops = {"4.1": [ast.Mult], "4.2": [ast.Sub], "4.3": [ast.Div, ast.FloorDiv],
           "4.4": [ast.Add, ast.Mult], "4.5": [ast.Sub, ast.Div, ast.FloorDiv]}
    if task in ops:
        kinds = ops[task]
        if task in {"4.3", "4.5"}:
            found_div = any(isinstance(n, (ast.Div, ast.FloorDiv)) for n in nodes)
            if not found_div:
                return "Покажи вычисление доли с помощью деления."
            kinds = [ast.Sub] if task == "4.5" else []
        if any(not any(isinstance(n, kind) for n in nodes) for kind in kinds):
            return "Запиши вычисление в коде."
    return ""

def check(task, output, expected, inputs, env):
    text = output.strip()
    if task == "1.2":
        return any(char.isalpha() for char in text) and len(text.splitlines()) == 1
    if task == "2.1":
        return isinstance(env.get("name"), str) and bool(env["name"].strip()) and text == env["name"].strip()
    if task == "2.2":
        return all(isinstance(env.get(key), str) and env[key].strip() and env[key] in text
                   for key in ("city", "country")) and len(text.splitlines()) == 1
    if task == "2.3":
        return env.get("tickets") == 5 and numbers(text) == [2, 5]
    if task == "2.4":
        values = [v for key, v in env.items() if key != "__builtins__"]
        return (len(text.splitlines()) >= 2 and any(type(v) is int and v in numbers(text) for v in values)
                and any(type(v) is str and bool(v.strip()) and v in text for v in values))
    if task == "2.5":
        return env.get("tickets") == 7 and env.get("saved_tickets") == 3 and numbers(text) == [7, 3]
    if task in {"3.1", "3.2", "3.3", "3.4"}:
        wanted = {"3.1":["int"], "3.2":["float"], "3.3":["int", "str"], "3.4":["bool"]}[task]
        types = re.findall(r"\b(?:int|float|str|bool)\b", text)
        return types == wanted and (task != "3.4" or ("True" in text and env.get("available") is True))
    if task == "5.1":
        return inputs[0].casefold() in text.casefold() and any(
            c.isalpha() for c in text.casefold().replace(inputs[0].casefold(), "", 1))
    if task == "5.5":
        return numbers(text) == numbers(expected)
    if task == "6.5" and inputs and int(inputs[0]) <= 0:
        return bool(text) and any(word in norm(text) for word in (
            "ошиб", "некоррект", "неверн", "недопуст", "должн", "положит", "больше", "нельзя", "минимум", "invalid", "error"))
    if task in {"7.1", "7.5"}:
        try:
            result = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return False
        if task == "7.1":
            return isinstance(result, list) and len(result) == 3 and all(isinstance(x, str) and x.strip() for x in result)
        return result == [1500, 1800, 2500] and any(
            isinstance(v, list) and v == result for key, v in env.items() if key != "__builtins__")
    if task in {"6.1", "6.2"}:
        return norm(text) == norm(expected)
    if task.startswith("1."):
        return text == expected
    if task in {"8.1", "8.2", "8.4"}:
        return [line.strip() for line in text.splitlines() if line.strip()] == expected.splitlines()
    return numeric(text, expected)

FUNCTIONS = {
    "9.1": "greet", "9.2": "square", "9.3": "ticket_total",
    "9.4": "order_total", "9.5": "sum_prices",
}


def grade(payload):
    task, code, cases = payload["id"], payload["code"], payload["cases"]
    try:
        tree = parse_submission(code)
    except SyntaxError as exc:
        return {"status": "error", "detail": f"Строка {exc.lineno}: {exc.msg}"}
    except (SandboxError, RecursionError) as exc:
        return {"status": "blocked", "detail": str(exc)[:750]}
    hint = structure(tree, task)
    if hint:
        return {"status": "wrong", "passed": 0, "total": len(cases), "detail": hint}

    for i, (inputs, expected) in enumerate(cases):
        sandbox = Sandbox(inputs if task not in FUNCTIONS else [])
        try:
            sandbox.run(tree)
            if task in FUNCTIONS:
                name = FUNCTIONS[task]
                if name not in sandbox.functions:
                    return {"status": "wrong", "passed": 0, "total": len(cases),
                            "detail": f"Определи функцию {name} с помощью def."}
                args = [value.copy() if type(value) is list else value for value in inputs]
                actual = sandbox.call_function(name, args)
                if task == "9.1":
                    passed = (isinstance(actual, str) and inputs[0].casefold() in actual.casefold()
                              and any(c.isalpha() for c in actual.casefold().replace(inputs[0].casefold(), "", 1)))
                else:
                    passed = type(actual) in (int, float) and actual == expected
                observed = repr(actual)
            else:
                observed = "".join(sandbox.output).strip()
                passed = check(task, observed, expected, inputs, sandbox.globals)
                if next(sandbox.inputs, None) is not None:
                    passed = False
        except SandboxError as exc:
            return {"status": "blocked", "passed": i, "total": len(cases), "detail": str(exc)[:750]}
        except (ValueError, TypeError, NameError, IndexError, EOFError, ArithmeticError) as exc:
            return {"status": "error", "passed": i, "total": len(cases), "detail": f"{type(exc).__name__}: {exc}"[:750]}
        if not passed:
            return {"status": "wrong", "passed": i, "total": len(cases), "detail": f"Проверь результат теста {i + 1}.",
                    "inputs": inputs, "actual": observed[:900]}
    return {"status": "ok", "passed": len(cases), "total": len(cases)}



def grade_json(raw):
    return json.dumps(grade(json.loads(raw)), ensure_ascii=False)


