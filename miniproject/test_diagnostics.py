import psycopg2
import google.generativeai as genai
import json
import traceback

def test_database():
    print("\n=== DATABASE TEST ===")
    try:
        conn = psycopg2.connect(
            host='localhost',
            database='fitlife',
            user='fituser',
            password='fitpass',
            port='5432'
        )
        cur = conn.cursor()
        
        # Test users table
        cur.execute("SELECT * FROM users LIMIT 1")
        print(f"Users table test: {'SUCCESS' if cur.fetchone() else 'EMPTY'}")
        
        # Test recommendations table
        cur.execute("SELECT * FROM recommendations LIMIT 1")
        print(f"Recommendations table test: {'SUCCESS' if cur.fetchone() else 'EMPTY'}")
        
        conn.close()
        return True
    except Exception as e:
        print(f"DATABASE ERROR: {str(e)}")
        print(traceback.format_exc())
        return False

def test_gemini_api():
    print("\n=== GEMINI API TEST ===")
    try:
        genai.configure(api_key='AIzaSyCsxiHYsmERU4C2RUKUkrJNDyITl2yUUbg')
        model = genai.GenerativeModel('models/gemini-1.5-pro-latest')
        
        test_prompt = "Respond with just the JSON: {'test': 'success'}"
        response = model.generate_content(test_prompt)
        
        print(f"Raw response type: {type(response)}")
        print(f"Response attributes: {dir(response)}")
        
        if hasattr(response, 'text'):
            print(f"Raw text response: {response.text}")
            try:
                # Handle markdown code block responses
                text = response.text.strip()
                if text.startswith('```json'):
                    text = text[7:].rstrip('`').strip()
                elif text.startswith('```'):
                    text = text[3:].rstrip('`').strip()
                
                result = json.loads(text)
                print(f"API Response: {result}")
                return True
            except json.JSONDecodeError:
                print("Response is not valid JSON. Full response:")
                print(response.text)
                return False
        elif hasattr(response, 'parts') and len(response.parts) > 0:
            print(f"Parts response: {response.parts[0].text}")
            return True
        else:
            print("API Response structure unexpected")
            print(f"Full response: {response}")
            return False
    except Exception as e:
        print(f"API ERROR: {str(e)}")
        print(traceback.format_exc())
        return False

if __name__ == '__main__':
    db_ok = test_database()
    api_ok = test_gemini_api()
    
    print("\n=== DIAGNOSTIC SUMMARY ===")
    print(f"Database: {'OK' if db_ok else 'FAILED'}")
    print(f"Gemini API: {'OK' if api_ok else 'FAILED'}")
