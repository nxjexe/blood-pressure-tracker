from flask import Flask, render_template, redirect, request, url_for
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from zoneinfo import ZoneInfo
import os # für Env-Variable

def custom_timezone_now():
    tz_name = os.getenv('APP_TZ', 'Europe/Berlin')
    return datetime.now(ZoneInfo(tz_name))

app = Flask(__name__)
engine = create_engine('sqlite:///bp.db')
Base = declarative_base()
class BPLog(Base):
    __tablename__ = 'logs'
    id = Column(Integer, primary_key=True)
    sys = Column(Integer)
    dia = Column(Integer)
    pulse = Column(Integer)
    comment = Column(String(255)) # Max 255 Zeichen
    time = Column(DateTime(timezone=True), default=custom_timezone_now)


Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

@app.route('/', methods=['GET', 'POST'])
def home():
    session = Session()
    if request.method == 'POST':
        try:
            log = BPLog(
                sys=int(request.form.get('sys', 0)),
                dia=int(request.form.get('dia', 0)),
                pulse=int(request.form.get('pulse', 0)),
                comment=request.form.get('comment', '') # Leerer String als Default
            )
            session.add(log)
            session.commit()
            session.close()
            return redirect(url_for('home'))
        except ValueError:
            logs = session.query(BPLog).all()
            session.close()
            return render_template('index.html', logs=logs, error="Bitte gültige Zahlen eingeben.")
    logs = session.query(BPLog).all()
    session.close()
    return render_template('index.html', logs=logs, error=None) # prüfe, ob du error=None weglassen kannst

@app.route('/delete/<int:log_id>', methods=['POST'])
def delete_log(log_id):
    session = Session()
    log = session.query(BPLog).get(log_id)
    if log:
        session.delete(log)
        session.commit()
    session.close()
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)