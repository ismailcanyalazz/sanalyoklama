"""Flask eklentilerinin tek noktada oluşturulması (circular import engellenir)."""
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

login_manager.login_view = "auth.login"
login_manager.login_message = "Bu sayfayı görüntülemek için giriş yapmalısınız."
login_manager.login_message_category = "warning"
login_manager.session_protection = "strong"
