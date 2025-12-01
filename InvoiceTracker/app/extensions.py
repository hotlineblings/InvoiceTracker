"""
Rozszerzenia Flask.
Inicjalizacja obiektów SQLAlchemy i Migrate tutaj aby uniknąć cyklicznych importów.
"""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()
