from __future__ import annotations

import random
from pathlib import Path
from dataclasses import dataclass

from flask import Flask, redirect, render_template, request, session, url_for


BASE_DIR = Path(__file__).resolve().parent
PROFILE_DIR = BASE_DIR / "job_profiles"
LIKERT_MIN = 1
LIKERT_MAX = 5


@dataclass
class JobProfile:
    key: str
    role: str
    description: str
    fun_fact: str
    statements: list[str]


def load_profiles() -> list[JobProfile]:
    profiles: list[JobProfile] = []
    for file_path in sorted(PROFILE_DIR.glob("*.txt")):
        raw_lines = [line.strip() for line in file_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        data: dict[str, str] = {}
        statements: list[str] = []
        in_statements = False

        for line in raw_lines:
            if line == "LikertStatements:":
                in_statements = True
                continue

            if in_statements and line.startswith("- "):
                statements.append(line[2:])
            elif not in_statements and ": " in line:
                key, value = line.split(": ", 1)
                data[key] = value

        if len(statements) != 7:
            raise ValueError(f"{file_path.name} must contain exactly 7 Likert statements.")

        profiles.append(
            JobProfile(
                key=file_path.stem,
                role=data["Role"],
                description=data["Description"],
                fun_fact=data["Fun Fact"],
                statements=statements,
            )
        )

    if len(profiles) != 7:
        raise ValueError("Exactly 7 job profile files are required in job_profiles/.")

    return profiles


PROFILES = load_profiles()
PROFILE_LOOKUP = {profile.key: profile for profile in PROFILES}
QUESTIONS_PER_ROLE = 5



app = Flask(__name__)
app.secret_key = "replace-this-with-a-secure-secret"


def get_question_sequence() -> list[dict[str, str | int]]:
    selected: list[dict[str, str | int]] = []
    for profile in PROFILES:
        statement_indexes = random.sample(range(len(profile.statements)), QUESTIONS_PER_ROLE)
        for statement_index in statement_indexes:
            selected.append({"role_key": profile.key, "statement_index": statement_index})

    random.shuffle(selected)
    return selected


@app.get("/")
def welcome():
    session.clear()
    return render_template("welcome.html")


@app.get("/start")
def start():
    return render_template("start.html")


@app.post("/start")
def submit_start():
    name = request.form.get("name", "").strip()
    course = request.form.get("course", "").strip()

    if not name or not course:
        return render_template("start.html", error="Please enter both your name and college course.", name=name, course=course)

    session["name"] = name
    session["course"] = course
    session["question_sequence"] = get_question_sequence()
    session["answers"] = []
    return redirect(url_for("question", index=0))


@app.get("/question/<int:index>")
def question(index: int):
    sequence = session.get("question_sequence")
    if not sequence:
        return redirect(url_for("start"))

    if index >= len(sequence):
        return redirect(url_for("evaluate"))

    question_meta = sequence[index]
    profile = PROFILE_LOOKUP[question_meta["role_key"]]
    question_item = {"statement": profile.statements[question_meta["statement_index"]]}
    progress = int((index / len(sequence)) * 100)
    return render_template(
        "question.html",
        question=question_item,
        index=index,
        total=len(sequence),
        progress=progress,
        likert_values=range(LIKERT_MIN, LIKERT_MAX + 1),
    )


@app.post("/question/<int:index>")
def submit_question(index: int):
    sequence = session.get("question_sequence")
    answers = session.get("answers", [])

    if not sequence or index >= len(sequence):
        return redirect(url_for("start"))

    selected = request.form.get("score")
    if selected is None:
        return redirect(url_for("question", index=index))

    score = int(selected)
    if score < LIKERT_MIN or score > LIKERT_MAX:
        return redirect(url_for("question", index=index))

    if len(answers) == index:
        answers.append(score)
    elif len(answers) > index:
        answers[index] = score
    else:
        return redirect(url_for("question", index=index))

    session["answers"] = answers
    return redirect(url_for("question", index=index + 1))


@app.get("/evaluate")
def evaluate():
    sequence = session.get("question_sequence")
    answers = session.get("answers")
    name = session.get("name")
    course = session.get("course")

    if not all([sequence, answers, name, course]) or len(answers) != len(sequence):
        return redirect(url_for("start"))

    role_scores: dict[str, int] = {profile.key: 0 for profile in PROFILES}
    for question_meta, score in zip(sequence, answers):
        role_scores[question_meta["role_key"]] += score

    best_role_key = max(role_scores, key=role_scores.get)
    best_role = PROFILE_LOOKUP[best_role_key]

    sorted_scores = sorted(
        [{"role": PROFILE_LOOKUP[key].role, "score": value} for key, value in role_scores.items()],
        key=lambda item: item["score"],
        reverse=True,
    )

    return render_template(
        "evaluation.html",
        name=name,
        course=course,
        role=best_role,
        scores=sorted_scores,
    )


if __name__ == "__main__":
    app.run(debug=True)
