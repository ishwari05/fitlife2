from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime
import os
import google.generativeai as genai
import json
import psycopg2
from psycopg2.extras import DictCursor
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configure Gemini API
genai.configure(api_key=os.getenv('AIzaSyCsxiHYsmERU4C2RUKUkrJNDyITl2yUUbg'))
model = genai.GenerativeModel('gemini-pro')

# PostgreSQL Database configuration
DATABASE_CONFIG = {
    'host': 'localhost',
    'database': 'fitlife',
    'user': 'fituser',
    'password': 'fitpass',
    'port': '5432'
}

def get_db():
    conn = psycopg2.connect(**DATABASE_CONFIG)
    conn.autocommit = True
    return conn

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    username VARCHAR(255) NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS recommendations (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    diet_plan TEXT NOT NULL,
                    workout_plan TEXT NOT NULL,
                    additional_tips TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')

# Initialize database
init_db()

@app.route('/')
def index():
    return render_template('main_landing.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        with get_db() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    'SELECT * FROM users WHERE email = %s', 
                    (email,)
                )
                user = cur.fetchone()
                
                if user and check_password_hash(user['password'], password):
                    session['user_id'] = user['id']
                    session['user_email'] = user['email']
                    return redirect(url_for('dashboard'))
                else:
                    flash('Invalid email or password')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        'INSERT INTO users (email, username, password) VALUES (%s, %s, %s)',
                        (email, username, password)
                    )
            flash('Account created successfully! Please login')
            return redirect(url_for('login'))
        except psycopg2.IntegrityError:
            flash('Email already exists')
    return render_template('signup.html')

@app.route('/dashboard')
def dashboard():
    if 'user_email' not in session:
        return redirect(url_for('login'))
    
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(
                'SELECT * FROM users WHERE email = %s',
                (session['user_email'],)
            )
            current_user = cur.fetchone()
            
            cur.execute(
                'SELECT * FROM recommendations WHERE user_id = %s',
                (session['user_id'],)
            )
            user_recommendations = cur.fetchall()
    
    return render_template('dashboard.html',
                         current_user=current_user,
                         recommendations=user_recommendations)

@app.route('/get_recommendations', methods=['POST'])
def get_recommendations():
    if 'user_email' not in session:
        return redirect(url_for('login'))
    
    # Get form data
    goal = request.form['goal']
    level = request.form['level']
    preferences = request.form['preferences']
    allergies = request.form.get('allergies', '')
    
    # Generate recommendations using Gemini API
    try:
        recommendation = generate_recommendation(goal, level, preferences, allergies)
        recommendation.update({
            "title": f"{goal.capitalize()} Plan for {level.capitalize()}",
            "summary": f"Customized {goal} plan with {preferences} diet options",
            "created_at": datetime.now()
        })
    except Exception as e:
        print(f"Error generating recommendation: {str(e)}")
        recommendation = {
            "title": "Error Generating Plan",
            "summary": "Failed to generate recommendation",
            "diet_plan": "Please try again later",
            "workout_plan": "Please try again later",
            "additional_tips": "Please try again later",
            "created_at": datetime.now()
        }
    
    # Store recommendation
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO recommendations 
                (user_id, title, summary, diet_plan, workout_plan, additional_tips)
                VALUES (%s, %s, %s, %s, %s, %s)''',
                (session['user_id'], 
                 recommendation['title'],
                 recommendation['summary'],
                 recommendation['diet_plan'],
                 recommendation['workout_plan'],
                 recommendation['additional_tips'])
            )
    
    return render_template('result.html',
                         diet_plan=recommendation['diet_plan'],
                         workout_plan=recommendation['workout_plan'],
                         additional_tips=recommendation['additional_tips'],
                         recommendation_date=recommendation['created_at'].strftime('%B %d, %Y'))

@app.route('/logout')
def logout():
    session.pop('user_email', None)
    session.pop('user_id', None)
    return redirect(url_for('index'))

def generate_recommendation(goal, level, preferences, allergies):
    """Generate personalized recommendations using Gemini API"""
    prompt = f"""
    Generate a comprehensive fitness and diet recommendation plan for:
    - Goal: {goal}
    - Fitness Level: {level}
    - Dietary Preferences: {preferences}
    - Allergies/Restrictions: {allergies if allergies else 'None'}
    
    Provide the response in JSON format with these keys:
    - "diet_plan": Detailed 7-day meal plan with breakfast, lunch, dinner
    - "workout_plan": Weekly workout schedule with exercises
    - "additional_tips": Helpful advice for achieving the goal
    
    Format the content with HTML line breaks (<br>) for proper display.
    """
    
    response = model.generate_content(prompt)
    return json.loads(response.text)

if __name__ == '__main__':
    app.run(debug=True)
