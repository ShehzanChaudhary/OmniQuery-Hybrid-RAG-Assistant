import os
from dotenv import load_dotenv

load_dotenv()

# Hardcoded for now so the container runs without configuring Azure App Settings.
# An env var (.env locally, or an App Setting on Azure) still overrides these —
# swap in real App Settings and drop these defaults before this goes public.
class Config:
    OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')
    OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', 'https://openrouter.ai/api/v1')
    MODEL = os.environ.get('MODEL', 'openai/gpt-4o-mini')
    EMBED_MODEL = os.environ.get('EMBED_MODEL', 'openai/text-embedding-3-small')

    # Secret key stays env-var-only (from .env locally; pass it as a real env var /
    # App Setting in Docker & Azure) — the public key and host aren't sensitive.
    LANGFUSE_SECRET_KEY = os.environ['LANGFUSE_SECRET_KEY']
    LANGFUSE_PUBLIC_KEY = os.environ.get('LANGFUSE_PUBLIC_KEY')
    LANGFUSE_BASE_URL = os.environ.get('LANGFUSE_BASE_URL', 'https://us.cloud.langfuse.com')

    DOCUMENT_INTELLIGENCE_KEY = os.environ['DOCUMENT_INTELLIGENCE_KEY']
    DOCUMENT_INTELLIGENCE_ENDPOINT = os.environ.get('DOCUMENT_INTELLIGENCE_ENDPOINT', "https://shehzan.cognitiveservices.azure.com/")

    TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY')

    MYSQL_HOST = os.environ.get('MYSQL_HOST', 'localhost')
    MYSQL_PORT = os.environ.get('MYSQL_PORT', '3306')
    MYSQL_USER = os.environ.get('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD')
    MYSQL_DATABASE = os.environ.get('MYSQL_DATABASE', 'OmniQuery')

    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'change-this-in-production')
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRY_MINUTES = 60 * 24 * 7   # 7 din