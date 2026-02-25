# OpenText Role Quest (Python)

A simple game-like assessment tool for HR talent acquisition.

## Flow
1. Welcome page
2. Data entry page (Name + College Course)
3. Randomized Likert assessment page (35 questions total, 7 questions for each of 7 job positions)
4. Evaluation page with:
   - best-fit role output (`WOW! You are fit to be a <role>`)
   - short job description
   - fun fact about OpenText role
   - role compatibility score breakdown

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open: `http://127.0.0.1:5000`

## Job profile content
The app reads role information from text files in `job_profiles/`.
Each file must include:
- `Role`
- `Description`
- `Fun Fact`
- exactly 7 `LikertStatements`

This makes it easy to swap in Copilot-generated question sets and role descriptions.
