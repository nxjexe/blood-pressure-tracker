from flask import Flask, render_template, redirect, request, url_for, flash
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from zoneinfo import ZoneInfo
from io import StringIO
from flask_login import UserMixin, LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os # für Env-Variable
import pandas as pd

def custom_timezone_now():
    tz_name = os.getenv('APP_TZ', 'Europe/Berlin')
    return datetime.now(ZoneInfo(tz_name))

app = Flask(__name__)
app.secret_key = 'dev-key'  # Für flash; in Prod: os.getenv('SECRET_KEY')
engine = create_engine('sqlite:///bp.db')
Base = declarative_base()

class User(Base, UserMixin):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password = Column(String(255), nullable=False)  # Gehashtes PW

class BPLog(Base):
    __tablename__ = 'logs'
    id = Column(Integer, primary_key=True)
    sys = Column(Integer)
    dia = Column(Integer)
    pul = Column(Integer)
    comment = Column(String(255)) # Max 255 Zeichen
    time = Column(DateTime(timezone=True), default=custom_timezone_now)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)   # Jeder Log gehört zu einem User
    user = relationship('User', back_populates='logs')  # Beziehung: Ermöglicht Zugriff wie log.user

User.logs = relationship('BPLog', order_by=BPLog.id, back_populates='user') # Rückbeziehung

Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Redirect zu Login, wenn nicht angemeldet

@login_manager.user_loader
def load_user(user_id):
    session = Session()
    user = session.query(User).get(int(user_id))
    session.close()
    return user

@login_required
@app.route('/', methods=['GET', 'POST'])
def index():
    session = Session()
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    if request.method == 'POST':
        try:
            manual_time_str = request.form.get('manual_time', '')
            if manual_time_str:
                manual_time = datetime.fromisoformat(manual_time_str).replace(tzinfo=ZoneInfo('Europe/Berlin'))
            else:
                manual_time = custom_timezone_now()
            
            log = BPLog(
                sys=int(request.form.get('sys', 0)),
                dia=int(request.form.get('dia', 0)),
                pul=int(request.form.get('pul', 0)),
                comment=request.form.get('comment', ''), # Leerer String als Default
                time=manual_time
            )
            log.user_id = current_user.id
            session.add(log)
            session.commit()
            session.close()
            return redirect(url_for('index'))
        except (ValueError, TypeError):
            logs = session.query(BPLog).filter_by(user_id=current_user.id).order_by(BPLog.time.desc()).all()
            users = [] if current_user.id != 1 else session.query(User).all() # User Liste für Admin-Account
            session.close()
            return render_template('index.html', logs=logs, error="Ungültige Eingabe - bitte Zahlen und Datum eingeben.", users=users)
    logs = session.query(BPLog).filter_by(user_id=current_user.id).order_by(BPLog.time.desc()).all()
    users = [] if current_user.id != 1 else session.query(User).all() # User Liste für Admin-Account
    session.close()
    return render_template('index.html', logs=logs, error=None, users=users)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        session = Session()
        existing_user = session.query(User).filter_by(username=username).first()
        if existing_user:
            flash("Username existiert schon!", "error")
            session.close()
            return redirect(url_for('register'))
        hashed_pw = generate_password_hash(password)  # Sicheres Hashing
        user = User(username=username, password=hashed_pw)
        session.add(user)
        session.commit()
        session.close()
        flash("Registriert! Jetzt einloggen.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')  # Erstelle eine neue HTML-Vorlage mit Form (username, password)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        session = Session()
        user = session.query(User).filter_by(username=username).first()
        session.close()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('index'))
        flash("Falsche Daten!", "error")
        return redirect(url_for('login'))
    return render_template('login.html')  # Form: <input name="username"> <input name="password" type="password">

@app.route('/logout')
@login_required  # Nur für Eingeloggte
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if current_user.id != 1:  # Nur Admin (ID 1) darf löschen – passe an
        flash("Nicht autorisiert!", "error")
        return redirect(url_for('index'))
    session = Session()
    user = session.query(User).get(user_id)
    if user_id == current_user.id:
        flash("Selbstlöschung verboten!", "error")
        return redirect(url_for('index'))
    if user:
        # Logs zuerst löschen (Kaskade)
        session.query(BPLog).filter_by(user_id=user_id).delete()
        session.delete(user)
        session.commit()
    session.close()
    flash("User gelöscht.", "success")
    return redirect(url_for('index'))  # Oder zu Admin-Seite

# Bulk upload from CSV
@login_required
@app.route('/bulk_upload', methods=['POST'])
def bulk_upload():
    if 'file' not in request.files:
        flash("Keine Datei!", "error")
        return redirect(url_for('index'))
    file = request.files['file']
    if file.filename == '':
        flash("Keine Datei ausgewählt!", "error")
        return redirect(url_for('index'))
    try:
        # Pre-prozess: Lese als Text, clean trailing ';', dann parse
        file.seek(0)
        content = file.read().decode('utf-8')
        lines = content.splitlines()
        cleaned_lines = []
        for i, line in enumerate(lines):
            if i == 0:  # Header: Skip clean
                cleaned_lines.append(line)
            else:
                cleaned_line = line.rstrip(';').strip()  # Entferne trailing ';', clean Spaces
                cleaned_lines.append(cleaned_line)
        cleaned_content = '\n'.join(cleaned_lines)
        
        df = pd.read_csv(StringIO(cleaned_content), delimiter=';', encoding='utf-8', parse_dates=['time'])
        df.columns = df.columns.str.strip()  # Clean Header-Spaces
        print(df.head())  # Debug: Terminal zeigt DF
        count = 0
        session = Session()
        for _, row in df.iterrows():
            sys_val = pd.to_numeric(row.get('sys', 0), errors='coerce')
            dia_val = pd.to_numeric(row.get('dia', 0), errors='coerce')
            pul_val = pd.to_numeric(row.get('pul', 0), errors='coerce')
            comment_raw = row.get('comment')
            comment = '' if pd.isna(comment_raw) else str(comment_raw).strip().rstrip(';')  # NaN zu '', clean
            time_val = row.get('time')
            if pd.isna(sys_val) or pd.isna(dia_val) or pd.isna(pul_val):
                continue
            try:
                if pd.isna(time_val):
                    manual_time = custom_timezone_now()
                else:
                    manual_time = pd.to_datetime(time_val).tz_localize('Europe/Berlin')
                log = BPLog(
                    sys=int(sys_val),
                    dia=int(dia_val),
                    pul=int(pul_val),
                    comment=comment,
                    time=manual_time
                )
                log.user_id = current_user.id
                session.add(log)
                count += 1
            except ValueError as ve:
                app.logger.error(f"Parse-Fehler in Zeile: {ve}")
                continue
        session.commit()
        session.close()
        flash(f"{count} Einträge importiert!", "success")
    except Exception as e:
        app.logger.error(f"Bulk-Import-Fehler: {str(e)}")
        flash(f"Fehler: {str(e)}", "error")
    return redirect(url_for('index'))

@app.route('/delete/<int:log_id>', methods=['POST'])
def delete_log(log_id):
    session = Session()
    log = session.query(BPLog).get(log_id)
    if log:
        session.delete(log)
        session.commit()
    session.close()
    return redirect(url_for('index'))

@login_required
@app.route('/plot')
def plot():
    session = Session()
    logs = session.query(BPLog).filter(BPLog.user_id == current_user.id).order_by(BPLog.time.asc()).all()
    session.close()
    return render_template('plot.html', logs=logs)

if __name__ == '__main__':
    app.run(debug=True)