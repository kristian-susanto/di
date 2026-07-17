import os
from flask import Flask, render_template, render_template_string, request, redirect, url_for, session, flash, jsonify
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
events_collection = db.events
invitations_collection = db.invitations

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
        
    settings = get_global_settings()
    
    if not settings.get('allow_all_invitations', True) and not invite.get('is_active', True):
        return render_template_string('''
            <!DOCTYPE html>
            <html>
            <head><title>Undangan Nonaktif</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"></head>
            <body class="bg-light d-flex align-items-center justify-content-center" style="height: 100vh;">
                <div class="card p-5 text-center shadow" style="max-width: 500px;">
                    <h1 class="text-danger mb-3">⚠️ Undangan Ditutup</h1>
                    <p class="text-muted">Maaf, akses undangan digital saat ini sedang dinonaktifkan sementara.</p>
                </div>
            </body>
            </html>
        '''), 403

    event = events_collection.find_one({"_id": invite['event_id']})
    
    # Karena data bersatu di invitations, current_rsvp adalah data invite itu sendiri
    current_rsvp = invite 
    
    # Cari ucapan (wishes) dari invitations_collection yang event_id-nya sama
    all_wishes = list(invitations_collection.find({
        "event_id": invite['event_id'], 
        "wishes": {"$ne": "", "$exists": True}
    }))
    
    qr_code_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={id}"
    
    return render_template('invitation.html', invite=invite, event=event, current_rsvp=current_rsvp, all_wishes=all_wishes, qr_code_url=qr_code_url)

@app.route('/invitation/<id>/rsvp', methods=['POST'])
def submit_rsvp(id):
    try:
        invitation_oid = ObjectId(id)
        invitation = invitations_collection.find_one({"_id": invitation_oid})
        if not invitation:
            return {"status": "error", "message": "Invitation not found."}, 404

        status = request.form.get('status')
        total_guests = request.form.get('total_guests', 1)

        # Update langsung ke dokumen invitations_collection
        invitations_collection.update_one(
            {"_id": invitation_oid},
            {
                "$set": {
                    "status": status,
                    "total_guests": int(total_guests) if total_guests else 1,
                    "submitted_at": datetime.datetime.now()
                }
            }
        )
        return {"status": "success", "message": "Your attendance confirmation has been successfully saved!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@app.route('/invitation/<id>/wishes', methods=['POST'])
def submit_wishes(id):
    try:
        invitation_oid = ObjectId(id)
        invitation = invitations_collection.find_one({"_id": invitation_oid})
        if not invitation:
            return {"status": "error", "message": "Invitation not found."}, 404
            
        wishes = request.form.get('wishes', '')
        event_oid = ObjectId(invitation['event_id']) if isinstance(invitation['event_id'], str) else invitation['event_id']

        # Update ucapan ke dalam koleksi invitations
        invitations_collection.update_one(
            {"_id": invitation_oid},
            {
                "$set": {
                    "wishes": wishes,
                    "submitted_at": datetime.datetime.now()
                }
            }
        )
        
        # Ambil ulang SEMUA ucapan dari tamu yang memiliki event_id yang sama di koleksi invitations
        all_wishes = list(invitations_collection.find({
            "event_id": event_oid, 
            "wishes": {"$ne": "", "$exists": True}
        }))
        
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

# Tambahkan inisialisasi koleksi baru di bagian MongoDB Connection
settings_collection = db.settings

def get_global_settings():
    settings = settings_collection.find_one({"type": "global_config"})
    if not settings:
        default = {
            "type": "global_config", 
            "allow_registration": True, 
            "allow_login": True,
            "allow_dashboard": True,    
            "allow_manage_data": True,  
            "allow_guestbook": True,
            "allow_profile": True,
            "allow_all_invitations": True  # Default: mengizinkan semua undangan dibuka
        }
        settings_collection.insert_one(default)
        return default
    
    # Memastikan key baru selalu ter-inisialisasi otomatis jika belum ada di DB
    updated = False
    for key in ["allow_dashboard", "allow_manage_data", "allow_guestbook", "allow_profile", "allow_all_invitations"]:
        if key not in settings:
            settings[key] = True if key != "allow_all_invitations" else True
            updated = True
    if updated:
        settings_collection.update_one({"type": "global_config"}, {"$set": settings})
        
    return settings

# --- MODIFIKASI RUTE REGISTER ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    settings = get_global_settings()
    if not settings.get('allow_registration', True):
        flash("Registrasi saat ini sedang ditutup oleh Superadmin.", "danger")
        return redirect(url_for('login'))
        
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
            "role": role,
            "allowed_events": [] # Inisialisasi array kosong untuk izin event usher
        })
        flash("Registration successful! Please login.", "success")
        return redirect(url_for('login'))
        
    return render_template('register.html')

# --- MODIFIKASI RUTE LOGIN ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    settings = get_global_settings()
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = users_collection.find_one({"email": email})
        
        # Proteksi halaman login: Jika ditutup, hanya role superadmin yang bisa lolos login bypass
        if not settings.get('allow_login', True):
            if not user or user.get('role') != 'superadmin':
                flash("Halaman Login saat ini sedang ditutup oleh pihak Superadmin.", "danger")
                return redirect(url_for('login'))

        if user and check_password_hash(user['password'], password):
            session['user'] = {
                "id": str(user['_id']),
                "username": user['username'],
                "email": user['email'],
                "role": user['role']
            }
            flash(f"Logged in successfully!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid email or password.", "danger")
            
    return render_template('login.html', settings=settings)

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash("You have been logged out.", "success")
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    settings = get_global_settings()
    # Jika ditutup, hanya role superadmin yang tetap bisa akses
    if not settings.get('allow_dashboard', True) and session['user']['role'] != 'superadmin':
        flash("Halaman Dashboard saat ini sedang ditutup oleh Superadmin.", "danger")
        return redirect(url_for('logout'))
    
    invitations = list(invitations_collection.find())

    return render_template('dashboard.html', user=session['user'], invitations=invitations)

@app.route('/manage', methods=['GET', 'POST'])
@login_required
@roles_required('superadmin', 'admin', 'usher')
def manage_data():
    settings = get_global_settings()
    # If closed, only the superadmin role can still access it.
    if not settings.get('allow_manage_data', True) and session['user']['role'] != 'superadmin':
        flash("Halaman Pengelolaan Data saat ini sedang ditutup oleh Superadmin.", "danger")
        return redirect(url_for('dashboard'))

    current_role = session['user']['role']
    username = session['user']['username']
    
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        
        # Create Event Feature
        if form_type == 'create_event':
            event_name = request.form.get('event_name')
            event_date = request.form.get('event_date')
            event_time = request.form.get('event_time', '10:00 - 13:00')
            event_location = request.form.get('event_location', 'Great Wall of China')
            event_logo = '🎉'
            
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
            
        # Create Invitation Feature
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
                    "event_name": selected_event['event_name'],
                    "date": selected_event['event_date'],
                    "guest_name": guest_name,
                    "status": "Active",
                    "is_active": True,
                    "created_by": username
                })
                flash("Invitation generated successfully!", "success")
            else:
                flash("Acara tidak ditemukan atau Anda tidak memiliki hak akses untuk acara ini.", "danger")
                
            return redirect(url_for('manage_data'))
        
        # Edit Event Feature
        elif form_type == 'edit_event':
            event_id = request.form.get('event_id')
            new_name = request.form.get('event_name')
            new_date = request.form.get('event_date')
            new_time = request.form.get('event_time')
            new_location = request.form.get('event_location')
            
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
            
            update_data = {
                "event_name": new_name,
                "event_date": new_date,
                "event_time": new_time,
                "event_location": new_location,
                "event_logo": final_logo
            }

            events_collection.update_one({"_id": ObjectId(event_id)}, {"$set": update_data})
            invitations_collection.update_many(
                {"event_id": ObjectId(event_id)},
                {"$set": {"event_name": new_name, "date": new_date}}
            )
            flash("Event updated successfully!", "success")
            return redirect(url_for('manage_data'))

        # Edit Invitation Feature
        elif form_type == 'edit_invitation':
            invite_id = request.form.get('invite_id')

            invitations_collection.update_one(
                {"_id": ObjectId(invite_id)},
                {"$set": {
                    "guest_name": request.form.get('guest_name'),
                    "domicile": request.form.get('domicile'),
                    "phone_number": request.form.get('phone_number')
                }}
            )
            flash("Invitation record updated successfully!", "success")
            return redirect(url_for('manage_data'))

    # Read Data to Display on Page
    if current_role in ['superadmin', 'admin']:
        all_events = list(events_collection.find())
        dropdown_events = list(events_collection.find({"status": "Approved"}))
        invitations = list(invitations_collection.find())
    else:
        all_events = list(events_collection.find({"created_by": username}))
        dropdown_events = []
        admin_event_ids = [ev['_id'] for ev in all_events]
        invitations = list(invitations_collection.find({"event_id": {"$in": admin_event_ids}}))

    for invite in invitations:
        rsvp_status = invite.get('status')
        
        # Mapping key agar template HTML lama tidak error/patah
        invite['rsvp'] = rsvp_status
        invite['total_guests'] = invite.get('total_guests', 0)
        invite['wishes'] = invite.get('wishes', None)
            
    return render_template('manage_data.html', events=all_events, approved_events=dropdown_events, invitations=invitations, role=current_role)

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
    flash("The event delete request was denied. The event remains active.", "success")
    return redirect(url_for('manage_data'))

@app.route('/delete-event/<id>')
@login_required
@roles_required('superadmin')
def delete_event(id):
    event_oid = ObjectId(id)
    invitations_collection.delete_many({"event_id": event_oid})
    events_collection.delete_one({"_id": event_oid})
    flash("The event and invite list have been successfully deleted permanently.", "success")
    return redirect(url_for('manage_data'))

@app.route('/reject-delete/<id>')
@login_required
@roles_required('superadmin')
def reject_delete(id):
    invitation_oid = ObjectId(id)
    invite = invitations_collection.find_one({"_id": invitation_oid})
    
    # Ambil status saat ini yang tersimpan di DB sebagai cadangan utama
    current_status = invite.get('status', 'Active') if invite else 'Active'
    
    # Jika sistem menyimpan status lama di 'previous_status', gunakan itu.
    # Jika tidak ada, gunakan 'current_status' (agar tetap 'Will be attend' / 'Will not be attend')
    # dan hindari pemaksaan merubah string menjadi 'Active' secara sepihak.
    prev_status = invite.get('previous_status', current_status)

    # Validasi tambahan: Jika status terlanjur rusak/kehilangan jejak, 
    # pastikan status dikembalikan ke status RSVP riil yang ada, bukan reset status admin.
    if prev_status in ['Pending Deletion', 'non-active']:
        prev_status = current_status

    invitations_collection.update_one(
        {"_id": invitation_oid},
        {
            "$set": {"status": prev_status}, 
            "$unset": {"requested_by": "", "previous_status": ""}  # Bersihkan field temporary
        }
    )
    flash("Delete request denied. Invitation RSVP status restored successfully.", "success")
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
    flash("An event delete request has been sent to the Superadmin.", "success")
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
    flash("The event delete request was successfully cancelled.", "success")
    return redirect(url_for('manage_data'))

@app.route('/request-delete/<id>')
@login_required
@roles_required('admin')
def request_delete(id):
    invitation_oid = ObjectId(id)
    invite = invitations_collection.find_one({"_id": invitation_oid})
    
    if invite:
        current_status = invite.get('status', 'Active')
        # HANYA simpan status lama jika status saat ini bukan 'Pending Deletion'
        if current_status != 'Pending Deletion':
            invitations_collection.update_one(
                {"_id": invitation_oid},
                {
                    "$set": {
                        "status": "Pending Deletion",
                        "previous_status": current_status,  # <-- Amankan status RSVP asli di sini
                        "requested_by": session['user']['username']
                    }
                }
            )
            flash("Permintaan hapus undangan telah dikirim ke Superadmin.", "success")
        else:
            flash("Undangan sudah dalam status antrean hapus.", "warning")
    else:
        flash("Undangan tidak ditemukan.", "danger")
        
    return redirect(url_for('manage_data'))

@app.route('/cancel-delete-request/<id>')
@login_required
@roles_required('admin')
def cancel_delete_request(id):
    invitation_oid = ObjectId(id)
    username = session['user']['username']
    invite = invitations_collection.find_one({"_id": invitation_oid})
    if not invite:
        flash("Invitation not found.", "danger")
        return redirect(url_for('manage_data'))
        
    # Panggil kembali status sebelumnya, default ke 'Active' jika tidak ditemukan
    prev_status = invite.get('previous_status', 'Active')
        
    invitations_collection.update_one(
        {"_id": invitation_oid},
        {
            "$set": {"status": prev_status}, 
            "$unset": {"requested_by": "", "previous_status": ""}
        }
    )
    flash("The delete invitation request was successfully cancelled.", "success")
    return redirect(url_for('manage_data'))

# --- ROUTE TAMBAHAN UNTUK BUKU TAMU USHER ---

@app.route('/guestbook', methods=['GET'])
@login_required
@roles_required('superadmin', 'usher')
def guestbook():
    settings = get_global_settings()
    if not settings.get('allow_guestbook', True) and session['user']['role'] != 'superadmin':
        flash("Halaman Buku Tamu saat ini sedang ditutup oleh Superadmin.", "danger")
        return redirect(url_for('dashboard'))

    current_role = session['user']['role']
    current_user_id = session['user']['id']
    selected_event_id = request.args.get('event_id')
    
    allowed_events = []
    has_permission = True

    if current_role == 'usher':
        usher_data = users_collection.find_one({"_id": ObjectId(current_user_id)})
        allowed_event_ids = usher_data.get('allowed_events', [])
        if not allowed_event_ids:
            has_permission = False
        else:
            allowed_events = list(events_collection.find({"_id": {"$in": allowed_event_ids}}))
            if not selected_event_id:
                selected_event_id = str(allowed_event_ids[0])
    else:
        allowed_events = list(events_collection.find({"status": "Approved"}))
        if allowed_events and not selected_event_id:
            selected_event_id = str(allowed_events[0]['_id'])

    attended_guests = []
    if has_permission and selected_event_id:
        # Mengambil dari koleksi invitations
        attended_guests = list(invitations_collection.find({
            "status": "Attend",
            "event_id": ObjectId(selected_event_id)
        }).sort("submitted_at", -1))
        
    return render_template('guestbook.html', attended_guests=attended_guests, allowed_events=allowed_events, selected_event_id=selected_event_id, has_permission=has_permission)

@app.route('/usher/check-in/<id>', methods=['POST'])
@login_required
@roles_required('superadmin', 'usher')
def usher_check_in(id):
    try:
        try:
            invitation_oid = ObjectId(id)
        except Exception:
            return jsonify({"status": "error", "message": "Format ID Undangan tidak valid."}), 400

        invitation = invitations_collection.find_one({"_id": invitation_oid})
        if not invitation:
            return jsonify({"status": "error", "message": "Undangan tidak ditemukan di database."}), 404

        guest_name = invitation.get('guest_name')
        event_id = invitation.get('event_id')
        event_oid = ObjectId(event_id) if isinstance(event_id, str) else event_id

        if session['user']['role'] == 'usher':
            usher_data = users_collection.find_one({"_id": ObjectId(session['user']['id'])})
            allowed_events = usher_data.get('allowed_events', [])
            if event_oid not in allowed_events:
                return jsonify({
                    "status": "error", 
                    "message": "Anda tidak memiliki izin dari Superadmin untuk mengelola buku tamu di acara ini!"
                }), 403

        # Update status kehadiran langsung ke koleksi invitations
        invitations_collection.update_one(
            {"_id": invitation_oid},
            {
                "$set": {
                    "status": "Attend",
                    "submitted_at": datetime.datetime.now()
                }
            }
        )

        return jsonify({
            "status": "success", 
            "message": f"Success! Attendance under the name '{guest_name}' has been recorded."
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": f"Terjadi kesalahan sistem: {str(e)}"}), 500

@app.route('/usher/search-guest', methods=['GET'])
@login_required
@roles_required('superadmin', 'usher')
def usher_search_guest():
    try:
        event_id = request.args.get('event_id')
        search_query = request.args.get('q', '').strip()
        
        if not event_id:
            return jsonify({"status": "error", "message": "Event ID diperlukan."}), 400

        # Proteksi Hak Akses untuk Usher
        if session['user']['role'] == 'usher':
            usher_data = users_collection.find_one({"_id": ObjectId(session['user']['id'])})
            allowed_events = usher_data.get('allowed_events', [])
            if event_id not in allowed_events:
                return jsonify({"status": "error", "message": "Akses ditolak."}), 403

        # Query pencarian nama tamu yang belum hadir pada event tersebut
        query = {
            "event_id": ObjectId(event_id),
            "status": {"$ne": "Attend"},
            "guest_name": {"$regex": search_query, "$options": "i"} # Case-insensitive search
        }
        
        guests = list(invitations_collection.find(query).limit(10)) # Batasi 10 hasil demi performa
        
        results = []
        for g in guests:
            results.append({
                "id": str(g['_id']),
                "guest_name": g.get('guest_name', 'Tamu Undangan')
            })
            
        return jsonify({"status": "success", "data": results})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/manage-people', methods=['GET', 'POST'])
@login_required
def manage_people():
    if session['user']['role'] != 'superadmin':
        flash("Akses ditolak! Halaman ini hanya untuk Superadmin.", "danger")
        return redirect(url_for('dashboard'))

    settings = db.settings.find_one({"type": "global_config"}) or get_global_settings()

    if request.method == 'POST':
        form_type = request.form.get('form_type')
        
        # -------------------------------------------------------------
        # FORM BARU: TAMBAH PENGGUNA BARU (REGISTER OLEH SUPERADMIN)
        # -------------------------------------------------------------
        if form_type == 'add_user':
            username = request.form.get('username')
            email = request.form.get('email')
            password = request.form.get('password')
            role = request.form.get('role', 'user')
            # allowed_events dihapus dari sini

            if not username or not email or not password or not role:
                flash("Semua data wajib diisi!", "danger")
                return redirect(url_for('manage_people'))

            if users_collection.find_one({"email": email}):
                flash("Email sudah terdaftar!", "danger")
                return redirect(url_for('manage_people'))

            hashed_password = generate_password_hash(password)
            users_collection.insert_one({
                "username": username,
                "email": email,
                "password": hashed_password,
                "role": role
            })
            flash(f"Pengguna baru '{username}' berhasil didaftarkan!", "success")
            return redirect(url_for('manage_people'))

        # -------------------------------------------------------------
        # FORM 1: TOGGLE GERBANG AKSES (REGISTRASI / LOGIN)
        # -------------------------------------------------------------
        elif form_type == 'toggle_gate':
            allow_reg = True if request.form.get('allow_registration') else False
            allow_login = True if request.form.get('allow_login') else False
            allow_dash = True if request.form.get('allow_dashboard') else False
            allow_manage = True if request.form.get('allow_manage_data') else False
            allow_gbook = True if request.form.get('allow_guestbook') else False
            allow_prof = True if request.form.get('allow_profile') else False
            allow_all_inv = True if request.form.get('allow_all_invitations') else False
            
            db.settings.update_one(
                {"type": "global_config"}, 
                {"$set": {
                    "allow_registration": allow_reg, 
                    "allow_login": allow_login,
                    "allow_dashboard": allow_dash,
                    "allow_manage_data": allow_manage,
                    "allow_guestbook": allow_gbook,
                    "allow_profile": allow_prof,
                    "allow_all_invitations": allow_all_inv
                }}, 
                upsert=True
            )

            if not allow_all_inv:
                # 1. Nonaktifkan tautan secara sistem (is_active: False) untuk SEMUA undangan
                invitations_collection.update_many(
                    {},
                    {"$set": {"is_active": False}}
                )
                
                # 2. Hanya ubah status undangan yang BELUM di-RSVP (misal: "Active" / kosong) menjadi "Non-active".
                # Pengecualian ditambahkan untuk status: "Attend", "Will be attend", dan "Will not be attend".
                invitations_collection.update_many(
                    {
                        "status": {"$nin": ["Attend", "Will be attend", "Will not be attend", "Non-active"]}
                    },
                    [
                        {"$set": {
                            "previous_status": "$status",
                            "status": "Non-active"
                        }}
                    ]
                )
                flash("Global settings are disabled. All individual invite links are automatically disabled!", "success")
            else:
                # Saat diaktifkan kembali:
                # 1. Aktifkan kembali tautan secara sistem (is_active: True) untuk semua undangan
                invitations_collection.update_many(
                    {},
                    {"$set": {"is_active": True}}
                )
                
                # 2. Kembalikan status asli dari 'previous_status' jika ada, 
                # jika tidak ada maka berikan status 'Active'
                invitations_collection.update_many(
                    {"status": "Non-active"},
                    [
                        {"$set": {
                            "status": {
                                "$cond": {
                                    "if": {"$and": [{"$ifNull": ["$previous_status", False]}, {"$ne": ["$previous_status", "Non-active"]}]},
                                    "then": "$previous_status",
                                    "else": "Active"
                                }
                            }
                        }},
                        {"$unset": ["previous_status"]}  # Hapus field temporary setelah berhasil dikembalikan
                    ]
                )
                flash("Access settings updated successfully!", "success")

            return redirect(url_for('manage_people'))

        # -------------------------------------------------------------
        # FORM 2: EDIT USER TERPADU (PROFIL, PASSWORD & IZIN ACARA)
        # -------------------------------------------------------------
        elif form_type == 'edit_user_unified':
            user_id = request.form.get('user_id')
            role = request.form.get('role')
            password_baru = request.form.get('password')
            allowed_events = request.form.getlist('allowed_events')

            # Validasi diubah karena username dan email sudah tidak dikirim
            if not user_id or not role:
                flash("Data wajib diisi!", "danger")
                return redirect(url_for('manage_people'))

            target_user = users_collection.find_one({"_id": ObjectId(user_id)})
            if not target_user:
                flash("Pengguna tidak ditemukan!", "danger")
                return redirect(url_for('manage_people'))

            # Proteksi agar role superadmin tidak berubah tidak sengaja
            if target_user.get('role') == 'superadmin':
                role = 'superadmin'

            # Update_data sekarang tidak menyertakan username dan email
            update_data = {
                "role": role,
                "allowed_events": allowed_events
            }

            if password_baru and password_baru.strip() != "":
                update_data["password"] = generate_password_hash(password_baru)

            users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": update_data}
            )

            # Menggunakan target_user['username'] untuk flash message karena input username sudah dihapus
            flash(f"Data pengguna '{target_user.get('username')}' berhasil diperbarui!", "success")
            return redirect(url_for('manage_people'))

    # --- HANDLING GET REQUEST ---
    all_users = list(users_collection.find())
    all_events = list(events_collection.find())

    return render_template(
        'manage_people.html', 
        users=all_users, 
        events=all_events, 
        settings=settings,
        role=session['user']['role']
    )

@app.route('/manage-people/delete-user/<user_id>')
@login_required
def delete_user(user_id):
    if session['user']['role'] != 'superadmin':
        flash("Akses ditolak!", "danger")
        return redirect(url_for('dashboard'))
        
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if user:
        if user['role'] == 'superadmin':
            flash("Tidak dapat menghapus sesama akun Superadmin!", "danger")
        else:
            users_collection.delete_one({"_id": ObjectId(user_id)})
            flash(f"Pengguna '{user['username']}' berhasil dihapus permanen.", "success")
    else:
        flash("Pengguna tidak ditemukan.", "danger")
        
    return redirect(url_for('manage_people'))

# ==========================================
# --- RUTE BARU: PROFIL PENGGUNA & HAPUS AKUN ---
# ==========================================

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    settings = get_global_settings()
    
    # JIKA AKSES PROFILE DITUTUP: Hanya superadmin yang tetap bisa tembus masuk
    if not settings.get('allow_profile', True) and session['user']['role'] != 'superadmin':
        flash("Halaman Pengaturan Profil saat ini sedang ditutup oleh Superadmin.", "danger")
        return redirect(url_for('dashboard')) # Dialihkan kembali ke dashboard terproteksi

    current_user_id = session['user']['id']
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        new_password = request.form.get('password')
        
        # Cek apakah email sudah digunakan oleh pengguna lain
        existing_user = users_collection.find_one({"email": email, "_id": {"$ne": ObjectId(current_user_id)}})
        if existing_user:
            flash("Email sudah digunakan oleh akun lain!", "danger")
            return redirect(url_for('profile'))
            
        # Siapkan data yang akan diperbarui
        update_data = {
            "username": username,
            "email": email
        }
        
        # Jika pengguna mengisi field password baru, lakukan enkripsi dan masukkan ke database
        if new_password:
            update_data["password"] = generate_password_hash(new_password)
            
        # Update ke MongoDB
        users_collection.update_one(
            {"_id": ObjectId(current_user_id)},
            {"$set": update_data}
        )
        
        # Perbarui data session agar nama/email di navbar langsung berubah
        session['user']['username'] = username
        session['user']['email'] = email
        
        flash("Profil Anda berhasil diperbarui!", "success")
        return redirect(url_for('profile'))
        
    # Ambil data terbaru pengguna dari database untuk ditampilkan di form
    user_data = users_collection.find_one({"_id": ObjectId(session['user']['id'])})
    return render_template('profile.html', user=user_data)

@app.route('/profile/delete-account', methods=['POST'])
@login_required
def delete_account():
    current_user_id = session['user']['id']
    
    # Hapus pengguna dari koleksi database
    users_collection.delete_one({"_id": ObjectId(current_user_id)})
    
    # Bersihkan session untuk logout otomatis
    session.clear()
    
    # Return JSON karena proses trigger aksi penghapusan dipanggil via JavaScript/Fetch oleh SweetAlert
    return jsonify({"status": "success", "message": "Akun Anda telah berhasil dihapus secara permanen."})

if __name__ == '__main__':
    app.run(debug=True)