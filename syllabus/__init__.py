# the actual logic lives here instead of app.py so each piece can be
# tested on its own:
#   pdf_extract     bytes -> raw text
#   gemini_client   text  -> structured items
#   ics_generate    items -> .ics file
#   google_oauth    the OAuth flow
#   google_calendar push events to the Calendar API
#   db              SQLite token storage
