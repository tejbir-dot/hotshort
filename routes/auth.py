import os
from urllib.parse import urlparse
import re

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from flask_login import login_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash

from models.user import User, db


auth = Blueprint('auth', __name__)


def _cookie_secure() -> bool:
    return bool(current_app.config.get("SESSION_COOKIE_SECURE"))


def _cookie_samesite() -> str:
    return str(current_app.config.get("SESSION_COOKIE_SAMESITE") or "Lax")

def normalize_template_id(raw_value):
    value = (raw_value or "").strip()
    if not value:
        return ""
    if len(value) > 80:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return ""
    return value


def normalize_next_target(raw_next):
    default_target = "/dashboard"
    value = (raw_next or "").strip()
    if not value:
        return default_target
    if value.startswith("/") and not value.startswith("//"):
        return value

    backend_url = (current_app.config.get("BACKEND_URL") or current_app.config.get("EXTERNAL_BASE_URL") or "").strip().rstrip("/")
    if not backend_url:
        return default_target

    parsed_next = urlparse(value)
    parsed_backend = urlparse(backend_url)
    if (
        parsed_next.scheme in ("http", "https")
        and parsed_next.netloc == parsed_backend.netloc
    ):
        normalized = parsed_next.path or default_target
        if parsed_next.query:
            normalized += f"?{parsed_next.query}"
        if parsed_next.fragment:
            normalized += f"#{parsed_next.fragment}"
        return normalized

    return default_target


def build_post_login_redirect(raw_next=None):
    next_target = normalize_next_target(raw_next)
    return redirect(next_target)


# ===============================
# GOOGLE LOGIN
# ===============================
@auth.route('/google_login')
def google_login():
    next_target = normalize_next_target(request.args.get("next"))
    template_id = normalize_template_id(request.args.get("template_id") or request.cookies.get("hs_template_id"))
    if "google" not in current_app.blueprints:
        flash("Google login is not configured right now. Please use email login.", "info")
        return redirect(url_for("auth.login", next=next_target))
    current_app.logger.info('[AUTH-DEBUG] CLIENT_ID=%r', os.getenv('GOOGLE_OAUTH_CLIENT_ID'))
    current_app.logger.info(
        '[AUTH-DEBUG] CLIENT_SECRET_SET=%s LEN=%d',
        bool(os.getenv('GOOGLE_OAUTH_CLIENT_SECRET')),
        len(os.getenv('GOOGLE_OAUTH_CLIENT_SECRET') or ''),
    )
    # Avoid wiping the full session; only clear stale Google OAuth artifacts.
    session.pop('google_oauth_token', None)
    session.pop('google_oauth_state', None)
    session['post_login_next'] = next_target
    if template_id:
        session["template_id"] = template_id
    response = redirect(url_for('google.login'))
    response.set_cookie(
        "hs_post_login_next",
        next_target,
        max_age=600,
        httponly=True,
        secure=_cookie_secure(),
        samesite=_cookie_samesite(),
        path="/",
    )
    if template_id:
        response.set_cookie(
            "hs_template_id",
            template_id,
            max_age=600,
            httponly=True,
            secure=_cookie_secure(),
            samesite=_cookie_samesite(),
            path="/",
        )
    return response


# ===============================
# EMAIL LOGIN
# ===============================
@auth.route('/login', methods=['GET', 'POST'])
def login():
    next_target = normalize_next_target(request.values.get('next'))
    template_id = normalize_template_id(request.values.get("template_id") or session.get("template_id") or request.cookies.get("hs_template_id"))
    if template_id:
        session["template_id"] = template_id
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password, password):
            flash('Invalid email or password.', 'error')
            return render_template('login.html', next_target=next_target, template_id=template_id)

        # Clear old session to avoid cached clips, but keep login intent context.
        preserved_template_id = template_id
        session.clear()
        login_user(user)
        session["user_id"] = user.id
        if preserved_template_id:
            session["template_id"] = preserved_template_id
        flash('Welcome back, HotCreator!', 'success')
        return build_post_login_redirect(next_target)

    return render_template('login.html', next_target=next_target, template_id=template_id)


# ===============================
# SIGNUP
# ===============================
@auth.route('/signup', methods=['GET', 'POST'])
def signup():
    next_target = normalize_next_target(request.values.get('next'))
    template_id = normalize_template_id(request.values.get("template_id") or session.get("template_id") or request.cookies.get("hs_template_id"))
    if template_id:
        session["template_id"] = template_id
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        # Validation
        if not email or not password:
            flash('Please fill all fields.', 'error')
            return render_template('signup.html', next_target=next_target, template_id=template_id)

        if User.query.filter_by(email=email).first():
            flash('This email is already registered.', 'error')
            return render_template('signup.html', next_target=next_target, template_id=template_id)

        hashed = generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)
        new_user = User(email=email, password=hashed)
        db.session.add(new_user)
        db.session.commit()

        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('auth.login', next=next_target, template_id=template_id or None))

    return render_template('signup.html', next_target=next_target, template_id=template_id)


# ===============================
# LOGOUT
# ===============================
@auth.route('/logout')
@login_required
def logout():
    # Clean up all session + user data
    session.clear()
    logout_user()
    flash('You have been logged out safely.', 'info')
    return redirect(url_for('auth.login'))


@auth.route('/session')
def session_status():
    from flask_login import current_user

    if not current_user.is_authenticated:
        return jsonify({"logged_in": False, "authenticated": False}), 200

    return jsonify({
        "logged_in": True,
        "authenticated": True,
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "name": current_user.name,
            "profile_pic": current_user.profile_pic,
            "plan_type": getattr(current_user, "plan_type", None),
        },
    }), 200
