from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path

import requests
from flask import Flask, redirect, render_template, request, session, url_for
from pypdf import PdfReader


BASE_DIR = Path(__file__).resolve().parent
TEXT_PROFILE_DIR = BASE_DIR / "job_profiles"
PDF_PROFILE_DIR = BASE_DIR / "job_profiles_pdf"
LIKERT_MIN = 1
LIKERT_MAX = 5
ROLE_COUNT = 7
QUESTIONS_PER_ROLE = 5
MIN_STATEMENTS_PER_ROLE = 7


@dataclass
class JobProfile:
    key: str
    role: str
    description: str
    fun_fact: str
    statements: list[str]


class CopilotQuestionGenerator:
    """Generates Likert statements from role material using GitHub Models (Copilot token), with local fallback."""

    def __init__(self) -> None:
        self.token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        self.endpoint = os.getenv("COPILOT_MODELS_ENDPOINT", "https://models.inference.ai.azure.com/chat/completions")
        self.model = os.getenv("COPILOT_MODEL", "gpt-4o-mini")

    def generate(self, role: str, description: str, material: str, count: int = 7) -> tuple[list[str], str]:
        if self.token:
            try:
                statements = self._generate_via_api(role=role, description=description, material=material, count=count)
                if len(statements) == count:
                    return statements, "copilot"
            except Exception:
                pass
        return self._generate_locally(role=role, description=description, material=material, count=count), "local-fallback"

    def _generate_via_api(self, role: str, description: str, material: str, count: int) -> list[str]:
        system_prompt = (
            "You create psychometric-style Likert statements for career fit assessments. "
            "Return strict JSON only."
        )
        user_prompt = f"""
Create exactly {count} first-person Likert statements for a {role} role.
Use the role material and description below.
Rules:
- each statement should be 8-18 words
- use clear, work-relevant wording
- avoid duplicates
- no numbering, no markdown
- output JSON object with a single key: statements (array of strings)

Role: {role}
Description: {description}
Material:\n{material[:8000]}
"""
        response = requests.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            timeout=25,
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        statements = [self._normalize_statement(item) for item in parsed.get("statements", [])]
        return [item for item in statements if item][:count]

    def _generate_locally(self, role: str, description: str, material: str, count: int) -> list[str]:
        seed_sentences = self._extract_candidate_sentences(material)
        if not seed_sentences:
            seed_sentences = self._extract_candidate_sentences(description)

        templates = [
            "I enjoy {topic}.",
            "I am motivated to improve {topic}.",
            "I feel confident when working on {topic}.",
            "I stay curious about {topic}.",
            "I can communicate clearly about {topic}.",
            "I am patient while handling {topic}.",
            "I like collaborating with others on {topic}.",
            "I enjoy solving problems involving {topic}.",
            "I pay attention to details in {topic}.",
        ]

        topics = []
        for sentence in seed_sentences:
            cleaned = re.sub(r"[^a-zA-Z0-9\s-]", "", sentence).strip()
            if 4 <= len(cleaned.split()) <= 12:
                topics.append(cleaned.lower())

        if not topics:
            topics = [f"key tasks for {role.lower()}"]

        statements: list[str] = []
        for idx in range(count):
            topic = topics[idx % len(topics)]
            template = templates[idx % len(templates)]
            statements.append(self._normalize_statement(template.format(topic=topic)))

        return statements[:count]

    @staticmethod
    def _extract_candidate_sentences(text: str) -> list[str]:
        chunks = re.split(r"[\n\r\.\?!;]+", text)
        filtered = [chunk.strip() for chunk in chunks if 5 <= len(chunk.split()) <= 20]
        return filtered[:20]

    @staticmethod
    def _normalize_statement(statement: str) -> str:
        normalized = " ".join(statement.strip().split())
        if not normalized:
            return ""
        if not normalized.endswith("."):
            normalized += "."
        return normalized[0].upper() + normalized[1:]


def read_pdf_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_text_profile(file_path: Path) -> JobProfile:
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

    if len(statements) < MIN_STATEMENTS_PER_ROLE:
        raise ValueError(f"{file_path.name} must contain at least {MIN_STATEMENTS_PER_ROLE} Likert statements.")

    return JobProfile(
        key=file_path.stem,
        role=data["Role"],
        description=data["Description"],
        fun_fact=data["Fun Fact"],
        statements=statements,
    )


def parse_pdf_profile(file_path: Path, generator: CopilotQuestionGenerator) -> JobProfile:
    text = read_pdf_text(file_path)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    role = lines[0] if lines else file_path.stem.replace("_", " ").title()
    description = lines[1] if len(lines) > 1 else f"{role} contributes to enterprise outcomes at OpenText."
    fun_fact = lines[2] if len(lines) > 2 else f"OpenText teams rely on {role.lower()} skills for customer impact."

    statements, _source = generator.generate(role=role, description=description, material=text, count=MIN_STATEMENTS_PER_ROLE)
    return JobProfile(
        key=file_path.stem,
        role=role,
        description=description,
        fun_fact=fun_fact,
        statements=statements,
    )


def load_profiles() -> tuple[list[JobProfile], str]:
    generator = CopilotQuestionGenerator()

    pdf_files = sorted(PDF_PROFILE_DIR.glob("*.pdf")) if PDF_PROFILE_DIR.exists() else []
    if pdf_files:
        profiles = [parse_pdf_profile(path, generator) for path in pdf_files]
        return profiles, "pdf-copilot"

    text_files = sorted(TEXT_PROFILE_DIR.glob("*.txt")) if TEXT_PROFILE_DIR.exists() else []
    profiles = [parse_text_profile(path) for path in text_files]
    return profiles, "txt-static"


def validate_profiles(profiles: list[JobProfile]) -> None:
    if len(profiles) != ROLE_COUNT:
        raise ValueError(f"Exactly {ROLE_COUNT} job profile files are required.")
    for profile in profiles:
        if len(profile.statements) < MIN_STATEMENTS_PER_ROLE:
            raise ValueError(f"{profile.key} must contain at least {MIN_STATEMENTS_PER_ROLE} statements.")


PROFILES, PROFILE_SOURCE = load_profiles()
validate_profiles(PROFILES)
PROFILE_LOOKUP = {profile.key: profile for profile in PROFILES}


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "replace-this-with-a-secure-secret")


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
    return render_template("welcome.html", profile_source=PROFILE_SOURCE)


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


@app.post("/admin/reload-profiles")
def reload_profiles():
    global PROFILES, PROFILE_LOOKUP, PROFILE_SOURCE

    profiles, source = load_profiles()
    validate_profiles(profiles)
    PROFILES = profiles
    PROFILE_SOURCE = source
    PROFILE_LOOKUP = {profile.key: profile for profile in profiles}
    return redirect(url_for("welcome"))


if __name__ == "__main__":
    app.run(debug=True)
