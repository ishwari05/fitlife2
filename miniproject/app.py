from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_cors import CORS
from datetime import datetime
import os
import google.generativeai as genai
import json
import psycopg2
import traceback
from psycopg2.extras import DictCursor
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, static_folder='../static', static_url_path='/static')
app.config.update(
    SESSION_COOKIE_SECURE=False,  # For development only
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=86400  # 1 day
)
CORS(app, supports_credentials=True, resources={
    r"/get_recommendations": {"origins": "http://127.0.0.1:5000"},
    r"/login": {"origins": "http://127.0.0.1:5000"}
})
app.secret_key = os.urandom(24)

# Custom Jinja2 filter for datetime formatting
@app.template_filter('datetimeformat')
def datetimeformat(value, format='%B %d, %Y'):
    if not value:
        return "Not available"
    if isinstance(value, str):
        value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S.%f')
    return value.strftime(format)

# Configure Gemini API
genai.configure(api_key='AIzaSyCsxiHYsmERU4C2RUKUkrJNDyITl2yUUbg')  # Using direct key for testing
model = genai.GenerativeModel('models/gemini-1.5-pro-latest')

# PostgreSQL Database configuration
DATABASE_CONFIG = {
    'host': 'localhost',
    'database': 'fitlife',
    'user': 'fituser',  # Use admin account temporarily
    'password': 'fitpass',  # Replace with actual password
    'port': '5432'
}

def get_db():
    conn = psycopg2.connect(**DATABASE_CONFIG)
    conn.autocommit = True
    return conn

def init_db():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # First ensure the user has proper permissions
                cur.execute("GRANT CREATE ON SCHEMA public TO fituser")
                cur.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO fituser")
                
                # Check if tables exist first
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'users'
                    )
                """)
                users_table_exists = cur.fetchone()[0]
                
                if not users_table_exists:
                    cur.execute('''
                        CREATE TABLE users (
                            id SERIAL PRIMARY KEY,
                            email VARCHAR(255) UNIQUE NOT NULL,
                            username VARCHAR(255) NOT NULL,
                            password VARCHAR(255) NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')
                    
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'recommendations'
                    )
                """)
                recs_table_exists = cur.fetchone()[0]
                
                if not recs_table_exists:
                    cur.execute('''
                        CREATE TABLE recommendations (
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
    except Exception as e:
        print(f"Database initialization error: {str(e)}")
        print("Please ensure:")
        print("1. PostgreSQL is running")
        print("2. User 'fituser' has CREATE privileges")
        print("3. Database 'fitlife' exists")

# Initialize database
init_db()

from flask import send_from_directory

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.route('/')
def home():
    return render_template('main_landing.html')

@app.route('/index')
def index():
    if 'user_email' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

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
                    session.permanent = True
                    session['user_id'] = user['id']
                    session['user_email'] = user['email']
                    session.modified = True
                    return redirect(url_for('dashboard'))
                else:
                    flash('Invalid email or password')
                    return redirect(url_for('login'))
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
    
    return render_template('dashboard.html',
                         current_user=current_user)

@app.route('/get_recommendations', methods=['POST', 'OPTIONS'])
def get_recommendations():
    if 'user_email' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    # Get form data and log it for debugging
    goal = request.form['goal']
    level = request.form['level']
    preferences = request.form['preferences']
    allergies = request.form.get('allergies', '')
    workout_type = request.form['workout_type']
    workout_split = request.form['workout_split']
    workout_frequency = request.form['workout_frequency']
    workout_duration = request.form['workout_duration']
    
    print(f"Form Data: goal={goal}, level={level}, preferences={preferences}, allergies={allergies}, workout_type={workout_type}, workout_split={workout_split}, workout_frequency={workout_frequency}, workout_duration={workout_duration}")
    
    # Generate recommendations using Gemini API
    try:
        print("Attempting to generate recommendation...")
        recommendation = generate_recommendation(
            goal=goal,
            level=level,
            preferences=preferences,
            allergies=allergies,
            workout_type=workout_type,
            workout_split=workout_split,
            workout_frequency=workout_frequency,
            workout_duration=workout_duration
        )
        print("Recommendation generated successfully")
        
        # Validate recommendation structure
        required_keys = ['diet_plan', 'workout_plan', 'additional_tips']
        if not all(key in recommendation for key in required_keys):
            raise ValueError("API response missing required fields")
            
        # Convert and validate diet plan format
        if isinstance(recommendation['diet_plan'], str):
            try:
                diet_data = json.loads(recommendation['diet_plan'])
                recommendation['diet_plan'] = diet_data
            except json.JSONDecodeError:
                recommendation['diet_plan'] = {'Day 1': [recommendation['diet_plan']]}
        
        # Flatten diet plan structure for template
        if isinstance(recommendation['diet_plan'], dict):
            flattened_diet = {}
            for day, meals in recommendation['diet_plan'].items():
                if isinstance(meals, dict):
                    # Convert meal objects to list format
                    meal_list = []
                    for meal_type, meal_details in meals.items():
                        if isinstance(meal_details, str):
                            meal_list.append(f"{meal_type.capitalize()}: {meal_details}")
                        elif isinstance(meal_details, dict):
                            # Format meal with just ingredients
                            ingredients = meal_details.get('ingredients', '')
                            meal_list.append(
                                f"<strong>{meal_type.capitalize()}</strong>: {ingredients}"
                            )
                    flattened_diet[day] = meal_list
                elif isinstance(meals, list):
                    flattened_diet[day] = meals
                else:
                    flattened_diet[day] = [str(meals)]
            recommendation['diet_plan'] = flattened_diet
                
        # Convert and validate workout plan format        
        if isinstance(recommendation['workout_plan'], str):
            try:
                workout_data = json.loads(recommendation['workout_plan'])
                # Ensure proper structure: dict with day keys and list values
                if isinstance(workout_data, dict):
                    recommendation['workout_plan'] = {
                        day: [exercise] if isinstance(exercise, str) else exercise
                        for day, exercise in workout_data.items()
                    }
                else:
                    recommendation['workout_plan'] = {'Day 1': [recommendation['workout_plan']]}
            except json.JSONDecodeError:
                recommendation['workout_plan'] = {'Day 1': [recommendation['workout_plan']]}
                
        if isinstance(recommendation['additional_tips'], str):
            recommendation['additional_tips'] = [recommendation['additional_tips']]
            
        recommendation.update({
            "title": f"{goal.capitalize()} Plan for {level.capitalize()}",
            "summary": f"Customized {goal} plan with {preferences} diet options",
            "created_at": datetime.now()
        })
        
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {str(e)}")
        print(f"API response: {response_text if 'response_text' in locals() else 'No response'}")
        flash('Error processing the recommendation. Please try again.')
        return redirect(url_for('index'))
    except Exception as e:
        print(f"Error generating recommendation: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        print(f"Traceback: {traceback.format_exc()}")
        flash('Error connecting to recommendation service. Please try again later.')
        return redirect(url_for('index'))
    
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
                 json.dumps(recommendation['diet_plan']),
                 json.dumps(recommendation['workout_plan']), 
                 json.dumps(recommendation['additional_tips']))
            )
    
    return render_template('result.html',
                         diet_plan=recommendation['diet_plan'],
                         workout_plan=recommendation['workout_plan'],
                         additional_tips=recommendation['additional_tips'],
                         recommendation_date=recommendation['created_at'].strftime('%B %d, %Y'),
                         workout_type=workout_type.replace('_', ' ').title(),
                         workout_split=workout_split.replace('_', ' ').title(),
                         workout_frequency=workout_frequency,
                         workout_duration=workout_duration)

@app.route('/logout')
def logout():
    session.pop('user_email', None)
    session.pop('user_id', None)
    return redirect(url_for('index'))

def generate_recommendation(goal, level, preferences, allergies, workout_type, workout_split, workout_frequency, workout_duration):
    """Generate personalized recommendations using Gemini API"""
    prompt = f"""
    Generate a comprehensive fitness and diet recommendation plan with the following specifications:
    
    USER REQUIREMENTS:
    - Primary Goal: {goal}
    - Current Fitness Level: {level}
    - Dietary Preferences: {preferences}
    - Food Allergies/Restrictions: {allergies if allergies else 'None'}
    - Preferred Workout Type: {workout_type}
    - Workout Split Preference: {workout_split}
    - Weekly Workout Frequency: {workout_frequency} days
    - Workout Session Duration: {workout_duration} minutes
    
    DIET PLAN REQUIREMENTS:
    - Must include 3 main meals (breakfast, lunch, dinner) and 2 snacks per day
    - Each meal should specify:
      * Ingredients with quantities
      * Preparation instructions
      * Estimated calories and macros (protein, carbs, fats)
    - Meals should align with the user's goal ({goal}) and preferences ({preferences})
    - Account for any allergies: {allergies if allergies else 'None'}
    
    RESPONSE FORMAT REQUIREMENTS:
    - Must return valid JSON with exactly these top-level keys:
      - "diet_plan" (object): 7-day meal plan with detailed meals for each day
      - "workout_plan" (object): Weekly schedule matching the specified parameters
      - "additional_tips" (array): Helpful advice strings
    
    EXAMPLE DIET PLAN FORMAT:
    {{
      "diet_plan": {{
        "Monday": {{
          "breakfast": "Scrambled eggs (2 eggs) with spinach (1 cup)<br>Calories: 300 | P: 20g | C: 5g | F: 22g",
          "morning_snack": "Greek yogurt (150g) with almonds (10g)",
          "lunch": "Grilled chicken breast (150g) with quinoa (1/2 cup) and steamed vegetables<br>Calories: 450 | P: 40g | C: 35g | F: 15g",
          "afternoon_snack": "Protein shake with banana",
          "dinner": "Salmon fillet (200g) with roasted sweet potatoes and asparagus<br>Calories: 500 | P: 35g | C: 40g | F: 20g"
        }},
        ... (all 7 days)
      }},
      "workout_plan": {{
        "Monday": [
          "Squats: 3 sets x 12 reps",
          "Bench Press: 3 sets x 10 reps"
        ],
        ... (all 7 days)
      }},
      "additional_tips": [
        "Drink at least 2L of water daily",
        "Get 7-8 hours of sleep for optimal recovery"
      ]
    }}
    
    IMPORTANT:
    - Include complete nutritional information for each meal
    - Ensure meals are varied throughout the week
    - Provide specific quantities for all ingredients
    - Use metric measurements (grams, milliliters)
    - Return ONLY the raw JSON without markdown or code blocks
    - Validate all meal plans meet the user's goal of {goal}
    """
    
    MAX_RETRIES = 3
    retry_count = 0
    
    while retry_count < MAX_RETRIES:
        try:
            print(f"\nSending prompt to Gemini API (attempt {retry_count + 1})...")
            response = model.generate_content(prompt)
            
            if not hasattr(response, 'text') and not hasattr(response, 'parts'):
                raise ValueError("Invalid API response format - missing text/parts")
                
            response_text = response.text if hasattr(response, 'text') else response.parts[0].text
            print(f"Raw API response: {response_text[:200]}...")  # Log first 200 chars
        
            # Clean response by removing markdown code blocks if present
            if response_text.startswith('```json'):
                response_text = response_text[7:].rstrip('`').strip()
            elif response_text.startswith('```'):
                response_text = response_text[3:].rstrip('`').strip()
                
            # Validate JSON structure
            result = json.loads(response_text)
            required_keys = ['diet_plan', 'workout_plan', 'additional_tips']
            if not all(key in result for key in required_keys):
                raise ValueError(f"Missing required keys in response: {required_keys}")
                
            # Validate plan completeness
            if len(result['diet_plan']) != 7 or len(result['workout_plan']) != 7:
                raise ValueError("Plans must include all 7 days")
                
            return result
            
        except json.JSONDecodeError as e:
            retry_count += 1
            print(f"JSON decode error (attempt {retry_count}): {str(e)}")
            print(f"Response was: {response_text}")
            if retry_count >= MAX_RETRIES:
                raise ValueError("API returned invalid JSON format after multiple attempts") from e
            continue
            
        except Exception as e:
            retry_count += 1
            print(f"API error (attempt {retry_count}): {str(e)}")
            if retry_count >= MAX_RETRIES:
                raise
            continue
            

if __name__ == '__main__':
    app.run(debug=True)
