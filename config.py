import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
    SUPABASE_KEY = os.environ.get('SUPABASE_KEY', os.environ.get('SUPABASE_ANON_KEY', ''))
    SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', os.environ.get('SUPABASE_SERVICE_ROLE_KEY', ''))
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 100 * 1024 * 1024))
    ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
    ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi', 'webm'}
    ALLOWED_DOC_EXTENSIONS = {'pdf'}
    INSTITUTION_NAME = os.environ.get('INSTITUTION_NAME', 'Thika Technical Training Institute')
    INSTITUTION_LOGO = os.environ.get('INSTITUTION_LOGO', 'images/logo.jpg')

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}
