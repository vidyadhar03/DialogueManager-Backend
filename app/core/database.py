import firebase_admin
from firebase_admin import credentials, firestore
from .config import settings

if not firebase_admin._apps:
    cred = credentials.Certificate(settings.FIREBASE_CRED_PATH)
    firebase_admin.initialize_app(cred)

db = firestore.client()