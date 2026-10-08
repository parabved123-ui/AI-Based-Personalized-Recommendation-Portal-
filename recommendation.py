import sqlite3
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DB = __import__('os').environ.get('DATABASE_PATH', __import__('os').path.join(__import__('os').path.dirname(__file__), 'database.db'))


def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def get_all_movies():
    conn = get_conn()
    rows = conn.execute('SELECT * FROM movies ORDER BY year DESC, title').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_movie(movie_id):
    conn = get_conn()
    row = conn.execute('SELECT * FROM movies WHERE id=?', (movie_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def search_movies(query):
    conn = get_conn()
    q = f'%{query}%'
    rows = conn.execute('''SELECT * FROM movies
        WHERE title LIKE ? OR genre LIKE ? OR director LIKE ? OR description LIKE ?
        ORDER BY year DESC, title''', (q, q, q, q)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _content_similarity(movies):
    df = pd.DataFrame(movies)
    if df.empty:
        return df, None
    df['content'] = (df['title'].fillna('') + ' ' + df['genre'].fillna('') + ' ' +
                     df['description'].fillna('') + ' ' + df['director'].fillna(''))
    vectorizer = TfidfVectorizer(stop_words='english', ngram_range=(1, 2))
    matrix = vectorizer.fit_transform(df['content'])
    return df, cosine_similarity(matrix)


def get_recommendations(rated_movies=None, favorite_ids=None, history_ids=None, limit=8):
    rated_movies = rated_movies or []
    favorite_ids = favorite_ids or []
    history_ids = history_ids or []
    movies = get_all_movies()
    if not movies:
        return []
    df, sim = _content_similarity(movies)
    id_to_index = {int(mid): i for i, mid in enumerate(df['id'])}
    scores = {int(m['id']): 0.0 for m in movies}
    counts = {int(m['id']): 0.0 for m in movies}
    for item in rated_movies:
        mid = int(item['movie_id'])
        if mid not in id_to_index: continue
        idx = id_to_index[mid]
        weight = max(0.2, float(item['rating']) / 5.0)
        for j, target_id in enumerate(df['id']):
            target_id = int(target_id)
            if target_id != mid:
                scores[target_id] += float(sim[idx][j]) * weight
                counts[target_id] += weight
    for mid in favorite_ids:
        mid = int(mid)
        if mid not in id_to_index: continue
        idx = id_to_index[mid]
        for j, target_id in enumerate(df['id']):
            target_id = int(target_id)
            if target_id != mid:
                scores[target_id] += float(sim[idx][j]) * 1.5
                counts[target_id] += 1.5
    for mid in history_ids[:10]:
        mid = int(mid)
        if mid not in id_to_index: continue
        idx = id_to_index[mid]
        for j, target_id in enumerate(df['id']):
            target_id = int(target_id)
            if target_id != mid:
                scores[target_id] += float(sim[idx][j]) * 0.4
                counts[target_id] += 0.4
    already_seen = {int(x['movie_id']) for x in rated_movies} | set(map(int, favorite_ids))
    ranked = []
    for movie in movies:
        mid = int(movie['id'])
        if mid in already_seen: continue
        score = scores[mid] / counts[mid] if counts[mid] else 0
        ranked.append((score, movie))
    ranked.sort(key=lambda x: (x[0], x[1].get('year') or 0), reverse=True)
    if max((x[0] for x in ranked), default=0) == 0:
        ranked = [(0, m) for m in movies if int(m['id']) not in already_seen]
    result = []
    for score, movie in ranked[:limit]:
        item = dict(movie)
        item['match'] = min(99, max(72, round(72 + score * 100))) if score else 78
        result.append(item)
    return result
