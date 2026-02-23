from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from models.user import User, db

auth = Blueprint('auth', __name__)

# ===============================
# 🔑 GOOGLE LOGIN
# ===============================
@auth.route("/google_login")
def google_login():
    # 🧹 Clear old session data before logging in new user
    session.clear()
    return redirect(url_for("auth.google_login"))


# ===============================
# 🔐 EMAIL LOGIN
# ===============================
@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password, password):
            flash("Invalid email or password.", "error")
            return render_template('login.html')

        # ✅ Clear old session to avoid cached clips
        session.clear()
        login_user(user)
        flash("Welcome back, HotCreator 🔥", "success")
        return redirect(url_for('dashboard'))

    return render_template('login.html')


# ===============================
# 🆕 SIGNUP
# ===============================
@auth.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        # Validation
        if not email or not password:
            flash("Please fill all fields.", "error")
            return render_template('signup.html')

        if User.query.filter_by(email=email).first():
            flash("This email is already registered.", "error")
            return render_template('signup.html')

        hashed = generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)
        new_user = User(email=email, password=hashed)
        db.session.add(new_user)
        db.session.commit()

        flash("Account created successfully! Please log in.", "success")
        # return redirect(url_for('auth.login'))
        return redirect(url_for("auth.google_login"))


    return render_template('signup.html')


# ===============================
# 🚪 LOGOUT (FINAL VERSION)
# ===============================
@auth.route('/logout')
@login_required
def logout():
    # 🧹 Clean up all session + user data
    session.clear()
    logout_user()
    flash("You have been logged out safely. 👋", "info")
    return redirect(url_for('auth.login'))
