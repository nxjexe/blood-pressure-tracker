from flask import Flask, render_template, redirect, request, url_for, flash
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from zoneinfo import ZoneInfo
from io import StringIO
import os # für Env-Variable
import pandas as pd

def custom_timezone_now():
    tz_name = os.getenv('APP_TZ', 'Europe/Berlin')
    return datetime.now(ZoneInfo(tz_name))

app = Flask(__name__)
app.secret_key = 'dev-key'  # Für flash; in Prod: os.getenv('SECRET_KEY')
engine = create_engine('sqlite:///bp.db')
Base = declarative_base()
class BPLog(Base):
    __tablename__ = 'logs'
    id = Column(Integer, primary_key=True)
    sys = Column(Integer)
    dia = Column(Integer)
    pul = Column(Integer)
    comment = Column(String(255)) # Max 255 Zeichen
    time = Column(DateTime(timezone=True), default=custom_timezone_now)


Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

@app.route('/', methods=['GET', 'POST'])
def index():
    session = Session()
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
            session.add(log)
            session.commit()
            session.close()
            return redirect(url_for('index'))
        except (ValueError, TypeError):
            logs = session.query(BPLog).order_by(BPLog.time.desc()).all()
            session.close()
            return render_template('index.html', logs=logs, error="Ungültige Eingabe - bitte Zahlen und Datum eingeben.")
    logs = session.query(BPLog).order_by(BPLog.time.desc()).all()
    session.close()
    return render_template('index.html', logs=logs, error=None)

# Bulk upload from CSV
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

@app.route('/plot')
def plot():
    session = Session()
    logs = session.query(BPLog).order_by(BPLog.time.asc()).all()
    session.close()
    return render_template('plot.html', logs=logs)

if __name__ == '__main__':
    app.run(debug=True)