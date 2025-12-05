from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import google.oauth2.credentials 
import os


CLIENT_SECRETS_FILE = "credentials1.json"
if not os.path.exists(CLIENT_SECRETS_FILE):
    json_content = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    if json_content:
        print("--> Creating credentials1.json from Environment Variable...")
        with open(CLIENT_SECRETS_FILE, 'w') as f:
            f.write(json_content)
    else:
        print("--> WARNING: No credentials file and no Env Var found!")


SCOPES = [
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'openid'
]



def get_calendar_service(authorization_response=None):
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri='http://127.0.0.1:5000/oauth2callback'
    )

    if authorization_response:
        flow.fetch_token(authorization_response=authorization_response)
        
        
        original_creds = flow.credentials
        
        creds = google.oauth2.credentials.Credentials(
            token=original_creds.token,
            refresh_token=original_creds.refresh_token,
            token_uri=flow.client_config['token_uri'],
            client_id=flow.client_config['client_id'],
            client_secret=flow.client_config['client_secret'],
            scopes=original_creds.scopes
        )

        service = build('calendar', 'v3', credentials=creds)
        return service, creds 
    else:
        auth_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent' 
        )
        return auth_url, state