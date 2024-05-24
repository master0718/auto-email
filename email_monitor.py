import base64
import logging
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import time
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import os.path
import pickle
import re
from requests import HTTPError
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone

load_dotenv()

# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# If modifying these SCOPES, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/gmail.modify', 'https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.send']

def create_message_with_attachment(sender, to, subject, message_text, file_path=None):
    """Create a message for an email with an optional attachment."""
    message = MIMEMultipart()
    message['to'] = to
    message['from'] = sender
    message['subject'] = subject
    
    # Attach the message text
    message.attach(MIMEText(message_text, 'plain'))
    # Attach the specified file if provided
    if file_path:
        with open(file_path, 'rb') as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(file_path))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
            message.attach(part)
    
    return {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}

def get_email_only(from_header):
    if from_header is None:
        return None

    # Regular expression to match email addresses
    email_regex = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

    # Extracting the email address using regex search
    from_email = re.search(email_regex, from_header)
    if from_email:
        from_email = from_email.group(0)
    else:
        from_email = None

    return from_email

def get_service():
    creds = None
    token_path = 'token.pickle'
    credentials_path = 'credentials.json'
    # print(credentials_path)
    if os.path.exists(token_path):
        with open(token_path, 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES, redirect_uri='http://localhost:5229/')
            creds = flow.run_local_server(port=5229)
        with open(token_path, 'wb') as token:
            pickle.dump(creds, token)
    service = build('gmail', 'v1', credentials=creds)
    return service

def create_message(sender, to, subject, message_text):
    """Create a message for an email."""
    message = MIMEText(message_text)
    message['to'] = to
    message['from'] = sender
    message['subject'] = subject
    return {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}

def send_message(service, user_id, message):
    """Send an email message."""
    try:
        message = service.users().messages().send(userId=user_id, body=message).execute()
        print(f"Message Id: {message['id']}")
        return message
    except HTTPError as error:
        print(f'An error occurred: {error}')
        return None

def reply_to_message(service, user_id, message_id, subject, reply_text, attachment_path, from_email):
    """Reply to a specific message."""
    if not from_email:
        print(f"Could not find sender's email for message ID: {message_id}")
        return

    # Preparing the reply
    reply_subject = f"Re: {subject}"
    reply_message = create_message_with_attachment(user_id, from_email, reply_subject, reply_text, attachment_path)

    # Sending the reply
    send_message(service, user_id, reply_message)

def mark_message_as_read(service, user_id, message_id):
    """Marks the message as read by removing the 'UNREAD' label."""
    try:
        service.users().messages().modify(
            userId=user_id,
            id=message_id,
            body={'removeLabelIds': ['UNREAD']}
        ).execute()
        print(f"Message {message_id} marked as read.")
    except Exception as error:
        print(f"An error occurred: {error}")

def check_unread_messages(service):
    try:
        from_email = os.getenv("MAIL_ADDRESS")
        query = f'is:unread from:{from_email}'
        results = service.users().messages().list(userId='me', q=query).execute()
        messages = results.get('messages', [])
        if not messages:
            print("No unread messages.")
        else:
            for message in messages:
                msg = service.users().messages().get(userId='me', id=message['id'], format='full').execute()
                subject = next((header['value'] for header in msg['payload']['headers'] if header['name'] == 'Subject'), None)
                content = msg['snippet']  # Using snippet as content for simplicity
                attachment_path = None

                print("Subject:\n" + subject)
                print("Content:\n" + content)
                if subject:
                    # Find the position of the last "-"
                    last_dash_index = subject.rfind('-')

                    if last_dash_index != -1:  # Ensure "-" is found in the subject
                        # Replace everything after the last "-" with "X ACCEPT"
                        reply_subject = subject[:last_dash_index].strip() + " " + os.getenv("SUBJECT_SUFFIX")
                    else:
                        reply_subject = subject  # If no "-", use original subject
                else:
                    reply_subject = ""  # Handle if subject is not found
                reply_content = os.getenv("MAIL_CONTENT")
                mark_message_as_read(service, 'me', message['id'])
                reply_to_message(service, 'me', message['id'], reply_subject, reply_content, attachment_path, from_email)
    except Exception as error:
        # print(f"An error occurred: {error}")
        print("Network Error! Check your internet connection.")
        return None

def main():    
    service = get_service()
    
    start_time_str = os.getenv("START_TIME")
    end_time_str = os.getenv("END_TIME")
    
    start_hour, start_minute = map(int, start_time_str.split(':'))
    end_hour, end_minute = map(int, end_time_str.split(':'))
    while True:
        utc_now = datetime.now(timezone.utc)
        est_offset = timedelta(hours=-4)
        now = utc_now + est_offset
        start_time = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
        end_time = now.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
        print(now.strftime('%Y-%m-%d %H:%M:%S'))
        if now < start_time or now > end_time:
            print('Checking unread messages from ' + os.getenv("MAIL_ADDRESS"))
            check_unread_messages(service)
        else:
            print('Bot is not working because this is working hour.')
            time_to_sleep = (start_time - now).total_seconds() if now < start_time else (end_time - now).total_seconds()
            time.sleep(time_to_sleep)

        time.sleep(int(os.getenv("INTERVAL_TIME")))  # Adjust the sleep time as necessary
    
if __name__ == '__main__':
    main()
