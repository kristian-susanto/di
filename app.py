import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from functools import wraps
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import shutil
import datetime

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# Konfigurasi Upload Folder
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# MongoDB Connection
client = MongoClient(os.getenv("MONGO_URI"))
db = client['digital_invitation']
users_collection = db.users
invitations_collection = db.invitations
events_collection = db.events
rsvps_collection = db.rsvps

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

@app.route('/invitation/<id>', methods=['GET'])
def view_invitation(id):
    invite = invitations_collection.find_one({"_id": ObjectId(id)})
    if not invite:
        return "Undangan tidak ditemukan", 404
        
    event = events_collection.find_one({"_id": invite['event_id']})
    
    current_rsvp = rsvps_collection.find_one({
        "invitation_id": ObjectId(id),
        "guest_name": invite['guest_name']
    })
    
    # 🛠️ PERBAIKAN: Cari ucapan berdasarkan event_id, bukan invitation_id
    all_wishes = list(rsvps_collection.find({
        "event_id": invite['event_id'],
        "wishes": {"$ne": "", "$exists": True}
    }))
    
    return render_template(
        'invitation.html', 
        invite=invite, 
        event=event, 
        current_rsvp=current_rsvp, 
        all_wishes=all_wishes
    )

@app.route('/invitation/<id>/rsvp', methods=['POST'])
def submit_rsvp(id):
    try:
        invitation_oid = ObjectId(id)
        invitation = invitations_collection.find_one({"_id": invitation_oid})
        if not invitation:
            return {"status": "error", "message": "Undangan tidak ditemukan."}, 404

        guest_name = request.form.get('guest_name')
        attendance = request.form.get('attendance')
        total_guests = request.form.get('total_guests', 1)

        rsvps_collection.update_one(
            {"invitation_id": invitation_oid, "guest_name": guest_name},
            {
                "$set": {
                    "invitation_id": invitation_oid,
                    "event_id": invitation.get('event_id'),
                    "guest_name": guest_name,
                    "attendance": attendance,
                    "total_guests": int(total_guests) if total_guests else 1,
                    "submitted_at": datetime.datetime.now()
                }
            },
            upsert=True
        )
        return {"status": "success", "message": "Konfirmasi kehadiran Anda berhasil disimpan!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@app.route('/invitation/<id>/wishes', methods=['POST'])
def submit_wishes(id):
    try:
        invitation_oid = ObjectId(id)
        invitation = invitations_collection.find_one({"_id": invitation_oid})
        if not invitation:
            return {"status": "error", "message": "Undangan tidak ditemukan."}, 404
            
        guest_name = request.form.get('guest_name')
        wishes = request.form.get('wishes', '')

        # Pastikan event_id disimpan sebagai ObjectId asli, bukan string
        event_oid = ObjectId(invitation['event_id']) if isinstance(invitation['event_id'], str) else invitation['event_id']

        # Update ucapan tamu saat ini
        rsvps_collection.update_one(
            {"invitation_id": invitation_oid},
            {
                "$set": {
                    "invitation_id": invitation_oid,
                    "event_id": event_oid,
                    "guest_name": guest_name,
                    "wishes": wishes,
                    "submitted_at": datetime.datetime.now()
                }
            },
            upsert=True
        )
        
        # Ambil ulang SEMUA ucapan yang berada di bawah event_id yang sama
        all_wishes = list(rsvps_collection.find({
            "event_id": event_oid, 
            "wishes": {"$ne": "", "$exists": True}
        }))
        
        # Susun struktur datanya dengan aman
        wishes_data = []
        for w in all_wishes:
            wishes_data.append({
                "guest_name": w.get('guest_name', 'Tamu Undangan'),
                "wishes": w.get('wishes', '')
            })

        return {
            "status": "success", 
            "message": "Terima kasih! Doa dan ucapan Anda telah diperbarui.",
            "wishes_list": wishes_data
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

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
            # LOKASI DIUBAH MENJADI GREAT WALL OF CHINA
            event_location = request.form.get('event_location', 'great wall of china Huairou District, China, 101406')
            event_logo = '🎉' # default berupa emoji saat pembuatan awal instan
            
            status = 'Pending Approval' if current_role == 'admin' else 'Approved'
            
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
            
        # B. FITUR CREATE INVITATION
        elif form_type == 'create_invitation':
            if current_role not in ['superadmin', 'admin']:
                flash("Unauthorized.", "danger")
                return redirect(url_for('manage_data'))
                
            event_id = request.form.get('event_id')
            guest_name = request.form.get('guest_name')
            
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
                    "created_by": username
                })
                flash("Invitation generated successfully!", "success")
            else:
                flash("Acara tidak ditemukan atau Anda tidak memiliki hak akses untuk acara ini.", "danger")
                
            return redirect(url_for('manage_data'))
        
        # C. FITUR EDIT EVENT (PROSES FAVICON LANGSUNG SETELAH UPLOAD LOGO)
        elif form_type == 'edit_event':
            event_id = request.form.get('event_id')
            new_name = request.form.get('event_name')
            new_date = request.form.get('event_date')
            new_time = request.form.get('event_time')
            new_location = request.form.get('event_location')
            new_status = request.form.get('status')
            
            current_event = events_collection.find_one({"_id": ObjectId(event_id)})
            final_logo = current_event.get('event_logo', '🎉') if current_event else '🎉'
            
            if 'event_logo' in request.files:
                file = request.files['event_logo']
                if file and file.filename != '':
                    ext = os.path.splitext(file.filename)[1]
                    filename = f"logo_{event_id}{ext}"
                    destination_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    
                    file.save(destination_path)
                    final_logo = f"/{UPLOAD_FOLDER}/{filename}"
                    # Proses pemindahan langsung ke static/favicon.ico dihapus di sini
            
            update_data = {
                "event_name": new_name,
                "event_date": new_date,
                "event_time": new_time,
                "event_location": new_location,
                "event_logo": final_logo
            }
            
            if new_status:
                update_data["status"] = new_status

            events_collection.update_one({"_id": ObjectId(event_id)}, {"$set": update_data})
            invitations_collection.update_many(
                {"event_id": ObjectId(event_id)},
                {"$set": {"title": new_name, "date": new_date}}
            )
            flash("Event updated successfully!", "success")
            return redirect(url_for('manage_data'))

        # D. FITUR EDIT INVITATION
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
    # Menampilkan semua event untuk superadmin maupun admin
    if current_role in ['superadmin', 'admin']:
        all_events = list(events_collection.find())
    else:
        all_events = list(events_collection.find({"created_by": username}))
    
    # Menampilkan pilihan event yang sudah disetujui di dropdown Generate Invitation
    if current_role in ['superadmin', 'admin']:
        dropdown_events = list(events_collection.find({"status": "Approved"}))
    else:
        dropdown_events = []
    
    # Menampilkan semua undangan yang sudah digenerate untuk admin & superadmin
    if current_role in ['superadmin', 'admin']:
        invitations = list(invitations_collection.find())
    else:
        admin_event_ids = [ev['_id'] for ev in all_events]
        invitations = list(invitations_collection.find({
            "event_id": {"$in": admin_event_ids}
        }))

    # Tambahkan kode penentuan status visual tanpa merusak status asli database
    for invite in invitations:
        rsvp_data = rsvps_collection.find_one({"invitation_id": invite['_id']})
        
        # Ambil status rsvp jika ada
        rsvp_status = rsvp_data.get('attendance') if rsvp_data else None
        
        # Jika rsvp sudah diisi Akan Hadir/Tidak akan hadir, display_status mengikuti RSVP
        if rsvp_status in ['Akan Hadir', 'Tidak akan hadir']:
            invite['display_status'] = rsvp_status
        elif invite.get('status') == 'Pending Deletion':
            invite['display_status'] = 'Pending Deletion'
        else:
            invite['display_status'] = 'Active'
        
        # Simpan data RSVP asli ke objek invite
        if rsvp_data:
            invite['rsvp'] = rsvp_status
            invite['total_guests'] = rsvp_data.get('total_guests', 1)
            invite['wishes'] = rsvp_data.get('wishes', '')
        else:
            invite['rsvp'] = None
            invite['total_guests'] = 0
            invite['wishes'] = None
    
    return render_template(
        'manage_data.html', 
        events=all_events, 
        approved_events=dropdown_events, 
        invitations=invitations, 
        role=current_role
    )

# ==========================================
# --- Superadmin Routs ---
# ==========================================

@app.route('/approve-event/<id>')
@login_required
@roles_required('superadmin')
def approve_event(id):
    events_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "Approved"}}
    )
    flash("Proposal acara berhasil disetujui!", "success")
    return redirect(url_for('manage_data'))

@app.route('/approve-delete-event/<id>')
@login_required
@roles_required('superadmin')
def approve_delete_event(id):
    event_oid = ObjectId(id)
    invitations_collection.delete_many({"event_id": event_oid})
    events_collection.delete_one({"_id": event_oid})
    flash("Permintaan hapus disetujui, acara dan daftar undangan dihapus.", "success")
    return redirect(url_for('manage_data'))

@app.route('/reject-delete-event/<id>')
@login_required
@roles_required('superadmin')
def reject_delete_event(id):
    events_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "Approved"}, "$unset": {"requested_by": ""}}
    )
    flash("Permintaan hapus acara ditolak. Acara tetap aktif.", "success")
    return redirect(url_for('manage_data'))

@app.route('/delete-event/<id>')
@login_required
@roles_required('superadmin')
def delete_event(id):
    event_oid = ObjectId(id)
    invitations_collection.delete_many({"event_id": event_oid})
    events_collection.delete_one({"_id": event_oid})
    flash("Acara dan daftar undangan berhasil dihapus permanen.", "success")
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
    invitations_collection.delete_one({"_id": ObjectId(id)})
    flash("Invitation deleted permanently!", "success")
    return redirect(url_for('manage_data'))

# --- Admin Routs ---

@app.route('/request-delete-event/<id>')
@login_required
@roles_required('admin')
def request_delete_event(id):
    events_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "Pending Deletion", "requested_by": session['user']['username']}}
    )
    flash("Permintaan hapus acara telah dikirim ke Superadmin.", "success")
    return redirect(url_for('manage_data'))

@app.route('/cancel-event-proposal/<id>')
@login_required
@roles_required('admin')
def cancel_event_proposal(id):
    event_oid = ObjectId(id)
    current_username = session['user']['username']
    event = events_collection.find_one({"_id": event_oid, "created_by": current_username, "status": "Pending Approval"})
    if not event:
        flash("Anda tidak memiliki akses untuk membatalkan proposal ini.", "danger")
        return redirect(url_for('manage_data'))
        
    invitations_collection.delete_many({"event_id": event_oid})
    events_collection.delete_one({"_id": event_oid})
    flash("Proposal acara berhasil dibatalkan.", "success")
    return redirect(url_for('manage_data'))

@app.route('/cancel-delete-event-request/<id>')
@login_required
@roles_required('admin')
def cancel_delete_event_request(id):
    events_collection.update_one(
        {"_id": ObjectId(id), "status": "Pending Deletion"},
        {"$set": {"status": "Approved"}, "$unset": {"requested_by": ""}}
    )
    flash("Permintaan hapus acara berhasil dibatalkan.", "success")
    return redirect(url_for('manage_data'))

@app.route('/request-delete/<id>')
@login_required
@roles_required('admin')
def request_delete(id):
    invitation_oid = ObjectId(id)
    username = session['user']['username']
    invite = invitations_collection.find_one({"_id": invitation_oid})
    if not invite:
        flash("Undangan tidak ditemukan.", "danger")
        return redirect(url_for('manage_data'))
        
    # Sederhanakan pengecekan: Jika dia seorang admin, dia berhak meminta hapus tamu
    invitations_collection.update_one(
        {"_id": invitation_oid},
        {"$set": {"status": "Pending Deletion", "requested_by": username}}
    )
    flash("Permintaan hapus undangan telah dikirim.", "success")
    return redirect(url_for('manage_data'))

@app.route('/cancel-delete-request/<id>')
@login_required
@roles_required('admin')
def cancel_delete_request(id):
    invitation_oid = ObjectId(id)
    username = session['user']['username']
    invite = invitations_collection.find_one({"_id": invitation_oid})
    if not invite:
        flash("Undangan tidak ditemukan.", "danger")
        return redirect(url_for('manage_data'))
        
    invitations_collection.update_one(
        {"_id": invitation_oid},
        {"$set": {"status": "Active"}, "$unset": {"requested_by": ""}}
    )
    flash("Permintaan hapus undangan berhasil dibatalkan.", "success")
    return redirect(url_for('manage_data'))

# --- ROUTE TAMBAHAN UNTUK BUKU TAMU USHER ---

@app.route('/usher/guestbook', methods=['GET'])
@login_required
@roles_required('superadmin', 'admin', 'usher')
def usher_guestbook():
    # Mengambil daftar tamu yang sudah sukses dicatat hadir pada hari H
    attended_guests = list(rsvps_collection.find({"attendance": "Akan Hadir"}).sort("submitted_at", -1))
    return render_template('usher_guestbook.html', attended_guests=attended_guests)

# Tambahkan route ini di dalam app.py Anda

@app.route('/usher/check-in/<id>', methods=['POST'])
@login_required
@roles_required('superadmin', 'admin', 'usher')
def usher_check_in(id):
    try:
        # PENTING: Ubah string ID dari QR Code menjadi ObjectId MongoDB
        try:
            invitation_oid = ObjectId(id)
        except Exception:
            return jsonify({"status": "error", "message": "Format ID Undangan tidak valid."}), 400

        # Cari data undangan berdasarkan id tersebut
        invitation = invitations_collection.find_one({"_id": invitation_oid})
        if not invitation:
            return jsonify({"status": "error", "message": "Undangan tidak ditemukan di database."}), 404

        guest_name = invitation.get('guest_name')
        event_id = invitation.get('event_id')

        # Lakukan update atau masukkan ke koleksi rsvps_collection sebagai "Akan Hadir"
        rsvps_collection.update_one(
            {"invitation_id": invitation_oid},
            {
                "$set": {
                    "invitation_id": invitation_oid,
                    "event_id": ObjectId(event_id) if isinstance(event_id, str) else event_id,
                    "guest_name": guest_name,
                    "attendance": "Akan Hadir",  # Menandakan tamu statusnya HADIR di sistem Anda
                    "total_guests": 1,
                    "submitted_at": datetime.datetime.now()
                }
            },
            upsert=True  # Jika data rsvp belum ada, otomatis buat baru
        )

        return jsonify({
            "status": "success", 
            "message": f"Berhasil! Kehadiran atas nama '{guest_name}' telah dicatat."
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": f"Terjadi kesalahan sistem: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True)