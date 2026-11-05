import json
from pathlib import Path

from grader import grade


def main():
    root = Path(__file__).resolve().parent
    topics = json.loads((root / "data/exercises.json").read_text(encoding="utf-8"))
    public_topics = []
    for topic in topics:
        tasks = []
        for exercise in topic["tasks"]:
            task = {key: exercise[key] for key in ("id", "prompt", "cases")}
            result = grade(task | {"code": exercise["solution"]})
            if result["status"] != "ok":
                raise RuntimeError(f"Задача {task['id']}: {result}")
            tasks.append(task)
        public_topics.append({**topic, "tasks": tasks})

    template = (root / "template.html").read_text(encoding="utf-8-sig")
    sandbox = (root / "sandbox.py").read_text(encoding="utf-8-sig")
    grader = (root / "grader.py").read_text(encoding="utf-8-sig")
    bundled_grader = sandbox + "\n" + grader.replace("from sandbox import Sandbox, SandboxError, parse_submission", "")
    html = template.replace("__TASK_DATA__", json.dumps(public_topics, ensure_ascii=False))
    html = html.replace("__GRADER_SOURCE__", json.dumps(bundled_grader, ensure_ascii=False))
    output = root / "dist/index.html"
    output.parent.mkdir(exist_ok=True)
    output.write_text(html, encoding="utf-8")
    print(f"Собран dist/index.html. Проверено решений: {sum(len(t['tasks']) for t in public_topics)}")


if __name__ == "__main__":
    main()

