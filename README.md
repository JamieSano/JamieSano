# OpenText Role Quest (Python)

A game-like HR assessment tool that maps candidates to role fit using Likert-scale questions.

## Flow
1. Welcome page
2. Data entry page (Name + College Course)
3. Randomized Likert assessment page (35 questions total, 5 questions × 7 roles)
4. Evaluation page with:
   - best-fit role output (`WOW! You are fit to be a <role>`)
   - short job description
   - fun fact about OpenText role
   - role compatibility score breakdown
5. Leaderboard page with Name, Course, Role Fit, and score percentage

## Game-like features
- Neon card styling and arcade-like button interactions
- Sound effects for starting, selecting Likert answers, and moving to next question
- Persistent leaderboard (`leaderboard.json`) that records top role-match results
- Floating mascot chatbot with animated “Hi! Talk with me.” prompt for role/OpenText PH Q&A
- RAG-style chatbot retrieval over uploaded role PDFs for context-grounded answers
- Voice assistant features: microphone speech-to-text input and text-to-speech bot replies

## Dynamic question generation from PDFs (Copilot-ready)
The app supports **PDF role materials** in `job_profiles_pdf/`.

- If `job_profiles_pdf/` contains 7 PDFs, the app reads each PDF and dynamically generates at least 7 Likert statements per role.
- If `GITHUB_TOKEN`/`GH_TOKEN` is set, the app calls GitHub Models endpoint (Copilot-compatible flow) to generate statements.
- If token/API is unavailable, the app uses a local text-to-Likert fallback generator.

### Expected PDF structure (recommended)
For best results, begin each PDF with:
1. Role title
2. One-line role description
3. One-line fun fact
Then include detailed role responsibilities/skills.

## Static mode
If `job_profiles_pdf/` is not present, the app falls back to text profiles in `job_profiles/`.

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open: `http://127.0.0.1:5000`


## Deploy with GitHub (recommended)
This app is Flask-based, so **GitHub Pages is not suitable**. The simplest GitHub-driven deployment is:

1. Push this repo to GitHub.
2. Create a new web service in [Render](https://render.com/) and choose **Build and deploy from a Git repository**.
3. Select this repository.
4. Render will auto-detect `render.yaml` in this repo and use:
   - build: `pip install -r requirements.txt`
   - start: `gunicorn --bind 0.0.0.0:$PORT wsgi:app`
5. In Render environment variables, ensure `FLASK_SECRET_KEY` is present (Render can auto-generate from `render.yaml`).

After deploy, open the Render URL to run the assessment publicly.

## Streamlit deployment note
If you specifically need Streamlit Community Cloud, the app would need to be rewritten as a Streamlit UI (`streamlit_app.py`) because the current implementation is Flask + Jinja templates.

For now, use the GitHub + Render path above for production deployment with minimal changes.

## Optional environment variables
- `FLASK_SECRET_KEY`: secure session secret
- `GITHUB_TOKEN` or `GH_TOKEN`: enables Copilot/API-powered generation
- `COPILOT_MODELS_ENDPOINT`: override endpoint (default: `https://models.inference.ai.azure.com/chat/completions`)
- `COPILOT_MODEL`: model name (default: `gpt-4o-mini`)

## Notes
Use **Reload Question Bank** on the welcome page after replacing PDFs to regenerate questions.
