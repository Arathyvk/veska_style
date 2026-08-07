# 👠 VESKA

<div align="center">

# VESKA Fashion

### Women's Footwear E-Commerce Platform

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![Django](https://img.shields.io/badge/Django-6.0-green?logo=django)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-blue?logo=postgresql)
![Stripe](https://img.shields.io/badge/Stripe-Payment-635BFF?logo=stripe)
![Cloudinary](https://img.shields.io/badge/Cloudinary-Media-3448C5?logo=cloudinary)
![License](https://img.shields.io/badge/License-MIT-yellow)

A modern Django-based eCommerce application for women's footwear featuring secure authentication, product management, Stripe payments, wallet, coupons, wishlist, and order management.

</div>

---

# 📚 Table of Contents

- Features
- Tech Stack
- Project Structure
- License

---

# ✨ Features

## 👤 User Features

| Feature | Description |
|---------|-------------|
| Authentication | Signup, Login, Email OTP Verification |
| Profile | Update Profile & Address Management |
| Products | Browse, Search, Filter Products |
| Wishlist | Save Favourite Products |
| Cart | Add, Update & Remove Cart Items |
| Checkout | Secure Checkout Process |
| Stripe Payment | Online Card Payment |
| Wallet | Wallet Recharge & Refund |
| Coupons | Discount Coupon System |
| Referral | Referral Bonus |
| Orders | Order History & Tracking |
| Returns | Return Request Management |
| Reviews | Product Ratings & Reviews |

---

## 🛠 Admin Features

| Module | Description |
|---------|-------------|
| Dashboard | Sales & Revenue Analytics |
| Users | User Management |
| Categories | Category Management |
| Products | Product CRUD |
| Inventory | Variant & Stock Management |
| Coupons | Coupon CRUD |
| Offers | Product & Category Offers |
| Orders | Order Processing |
| Wallet | Wallet Transactions |

---

# 💻 Tech Stack

- Python 3.12
- Django 6.x
- PostgreSQL
- HTML5
- CSS3
- Bootstrap
- JavaScript
- Stripe
- Cloudinary
- Git & GitHub
- Tailwind CSS
---

# 📂 Project Structure

```
veska_fashion/
│
├── about_us/                         # About Us module
│   ├── templates/
│   ├── models.py
│   ├── urls.py
│   └── views.py
│
├── admin_side/                       # Admin authentication & dashboard
│   ├── templates/
│   ├── models.py
│   ├── urls.py
│   └── views.py
│
├── cart_user/                        # Shopping cart management
│   ├── templates/
│   ├── context_processor.py
│   ├── models.py
│   ├── cart_helpers.py
│   ├── urls.py
│   └── views.py
│
├── category_admin/                   # Category management
│   ├── templates/
│   ├── forms.py
│   ├── models.py
│   ├── urls.py
│   └── views.py
│
├── checkout_page/                    # Checkout & payment processing
│   ├── templates/
│   ├── models.py
│   ├── urls.py
│   └── views.py
│
├── core/                             # Shared utilities & common logic
│   ├── adapters.py
│   ├── otp.py
│   ├── validators.py
│   ├── utils.py
│
├── coupon_admin/                     # Coupon management
│   ├── templates/
│   ├── models.py
│   ├── urls.py
│   └── views.py
│
├── customers/                        # Customer management
│   ├── templates/
│   ├── models.py
│   ├── urls.py
│   └── views.py
│
├── dashboard/                        # Dashboard & analytics
│   ├── templates/
│   ├── models.py
│   ├── urls.py
│   └── views.py
│
├── offer_admin/                      # Offer management
│   ├── templates/
│   ├── models.py
│   ├── urls.py
│   ├── forms.py
│   └── views.py
│
├── order_admin/                      # Admin order management
│   ├── templates/
│   ├── models.py
│   ├── urls.py
│   └── views.py
│
├── order_user/                       # User order management
│   ├── templates/
│   ├── models.py
│   ├── order_email.py
│   ├── urls.py
│   └── views.py
│
├── product_admin/                    # Product & inventory management
│   ├── templates/
│   ├── models.py
│   ├── urls.py
│   ├── forms.py
│   └── views.py
│
├── product_user/                     # Product and Shop management
│   ├── templates/
│   ├── models.py
│   ├── urls.py
│   └── views.py                                            
├── templates/                        # Gobal HTML templates
│
├── users/                            # Authentication & user management
│   ├── templates/
│   ├── backends.py
│   ├── models.py
│   ├── urls.py
│   ├── utils.py
│   ├── validators.py
│   └── views.py
│
├── wallet_admin/                     # Wallet administration
│   ├── templates/
│   ├── models.py
│   ├── urls.py
│   └── views.py
│
├── wallet_user/                      # User wallet & transactions
│   ├── templates/
│   ├── models.py
│   ├── urls.py
│   ├── utils.py
│   └── views.py
│
├── wishlist_user/                    # Wishlist management
│   ├── templates/
│   ├── models.py
│   ├── urls.py
│   └── views.py
│
├── veska_fashion/                    # Django project configuration
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
│
├── .env                              # Environment variables
├── .gitignore                        # Git ignored files
├── manage.py                         # Django management script
├── requirements.txt                  # Project dependencies
└── README.md                         # Project documentation
```


---

# 🚀 Getting Started

## Clone Repository

```bash
git clone https://github.com/<username>/veska_fashion.git
cd veska_fashion
```

## Create Virtual Environment

```bash
python3 -m venv env
```

Linux

```bash
source env/bin/activate
```

Windows

```bash
env\Scripts\activate
```

---

## Install Requirements

```bash
pip install -r requirements.txt
```

---

## Database

```bash
python3 manage.py makemigrations
python3 manage.py migrate
```

---

## Create Admin

```bash
python3 manage.py createsuperuser
```

---

## Run Server

```bash
python3 manage.py runserver
```

Visit

```
http://127.0.0.1:8000/
```

Admin

```
http://127.0.0.1:8000/admin/
```

---

# ⚙️ Environment Variables

Create a `.env` file:

```env
SECRET_KEY=your_secret_key
DEBUG=True

DB_NAME=DB_NAME=veska_db
DB_USER=postgres
DB_PASSWORD=your_database_password
DB_HOST=localhost
DB_PORT=5432

STRIPE_SECRET_KEY=your_secret_key
STRIPE_PUBLISHABLE_KEY=your_publishable_key

CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret
```
---

## 🤝 Contributing

Contributions are welcome! To get started:

1. **Fork** the repository
2. **Create** your feature branch — `git checkout -b feature/your-feature`
3. **Commit** your changes — `git commit -m 'Add some feature'`
4. **Push** to the branch — `git push origin feature/your-feature`
5. **Open** a Pull Request

Please ensure your code follows the existing style and all tests pass before submitting.

---

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
