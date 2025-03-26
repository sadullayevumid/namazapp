from flask import Flask, render_template, redirect, url_for, flash, request
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_migrate import Migrate
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user, current_user
import requests
from models import Prayer  # Prayer modelini import qilish
from models import db, User, Prayer
from datetime import datetime
from telebot import TeleBot, types
import os


  # Shu yerga web sahifang URLini qo‘y




# SQLAlchemy obyektini yaratish
db = SQLAlchemy()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'supersecretkey'

# Kutubxonalarni ilovaga bog‘lash
db.init_app(app)
bcrypt = Bcrypt(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# O‘zbekiston shaharlari
CITIES = ["Toshkent", "Samarqand", "Buxoro", "Xiva", "Namangan", "Andijon", "Farg‘ona", "Qo‘qon", "Navoiy", "Qarshi", "Jizzax"]


# Namozlarni saqlash modeli
class Prayer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    fajr = db.Column(db.Boolean, default=False)
    dhuhr = db.Column(db.Boolean, default=False)
    asr = db.Column(db.Boolean, default=False)
    maghrib = db.Column(db.Boolean, default=False)
    isha = db.Column(db.Boolean, default=False)

# Namoz tahlili sahifasi
@app.route('/prayer-analysis', methods=['GET', 'POST'])
@login_required
def prayer_analysis():
    prayers = []
    
    start_date = None
    end_date = None
    
    if request.method == 'POST':
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')

        if start_date and end_date:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            prayers = Prayer.query.filter(
                Prayer.user_id == current_user.id,
                Prayer.date >= start_date,
                Prayer.date <= end_date
            ).all()
    
    return render_template('prayer_analysis.html', prayers=prayers, start_date=start_date, end_date=end_date)

@app.route('/api/prayer-calendar')
@login_required
def prayer_calendar():
    # Oxirgi 3 oy va keyingi 3 oy uchun kalendar ma'lumotlari
    today = datetime.today().date()
    start_date = today - timedelta(days=90)
    end_date = today + timedelta(days=90)
    
    # Namoz ma'lumotlarini bazadan olish
    prayers = Prayer.query.filter(
        Prayer.user_id == current_user.id,
        Prayer.date.between(start_date, end_date)
    ).all()
    
    # Kalendar ma'lumotlarini tayyorlash
    calendar_data = []
    current_month = None
    
    for day in (today + timedelta(days=n) for n in range(-90, 90)):
        month_name = day.strftime("%B %Y")
        if month_name != current_month:
            current_month = month_name
            calendar_data.append({
                "name": month_name,
                "days": []
            })
        
        prayer = next((p for p in prayers if p.date == day), None)
        status = "none"
        
        if prayer:
            if all([prayer.fajr, prayer.dhuhr, prayer.asr, prayer.maghrib, prayer.isha]):
                status = "complete"
            elif any([prayer.fajr, prayer.dhuhr, prayer.asr, prayer.maghrib, prayer.isha]):
                status = "incomplete"
        
        calendar_data[-1]["days"].append({
            "day": day.day,
            "date": day.isoformat(),
            "status": status
        })
    
    return jsonify({"months": calendar_data})

@app.route('/api/prayer-data')
@login_required
def prayer_data():
    try:
        # 1. Sana parametrini olish va tekshirish
        date_str = request.args.get('date')
        if not date_str:
            return jsonify({
                "success": False,
                "error": "missing_date",
                "message": "Iltimos, sana parametrini yuboring"
            }), 400

        # 2. Sana formatini tekshirish
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({
                "success": False,
                "error": "invalid_date_format",
                "message": "Sana noto'g'ri formatda. 'YYYY-MM-DD' formatida bo'lishi kerak"
            }), 400

        # 3. Foydalanuvchining mintaqasini olish
        if not current_user.region:
            return jsonify({
                "success": False,
                "error": "region_not_set",
                "message": "Foydalanuvchi mintaqasi aniqlanmagan. Iltimos, profilni yangilang"
            }), 400

        # 4. Namoz vaqtlarini API dan olish
        try:
            prayer_times = get_prayer_times(current_user.region, date)
            if not prayer_times:
                raise ValueError("Namoz vaqtlari API dan olinmadi")
        except Exception as e:
            return jsonify({
                "success": False,
                "error": "prayer_times_error",
                "message": f"Namoz vaqtlarini olishda xatolik: {str(e)}"
            }), 500

        # 5. Bazadan namoz ma'lumotlarini olish
        prayer = db.session.query(Prayer).filter(
            Prayer.user_id == current_user.id,
            Prayer.date == date
        ).first()

        # 6. Agar ma'lumot topilmasa, standart javob
        if not prayer:
            return jsonify({
                "success": True,
                "exists": False,
                "message": f"{date} sanasida namoz ma'lumotlari topilmadi",
                "date": date_str,
                "prayer": {
                    "Bomdod": {"status": False, "time": prayer_times.get('Bomdod', "Noma'lum")},
                    "Peshin": {"status": False, "time": prayer_times.get('Peshin', "Noma'lum")},
                    "Asr": {"status": False, "time": prayer_times.get('Asr', "Noma'lum")},
                    "Shom": {"status": False, "time": prayer_times.get('Shom', "Noma'lum")},
                    "Xufton": {"status": False, "time": prayer_times.get('Xufton', "Noma'lum")}
                }
            })

        # 7. Muvaffaqiyatli javobni tayyorlash
        response_data = {
            "success": True,
            "exists": True,
            "message": f"{date} sanasidagi namoz ma'lumotlari topildi",
            "date": date_str,
            "prayer": {
                "Bomdod": {
                    "status": prayer.fajr,
                    "time": prayer_times.get('Bomdod', "Noma'lum")
                },
                "Peshin": {
                    "status": prayer.dhuhr,
                    "time": prayer_times.get('Peshin', "Noma'lum")
                },
                "Asr": {
                    "status": prayer.asr,
                    "time": prayer_times.get('Asr', "Noma'lum")
                },
                "Shom": {
                    "status": prayer.maghrib,
                    "time": prayer_times.get('Shom', "Noma'lum")
                },
                "Xufton": {
                    "status": prayer.isha,
                    "time": prayer_times.get('Xufton', "Noma'lum")
                }
            }
        }

        return jsonify(response_data)

    except Exception as e:
        # 8. Kutilmagan xatolarni qayta ishlash
        return jsonify({
            "success": False,
            "error": "server_error",
            "message": f"Server xatosi: {str(e)}"
        }), 500

        return jsonify(response_data)

    except Exception as e:
        # Har qanday kutilmagan xatolikni qaytarish
        app.logger.error(f"Error in prayer_data: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error",
            "message": "Serverda ichki xatolik yuz berdi"
        }), 500


def get_prayer_times(region, date):
    """Namoz vaqtlarini API orqali olish"""
    try:
        if not region:
            return None
            
        date_str = date.strftime("%d-%m-%Y")
        url = f"https://api.aladhan.com/v1/timingsByCity/{date_str}?city={region}&country=Uzbekistan&method=2"
        
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        timings = data.get("data", {}).get("timings", {})
        
        return {
            "Bomdod": timings.get("Fajr", "Noma'lum"),
            "Peshin": timings.get("Dhuhr", "Noma'lum"),
            "Asr": timings.get("Asr", "Noma'lum"),
            "Shom": timings.get("Maghrib", "Noma'lum"),
            "Xufton": timings.get("Isha", "Noma'lum")
        }
        
    except Exception as e:
        app.logger.error(f"Error getting prayer times: {str(e)}")
        return None

@app.route('/mark-prayer', methods=['GET', 'POST'])
@login_required
def mark_prayer():
    region = current_user.region
    prayer_times = get_prayer_times(region)  # API orqali namoz vaqtlarini olish

    if not prayer_times:
        flash("Namoz vaqtlari yuklanmadi, iltimos qayta urinib ko'ring!", "danger")
        return redirect(url_for("dashboard"))

    current_time = datetime.now().strftime("%H:%M")
    current_date = datetime.now().strftime("%Y-%m-%d")
    today = datetime.today().date()

    # Bugungi belgilangan namozlarni olamiz
    today_prayer = Prayer.query.filter_by(user_id=current_user.id, date=today).first()

    if request.method == 'POST':
        # Faqat vaqti o'tgan namozlarni olamiz
        selected_prayers = request.form.getlist('prayer')
        
        if today_prayer:
            # Faqat yangi belgilangan namozlarni qo'shamiz
            if 'Bomdod' in selected_prayers and not today_prayer.fajr:
                today_prayer.fajr = True
            if 'Peshin' in selected_prayers and not today_prayer.dhuhr:
                today_prayer.dhuhr = True
            if 'Asr' in selected_prayers and not today_prayer.asr:
                today_prayer.asr = True
            if 'Shom' in selected_prayers and not today_prayer.maghrib:
                today_prayer.maghrib = True
            if 'Xufton' in selected_prayers and not today_prayer.isha:
                today_prayer.isha = True
        else:
            # Yangi yozuv yaratamiz
            new_prayer = Prayer(
                user_id=current_user.id,
                date=today,
                fajr='Bomdod' in selected_prayers,
                dhuhr='Peshin' in selected_prayers,
                asr='Asr' in selected_prayers,
                maghrib='Shom' in selected_prayers,
                isha='Xufton' in selected_prayers
            )
            db.session.add(new_prayer)

        db.session.commit()
        flash("Namoz belgilandi!", "success")
        return redirect(url_for('dashboard'))

    # Faqat vaqti o'tgan va belgilanmagan namozlarni olamiz
    available_prayers = {}
    for name, time in prayer_times.items():
        prayer_hour, prayer_minute = map(int, time.split(':'))
        current_hour, current_minute = map(int, current_time.split(':'))
        
        # Vaqti o'tganligini tekshiramiz
        time_passed = (prayer_hour < current_hour) or \
                     (prayer_hour == current_hour and prayer_minute <= current_minute)
        
        # Belgilanmaganligini tekshiramiz
        not_marked = not today_prayer or not getattr(today_prayer, name.lower(), False)
        
        if time_passed and not_marked:
            available_prayers[name] = time

    return render_template('mark_prayer.html', 
                         prayer_times=prayer_times,
                         available_prayers=available_prayers,
                         current_time=current_time,
                         current_date=current_date,
                         today_prayer=today_prayer)
    
# Foydalanuvchi modeli
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    region = db.Column(db.String(100), nullable=True)
    prayers = db.relationship('Prayer', backref='user', lazy=True)

    def set_password(self, password):
        self.password = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password, password)

import requests
from datetime import datetime

def get_prayer_times(region, date=None):
    """
    Berilgan shahar va sana uchun namoz vaqtlarini qaytaradi
    
    :param region: Namoz vaqtlari olinadigan shahar (masalan, 'Tashkent')
    :param date: Sana (format: 'DD-MM-YYYY'). Agar None bo'lsa, bugungi sana ishlatiladi
    :return: Namoz vaqtlari lug'ati yoki None (agar xato bo'lsa)
    """
    if date is None:
        date = datetime.now().strftime("%d-%m-%Y")
    
    url = f"https://api.aladhan.com/v1/timingsByCity/{date}?city={region}&country=Uzbekistan&method=2"
    
    try:
        response = requests.get(url)
        response.raise_for_status()  # HTTP xatolarni tekshiradi
        
        data = response.json()
        timings = data["data"]["timings"]
        
        prayer_times = {
            "Bomdod": timings["Fajr"],
            "Quyosh": timings["Sunrise"],  # Qo'shimcha ma'lumot
            "Peshin": timings["Dhuhr"],
            "Asr": timings["Asr"],
            "Shom": timings["Maghrib"],
            "Xufton": timings["Isha"]
        }
        return prayer_times
    
    except requests.exceptions.RequestException as e:
        print(f"API so'rovi xatosi: {e}")
        return None
    except (KeyError, ValueError) as e:
        print(f"Ma'lumotlarni qayta ishlash xatosi: {e}")
        return None


from flask import request, jsonify

@app.route('/dashboard')
@login_required
def dashboard():
    region = current_user.region  # Foydalanuvchining tanlagan hududi
    prayer_times = get_prayer_times(region)  # API orqali namoz vaqtlarini olish
    
    today = datetime.today().date()  # Bugungi sana
    today_prayer = Prayer.query.filter_by(user_id=current_user.id, date=today).first()  # Bugungi namozlar
    
    # Agar so'rov JSON formatda bo'lsa, JSON ma'lumot qaytarish
    if request.headers.get('Accept') == 'application/json':
        return jsonify({
            "region": region,
            "prayer_times": prayer_times,
            "today_prayer": {
                "fajr": today_prayer.fajr if today_prayer else False,
                "dhuhr": today_prayer.dhuhr if today_prayer else False,
                "asr": today_prayer.asr if today_prayer else False,
                "maghrib": today_prayer.maghrib if today_prayer else False,
                "isha": today_prayer.isha if today_prayer else False
            }
        })
    
    return render_template('dashboard.html', prayer_times=prayer_times, region=region, today_prayer=today_prayer)

@app.route('/save-prayer', methods=['POST'])
@login_required
def save_prayer():
    today = datetime.today().date()
    existing_prayer = Prayer.query.filter_by(user_id=current_user.id, date=today).first()

    # Belgilangan namozlarni olamiz
    selected_prayers = request.form.getlist('prayer')
    
    # Agar allaqachon barcha namozlar belgilangan bo'lsa
    if existing_prayer and all([existing_prayer.fajr, existing_prayer.dhuhr,
                              existing_prayer.asr, existing_prayer.maghrib, existing_prayer.isha]):
        flash('Bugungi barcha namozlaringiz allaqachon belgilangan!', 'info')
        return redirect(url_for('dashboard'))

    if existing_prayer:
        # Faqat yangi belgilangan namozlarni qo'shamiz
        if 'Bomdod' in selected_prayers and not existing_prayer.fajr:
            existing_prayer.fajr = True
        if 'Peshin' in selected_prayers and not existing_prayer.dhuhr:
            existing_prayer.dhuhr = True
        if 'Asr' in selected_prayers and not existing_prayer.asr:
            existing_prayer.asr = True
        if 'Shom' in selected_prayers and not existing_prayer.maghrib:
            existing_prayer.maghrib = True
        if 'Xufton' in selected_prayers and not existing_prayer.isha:
            existing_prayer.isha = True
        
        # Agar hech qanday yangi namoz belgilanmagan bo'lsa
        if not any(selected_prayers):
            flash('Hech qanday namoz belgilanmadi!', 'warning')
            return redirect(url_for('mark_prayer'))
    else:
        # Yangi yozuv yaratamiz
        new_prayer = Prayer(
            user_id=current_user.id,
            date=today,
            fajr='Bomdod' in selected_prayers,
            dhuhr='Peshin' in selected_prayers,
            asr='Asr' in selected_prayers,
            maghrib='Shom' in selected_prayers,
            isha='Xufton' in selected_prayers
        )
        db.session.add(new_prayer)

    db.session.commit()
    
    # Agar barcha namozlar belgilangan bo'lsa
    updated_prayer = Prayer.query.filter_by(user_id=current_user.id, date=today).first()
    if all([updated_prayer.fajr, updated_prayer.dhuhr,
           updated_prayer.asr, updated_prayer.maghrib, updated_prayer.isha]):
        flash('Barcha namozlar muvaffaqiyatli belgilandi!', 'success')
    else:
        flash('Namozlar muvaffaqiyatli saqlandi!', 'success')
    
    return redirect(url_for('dashboard'))
    
    
# Bazani yaratish yoki mavjudligini tekshirish
with app.app_context():
    db.create_all()
    print("✅ Baza yaratildi yoki allaqachon mavjud!")


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Ro‘yxatdan o‘tish
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        region = request.form.get('region', 'tashkent')  # Default hudud

        # Takroriy username va emailni tekshirish
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Bu foydalanuvchi nomi allaqachon mavjud!', 'danger')
            return redirect(url_for('register'))

        existing_email = User.query.filter_by(email=email).first()
        if existing_email:
            flash('Bu email allaqachon ishlatilgan!', 'danger')
            return redirect(url_for('register'))

        new_user = User(username=username, email=email, region=region)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash('Ro‘yxatdan muvaffaqiyatli o‘tdingiz! Endi tizimga kiring.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

# Login qilish
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            flash('Tizimga muvaffaqiyatli kirdingiz!', 'success')
            return redirect(url_for('dashboard'))  # Login muvaffaqiyatli bo'lsa dashboardga o'tkaziladi
        else:
            flash('Login yoki parol noto‘g‘ri!', 'danger')  # Faqat login sahifasida chiqadi

    return render_template('login.html')

# Logout qilish
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Tizimdan chiqdingiz!', 'info')
    return redirect(url_for('login'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        new_region = request.form.get('region')
        new_language = request.form.get('language')

        # Foydalanuvchi ma’lumotlarini yangilash
        current_user.region = new_region
        current_user.language = new_language
        db.session.commit()

        flash("Muvaffaqiyatli saqlandi!", "success")
        return redirect(url_for('settings'))

    return render_template('settings.html')




# Asosiy sahifa
@app.route('/')
def home():
    return redirect(url_for('login'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Baza yaratish
    app.run(debug=True)
