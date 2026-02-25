from __future__ import annotations

import json
import math
import os
import random
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from pypdf import PdfReader


BASE_DIR = Path(__file__).resolve().parent
TEXT_PROFILE_DIR = BASE_DIR / "job_profiles"
PDF_PROFILE_DIR = BASE_DIR / "job_profiles_pdf"
LEADERBOARD_FILE = BASE_DIR / "leaderboard.json"
LIKERT_MIN = 1
LIKERT_MAX = 5
ROLE_COUNT = 7
QUESTIONS_PER_ROLE = 5
MIN_STATEMENTS_PER_ROLE = 7
LEADERBOARD_LIMIT = 50
CHUNK_SIZE = 700
CHUNK_OVERLAP = 120


@dataclass
class JobProfile:
    key: str
    role: str
    description: str
    fun_fact: str
    statements: list[str]


@dataclass
class RAGChunk:
    source: str
    text: str
    tokens: Counter[str]


class RAGIndex:
    def __init__(self, chunks: list[RAGChunk]) -> None:
        self.chunks = chunks
        self.doc_count = len(chunks)
        self.df: Counter[str] = Counter()
        for chunk in chunks:
            self.df.update(set(chunk.tokens.keys()))

    @staticmethod
    def tokenize(text: str) -> list[str]:
        return re.findall(r"[a-zA-Z][a-zA-Z0-9-]{1,}", text.lower())

    @classmethod
    def from_documents(cls, docs: list[tuple[str, str]]) -> "RAGIndex":
        chunks: list[RAGChunk] = []
        for source, text in docs:
            for chunk_text in chunk_text_with_overlap(text):
                tokens = Counter(cls.tokenize(chunk_text))
                if tokens:
                    chunks.append(RAGChunk(source=source, text=chunk_text, tokens=tokens))
        return cls(chunks)

    def retrieve(self, query: str, top_k: int = 4) -> list[RAGChunk]:
        query_tokens = Counter(self.tokenize(query))
        if not query_tokens or not self.chunks:
            return []

        scored: list[tuple[float, RAGChunk]] = []
        for chunk in self.chunks:
            score = self._score(query_tokens, chunk)
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]

    def _score(self, query_tokens: Counter[str], chunk: RAGChunk) -> float:
        score = 0.0
        norm_query = math.sqrt(sum(value * value for value in query_tokens.values())) or 1.0
        norm_chunk = math.sqrt(sum(value * value for value in chunk.tokens.values())) or 1.0

        for token, q_tf in query_tokens.items():
            c_tf = chunk.tokens.get(token, 0)
            if not c_tf:
                continue
            df = self.df.get(token, 1)
            idf = math.log((self.doc_count + 1) / df)
            score += (q_tf * c_tf) * (1 + idf)

        return score / (norm_query * norm_chunk)


class CopilotQuestionGenerator:
    """Generate Likert statements via GitHub Models (Copilot token) with local fallback."""

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
        system_prompt = "You create psychometric-style Likert statements for career fit assessments. Return strict JSON only."
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
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
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
        parsed = json.loads(response.json()["choices"][0]["message"]["content"])
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

        topics: list[str] = []
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
        return [chunk.strip() for chunk in chunks if 5 <= len(chunk.split()) <= 20][:20]

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
    return JobProfile(key=file_path.stem, role=role, description=description, fun_fact=fun_fact, statements=statements)


def load_profiles() -> tuple[list[JobProfile], str]:
    generator = CopilotQuestionGenerator()

    pdf_files = sorted(PDF_PROFILE_DIR.glob("*.pdf")) if PDF_PROFILE_DIR.exists() else []
    if pdf_files:
        return [parse_pdf_profile(path, generator) for path in pdf_files], "pdf-copilot"

    text_files = sorted(TEXT_PROFILE_DIR.glob("*.txt")) if TEXT_PROFILE_DIR.exists() else []
    return [parse_text_profile(path) for path in text_files], "txt-static"


def validate_profiles(profiles: list[JobProfile]) -> None:
    if len(profiles) != ROLE_COUNT:
        raise ValueError(f"Exactly {ROLE_COUNT} job profile files are required.")
    for profile in profiles:
        if len(profile.statements) < MIN_STATEMENTS_PER_ROLE:
            raise ValueError(f"{profile.key} must contain at least {MIN_STATEMENTS_PER_ROLE} statements.")


def chunk_text_with_overlap(text: str) -> list[str]:
    clean = " ".join(text.split())
    if not clean:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = start + CHUNK_SIZE
        chunks.append(clean[start:end])
        if end >= len(clean):
            break
        start = max(0, end - CHUNK_OVERLAP)
    return chunks


def build_rag_documents(profiles: list[JobProfile], profile_source: str) -> list[tuple[str, str]]:
    docs: list[tuple[str, str]] = []
    if profile_source == "pdf-copilot" and PDF_PROFILE_DIR.exists():
        for path in sorted(PDF_PROFILE_DIR.glob("*.pdf")):
            docs.append((path.name, read_pdf_text(path)))
    if not docs:
        for profile in profiles:
            role_text = "\n".join(
                [
                    f"Role: {profile.role}",
                    f"Description: {profile.description}",
                    f"Fun Fact: {profile.fun_fact}",
                    "Statements:",
                    *profile.statements,
                ]
            )
            docs.append((f"{profile.role}.txt", role_text))
    return docs


def load_leaderboard() -> list[dict[str, str | int]]:
    if not LEADERBOARD_FILE.exists():
        return []
    try:
        data = json.loads(LEADERBOARD_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        return []
    return []


def save_leaderboard(entries: list[dict[str, str | int]]) -> None:
    LEADERBOARD_FILE.write_text(json.dumps(entries[:LEADERBOARD_LIMIT], indent=2), encoding="utf-8")


def add_leaderboard_entry(name: str, course: str, role: str, score: int, score_max: int) -> None:
    entries = load_leaderboard()
    percent = round((score / score_max) * 100) if score_max else 0
    entries.append(
        {
            "name": name,
            "course": course,
            "role": role,
            "score": score,
            "score_max": score_max,
            "percent": percent,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    entries.sort(key=lambda item: (item.get("percent", 0), item.get("score", 0)), reverse=True)
    save_leaderboard(entries)


def format_leaderboard_entries(entries: list[dict[str, str | int]], limit: int = 10) -> list[dict[str, str | int]]:
    formatted: list[dict[str, str | int]] = []
    for idx, entry in enumerate(entries[:limit], start=1):
        formatted.append(
            {
                "rank": idx,
                "name": entry.get("name", "Unknown"),
                "course": entry.get("course", ""),
                "role": entry.get("role", "N/A"),
                "score": entry.get("score", 0),
                "score_max": entry.get("score_max", QUESTIONS_PER_ROLE * LIKERT_MAX),
                "percent": entry.get("percent", 0),
            }
        )
    return formatted


def local_chatbot_answer(question: str, retrieved_chunks: list[RAGChunk]) -> str:
    q = question.lower()

    for profile in PROFILES:
        role_name = profile.role.lower()
        if role_name in q or profile.key.replace("_", " ") in q:
            return (
                f"For {profile.role}: {profile.description} "
                f"Fun fact: {profile.fun_fact}"
            )

    if "opentext" in q and ("philippines" in q or "ph" in q):
        if retrieved_chunks:
            snippet = retrieved_chunks[0].text[:260]
            return (
                "Based on the available role materials, here is related context: "
                f"{snippet}... For official OpenText Philippines details, please check OpenText's official site."
            )
        return (
            "OpenText Philippines is part of OpenText's global organization. "
            "For official office and hiring details, please refer to OpenText's official pages."
        )

    if retrieved_chunks:
        return f"I found this in your uploaded materials: {retrieved_chunks[0].text[:320]}..."

    return (
        "I can answer questions using your role PDF materials. Try asking about a specific role, "
        "skills, job fit, or OpenText Philippines."
    )


def generate_chatbot_reply(question: str) -> tuple[str, str, list[str]]:
    retrieved = RAG_KNOWLEDGE.retrieve(question, top_k=4)
    references = [chunk.source for chunk in retrieved]
    context = "\n\n".join([f"Source: {chunk.source}\n{chunk.text}" for chunk in retrieved])

    generator = CopilotQuestionGenerator()
    if generator.token and context:
        try:
            response = requests.post(
                generator.endpoint,
                headers={"Authorization": f"Bearer {generator.token}", "Content-Type": "application/json"},
                timeout=20,
                json={
                    "model": generator.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are an assistant for OpenText Role Quest. "
                                "Answer using only retrieved context. If context is insufficient, say so briefly. "
                                "Do not invent detailed facts."
                            ),
                        },
                        {"role": "system", "content": f"Retrieved context:\n{context[:9000]}"},
                        {"role": "user", "content": question[:1200]},
                    ],
                    "temperature": 0.3,
                },
            )
            response.raise_for_status()
            reply = response.json()["choices"][0]["message"]["content"].strip()
            if reply:
                return reply, "copilot-rag", references
        except Exception:
            pass

    return local_chatbot_answer(question, retrieved), "local-rag", references


PROFILES, PROFILE_SOURCE = load_profiles()
validate_profiles(PROFILES)
PROFILE_LOOKUP = {profile.key: profile for profile in PROFILES}
RAG_KNOWLEDGE = RAGIndex.from_documents(build_rag_documents(PROFILES, PROFILE_SOURCE))


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
    leaderboard = format_leaderboard_entries(load_leaderboard(), limit=5)
    return render_template("welcome.html", profile_source=PROFILE_SOURCE, leaderboard=leaderboard)


@app.get("/leaderboard")
def leaderboard():
    entries = format_leaderboard_entries(load_leaderboard(), limit=50)
    return render_template("leaderboard.html", entries=entries)


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
    best_role_score = role_scores[best_role_key]
    max_possible = QUESTIONS_PER_ROLE * LIKERT_MAX

    sorted_scores = sorted(
        [{"role": PROFILE_LOOKUP[key].role, "score": value} for key, value in role_scores.items()],
        key=lambda item: item["score"],
        reverse=True,
    )

    add_leaderboard_entry(name=name, course=course, role=best_role.role, score=best_role_score, score_max=max_possible)

    return render_template(
        "evaluation.html",
        name=name,
        course=course,
        role=best_role,
        scores=sorted_scores,
        best_score=best_role_score,
        best_score_max=max_possible,
        best_percent=round((best_role_score / max_possible) * 100),
    )


@app.post("/chatbot/ask")
def chatbot_ask():
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()
    if not question:
        return jsonify({"reply": "Please type a question first.", "source": "local"}), 400

    reply, source, references = generate_chatbot_reply(question)
    return jsonify({"reply": reply, "source": source, "references": references[:3]})


@app.post("/admin/reload-profiles")
def reload_profiles():
    global PROFILES, PROFILE_LOOKUP, PROFILE_SOURCE, RAG_KNOWLEDGE

    profiles, source = load_profiles()
    validate_profiles(profiles)
    PROFILES = profiles
    PROFILE_SOURCE = source
    PROFILE_LOOKUP = {profile.key: profile for profile in profiles}
    RAG_KNOWLEDGE = RAGIndex.from_documents(build_rag_documents(PROFILES, PROFILE_SOURCE))
    return redirect(url_for("welcome"))


if __name__ == "__main__":
    app.run(debug=True)
