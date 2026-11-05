"""Interpreter for the Python subset used by the classroom exercises."""

import ast
import math
import operator
import re


class SandboxError(Exception):
    pass


class ReturnValue(Exception):
    pass


class BreakLoop(Exception):
    pass


class ContinueLoop(Exception):
    pass


MAX_SOURCE = 16000
MAX_STRING = 2048
MAX_ITEMS = 256
MAX_INT_BITS = 256
MAX_OUTPUT = 8192
VALUE_TYPES = (str, int, float, bool, list, tuple, range, type(None))
TYPE_NAMES = {kind.__name__: kind for kind in VALUE_TYPES if kind is not type(None)}
BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}
COMPARE = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_, ast.IsNot: operator.is_not,
}
BUILTINS = {
    **TYPE_NAMES, "abs": abs, "len": len, "max": max, "min": min,
    "round": round, "sum": sum, "sorted": sorted, "repr": repr,
    "all": all, "any": any,
}
METHODS = {
    str: {"strip": str.strip, "upper": str.upper, "lower": str.lower,
          "startswith": str.startswith, "endswith": str.endswith,
          "count": str.count, "split": str.split, "join": str.join},
    list: {"pop": list.pop, "count": list.count, "index": list.index},
    tuple: {"count": tuple.count, "index": tuple.index},
}
METHOD_NAMES = {"append", "__name__"} | {
    name for methods in METHODS.values() for name in methods
}
NODES = {
    ast.Module, ast.Expr, ast.Constant, ast.Name, ast.Load, ast.Store,
    ast.Assign, ast.AugAssign, ast.List, ast.Tuple, ast.Subscript, ast.Slice,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.And, ast.Or, ast.Call, ast.keyword, ast.Attribute,
    ast.JoinedStr, ast.FormattedValue, ast.If, ast.For, ast.While,
    ast.Break, ast.Continue, ast.Pass, ast.FunctionDef, ast.arguments,
    ast.arg, ast.Return, *BINARY, *UNARY, *COMPARE,
}
BLOCKED_NAMES = {
    "open", "eval", "exec", "compile", "getattr", "setattr", "delattr",
    "globals", "locals", "vars", "dir", "help", "breakpoint",
    "js", "pyodide", "os", "sys", "subprocess",
}


def bounded(value):
    kind = type(value)
    if kind is int and value.bit_length() > MAX_INT_BITS:
        raise SandboxError("Слишком большое число.")
    if kind is float and not math.isfinite(value):
        raise SandboxError("Число должно быть конечным.")
    if kind is str and len(value) > MAX_STRING:
        raise SandboxError("Слишком длинная строка.")
    if kind in (list, tuple, range):
        if len(value) > MAX_ITEMS:
            raise SandboxError("Слишком много элементов.")
        if kind in (list, tuple):
            chars = 0
            for item in value:
                if type(item) not in (str, int, float, bool, type(None)):
                    raise SandboxError("В списках и кортежах используй простые значения.")
                bounded(item)
                if type(item) is str:
                    chars += len(item)
            if chars > 2 * MAX_STRING:
                raise SandboxError("Слишком много текста в списке.")
    if kind not in VALUE_TYPES and not (kind is type and value in VALUE_TYPES):
        raise SandboxError("Этот тип данных недоступен в практикуме.")
    return value


def parse_submission(code):
    if len(code) > MAX_SOURCE:
        raise SandboxError("Решение слишком длинное.")
    tree = ast.parse(code, filename="solution.py")
    stack = [(tree, 0)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > 1200 or depth > 40:
            raise SandboxError("Программа слишком сложная для практикума.")
        if type(node) not in NODES:
            raise SandboxError(f"Строка {getattr(node, 'lineno', '?')}. Эта команда недоступна в практикуме.")
        if isinstance(node, ast.Name) and (node.id.startswith("__") or node.id in BLOCKED_NAMES):
            raise SandboxError(f"Строка {node.lineno}. Это имя недоступно в практикуме.")
        if isinstance(node, ast.Attribute) and node.attr not in METHOD_NAMES:
            raise SandboxError(f"Строка {node.lineno}. Этот атрибут недоступен в практикуме.")
        if isinstance(node, ast.Constant):
            bounded(node.value)
        if isinstance(node, ast.FunctionDef):
            args = node.args
            if (node.decorator_list or node.returns or args.defaults or args.kw_defaults or
                args.vararg or args.kwarg or args.posonlyargs or args.kwonlyargs or
                node.name.startswith("_") or node.name in BLOCKED_NAMES or
                any(a.annotation or a.arg.startswith("__") or a.arg in BLOCKED_NAMES for a in args.args)):
                raise SandboxError(f"Строка {node.lineno}. Используй простое объявление функции с параметрами.")
        if isinstance(node, ast.keyword) and node.arg is None:
            raise SandboxError("Распаковка аргументов недоступна в практикуме.")
        stack.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    return tree


class Sandbox:
    def __init__(self, inputs):
        self.inputs = iter(inputs)
        self.globals = {}
        self.functions = {}
        self.output = []
        self.output_size = 0
        self.steps = 20000
        self.depth = 0

    def tick(self, cost=1):
        self.steps -= cost
        if self.steps < 0:
            raise SandboxError("Превышен лимит шагов. Проверь условие выхода из цикла.")

    def run(self, tree):
        try:
            self.block(tree.body, self.globals)
        except (BreakLoop, ContinueLoop):
            raise SandboxError("break и continue используются внутри цикла.") from None
        except ReturnValue:
            raise SandboxError("return используется внутри функции.") from None

    def block(self, statements, env):
        for node in statements:
            self.statement(node, env)

    def statement(self, node, env):
        self.tick()
        if isinstance(node, ast.Expr):
            self.expr(node.value, env)
        elif isinstance(node, ast.Assign):
            value = self.expr(node.value, env)
            for target in node.targets:
                self.assign(target, value, env)
        elif isinstance(node, ast.AugAssign):
            if not isinstance(node.target, ast.Name):
                raise SandboxError("Для сокращённого присваивания используй имя переменной.")
            value = self.binary(node.op, self.expr(node.target, env), self.expr(node.value, env))
            self.assign(node.target, value, env)
        elif isinstance(node, ast.If):
            self.block(node.body if self.expr(node.test, env) else node.orelse, env)
        elif isinstance(node, (ast.For, ast.While)):
            if isinstance(node, ast.For):
                values = self.sequence(self.expr(node.iter, env))
                iterations = iter(values)
            else:
                iterations = iter(lambda: bool(self.expr(node.test, env)), False)
            for value in iterations:
                self.tick()
                if isinstance(node, ast.For):
                    self.assign(node.target, value, env)
                try:
                    self.block(node.body, env)
                except ContinueLoop:
                    continue
                except BreakLoop:
                    break
            else:
                self.block(node.orelse, env)
        elif isinstance(node, ast.Break):
            raise BreakLoop()
        elif isinstance(node, ast.Continue):
            raise ContinueLoop()
        elif isinstance(node, ast.Return):
            raise ReturnValue(self.expr(node.value, env) if node.value else None)
        elif isinstance(node, ast.FunctionDef):
            if env is not self.globals:
                raise SandboxError("Объяви функцию в основном коде.")
            names = [arg.arg for arg in node.args.args]
            if len(names) != len(set(names)):
                raise SandboxError("Имена параметров функции должны различаться.")
            self.functions[node.name] = node
        elif not isinstance(node, ast.Pass):
            raise SandboxError("Эта команда недоступна в практикуме.")

    def assign(self, target, value, env):
        if isinstance(target, ast.Name):
            env[target.id] = value
        elif isinstance(target, ast.Subscript):
            seq = self.expr(target.value, env)
            if type(seq) is not list or isinstance(target.slice, ast.Slice):
                raise SandboxError("По индексу можно менять один элемент списка.")
            index = self.expr(target.slice, env)
            updated = seq.copy()
            updated[index] = value
            bounded(updated)
            seq[index] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            values = self.sequence(value)
            if len(target.elts) != len(values):
                raise ValueError("Количество значений не совпадает с количеством переменных.")
            for item, item_value in zip(target.elts, values):
                self.assign(item, item_value, env)
        else:
            raise SandboxError("Используй имя переменной или индекс списка.")

    def expr(self, node, env):
        self.tick()
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            if node.id in self.globals:
                return self.globals[node.id]
            if node.id in TYPE_NAMES:
                return TYPE_NAMES[node.id]
            raise NameError(f"Имя {node.id} не определено.")
        if isinstance(node, (ast.List, ast.Tuple)):
            if len(node.elts) > MAX_ITEMS:
                raise SandboxError("Слишком много элементов.")
            values = [self.expr(element, env) for element in node.elts]
            return bounded(values if isinstance(node, ast.List) else tuple(values))
        if isinstance(node, ast.Subscript):
            seq = self.sequence(self.expr(node.value, env))
            index = node.slice
            if isinstance(index, ast.Slice):
                index = slice(*(self.expr(i, env) if i else None for i in (index.lower, index.upper, index.step)))
            else:
                index = self.expr(index, env)
            return bounded(seq[index])
        if isinstance(node, ast.BinOp):
            return self.binary(node.op, self.expr(node.left, env), self.expr(node.right, env))
        if isinstance(node, ast.UnaryOp):
            return bounded(UNARY[type(node.op)](self.expr(node.operand, env)))
        if isinstance(node, ast.BoolOp):
            for value in node.values:
                current = self.expr(value, env)
                if bool(current) == isinstance(node.op, ast.Or):
                    break
            return current
        if isinstance(node, ast.Compare):
            left = self.expr(node.left, env)
            for op, right_node in zip(node.ops, node.comparators):
                right = self.expr(right_node, env)
                if not COMPARE[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return self.expr(node.body if self.expr(node.test, env) else node.orelse, env)
        if isinstance(node, ast.Call):
            return self.call(node, env)
        if isinstance(node, ast.Attribute):
            value = self.expr(node.value, env)
            if type(value) is type and value in VALUE_TYPES and node.attr == "__name__":
                return value.__name__
            raise SandboxError("Этот атрибут недоступен в практикуме.")
        if isinstance(node, ast.JoinedStr):
            text = ""
            for value in node.values:
                text = bounded(text + self.expr(value, env))
            return text
        if isinstance(node, ast.FormattedValue):
            value = self.expr(node.value, env)
            if node.conversion in (115, 114, 97):
                value = bounded({115: str, 114: repr, 97: ascii}[node.conversion](value))
            spec = self.expr(node.format_spec, env) if node.format_spec else ""
            if not re.fullmatch(r"[<>=^]?[+ -]?0?\d{0,2}(?:\.\d{1,2})?[bcdEeFfgGnosxX%]?", spec):
                raise SandboxError("Такой формат f-строки недоступен в практикуме.")
            return bounded(format(value, spec))
        raise SandboxError("Это выражение недоступно в практикуме.")

    @staticmethod
    def sequence(value):
        if type(value) not in (str, list, tuple, range):
            raise TypeError("Ожидалась строка, список, кортеж или range().")
        return value

    def binary(self, op, left, right):
        if isinstance(op, ast.Mod) and isinstance(left, str):
            raise SandboxError("Для подстановки в текст используй f-строку.")
        if isinstance(op, ast.Pow) and type(right) in (int, float, bool) and abs(right) > MAX_INT_BITS:
            raise SandboxError("Слишком большая степень.")
        if isinstance(op, ast.Mult):
            seq, n = (left, right) if type(left) in (str, list, tuple) else (right, left)
            if type(seq) in (str, list, tuple) and type(n) in (int, bool):
                limit = MAX_STRING if type(seq) is str else MAX_ITEMS
                if len(seq) * max(0, n) > limit:
                    raise SandboxError("Слишком много повторений.")
        return bounded(BINARY[type(op)](left, right))

    def call(self, node, env):
        args = [self.expr(arg, env) for arg in node.args]
        kwargs = {item.arg: self.expr(item.value, env) for item in node.keywords}
        if isinstance(node.func, ast.Attribute):
            if kwargs:
                raise SandboxError("Используй позиционные аргументы для методов.")
            return self.method(self.expr(node.func.value, env), node.func.attr, args)
        if not isinstance(node.func, ast.Name):
            raise SandboxError("Вызывай функции по имени.")
        name = node.func.id
        if name in self.functions:
            return self.call_function(name, args, kwargs)
        if name == "print":
            return self.print_values(args, kwargs)
        if name == "input" and len(args) <= 1 and not kwargs:
            try:
                return next(self.inputs)
            except StopIteration:
                raise EOFError("Программа запросила больше значений, чем есть в тесте.") from None
        if name == "type" and len(args) == 1 and not kwargs:
            return type(args[0])
        if name not in BUILTINS:
            raise SandboxError(f"Функция {name} недоступна в практикуме.")
        return bounded(BUILTINS[name](*args, **kwargs))

    def print_values(self, args, kwargs):
        if kwargs.keys() - {"sep", "end"}:
            raise SandboxError("Для print() доступны параметры sep и end.")
        sep, end = kwargs.get("sep", " "), kwargs.get("end", "\n")
        sep = " " if sep is None else sep
        end = "\n" if end is None else end
        if type(sep) is not str or type(end) is not str:
            raise TypeError("Параметры sep и end должны быть строками.")
        for index, value in enumerate(args):
            if index:
                self.write(sep)
            self.write(str(value))
        self.write(end)

    def write(self, text):
        self.output_size += len(text)
        if self.output_size > MAX_OUTPUT:
            raise SandboxError("Слишком много текста на экране.")
        self.output.append(text)

    def method(self, value, name, args):
        if type(value) is list and name == "append" and len(args) == 1:
            bounded(value + args)
            value.append(args[0])
            return None
        method = METHODS.get(type(value), {}).get(name)
        if method is None:
            raise SandboxError(f"Метод {name} недоступен для этого значения.")
        if name == "join" and len(args) == 1:
            items = self.sequence(args[0])
            if all(type(item) is str for item in items) and (
                sum(map(len, items)) + len(value) * max(0, len(items) - 1) > MAX_STRING
            ):
                raise SandboxError("Слишком длинная строка.")
        return bounded(method(value, *args))

    def call_function(self, name, args, kwargs=None):
        self.tick()
        if self.depth >= 24:
            raise SandboxError("Слишком много вложенных вызовов функций.")
        node = self.functions[name]
        names = [a.arg for a in node.args.args]
        kwargs = kwargs or {}
        env = dict(zip(names, args))
        if len(args) > len(names) or env.keys() & kwargs.keys() or (env.keys() | kwargs.keys()) != set(names):
            raise TypeError(f"Проверь аргументы функции {name}.")
        env.update(kwargs)
        self.depth += 1
        try:
            self.block(node.body, env)
        except ReturnValue as result:
            return result.args[0]
        except (BreakLoop, ContinueLoop):
            raise SandboxError("break и continue используются внутри цикла.") from None
        finally:
            self.depth -= 1
        return None

