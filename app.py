import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# MongoDB Connection
client = MongoClient(os.getenv("MONGO_URI"))
db = client['digital_invitation']
users_collection = db.users
invitations_collection = db.invitations
events_collection = db.events

UPLOAD_FOLDER = 'static/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
# --- DECORATORS (Role & Auth Protection) ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash("Please log in first.", "danger")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session or session['user']['role'] not in roles:
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# --- ROUTES ---

@app.route('/')
def home():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/invitation/<id>')
def invitation(id):
    invite = invitations_collection.find_one({"_id": ObjectId(id)})
    if not invite:
        return "Invitation Not Found", 404
    return render_template('invitation.html', invite=invite)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'user')
        
        if users_collection.find_one({"email": email}):
            flash("Email already exists!", "danger")
            return redirect(url_for('register'))
            
        hashed_password = generate_password_hash(password)
        users_collection.insert_one({
            "username": username,
            "email": email,
            "password": hashed_password,
            "role": role
        })
        flash("Registration successful! Please login.", "success")
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = users_collection.find_one({"email": email})
        if user and check_password_hash(user['password'], password):
            session['user'] = {
                "id": str(user['_id']),
                "username": user['username'],
                "email": user['email'],
                "role": user['role']
            }
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid email or password.", "danger")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash("You have been logged out.", "success")
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=session['user'])

@app.route('/manage', methods=['GET', 'POST'])
@login_required
@roles_required('superadmin', 'admin', 'usher')
def manage_data():
    current_role = session['user']['role']
    username = session['user']['username']
    
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        
        # A. FITUR CREATE EVENT
        if form_type == 'create_event':
            event_name = request.form.get('event_name')
            event_date = request.form.get('event_date')
            event_time = request.form.get('event_time', '10:00 - 13:00')
            event_location = request.form.get('event_location', 'Gedung Pertemuan Utama')
            event_logo = request.form.get('event_logo', '🎉') # default berupa emoji jika kosong
            
            status = '❓' if current_role == 'admin' else '✅'
            
            events_collection.insert_one({
                "event_name": event_name,
                "event_date": event_date,
                "event_time": event_time,
                "event_location": event_location,
                "event_logo": event_logo,
                "status": status,
                "created_by": username
            })
            flash("Event created successfully!", "success")
            return redirect(url_for('manage_data'))
            
        # B. FITUR CREATE INVITATION (Admin & Superadmin)
        elif form_type == 'create_invitation':
            if current_role not in ['superadmin', 'admin']:
                flash("Unauthorized.", "danger")
                return redirect(url_for('manage_data'))
                
            event_id = request.form.get('event_id')
            guest_name = request.form.get('guest_name')
            
            # Pengamanan query: Jika dia admin, pastikan acara tersebut miliknya sendiri
            query = {"_id": ObjectId(event_id)}
            if current_role == 'admin':
                query["created_by"] = username

            selected_event = events_collection.find_one(query)
            
            if selected_event:
                invitations_collection.insert_one({
                    "event_id": ObjectId(event_id),
                    "title": selected_event['event_name'],
                    "date": selected_event['event_date'],
                    "guest_name": guest_name,
                    "status": "Active",
                    "created_by": username # Menyimpan siapa yang generate undangan (opsional)
                })
                flash("Invitation generated successfully!", "success")
            else:
                flash("Acara tidak ditemukan atau Anda tidak memiliki hak akses untuk acara ini.", "danger")
                
            return redirect(url_for('manage_data'))
        
        # C. FITUR EDIT EVENT
        if form_type == 'edit_event':
            event_id = request.form.get('event_id')
            event_name = request.form.get('event_name')
            event_date = request.form.get('event_date')
            event_time = request.form.get('event_time')
            event_location = request.form.get('event_location')
            status = request.form.get('status')
            
            # Ambil data lama terlebih dahulu agar jika tidak upload gambar baru, logo lama tidak hilang
            current_event = events_collection.find_one({"_id": ObjectId(event_id)})
            event_logo_path = current_event.get('event_logo', '🎉') if current_event else '🎉'
            
            # PROSES UPLOAD GAMBAR LOGO
            if 'event_logo' in request.files:
                file = request.files['event_logo']
                if file and file.filename != '':
                    # Simpan file ke dalam folder static/uploads
                    filename = f"logo_{event_id}_{file.filename}"
                    file_path = os.path.join(UPLOAD_FOLDER, filename)
                    file.save(file_path)
                    # Simpan path yang bisa diakses oleh browser ke database
                    event_logo_path = f"/{UPLOAD_FOLDER}/{filename}"
            
            # Update ke MongoDB
            events_collection.update_one(
                {"_id": ObjectId(event_id)},
                {"$set": {
                    "event_name": event_name,
                    "event_date": event_date,
                    "event_time": event_time,
                    "event_location": event_location,
                    "event_logo": event_logo_path,
                    "status": status
                }}
            )
            flash("Event berhasil diperbarui!", "success")
            return redirect(url_for('manage_data'))

        # D. FITUR EDIT INVITATION (Saves Edit Modal)
        elif form_type == 'edit_invitation':
            invite_id = request.form.get('invite_id')
            invitations_collection.update_one(
                {"_id": ObjectId(invite_id)},
                {"$set": {
                    "guest_name": request.form.get('guest_name'),
                    "status": request.form.get('status')
                }}
            )
            flash("Invitation record updated successfully!", "success")
            return redirect(url_for('manage_data'))

    # ==========================================
    # READ DATA UNTUK DITAMPILKAN DI HALAMAN
    # ==========================================
    
    # 1. Filter Event List berdasarkan Role
    if current_role == 'admin':
        # Admin hanya bisa melihat list acara yang dia buat sendiri
        all_events = list(events_collection.find({"created_by": username}))
    else:
        # Superadmin dan Usher tetap bisa melihat semua acara
        all_events = list(events_collection.find())
    
    # 2. Filter Dropdown Pilihan Acara saat Membuat Undangan
    if current_role == 'admin':
        dropdown_events = list(events_collection.find({
            "created_by": username,
            "status": {"$in": ["✅", "❓", "❗"]}
        }))
    elif current_role == 'superadmin':
        dropdown_events = list(events_collection.find({"status": "✅"}))
    else:
        dropdown_events = []
    
    # 3. PERBAIKAN UTAMA: Filter Generated Invitations (Daftar Tamu Undangan)
    if current_role == 'admin':
        # Langkah A: Ambil semua ID acara (_id) yang dibuat oleh admin yang sedang login
        admin_event_ids = [ev['_id'] for ev in all_events]
        
        # Langkah B: Hanya tampilkan undangan yang field 'event_id'-nya ada di dalam list ID acara milik admin ini
        invitations = list(invitations_collection.find({
            "event_id": {"$in": admin_event_ids}
        }))
    else:
        # Superadmin dan Usher tetap bisa memantau dan melihat semua daftar undangan secara global
        invitations = list(invitations_collection.find())
    
    # --- MODIFIKASI TERBARU (Filter Berdasarkan Pembuat Acara) ---
    if current_role == 'admin':
        # Admin hanya bisa memilih acara miliknya sendiri yang berstatus ✅, ❓, atau ❗
        dropdown_events = list(events_collection.find({
            "created_by": username,
            "status": {"$in": ["✅", "❓", "❗"]}
        }))
    elif current_role == 'superadmin':
        # Superadmin bisa melihat semua acara yang sudah Approved (✅) untuk dibuatkan undangan
        dropdown_events = list(events_collection.find({"status": "✅"}))
    else:
        # Role lainnya (seperti usher) tidak melihat opsi apa-apa atau kosong
        dropdown_events = []
    
    # --- PROSES FILTER TAMU UNDANGAN (DIPERBAIKI) ---
    if current_role == 'admin':
        # Ambil semua ID acara milik admin yang sedang login saat ini
        admin_event_ids = [ev['_id'] for ev in all_events]
        # Hanya ambil undangan yang terikat dengan ID acara milik admin ini
        invitations = list(invitations_collection.find({
            "event_id": {"$in": admin_event_ids}
        }))
    else:
        # Superadmin dan Usher tetap bisa memantau semua undangan secara global
        invitations = list(invitations_collection.find())
    
    return render_template(
        'manage_data.html', 
        events=all_events, 
        approved_events=dropdown_events, 
        invitations=invitations, 
        role=current_role
    )

# ==========================================
# --- Superadmin ---
# ==========================================

@app.route('/approve-event/<id>')
@login_required
@roles_required('superadmin')
def approve_event(id):
    """Superadmin menyetujui proposal acara baru dari Admin"""
    events_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "✅"}}
    )
    flash("Proposal acara berhasil disetujui!", "success")
    return redirect(url_for('manage_data'))

@app.route('/approve-delete-event/<id>')
@login_required
@roles_required('superadmin')
def approve_delete_event(id):
    """Superadmin menyetujui permintaan hapus acara dari Admin"""
    event_oid = ObjectId(id)
    
    # 1. Hapus semua undangan yang memiliki event_id terkait
    invitations_collection.delete_many({"event_id": event_oid})
    
    # 2. Hapus dokumen acara
    events_collection.delete_one({"_id": event_oid})
    
    flash("Permintaan hapus disetujui, acara dan daftar undangan dihapus permanen.", "success")
    return redirect(url_for('manage_data'))

@app.route('/reject-delete-event/<id>')
@login_required
@roles_required('superadmin')
def reject_delete_event(id):
    """Superadmin menolak permohonan hapus acara, status kembali Approved"""
    events_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "✅"}, "$unset": {"requested_by": ""}}
    )
    flash("Permintaan hapus acara ditolak. Acara tetap aktif.", "success")
    return redirect(url_for('manage_data'))

@app.route('/delete-event/<id>')
@login_required
@roles_required('superadmin')
def delete_event(id):
    """Direct Delete Event / Reject Proposal baru oleh Superadmin"""
    event_oid = ObjectId(id)
    
    # 1. Hapus semua undangan yang memiliki event_id terkait
    invitations_collection.delete_many({"event_id": event_oid})
    
    # 2. Hapus dokumen acara
    events_collection.delete_one({"_id": event_oid})
    
    flash("Acara dan daftar undangan berhasil dihapus permanen oleh Superadmin.", "success")
    return redirect(url_for('manage_data'))

@app.route('/reject-delete/<id>')
@login_required
@roles_required('superadmin')
def reject_delete(id):
    invitations_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "Active"}, "$unset": {"requested_by": ""}}
    )
    flash("Deletion request rejected. Invitation is now active.", "success")
    return redirect(url_for('manage_data'))

@app.route('/delete/<id>')
@login_required
@roles_required('superadmin')
def delete_data(id):
    # Superadmin menyetujui hapus undangan (Langsung hapus permanen)
    invitations_collection.delete_one({"_id": ObjectId(id)})
    flash("Invitation deleted permanently!", "success")
    return redirect(url_for('manage_data'))

## Admin

@app.route('/request-delete-event/<id>')
@login_required
@roles_required('admin')
def request_delete_event(id):
    """Admin mengajukan permohonan hapus acara yang sudah Approved"""
    events_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "❗", "requested_by": session['user']['username']}}
    )
    flash("Permintaan hapus acara telah dikirim ke Superadmin.", "success")
    return redirect(url_for('manage_data'))

@app.route('/cancel-event-proposal/<id>')
@login_required
@roles_required('admin')
def cancel_event_proposal(id):
    """Admin membatalkan proposal acara sebelum di-approve superadmin"""
    event_oid = ObjectId(id)
    current_username = session['user']['username']
    
    # Pastikan proposal ini memang milik admin yang sedang login
    event = events_collection.find_one({"_id": event_oid, "created_by": current_username, "status": "❓"})
    
    if not event:
        flash("Anda tidak memiliki akses untuk membatalkan proposal milik admin lain.", "danger")
        return redirect(url_for('manage_data'))
        
    # 1. Hapus semua undangan yang terikat dengan event_id ini
    invitations_collection.delete_many({"event_id": event_oid})
    
    # 2. Hapus proposal acara
    events_collection.delete_one({"_id": event_oid})
    
    flash("Proposal acara dan daftar undangan terkait berhasil dibatalkan.", "success")
    return redirect(url_for('manage_data'))

@app.route('/cancel-delete-event-request/<id>')
@login_required
@roles_required('admin')
def cancel_delete_event_request(id):
    """Admin membatalkan permintaan hapus acara (mengembalikan status menjadi Approved)"""
    events_collection.update_one(
        {"_id": ObjectId(id), "status": "❗"},
        {"$set": {"status": "✅"}, "$unset": {"requested_by": ""}}
    )
    flash("Permintaan hapus acara berhasil dibatalkan. Acara kembali aktif.", "success")
    return redirect(url_for('manage_data'))

@app.route('/request-delete/<id>')
@login_required
@roles_required('admin')
def request_delete(id):
    """Admin mengajukan permohonan hapus undangan yang aktif milik acaranya sendiri"""
    invitation_oid = ObjectId(id)
    username = session['user']['username']
    
    # Ambil data undangan terlebih dahulu
    invite = invitations_collection.find_one({"_id": invitation_oid})
    if not invite:
        flash("Undangan tidak ditemukan.", "danger")
        return redirect(url_for('manage_data'))
        
    # Pastikan acara dari undangan tersebut adalah milik admin yang sedang login
    event = events_collection.find_one({"_id": invite['event_id'], "created_by": username})
    if not event:
        flash("Anda tidak memiliki hak akses untuk meminta penghapusan undangan ini.", "danger")
        return redirect(url_for('manage_data'))
        
    invitations_collection.update_one(
        {"_id": invitation_oid},
        {"$set": {"status": "❗", "requested_by": username}}
    )
    flash("Permintaan hapus undangan telah dikirim ke Superadmin.", "success")
    return redirect(url_for('manage_data'))

@app.route('/cancel-delete-request/<id>')
@login_required
@roles_required('admin')
def cancel_delete_request(id):
    """Admin membatalkan permintaan hapus undangan yang terlanjur dikirim"""
    invitation_oid = ObjectId(id)
    username = session['user']['username']
    
    # 1. Ambil data undangan terlebih dahulu
    invite = invitations_collection.find_one({"_id": invitation_oid})
    if not invite:
        flash("Undangan tidak ditemukan.", "danger")
        return redirect(url_for('manage_data'))
        
    # 2. Pastikan acara dari undangan tersebut adalah milik admin yang sedang login
    event = events_collection.find_one({"_id": invite['event_id'], "created_by": username})
    if not event:
        flash("Anda tidak memiliki hak akses untuk membatalkan permintaan hapus undangan ini.", "danger")
        return redirect(url_for('manage_data'))
        
    # 3. Jika valid, lakukan pembatalan status permintaan hapus
    invitations_collection.update_one(
        {"_id": invitation_oid},
        {"$set": {"status": "Active"}, "$unset": {"requested_by": ""}}
    )
    flash("Permintaan hapus undangan berhasil dibatalkan.", "success")
    return redirect(url_for('manage_data'))

if __name__ == '__main__':
    app.run(debug=True)