import json 
from langchain.chat_models import init_chat_model
from datetime import datetime,timedelta,timezone, date
from dotenv import load_dotenv
import re

load_dotenv()

model=init_chat_model(
    model="llama-3.3-70b-versatile",
    model_provider="groq",
    temperature=0.1
)

def calculate_search_end_date(query):
    today = date.today()
    
    if "weekend" in query.lower():
        days_ahead = 4 - today.weekday()
        if days_ahead <= 0: days_ahead += 7
        next_friday = today + timedelta(days=days_ahead)
        return next_friday.strftime("%Y-%m-%d")
        
    elif "next week" in query.lower():
        return (today + timedelta(days=10)).strftime("%Y-%m-%d")
        
    return (today + timedelta(days=7)).strftime("%Y-%m-%d")
    
def ask_database_assistant(question, db_rows):
    """
    db_rows: List of tuples (event_date, event_time, title, raw_input)
    """
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")
    
    tasks_text = ""
    if not db_rows:
        tasks_text = "No upcoming tasks found in database."
    else:
        for row in db_rows:
            tasks_text += f"- [{row[0]} at {row[1]}] Title: {row[2]} (Context: '{row[3]}')\n"

    prompt = f"""
    Current Date: {today} | Current Time: {now}
    User Question: "{question}"
    User Tasks:
    {tasks_text}
    
    INSTRUCTIONS:
    1. Filter the tasks based on the User's Question (Time & Topic).
    2. Understand semantics: "Practice" = "Learn" = "Study" = "Homework".
    3. Answer the question based strictly on the tasks.
    4. If the user asks "What should I practice before weekend?", look for tasks strictly BEFORE or ON Friday.
    5. BE DIRECT AND SHORT.
    6. Explicitly mention "today" or "tomorrow" and the time (e.g., "by 9 PM").
    7. NO MARKDOWN. Do not use **bold** or ## headers. Pure text only.
    8. If the user asks "What to do before sleeping", look for tasks scheduled for TONIGHT (after current time).
    9. If nothing matches, say so.

    Example Output:
    "You need to finish the database questions by 9 PM today. Good luck!"
    """
    
    return model.invoke(prompt).content
    
def create_event(service, event):
    date = event['date']
    start_time = event.get('start_time')
    end_time = event.get('end_time')

    if start_time and end_time:
        event_body = {
            'summary': event['title'],
            'description': event.get('notes', event.get('raw_input', '')),
            'location': event.get('location', ''),
            'start': {'dateTime': f"{date}T{start_time}:00", 'timeZone': 'Asia/Kolkata'},
            'end': {'dateTime': f"{date}T{end_time}:00", 'timeZone': 'Asia/Kolkata'},
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 30},
                    {'method': 'popup', 'minutes': 10}
                ]
            },
        }
    else:
        event_body = {
            'summary': event['title'],
            'description': event.get('notes', event.get('raw_input', '')),
            'location': event.get('location', ''),
            'start': {'date': date},
            'end': {'date': date}
        }

    recurrence_map = {
        "daily": "RRULE:FREQ=DAILY",
        "weekly": "RRULE:FREQ=WEEKLY",
        "monthly": "RRULE:FREQ=MONTHLY"
    }
    if event.get('recurring') in recurrence_map:
        event_body['recurrence'] = [recurrence_map[event['recurring']]]

    created_event = service.events().insert(calendarId='primary', body=event_body).execute()
    start_display = created_event.get('start', {}).get('dateTime', created_event.get('start', {}).get('date'))
    print(f"Created: {created_event['summary']} at {start_display}")
    pass 

def process_and_create_events(user_input, service):
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")
    
    prompt = (
        user_input+
        f"""
    You are an event extraction engine.
    REFERENCE DATE (for interpreting words like "tomorrow"): {today}
    Reference Time: {now}
Your task:
Given a user's scheduling message, extract the event details in STRICT JSON format.
RULES:
- Output ONLY valid JSON. No markdown. No explanations.
- If information is missing, infer only when obvious (e.g., "tomorrow", "next monday").
- If the user does not specify a date, assume the event is today.
- CRITICAL: If the user provides a time without AM/PM (e.g., "at 8" or "before 9"), compare it to the Reference Time.
- If the implied AM time has ALREADY PASSED today, you MUST assume PM (e.g., convert "9" to "21:00").
- If the user does not specify a start time, assume now or a reasonable default.
- If the user specifies a start time but no end time:
    - If duration is provided (e.g., "for 2 hours"), calculate end_time.
    - If duration is not provided, predict typical duration based on the event title (e.g., yoga = 60 min, meeting = 60 min, call = 30 min).
- If the event repeats regularly, fill the "recurring" field:
    - "daily" for every day
    - "weekly" for once a week
    - "monthly" for once a month
- If the event is not recurring, leave "recurring" as an empty string.
- If only end_time is provided, back-calculate start_time from duration if obvious.
- Times must be in 24-hour format HH:MM.
- Date must be in YYYY-MM-DD.
- If the user says "tomorrow", convert it to YYYY-MM-DD using the reference date.
- If the user says "next week", assume the event is on the same weekday next week.
- Output a SINGLE JSON array of event objects.
- Title should be short and human-friendly.
JSON SCHEMA:
{{
  "event_id": "",
  "title": "",
  "date": "",
  "start_time": "",
  "end_time": "",
  "duration_minutes": null,
  "location": "",
  "notes": "",
  "raw_input": "",
  "recurring": ""
}}
"""
    )
    response = model.invoke(prompt)
    content = response.content.strip()
    if "```" in content:
        content = re.search(r"```(?:json)?(.*?)```", content, re.DOTALL)
        if content:
            content = content.group(1).strip()
    try:
        events_json = json.loads(content)
        
        if isinstance(events_json, dict):
            events_json = [events_json]
            
        created_data = []
        
        for event in events_json:
            create_event(service, event)
            
            created_data.append({
                "title": event.get('title', 'Untitled Event'),
                "date": event.get('date', today),
                "time": event.get('start_time', '00:00'),
                "raw_input": user_input 
            })
            
        return {"type": "action", "data": created_data}
        
    except Exception as e:
        return {"type": "chat", "reply": f"Error processing task: {str(e)}"}