import os
import json
import psycopg2 
from flask import Flask, render_template, request, redirect, session, jsonify
from auth1 import get_calendar_service
from calender_utils1 import process_and_create_events,calculate_search_end_date,ask_database_assistant
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv
from datetime import datetime,date

load_dotenv()
app = Flask(__name__)

app.secret_key = os.getenv('FLASK_SECRET') 
DB_URL = os.getenv('DATABASE_URL')


#os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
#os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'


def get_db_connection():
    conn = psycopg2.connect(DB_URL)
    return conn
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS event_history (
            id SERIAL PRIMARY KEY,
            user_email TEXT NOT NULL,
            event_title TEXT NOT NULL,
            raw_input TEXT,
            event_date DATE,
            event_time TIME,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    print("--> Connected to Cloud Database!")
try:
    init_db()
except Exception as e:
    print(f"--> DB Connection Error: {e}")

@app.route('/')
def index():
    is_logged_in = 'credentials' in session
    user_history = []
    user_name = "User"
    user_picture = None

    if is_logged_in:
        user_name = session.get('user_name', 'User')
        user_picture = session.get('user_picture')
        email = session.get('user_email')
        
        if email:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT event_title FROM event_history WHERE user_email = %s ORDER BY id DESC", (email,))
            rows = c.fetchall()
            user_history = [row[0] for row in rows]
            conn.close()

    return render_template('index.html', 
                           logged_in=is_logged_in, 
                           history=user_history,
                           user_name=user_name,
                           user_picture=user_picture)

@app.route('/login')
def login():
    auth_url, state = get_calendar_service()
    session['state'] = state
    return redirect(auth_url)

@app.route('/oauth2callback')
def oauth2callback():
    state = session['state']
    service, creds = get_calendar_service(authorization_response=request.url)
    
    try:
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(BASE_DIR, 'credentials1.json'), 'r') as f:
            secret_data = json.load(f)
            cfg = secret_data.get('web') or secret_data.get('installed')
            
        if not creds.token_uri: creds.token_uri = cfg.get('token_uri')
        if not creds.client_id: creds.client_id = cfg.get('client_id')
        if not creds.client_secret: creds.client_secret = cfg.get('client_secret')
    except Exception as e:
        print(f"Warning patching creds: {e}")

    user_info_service = build('oauth2', 'v2', credentials=creds)
    user_info = user_info_service.userinfo().get().execute()
    
    session['credentials'] = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': creds.scopes
    }
    session['user_email'] = user_info.get('email')
    session['user_name'] = user_info.get('name')
    session['user_picture'] = user_info.get('picture')
    
    return redirect('/')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')
@app.route('/api/process', methods=['POST'])
def process_schedule():
    if 'credentials' not in session: 
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    user_text = data.get('message')
    user_email = session.get('user_email')
    
    creds_data = session['credentials']
    creds = Credentials(**creds_data)
    service = build('calendar', 'v3', credentials=creds)

    try:
        result = process_and_create_events(user_text, service)
        
        if result['type'] == 'action':
            events_data = result['data'] 
            
            if user_email and events_data:
                conn = get_db_connection()
                c = conn.cursor()
                for item in events_data:
                    c.execute("""
                        INSERT INTO event_history 
                        (user_email, event_title, raw_input, event_date, event_time) 
                        VALUES (%s, %s, %s, %s, %s)
                    """, (user_email, item['title'], item['raw_input'], item['date'], item['time']))
                conn.commit()
                conn.close()

            titles = [e['title'] for e in events_data]
            return jsonify({"status": "success", "events": titles, "reply": "Saved to Calendar & Database."})
            
        else:
             return jsonify({"status": "success", "events": [], "reply": result.get('reply')})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})
    
@app.route('/api/ask', methods=['POST'])
def ask_assistant():
    if 'credentials' not in session: 
        return jsonify({"reply": "Please log in."})

    data = request.json
    question = data.get('question')
    user_email = session.get('user_email')
    
    if not user_email: 
        return jsonify({"reply": "No email found."})

    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        end_date_str = calculate_search_end_date(question)
        
        conn = get_db_connection()
        c = conn.cursor()
        
        query = """
            SELECT event_date, event_time, event_title, raw_input 
            FROM event_history 
            WHERE user_email = %s 
            AND event_date >= %s 
            AND event_date <= %s
            ORDER BY event_date ASC, event_time ASC
        """
        c.execute(query, (user_email, today_str, end_date_str))
        rows = c.fetchall()
        conn.close()

        answer = ask_database_assistant(question, rows)
        
        return jsonify({"reply": answer})

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"reply": "I'm having trouble accessing the database."})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)