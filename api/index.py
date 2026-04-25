from web_app import app as flask_app

# Export the Flask WSGI app using the canonical name Vercel looks for.
app = flask_app
application = app
