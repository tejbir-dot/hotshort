import os
import sys
sys.path.insert(0, '.')

from flask import Flask
from models.user import db
from sqlalchemy import inspect

app = Flask(__name__)
base_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(base_dir, 'instance', 'hotshort.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path.replace(chr(92), "/")}'
db.init_app(app)

with app.app_context():
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    print("Tables:", sorted(tables))
