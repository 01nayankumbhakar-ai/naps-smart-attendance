NAPS TRAINEE ATTENDANCE SYSTEM
==============================

FEATURES
- Admin login and trainee login (mobile number + password)
- Admin can create trainee accounts and record punch in/out
- Trainees can punch in/out from mobile browser
- A Shift: 05:45 AM to 02:10 PM
- B Shift: 02:10 PM to 10:40 PM
- GPS geofence verification for trainee self punch
- Late flag, monthly report, CSV export (Excel mein khul jayega)
- Attendance database SQLite mein save hota hai

INSTALLATION (Windows)
1. Python 3.10+ install karein.
2. Is folder mein Command Prompt / Terminal kholein.
3. Run: py -m venv venv
4. Run: venv\Scripts\activate
5. Run: pip install -r requirements.txt
6. Company GPS coordinates set karein (neeche dekhein).
7. Admin credentials set karein:
   set ADMIN_MOBILE=apna_admin_mobile
   set ADMIN_PASSWORD=ek_strong_password
   set FLASK_SECRET_KEY=ek_lambi_random_secret_key
8. Run: python app.py
9. Browser: http://127.0.0.1:5000

DEFAULT ADMIN (sirf first local test ke liye)
Mobile: 9999999999
Password: ChangeMe123!
Production se pehle environment variables se credentials badlein.
Agar database pehle hi default admin ke saath ban chuka hai, to credentials
badalne ke liye database mein admin password reset karna hoga ya fresh test
database banayein. Real deployment mein default credentials kabhi na rakhein.

GPS SETUP
Company ke exact latitude/longitude environment variables mein set karein:
Windows CMD:
set COMPANY_LAT=26.123456
set COMPANY_LON=87.123456
set GPS_RADIUS_METERS=150

Coordinates example ke liye placeholder hain - apni company ke verified
coordinates hi daalein. Latitude/longitude Google Maps se company gate par
tap karke mil sakte hain. GPS browser permission ke liye deployed website
HTTPS par honi chahiye (localhost testing exception). Geofence radius ko
workplace ke hisaab se set karein.

IMPORTANT
- GPS spoofing ko browser GPS akela poori tarah prevent nahi karta.
- Admin-entered punch records ko admin method ke roop mein mark kiya jata hai.
- Is starter project mein password hashes use hote hain, plain-text passwords nahi.
- Public deployment se pehle HTTPS, strong FLASK_SECRET_KEY, secure hosting,
  regular database backup, admin account security, privacy notice aur testing
  zaroor karein.
- Current version mein ek trainee ke liye ek duty_date par ek attendance
  record hai. Overnight shift ya multiple sessions chahiye hon to logic badalna hoga.
- Late mark shift ke scheduled start ke baad lagta hai; grace period abhi 0 minute hai.
