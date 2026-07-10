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

# 1. Public Invitation Page
@app.route('/invitation/<id>')
def invitation(id):
    invite = invitations_collection.find_one({"_id": ObjectId(id)})
    if not invite:
        return "Invitation Not Found", 404
    return render_template('invitation.html', invite=invite)

# 2. Auth: Register
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

# 3. Auth: Login
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

# 4. Auth: Logout
@app.route('/logout')
def logout():
    session.pop('user', None)
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

# 5. Dashboard
@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=session['user'])

# 6. Data Management
@app.route('/manage', methods=['GET', 'POST'])
@login_required
@roles_required('superadmin', 'admin', 'usher')
def manage_data():
    current_role = session['user']['role']
    username = session['user']['username']
    
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        
        # A. FITUR CREATE EVENT (Admin & Superadmin)
        if form_type == 'create_event':
            if current_role not in ['superadmin', 'admin']:
                flash("Unauthorized.", "danger")
                return redirect(url_for('manage_data'))
                
            event_name = request.form.get('event_name')
            event_date = request.form.get('event_date')
            status = "Approved" if current_role == 'superadmin' else "Pending Approval"
            
            events_collection.insert_one({
                "event_name": event_name,
                "event_date": event_date,
                "status": status,
                "created_by": username
            })
            
            msg = "Event created successfully!" if status == "Approved" else "Event proposal submitted to Superadmin!"
            flash(msg, "success" if status == "Approved" else "warning")
            return redirect(url_for('manage_data'))
            
        # B. FITUR CREATE INVITATION (Admin & Superadmin)
        elif form_type == 'create_invitation':
            if current_role not in ['superadmin', 'admin']:
                flash("Unauthorized.", "danger")
                return redirect(url_for('manage_data'))
                
            event_id = request.form.get('event_id')
            guest_name = request.form.get('guest_name')
            
            selected_event = events_collection.find_one({"_id": ObjectId(event_id)})
            if selected_event:
                invitations_collection.insert_one({
                    "event_id": ObjectId(event_id),
                    "title": selected_event['event_name'],
                    "date": selected_event['event_date'],
                    "guest_name": guest_name,
                    "status": "Active"
                })
                flash("Invitation generated successfully!", "success")
            return redirect(url_for('manage_data'))

    # READ DATA UNTUK DITAMPILKAN DI HALAMAN
    all_events = list(events_collection.find())
    
    # --- MODIFIKASI TERBARU ---
    # Jika role adalah admin, tampilkan acara 'Approved', 'Pending Approval', dan 'Pending Deletion' di dropdown
    if current_role == 'admin':
        dropdown_events = list(events_collection.find({
            "status": {"$in": ["Approved", "Pending Approval", "Pending Deletion"]}
        }))
    else:
        # Untuk superadmin/usher tetap hanya menampilkan yang sudah Approved jika diperlukan
        dropdown_events = list(events_collection.find({"status": "Approved"}))
    
    invitations = list(invitations_collection.find())
    
    return render_template(
        'manage_data.html', 
        events=all_events, 
        approved_events=dropdown_events, # Variable ini dipakai di template untuk looping dropdown
        invitations=invitations, 
        role=current_role
    )

# ==========================================
# --- FITUR PASCA-PERUBAHAN (EVENT ACTIONS) ---
# ==========================================

@app.route('/cancel-event-proposal/<id>')
@login_required
@roles_required('admin')
def cancel_event_proposal(id):
    """Admin membatalkan proposal acara sebelum di-approve superadmin"""
    events_collection.delete_one({"_id": ObjectId(id), "status": "Pending Approval"})
    flash("Proposal acara berhasil dibatalkan.", "info")
    return redirect(url_for('manage_data'))


@app.route('/request-delete-event/<id>')
@login_required
@roles_required('admin')
def request_delete_event(id):
    """Admin mengajukan permohonan hapus acara yang sudah Approved"""
    events_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "Pending Deletion", "requested_by": session['user']['username']}}
    )
    flash("Permintaan hapus acara telah dikirim ke Superadmin.", "warning")
    return redirect(url_for('manage_data'))


@app.route('/approve-delete-event/<id>')
@login_required
@roles_required('superadmin')
def approve_delete_event(id):
    """Superadmin menyetujui permintaan hapus acara dari Admin"""
    events_collection.delete_one({"_id": ObjectId(id)})
    flash("Permintaan hapus disetujui, acara dihapus permanen.", "success")
    return redirect(url_for('manage_data'))

@app.route('/approve-event/<id>')
@login_required
@roles_required('superadmin')
def approve_event(id):
    """Superadmin menyetujui proposal acara baru dari Admin"""
    events_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "Approved"}}
    )
    flash("Proposal acara berhasil disetujui!", "success")
    return redirect(url_for('manage_data'))

@app.route('/reject-delete-event/<id>')
@login_required
@roles_required('superadmin')
def reject_delete_event(id):
    """Superadmin menolak permohonan hapus acara, status kembali Approved"""
    events_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "Approved"}, "$unset": {"requested_by": ""}}
    )
    flash("Permintaan hapus acara ditolak. Acara tetap aktif.", "info")
    return redirect(url_for('manage_data'))

@app.route('/request-delete/<id>')
@login_required
@roles_required('admin')
def request_delete(id):
    """Admin mengajukan permohonan hapus undangan yang aktif"""
    invitations_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "Pending Deletion", "requested_by": session['user']['username']}}
    )
    flash("Permintaan hapus undangan telah dikirim ke Superadmin.", "warning")
    return redirect(url_for('manage_data'))

@app.route('/delete-event/<id>')
@login_required
@roles_required('superadmin')
def delete_event(id):
    """Direct Delete Event oleh Superadmin (Dengan SweetAlert Konfirmasi)"""
    events_collection.delete_one({"_id": ObjectId(id)})
    flash("Acara berhasil dihapus permanen oleh Superadmin.", "success")
    return redirect(url_for('manage_data'))


# ===============================================
# --- FITUR PEMBATALAN PERMINTAAN HAPUS UNDANGAN (ADMIN) ---
# ===============================================

@app.route('/cancel-delete-request/<id>')
@login_required
@roles_required('admin')
def cancel_delete_request(id):
    """Admin membatalkan permintaan hapus undangan yang terlanjur dikirim"""
    invitations_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "Active"}, "$unset": {"requested_by": ""}}
    )
    flash("Permintaan hapus undangan berhasil dibatalkan.", "info")
    return redirect(url_for('manage_data'))

@app.route('/cancel-delete-event-request/<id>')
@login_required
@roles_required('admin')
def cancel_delete_event_request(id):
    """Admin membatalkan permintaan hapus acara (mengembalikan status menjadi Approved)"""
    events_collection.update_one(
        {"_id": ObjectId(id), "status": "Pending Deletion"},
        {"$set": {"status": "Approved"}, "$unset": {"requested_by": ""}}
    )
    flash("Permintaan hapus acara berhasil dibatalkan. Acara kembali aktif.", "info")
    return redirect(url_for('manage_data'))

@app.route('/delete/<id>')
@login_required
@roles_required('superadmin')
def delete_data(id):
    # Superadmin menyetujui hapus undangan (Langsung hapus permanen)
    invitations_collection.delete_one({"_id": ObjectId(id)})
    flash("Invitation deleted permanently!", "success")
    return redirect(url_for('manage_data'))

@app.route('/reject-delete/<id>')
@login_required
@roles_required('superadmin')
def reject_delete(id):
    invitations_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "Active"}, "$unset": {"requested_by": ""}}
    )
    flash("Deletion request rejected. Invitation is now active.", "info")
    return redirect(url_for('manage_data'))

if __name__ == '__main__':
    app.run(debug=True)