# CineAI — AI-Based Personalized Movie Recommendation Portal

A cinematic Flask movie recommendation portal using TF-IDF + cosine similarity, user ratings, favorites and viewing history.

## Run locally

```powershell
python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Demo admin

- Email: `admin@example.com`
- Password: `admin123`

Change these before a real deployment.

## Deploy on Render

1. Push this folder to GitHub.
2. Create a new Web Service on Render and connect the repository.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Add environment variable `SECRET_KEY` with a long random value.

### Important database note

This version keeps SQLite so it is simple for a college project and local development. A hosted SQLite database can be lost if the hosting filesystem is replaced. For a production-grade deployment with persistent user data, move the database layer to PostgreSQL.

## Design

The UI is a custom dark cinematic interface inspired by modern streaming-platform layouts: large hero artwork, poster grids, editorial sections, AI recommendation banner, dashboard cards and responsive mobile layouts.
