import os
import sqlite3
import csv
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
from recommendation import get_recommendations, get_movie, search_movies, get_all_movies

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-change-this-secret-key')
DB = os.environ.get('DATABASE_PATH', os.path.join(os.path.dirname(__file__), 'database.db'))


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db():
    conn = db()
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS movies(
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        genre TEXT NOT NULL,
        description TEXT,
        director TEXT,
        year INTEGER,
        poster TEXT,
        backdrop TEXT
    );
    CREATE TABLE IF NOT EXISTS ratings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        movie_id INTEGER NOT NULL,
        rating REAL NOT NULL CHECK(rating >= 1 AND rating <= 5),
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id,movie_id),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(movie_id) REFERENCES movies(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS favorites(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        movie_id INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id,movie_id),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(movie_id) REFERENCES movies(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        movie_id INTEGER NOT NULL,
        viewed_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(movie_id) REFERENCES movies(id) ON DELETE CASCADE
    );
    ''')

    # Backwards-compatible upgrade for the old database.
    cols = {r['name'] for r in conn.execute('PRAGMA table_info(movies)').fetchall()}
    if 'backdrop' not in cols:
        conn.execute('ALTER TABLE movies ADD COLUMN backdrop TEXT')

    if conn.execute('SELECT COUNT(*) FROM movies').fetchone()[0] == 0:
        with open(os.path.join(os.path.dirname(__file__), 'dataset', 'movies.csv'), newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                conn.execute('''INSERT INTO movies
                    (id,title,genre,description,director,year,poster,backdrop)
                    VALUES(?,?,?,?,?,?,?,?)''',
                    (int(row['id']), row['title'], row['genre'], row['description'],
                     row['director'], int(row['year']), row['poster'], row.get('backdrop', '')))
    else:
        # Add the richer poster/backdrop URLs from the current CSV when available.
        with open(os.path.join(os.path.dirname(__file__), 'dataset', 'movies.csv'), newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                conn.execute('UPDATE movies SET poster=?, backdrop=? WHERE id=?',
                             (row['poster'], row.get('backdrop', ''), int(row['id'])))

    if not conn.execute('SELECT id FROM users WHERE email=?', ('admin@example.com',)).fetchone():
        conn.execute('INSERT INTO users(name,email,password,is_admin) VALUES(?,?,?,1)',
                     ('Administrator', 'admin@example.com', generate_password_hash('admin123')))
    conn.commit()
    conn.close()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user' not in session:
            flash('Please log in first.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user' not in session or not session['user']['is_admin']:
            abort(403)
        return f(*args, **kwargs)
    return wrapper


@app.context_processor
def common():
    return {'current_user': session.get('user')}


def movie_groups(movies):
    return {
        'featured': movies[:5],
        'trending': sorted(movies, key=lambda m: (m.get('year') or 0), reverse=True)[:8],
        'top_rated': movies[:8],
        'action': [m for m in movies if 'Action' in (m.get('genre') or '')][:8],
        'sci_fi': [m for m in movies if 'Sci-Fi' in (m.get('genre') or '')][:8],
    }


@app.route('/')
def home():
    q = request.args.get('q', '').strip()
    all_movies = get_all_movies()
    movies = search_movies(q) if q else all_movies[:12]
    groups = movie_groups(all_movies)
    featured = groups['featured'][0] if groups['featured'] else None
    return render_template('index.html', movies=movies, query=q, groups=groups, featured=featured)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if not name or not email or len(password) < 6:
            flash('Enter a name, valid email and password of at least 6 characters.', 'danger')
            return redirect(url_for('register'))
        conn = db()
        try:
            conn.execute('INSERT INTO users(name,email,password) VALUES(?,?,?)',
                         (name, email, generate_password_hash(password)))
            conn.commit()
            flash('Account created. Welcome to CineAI.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already registered.', 'danger')
        finally:
            conn.close()
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        conn = db()
        user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user'] = dict(id=user['id'], name=user['name'], email=user['email'], is_admin=user['is_admin'])
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))


@app.route('/dashboard')
@login_required
def dashboard():
    uid = session['user']['id']
    conn = db()
    ratings = conn.execute('SELECT movie_id,rating FROM ratings WHERE user_id=?', (uid,)).fetchall()
    favs = conn.execute('SELECT m.* FROM favorites f JOIN movies m ON m.id=f.movie_id WHERE f.user_id=? ORDER BY f.created_at DESC', (uid,)).fetchall()
    hist = conn.execute('SELECT m.*,h.viewed_at FROM history h JOIN movies m ON m.id=h.movie_id WHERE h.user_id=? ORDER BY h.viewed_at DESC LIMIT 10', (uid,)).fetchall()
    stats = {
        'ratings': len(ratings),
        'favorites': conn.execute('SELECT COUNT(*) FROM favorites WHERE user_id=?', (uid,)).fetchone()[0],
        'watched': conn.execute('SELECT COUNT(DISTINCT movie_id) FROM history WHERE user_id=?', (uid,)).fetchone()[0],
    }
    conn.close()
    recs = get_recommendations(
        [{'movie_id': r['movie_id'], 'rating': r['rating']} for r in ratings],
        [r['movie_id'] for r in favs],
        [r['movie_id'] for r in hist]
    )
    return render_template('dashboard.html', recommendations=recs, favorites=favs, history=hist, rating_count=len(ratings), stats=stats)


@app.route('/movie/<int:movie_id>', methods=['GET', 'POST'])
def movie_detail(movie_id):
    movie = get_movie(movie_id)
    if not movie:
        abort(404)
    uid = session.get('user', {}).get('id')
    conn = db()
    if request.method == 'POST':
        if not uid:
            flash('Please log in to rate or save movies.', 'warning')
            conn.close()
            return redirect(url_for('login'))
        action = request.form.get('action')
        if action == 'rate':
            try:
                rating = float(request.form['rating'])
                if not 1 <= rating <= 5:
                    raise ValueError
                conn.execute('''INSERT INTO ratings(user_id,movie_id,rating) VALUES(?,?,?)
                    ON CONFLICT(user_id,movie_id) DO UPDATE SET rating=excluded.rating, created_at=CURRENT_TIMESTAMP''',
                    (uid, movie_id, rating))
                flash('Your rating was saved.', 'success')
            except (ValueError, KeyError):
                flash('Rating must be between 1 and 5.', 'danger')
        elif action == 'favorite':
            exists = conn.execute('SELECT id FROM favorites WHERE user_id=? AND movie_id=?', (uid, movie_id)).fetchone()
            if exists:
                conn.execute('DELETE FROM favorites WHERE id=?', (exists['id'],))
                flash('Removed from your favorites.', 'info')
            else:
                conn.execute('INSERT INTO favorites(user_id,movie_id) VALUES(?,?)', (uid, movie_id))
                flash('Added to your favorites.', 'success')
        conn.commit()
    if uid:
        conn.execute('INSERT INTO history(user_id,movie_id) VALUES(?,?)', (uid, movie_id))
        conn.commit()
        rating = conn.execute('SELECT rating FROM ratings WHERE user_id=? AND movie_id=?', (uid, movie_id)).fetchone()
        favorite = conn.execute('SELECT id FROM favorites WHERE user_id=? AND movie_id=?', (uid, movie_id)).fetchone()
    else:
        rating, favorite = None, None
    conn.close()
    return render_template('movie.html', movie=movie, user_rating=rating['rating'] if rating else None, is_favorite=bool(favorite))


@app.route('/history')
@login_required
def history():
    conn = db()
    rows = conn.execute('SELECT m.*,h.viewed_at FROM history h JOIN movies m ON m.id=h.movie_id WHERE h.user_id=? ORDER BY h.viewed_at DESC', (session['user']['id'],)).fetchall()
    conn.close()
    return render_template('history.html', movies=rows)


@app.route('/favorites')
@login_required
def favorites():
    conn = db()
    rows = conn.execute('SELECT m.* FROM favorites f JOIN movies m ON m.id=f.movie_id WHERE f.user_id=? ORDER BY f.created_at DESC', (session['user']['id'],)).fetchall()
    conn.close()
    return render_template('favorites.html', movies=rows)


@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = db()
    users = conn.execute('SELECT id,name,email,is_admin,created_at FROM users ORDER BY id DESC').fetchall()
    movies = conn.execute('SELECT * FROM movies ORDER BY id DESC').fetchall()
    stats = {
        'users': conn.execute('SELECT COUNT(*) FROM users').fetchone()[0],
        'movies': conn.execute('SELECT COUNT(*) FROM movies').fetchone()[0],
        'ratings': conn.execute('SELECT COUNT(*) FROM ratings').fetchone()[0],
        'favorites': conn.execute('SELECT COUNT(*) FROM favorites').fetchone()[0],
    }
    conn.close()
    return render_template('admin.html', users=users, movies=movies, stats=stats)


@app.route('/admin/movie/add', methods=['GET', 'POST'])
@admin_required
def admin_add_movie():
    if request.method == 'POST':
        conn = db()
        try:
            conn.execute('''INSERT INTO movies(id,title,genre,description,director,year,poster,backdrop)
                            VALUES(?,?,?,?,?,?,?,?)''', (
                int(request.form['id']), request.form['title'].strip(), request.form['genre'].strip(),
                request.form['description'].strip(), request.form['director'].strip(), int(request.form['year']),
                request.form['poster'].strip(), request.form.get('backdrop', '').strip()))
            conn.commit()
            flash('Movie added successfully.', 'success')
            return redirect(url_for('admin_dashboard'))
        except (sqlite3.IntegrityError, ValueError):
            flash('Could not add movie. Check the ID and fields.', 'danger')
        finally:
            conn.close()
    return render_template('movie_form.html', movie=None, action='Add Movie')


@app.route('/admin/movie/edit/<int:movie_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_movie(movie_id):
    movie = get_movie(movie_id)
    if not movie:
        abort(404)
    if request.method == 'POST':
        conn = db()
        conn.execute('''UPDATE movies SET title=?,genre=?,description=?,director=?,year=?,poster=?,backdrop=? WHERE id=?''', (
            request.form['title'].strip(), request.form['genre'].strip(), request.form['description'].strip(),
            request.form['director'].strip(), int(request.form['year']), request.form['poster'].strip(),
            request.form.get('backdrop', '').strip(), movie_id))
        conn.commit(); conn.close()
        flash('Movie updated successfully.', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('movie_form.html', movie=movie, action='Edit Movie')


@app.post('/admin/movie/delete/<int:movie_id>')
@admin_required
def admin_delete_movie(movie_id):
    conn = db()
    conn.execute('DELETE FROM movies WHERE id=?', (movie_id,))
    conn.commit(); conn.close()
    flash('Movie deleted.', 'info')
    return redirect(url_for('admin_dashboard'))


@app.errorhandler(403)
def forbidden(_):
    return render_template('error.html', code=403, message='You do not have permission to view this page.'), 403


@app.errorhandler(404)
def not_found(_):
    return render_template('error.html', code=404, message='The movie or page you are looking for could not be found.'), 404


@app.errorhandler(500)
def server_error(_):
    return render_template('error.html', code=500, message='Something went wrong on the server.'), 500


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=os.environ.get('FLASK_DEBUG') == '1')
