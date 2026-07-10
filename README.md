# Digital Invitation

## Project Structure

digital_invitation/
│
├── app/
│ ├── **init**.py # Inisialisasi Flask, Mongo, & Bcrypt
│ ├── config.py # Load environment variables
│ ├── decorators.py # Decorator untuk pengecekan Role
│ │
│ ├── auth/ # Blueprint untuk Register & Login
│ │ ├── **init**.py
│ │ └── routes.py
│ │
│ ├── dashboard/ # Blueprint untuk Dashboard & Manajemen Data
│ │ ├── **init**.py
│ │ └── routes.py
│ │
│ ├── invitation/ # Blueprint untuk Surat Undangan (Public/Guest view)
│ │ ├── **init**.py
│ │ └── routes.py
│ │
│ ├── templates/ # Folder HTML (Responsive Tailwind/Bootstrap)
│ │ ├── base.html
│ │ ├── auth/
│ │ │ ├── login.html
│ │ │ └── register.html
│ │ ├── dashboard/
│ │ │ ├── index.html
│ │ │ └── manage_data.html
│ │ └── invitation/
│ │ └── index.html
│ └── static/ # CSS, JS, Images
│ ├── css/
│ └── js/
│
├── .env # File konfigurasi rahasia
├── requirements.txt # Dependency Python
└── run.py # Entry point aplikasi
