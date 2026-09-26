import os
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, render_template_string, request, redirect, jsonify, session
import sqlite3,  json, io, datetime
import datetime as dt_module
from datetime import datetime as dt_class, timedelta
from werkzeug.utils import secure_filename
from PIL import Image

app = Flask(__name__)
app.secret_key = 'tibishop_2026_final_v4'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs('static/uploads', exist_ok=True)

# ===== FIX ALL YOUR ERRORS - HEADERS =====
ORDERS_FILE = "orders.json"
PRODUCTS_FILE = "products.json"
SELLERS_FILE = "sellers.json"
if not os.path.exists(ORDERS_FILE):
    with open(ORDERS_FILE,'w') as f:
        json.dump([], f)

ALLOWED = {'png','jpg','jpeg','webp'}
def allowed(f):
    return '.' in f and f.rsplit('.',1)[1].lower() in ALLOWED

def compress_to_80kb(file_storage):
    try:
        img = Image.open(file_storage)
        if img.mode in ("RGBA", "P"): img = img.convert("RGB")
        if max(img.size) > 1200: img.thumbnail((1200, 1200))
        quality = 85
        while quality >= 20:
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=quality, optimize=True)
            if buffer.tell() / 1024 <= 80:
                buffer.seek(0)
                return buffer
            quality -= 10
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=20, optimize=True)
        buffer.seek(0)
        return buffer
    except:
        return file_storage

# ===== IN-MEMORY LISTS FOR SELLER DASHBOARD =====
products_list = []
sellers_list = []
orders_list = []
boosts_list = []
active_boosts_list = boosts_list

class SellerObj:
    def __init__(self, phone, plan="commission", charge_payer="seller", yearly_expiry=None):
        self.phone = phone
        self.plan = plan
        self.charge_payer = charge_payer
        self.yearly_expiry = yearly_expiry or (dt_class.utcnow() + timedelta(days=365))
    def is_yearly_active(self):
        if self.plan!= "yearly" or not self.yearly_expiry: return False
        return dt_class.utcnow() < self.yearly_expiry

class BoostObj:
    def __init__(self, product_id, boost_type, amount_paid):
        self.product_id = product_id
        self.boost_type = boost_type
        self.amount_paid = amount_paid
        self.cancelled = False
        now = dt_class.utcnow()
        if boost_type == "daily": self.expiry = now + timedelta(days=1)
        elif boost_type == "weekly": self.expiry = now + timedelta(days=7)
        else: self.expiry = now + timedelta(days=30)
    def is_active(self):
        if self.cancelled: return False
        return dt_class.utcnow() < self.expiry
    def cancel(self):
        self.cancelled = True
        return True

def add_boost(product_id, boost_type, amount_paid):
    cancel_boost(product_id)
    b = BoostObj(product_id, boost_type, amount_paid)
    boosts_list.append(b)
    return b

def cancel_boost(product_id):
    for b in boosts_list:
        if b.product_id == product_id and b.is_active():
            b.cancel()
            return {"status": "cancelled", "id": product_id}
    return {"status": "not_found"}

def get_active_boosts():
    return [b for b in boosts_list if b.is_active()]

def get_admin_settings():
    return {
        "yearly_price": int(os.getenv("YEARLY_PRICE", 99900)),
        "commission_rate": float(os.getenv("COMMISSION_RATE", 0.04)),
        "daily_boost": int(os.getenv("DAILY_BOOST", 2000)),
        "weekly_boost": int(os.getenv("WEEKLY_BOOST", 10000)),
        "monthly_boost": int(os.getenv("MONTHLY_BOOST", 35000)),
        "flutterwave_percent": float(os.getenv("FLW_PERCENT", 0.03))
    }

def init_db():
    conn = sqlite3.connect('tibishop.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY, name TEXT, type TEXT, options TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT, price INTEGER, photo TEXT, details TEXT, category TEXT, seller_phone TEXT, status TEXT DEFAULT "approved")')
    c.execute('CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, product_id INTEGER, product_name TEXT, price INTEGER, buyer_phone TEXT, seller_phone TEXT, status TEXT, date TEXT, fee REAL, delivery_status TEXT DEFAULT "Packed", seller_location TEXT, buyer_location TEXT, paid_out INTEGER DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS leads (id INTEGER PRIMARY KEY, buyer_phone TEXT, product_id INTEGER, question TEXT, viewed_at TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS wallets (phone TEXT PRIMARY KEY, balance REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY, buyer_phone TEXT, seller_phone TEXT, message TEXT, time TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS users (phone TEXT PRIMARY KEY, role TEXT, shop_name TEXT, agreed_terms INTEGER DEFAULT 0, location TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS terms (id INTEGER PRIMARY KEY, content TEXT, updated_at TEXT)')
    conn.commit(); conn.close()
init_db()

def get_header():
    return """
    <html><head><meta name='viewport' content='width=device-width, initial-scale=1'>
    <style>
    body{margin:0;font-family:Inter,sans-serif;background:#f7f7f8;padding-bottom:90px}
   .nav{padding:12px 16px;background:#111;color:#fff;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100}
   .nav a{color:#fff;text-decoration:none;margin-left:10px;font-size:14px}
   .orange-bar{display:flex;gap:8px;overflow-x:auto;padding:10px;background:#fff;border-bottom:1px solid #eee;position:sticky;top:50px;z-index:90}
   .orange-bar a{background:#ff8a00;color:#fff;padding:8px 14px;border-radius:20px;text-decoration:none;font-weight:600;font-size:13px;white-space:nowrap}
   .orange-bar a.black{background:#111}
    </style></head><body>
    <div class='nav'><b onclick="location.href='/'" style="cursor:pointer">TibiShop</b><div><a href='/shop'>Shop</a><a href='/seller/dashboard?phone=' id="dashLink">Seller</a><a href='/profile'>👤 Profile</a><a href='/admin'>Admin</a></div></div>
    <div class='orange-bar'>
      <a href='/admin'>📊 Admin</a><a href='/shop'>🛒 Shop</a><a href='/leads'>📈 Leads</a><a href='/wallet'>💳 TibiPay</a><a href='/orders'>📦 Orders</a><a href='/terms'>📜 Terms</a><a href='/welcome'>🚀 Welcome</a><a href='/login' class="black">🔐 Login</a>
    </div>
    <script>let p=localStorage.getItem('tibi_phone'); if(p){ let l=document.getElementById('dashLink'); if(l) l.href='/seller/dashboard?phone='+p; }</script>
    """
def header(): return get_header()

BASE_CSS = """<style>
*{box-sizing:border-box;margin:0;padding:0;font-family:Inter,sans-serif}
body{background:#f7f7f8;padding-bottom:85px}
.top{background:#111;color:#fff;padding:12px 16px;display:flex;justify-content:space-between;align-items:center}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;padding:12px}
.card{background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.06);display:flex;flex-direction:column}
.card img{width:100%;height:160px;object-fit:cover;background:#eee}
.card.info{padding:10px}
.price{font-weight:700}.badge{background:#e7f9ef;color:#0a7d3e;padding:2px 8px;border-radius:20px;font-size:11px}
.bottom-nav{position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1px solid #e5e5e5;display:flex;justify-content:space-around;padding:8px 0;z-index:200}
.bottom-nav a{text-decoration:none;color:#666;font-size:11px;text-align:center;display:flex;flex-direction:column;align-items:center;gap:2px}
.bottom-nav a.active{color:#111;font-weight:700}
.btn{border:none;border-radius:12px;padding:10px 14px;cursor:pointer;font-weight:600}
.btn-black{background:#111;color:#fff;width:100%}.btn-orange{background:#ff8a00;color:#fff}
.wallet{background:linear-gradient(135deg,#111,#333);color:#fff;border-radius:20px;padding:18px;margin:12px}
.filter-bar{background:#fff;padding:10px;display:flex;gap:8px;overflow-x:auto;position:sticky;top:90px;z-index:80}
.filter-bar input,.filter-bar select{border:1px solid #ddd;border-radius:20px;padding:8px 12px}
.lead-card{background:#fff;border-left:4px solid #ff8a00;padding:10px;border-radius:8px;margin:8px 0}
.chat-bar{position:fixed;bottom:70px;left:0;right:0;background:#fff;border-top:1px solid #eee;padding:8px;display:flex;gap:8px}
</style>"""

JS = """<script>function filterCategory(cat){document.querySelectorAll('.card').forEach(c=>{if(cat=='all'||c.dataset.cat==cat)c.style.display='flex';else c.style.display='none'})}</script>"""

# ===== NEW FEATURES: LOGIN, PROFILE, TERMS =====
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        phone = request.form.get('phone','').strip()
        role = request.form.get('role','buyer')
        shop_name = request.form.get('shop_name','')
        if len(phone) < 9:
            return get_header() + "<div style='padding:20px'>Invalid phone <a href='/login'>Back</a></div>"
        conn=sqlite3.connect('tibishop.db'); c=conn.cursor()
        c.execute('INSERT OR REPLACE INTO users (phone, role, shop_name, agreed_terms) VALUES (?,?,?, COALESCE((SELECT agreed_terms FROM users WHERE phone=?),0))',(phone, role, shop_name, phone))
        c.execute('INSERT OR IGNORE INTO wallets (phone,balance) VALUES (?,0)',(phone,))
        conn.commit(); conn.close()
        if role == 'seller':
            return f"<script>localStorage.setItem('tibi_phone','{phone}');localStorage.setItem('tibi_role','seller');location.href='/seller/dashboard?phone={phone}'</script>"
        else:
            return f"<script>localStorage.setItem('tibi_phone','{phone}');localStorage.setItem('tibi_role','buyer');location.href='/shop?phone={phone}'</script>"
    return get_header() + """
    <div style="max-width:420px;margin:20px auto;background:#fff;padding:20px;border-radius:20px">
    <h2>🔐 Simple Login</h2><p style="color:#666;font-size:13px">Any SIM, no password</p>
    <form method="post" style="margin-top:15px">
      <select name="role" onchange="document.getElementById('shopDiv').style.display=this.value=='seller'?'block':'none'" style="width:100%;padding:12px;border-radius:12px;border:1px solid #ddd;margin-bottom:10px">
        <option value="buyer">I want to Buy</option><option value="seller">I want to Sell</option>
      </select>
      <input name="phone" placeholder="07XXXXXXXX" required style="width:100%;padding:12px;border-radius:12px;border:1px solid #ddd;margin-bottom:10px">
      <div id="shopDiv" style="display:none"><input name="shop_name" placeholder="Shop name" style="width:100%;padding:12px;border-radius:12px;border:1px solid #ddd;margin-bottom:10px"></div>
      <button class="btn btn-black">Continue →</button>
    </form><br><a href="/terms">Read Terms</a> | <a href="/profile">Profile</a></div>"""

@app.route('/profile')
def profile():
    phone = request.args.get('phone','')
    conn=sqlite3.connect('tibishop.db'); c=conn.cursor()
    terms_row=c.execute('SELECT * FROM terms ORDER BY id DESC LIMIT 1').fetchone()
    conn.close()
    terms_content = terms_row[1] if terms_row else "No terms yet. Admin please add."
    return get_header() + f"""
    <div style="max-width:500px;margin:10px auto;padding:12px">
      <div style="background:#fff;padding:16px;border-radius:16px">
        <h3>👤 My Profile</h3>
        <p id="pPhone">Phone: {phone or 'Not logged - <a href=/login>Login</a>'}</p><p id="pRole"></p>
        <div style="margin-top:10px"><label><b>📍 Pin My Location</b></label><br>
          <button onclick="pinLoc()" class="btn btn-orange">📍 Pin My Current Location</button>
          <span id="locStatus">Not pinned</span><div id="mapLink"></div></div>
        <hr style="margin:12px 0"><h4>📜 Terms</h4>
        <div style="background:#f7f7f8;padding:10px;border-radius:10px;max-height:200px;overflow:auto;font-size:13px">{terms_content}</div>
        <form method="post" action="/agree_terms" style="margin-top:10px;display:flex;gap:8px">
          <input type="hidden" name="phone" id="agreePhone" value="{phone}">
          <button name="agree" value="1" class="btn btn-black" style="width:auto">✅ I Agree</button>
          <button name="agree" value="0" class="btn" style="width:auto;background:#eee">❌ Disagree</button>
        </form>
      </div></div>
    <script>
    let ph=localStorage.getItem('tibi_phone')||'{phone}';let role=localStorage.getItem('tibi_role')||'';
    document.getElementById('pPhone').innerText='Phone: '+ph;document.getElementById('pRole').innerText='Role: '+role;
    document.getElementById('agreePhone').value=ph;
    function pinLoc(){{if(!navigator.geolocation){{alert('No GPS');return}}document.getElementById('locStatus').innerText='Locating...';
      navigator.geolocation.getCurrentPosition(pos=>{{let loc=pos.coords.latitude+','+pos.coords.longitude;
      document.getElementById('locStatus').innerText='📍 Pinned: '+loc;
      document.getElementById('mapLink').innerHTML='<a target=_blank href=https://www.google.com/maps?q='+loc+'>View Map</a>';
      let fd=new FormData();fd.append('phone',ph);fd.append('location',loc);fetch('/save_user_location',{{method:'POST',body:fd}}).then(r=>r.json()).then(d=>alert('Location saved'))}},err=>{{document.getElementById('locStatus').innerText='Failed'}})}}
    </script></body></html>"""

@app.route('/save_user_location', methods=['POST'])
def save_user_location():
    phone=request.form.get('phone','').strip(); loc=request.form.get('location','').strip()
    conn=sqlite3.connect('tibishop.db'); c=conn.cursor(); c.execute('UPDATE users SET location=? WHERE phone=?',(loc, phone)); conn.commit(); conn.close()
    return {"status":"ok","location":loc}

@app.route('/agree_terms', methods=['POST'])
def agree_terms():
    phone=request.form.get('phone',''); agree=int(request.form.get('agree',0))
    conn=sqlite3.connect('tibishop.db'); c=conn.cursor(); c.execute('UPDATE users SET agreed_terms=? WHERE phone=?',(agree, phone)); conn.commit(); conn.close()
    return redirect(f'/profile?phone={phone}')

@app.route('/terms', methods=['GET','POST'])
def terms():
    conn=sqlite3.connect('tibishop.db'); c=conn.cursor()
    if request.method=='POST':
        content=request.form.get('content',''); c.execute('INSERT INTO terms (content, updated_at) VALUES (?,?)',(content, dt_class.now().isoformat())); conn.commit()
    row=c.execute('SELECT * FROM terms ORDER BY id DESC LIMIT 1').fetchone(); conn.close()
    content=row[1] if row else ""
    return get_header() + f"""
    <div style="max-width:700px;margin:10px auto;padding:12px"><div style="background:#fff;padding:16px;border-radius:16px">
      <h3>📜 Terms & Conditions</h3><div style="background:#f7f7f8;padding:12px;border-radius:12px;margin:10px 0;white-space:pre-wrap">{content or 'No terms yet'}</div>
      <hr><h4>✍️ Admin - Edit Terms</h4><form method="post">
      <textarea name="content" style="width:100%;height:200px;padding:10px;border-radius:12px;border:1px solid #ddd">{content}</textarea><br>
      <button class="btn btn-orange">💾 Save Terms</button></form></div></div>"""

# ===== SHOP / ADMIN (keep your original) =====
ADMIN_HTML = BASE_CSS + """
<div class="top"><b>TibiShop Admin + TibiPay</b><a href="/shop" style="color:#fff">View Shop</a></div>
<div style="padding:12px;display:flex;gap:8px;flex-wrap:wrap">
<a href="/admin" style="background:#ff8a00;color:#fff;padding:8px 14px;border-radius:20px;text-decoration:none">Admin</a>
<a href="/shop" style="background:#ff8a00;color:#fff;padding:8px 14px;border-radius:20px;text-decoration:none">Shop</a>
<a href="/leads" style="background:#ff8a00;color:#fff;padding:8px 14px;border-radius:20px;text-decoration:none">Leads</a>
<a href="/wallet" style="background:#ff8a00;color:#fff;padding:8px 14px;border-radius:20px;text-decoration:none">Wallet</a>
<a href="/orders" style="background:#ff8a00;color:#fff;padding:8px 14px;border-radius:20px;text-decoration:none">Orders</a>
<a href="/terms" style="background:#111;color:#fff;padding:8px 14px;border-radius:20px;text-decoration:none">Terms</a>
<a href="/profile" style="background:#111;color:#fff;padding:8px 14px;border-radius:20px;text-decoration:none">Profile</a>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px">
<div style="background:#fff;padding:16px;border-radius:16px">
<h3>Questions</h3>
<form method="post" action="/add_question"><input name="name" placeholder="e.g occasion" required style="width:100%;padding:8px;margin:4px 0"><select name="type" style="width:100%;padding:8px"><option>Choice</option><option>Text</option></select><input name="options" placeholder="wedding,birthday" style="width:100%;padding:8px;margin:4px 0"><button class="btn btn-black">Add</button></form>
{% for q in questions %}<div>{{q[1]}} <a href="/delete_q/{{q[0]}}">x</a></div>{% endfor %}
</div>
<div style="background:#fff;padding:16px;border-radius:16px">
<h3>Add Product</h3>
<form method="post" action="/add_product" enctype="multipart/form-data">
<input name="name" placeholder="Product name" required style="width:100%;padding:8px;margin:4px 0">
<input name="price" type="number" placeholder="Price UGX" required style="width:100%;padding:8px">
<select name="category" style="width:100%;padding:8px;margin:4px 0"><option value="fashion">Fashion</option><option value="beauty">Beauty</option><option value="food">Food</option><option value="services">Services</option></select>
<input name="seller_phone" placeholder="Seller phone ANY SIM" required style="width:100%;padding:8px">
<input name="details" placeholder="Details" style="width:100%;padding:8px">
<input type="file" name="photo" accept="image/*" required style="margin:8px 0">
<button class="btn btn-black">Add Product</button></form>
{% for p in products %}<div style="display:flex;gap:8px;margin:6px 0"><img src="/{{p[3]}}" width="40" height="40" style="border-radius:8px;object-fit:cover"><span>{{p[1]}} {{p[2]}} {{p[6]}}</span> <a href="/delete_p/{{p[0]}}">x</a></div>{% endfor %}
</div></div>"""

SHOP_HTML = BASE_CSS + """
<div class="top"><b>TibiShop</b><span style="font-size:12px">TibiPay 0% fee • <a href="/profile" style="color:#ff8a00">Profile</a></span></div>
<div class="filter-bar">
<select onchange="filterCategory(this.value)"><option value="all">All Categories</option><option value="fashion">Fashion</option><option value="beauty">Beauty</option><option value="food">Food</option><option value="services">Services</option></select>
<form method="get" style="display:flex;gap:6px">{% for q in questions %}<input name="{{q[1]}}" placeholder="{{q[1]}}" style="width:100px">{% endfor %}<button class="btn" style="background:#111;color:#fff;border-radius:20px">Filter</button></form>
</div>
<div class="wallet"><h2>UGX {{wallet_balance}}</h2><span class="badge">Buyer 0%</span><span class="badge">Seller 98.5%</span></div>
<div class="grid">
{% for p in products %}<div class="card" data-cat="{{p[5]}}"><img src="/{{p[3]}}" onerror="this.src='https://via.placeholder.com/300'">
<div class="info"><b>{{p[1]}}</b> <span class="badge">{{p[5]}}</span><div class="price">{{p[2]}} UGX</div><div style="font-size:11px;color:#666">{{p[4]}} • {{p[6]}}</div>
<form method="post" action="/buy/{{p[0]}}" style="margin-top:8px"><input name="buyer_phone" placeholder="Buyer phone 07..." required style="width:100%;padding:8px;border:1px solid #ddd;border-radius:8px;margin-bottom:6px"><input type="hidden" name="buyer_location" id="bloc_{{p[0]}}"><button type="button" onclick="pinBuyer({{p[0]}})" style="font-size:11px;margin-bottom:4px">📍 Pin My Location</button><button class="btn btn-black">Pay with TibiPay</button></form>
<a href="/chat/{{p[0]}}" style="font-size:12px;display:block;text-align:center;margin-top:6px">💬 Chat seller</a></div></div>{% endfor %}</div>
<div class="bottom-nav"><a class="active" href="/shop">🏠<br>Home</a><a href="#" onclick="filterCategory('all')">📂<br>Categories</a><a href="/wallet">💳<br>TibiPay</a><a href="/leads">📊<br>Leads</a><a href="/orders">📦<br>Orders</a></div>
<script>function pinBuyer(id){if(!navigator.geolocation){alert('No GPS');return}navigator.geolocation.getCurrentPosition(p=>{let loc=p.coords.latitude+','+p.coords.longitude;document.getElementById('bloc_'+id).value=loc;alert('📍 Pinned: '+loc);});}</script>
""" + JS

@app.route('/')
@app.route('/admin')
def admin():
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();q=c.execute('SELECT * FROM questions').fetchall();p=c.execute('SELECT * FROM products').fetchall();conn.close()
    return render_template_string(ADMIN_HTML, questions=q, products=p)

@app.route('/shop')
def shop():
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();questions=c.execute('SELECT * FROM questions').fetchall();products=c.execute('SELECT * FROM products').fetchall();w=c.execute('SELECT balance FROM wallets WHERE phone="TIBIPAY_EARNINGS"').fetchone();bal=int(w[0]) if w else 0;conn.close()
    return render_template_string(SHOP_HTML, questions=questions, products=products, wallet_balance=bal)

@app.route('/add_question', methods=['POST'])
def add_q():
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();c.execute('INSERT INTO questions (name,type,options) VALUES (?,?,?)',(request.form['name'],request.form['type'],request.form['options']));conn.commit();conn.close();return redirect('/')
@app.route('/add_product', methods=['POST'])
def add_p():
    name=request.form['name'];price=request.form['price'];details=request.form['details'];cat=request.form['category'];seller_phone=request.form['seller_phone']
    file=request.files.get('photo');photo_path=''
    if file and allowed(file.filename):
        compressed=compress_to_80kb(file);fname=str(len(os.listdir(app.config['UPLOAD_FOLDER']))+1)+"_"+secure_filename(file.filename)
        if not fname.lower().endswith('.jpg'): fname+='.jpg'
        fpath=os.path.join(app.config['UPLOAD_FOLDER'], fname)
        with open(fpath,'wb') as out: out.write(compressed.read() if hasattr(compressed,'read') else compressed.getvalue())
        photo_path=fpath
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();c.execute('INSERT INTO products (name,price,photo,details,category,seller_phone) VALUES (?,?,?,?,?,?)',(name,price,photo_path,details,cat,seller_phone));c.execute('INSERT OR IGNORE INTO wallets (phone,balance) VALUES (?,0)',(seller_phone,));conn.commit();conn.close();return redirect('/')
@app.route('/delete_q/<int:id>')
def del_q(id):
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();c.execute('DELETE FROM questions WHERE id=?',(id,));conn.commit();conn.close();return redirect('/')
@app.route('/delete_p/<int:id>')
def del_p(id):
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();c.execute('DELETE FROM products WHERE id=?',(id,));conn.commit();conn.close();return redirect('/')

@app.route('/buy/<int:pid>', methods=['POST'])
def buy(pid):
    buyer_phone=request.form['buyer_phone'];buyer_loc=request.form.get('buyer_location','')
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();prod=c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()
    if not prod: conn.close();return "Product not found",404
    price=int(prod[2]);fee=round(price*0.015);seller_get=price-fee;seller_phone=prod[6]
    c.execute('INSERT OR IGNORE INTO wallets (phone,balance) VALUES (?,0)',(buyer_phone,));c.execute('INSERT OR IGNORE INTO wallets (phone,balance) VALUES (?,0)',(seller_phone,));c.execute('INSERT OR IGNORE INTO wallets (phone,balance) VALUES (?,0)',('TIBIPAY_EARNINGS',))
    c.execute('UPDATE wallets SET balance=balance+? WHERE phone=?',(seller_get,seller_phone));c.execute('UPDATE wallets SET balance=balance+? WHERE phone=?',(fee,'TIBIPAY_EARNINGS'))
    c.execute('INSERT INTO orders (product_id,product_name,price,buyer_phone,seller_phone,status,date,fee,delivery_status,buyer_location) VALUES (?,?,?,?,?,?,?,?,?,?)',(pid,prod[1],price,buyer_phone,seller_phone,'paid',dt_class.now().isoformat(),fee,'Packed',buyer_loc))
    oid=c.lastrowid;c.execute('INSERT INTO leads (buyer_phone,product_id,question,viewed_at) VALUES (?,?,?,?)',(buyer_phone,pid,'bought',dt_class.now().isoformat()))
    try:
        with open(ORDERS_FILE,'r') as f: jorders=json.load(f)
    except: jorders=[]
    jorders.append({"id":oid,"product_id":pid,"product_name":prod[1],"price":price,"buyer_phone":buyer_phone,"seller_phone":seller_phone,"buyer_location":buyer_loc,"delivery_status":"Packed","date":dt_class.now().isoformat()})
    with open(ORDERS_FILE,'w') as f: json.dump(jorders,f,indent=2)
    conn.commit();conn.close()
    return BASE_CSS + f"<div class='top'><b>Payment Success</b></div><div style='padding:20px;text-align:center;background:#fff;margin:12px;border-radius:16px'><h2>Paid {price} UGX</h2><p>Seller {seller_phone} got {seller_get}</p><p>Buyer loc: {buyer_loc or 'not pinned'}</p><br><a href='/track/{oid}' class='btn' style='background:#ff8a00;color:#fff;padding:12px 20px;text-decoration:none;border-radius:12px'>🚚 Track Order</a> <a href='/shop'>Shop</a></div>"

# ===== SELLER DASHBOARD (FIXED PLACEMENT) =====
@app.route('/seller/dashboard')
def seller_dashboard():
    phone=request.args.get('phone','')
    if not phone: return get_header()+"<div style='padding:20px'>Add?phone=2567... <a href='/login'>Login</a></div>"
    seller=next((s for s in sellers_list if s.phone==phone),None)
    if not seller:
        seller=SellerObj(phone=phone);sellers_list.append(seller)
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();db_prods=c.execute('SELECT * FROM products WHERE seller_phone=?',(phone,)).fetchall();conn.close()
    my_mem=[p for p in products_list if p.get('seller_phone')==phone]
    my_db=[{'id':p[0],'name':p[1],'price':p[2],'photos':[p[3].replace('static/uploads/','') if p[3] else ''],'status':'approved','views':0,'leads':0,'leads_list':[],'location':{},'desc':p[4]} for p in db_prods]
    my_products=my_mem+my_db;active_boosts=get_active_boosts();settings=get_admin_settings();msg=request.args.get('msg','')
    total_views=sum([p.get('views',0) for p in my_products]);total_leads=sum([p.get('leads',0) for p in my_products])
    html=f"""
    <style>body{{font-family:sans-serif;padding:10px;background:#f9f9f9;padding-bottom:100px}}.card{{background:white;border:1px solid #e5e5e5;padding:14px;margin:12px 0;border-radius:12px}}.grid{{display:flex;gap:10px;flex-wrap:wrap}}.stat{{flex:1;min-width:90px;text-align:center;background:#f0f7ff;padding:10px;border-radius:8px}}.slideshow-wrap{{position:relative;width:100%;max-width:260px;height:180px;overflow:hidden;border-radius:10px;background:#eee}}.slides{{display:flex;height:100%;overflow-x:auto;scroll-snap-type:x mandatory}}.slides img{{width:260px;height:180px;object-fit:cover;flex-shrink:0;scroll-snap-align:start}}.nextBtn{{position:absolute;right:6px;top:50%;transform:translateY(-50%);background:rgba(0,0,0,.6);color:white;border:none;border-radius:50%;width:30px;height:30px}}.btn{{padding:7px 14px;border:none;border-radius:6px;cursor:pointer}}.btn-red{{background:#ff3b30;color:white}}.btn-green{{background:#34c759;color:white}}.btn-black{{background:black;color:white}}.btn-orange{{background:#ff8a00;color:white}}</style>
    <div style="padding:10px;background:#111;color:#fff;display:flex;justify-content:space-between"><b>Seller: {phone}</b><a href="/profile?phone={phone}" style="color:#ff8a00">👤 Profile</a></div>
    <p>Plan: <b>{seller.plan.upper()}</b> | {msg}</p>
    <div class="grid"><div class="stat"><b>{len(my_products)}</b><br>Products</div><div class="stat"><b>{total_views}</b><br>Views</div><div class="stat"><b>{total_leads}</b><br>Leads</div><div class="stat"><b>{len([b for b in active_boosts if any(p['id']==b.product_id for p in my_products)])}</b><br>Boosts</div></div>
    <div class="card"><h3>💳 Subscription</h3><form method="POST" action="/seller/upgrade"><input type="hidden" name="phone" value="{phone}"><select name="plan"><option value="commission">Free 4%</option><option value="yearly">Yearly 99.9k</option></select><select name="charge_payer"><option value="seller">I pay 3%</option><option value="buyer">Buyer pays 3%</option></select><button class="btn btn-black">Save</button></form></div>
    <div class="card"><h3>➕ Add Product - Max 4 Photos</h3><form method="POST" action="/product/add" enctype="multipart/form-data"><input type="hidden" name="phone" value="{phone}"><input type="hidden" name="lat" id="lat"><input type="hidden" name="lng" id="lng"><input name="name" placeholder="Product name" required style="width:100%;padding:8px;margin:5px 0"><input name="price" type="number" placeholder="Price UGX" required style="width:100%;padding:8px;margin:5px 0"><input name="desc" placeholder="Description" style="width:100%;padding:8px;margin:5px 0"><input type="file" name="photos" id="photoInput" multiple accept="image/*" required><button type="button" onclick="document.getElementById('cameraInput').click()" class="btn btn-orange">📷 Camera</button><input type="file" id="cameraInput" accept="image/*" capture="environment" style="display:none"><div id="preview" style="display:flex;gap:6px;margin:10px 0;flex-wrap:wrap"></div><p id="photoCount">0/4</p><button type="button" onclick="getLocation()" class="btn btn-orange">📍 Pin My Location</button><span id="locStatus">Not pinned</span><br><br><button type="submit" class="btn btn-black" style="width:100%">Upload</button></form></div><h3>📦 My Products</h3>
    """
    for prod in my_products:
        pid=prod['id'];boost=next((b for b in active_boosts if b.product_id==pid),None)
        boost_html=f"<span style='background:#ffeb3b;padding:3px 6px;border-radius:5px'>🔥 BOOSTED till {boost.expiry.strftime('%d %b %H:%M')}</span>" if boost else "<span style='background:#eee;padding:3px 6px'>Not Boosted</span>"
        photos_inner="".join([f"<img src='/static/uploads/{p}'>" if p else "" for p in prod.get('photos',[])])
        html+=f"""<div class="card"><div class="slideshow-wrap"><div class="slides" id="slides-{pid}">{photos_inner or "<img src='https://via.placeholder.com/300'>"}</div><button class="nextBtn" onclick="nextSlide({pid})">›</button></div><p><b>{prod.get('name','')}</b> - {prod.get('price','')} UGX</p><p>{prod.get('desc','')}</p><p>{boost_html}</p>"""
        if boost:
            html+=f"""<form method="POST" action="/boost/cancel"><input type="hidden" name="product_id" value="{pid}"><input type="hidden" name="phone" value="{phone}"><button class="btn btn-red">Cancel Boost</button></form>"""
        else:
            html+=f"""<form method="POST" action="/boost/buy"><input type="hidden" name="product_id" value="{pid}"><input type="hidden" name="phone" value="{phone}"><select name="boost_type"><option value="daily">Daily {settings['daily_boost']} UGX</option><option value="weekly">Weekly {settings['weekly_boost']} UGX</option><option value="monthly">Monthly {settings['monthly_boost']} UGX</option></select><button class="btn btn-green">Boost</button></form>"""
        html+="</div>"
    html+="""
    <script>
    function nextSlide(id){const el=document.getElementById('slides-'+id);el.scrollBy({left:260,behavior:'smooth'});if(el.scrollLeft+260>=el.scrollWidth-20)setTimeout(()=>el.scrollTo({left:0,behavior:'smooth'}),600)}
    function getLocation(){if(!navigator.geolocation){alert('No GPS');return}document.getElementById('locStatus').innerText='Locating...';navigator.geolocation.getCurrentPosition(pos=>{document.getElementById('lat').value=pos.coords.latitude;document.getElementById('lng').value=pos.coords.longitude;document.getElementById('locStatus').innerText='📍 Pinned: '+pos.coords.latitude.toFixed(4)+','+pos.coords.longitude.toFixed(4)},err=>{document.getElementById('locStatus').innerText='Failed'})}
    document.addEventListener('DOMContentLoaded',()=>{const input=document.getElementById('photoInput');const cam=document.getElementById('cameraInput');const preview=document.getElementById('preview');const count=document.getElementById('photoCount');const handleFiles=files=>{if(files.length>4){alert('Max 4');return}preview.innerHTML='';for(let f of files){const img=document.createElement('img');img.src=URL.createObjectURL(f);img.style='width:65px;height:65px;object-fit:cover;border-radius:6px;border:1px solid #ddd';preview.appendChild(img)}count.innerText=files.length+'/4'};if(input)input.addEventListener('change',()=>handleFiles(input.files));if(cam)cam.addEventListener('change',()=>{const dt=new DataTransfer();if(input.files)for(let f of input.files)dt.items.add(f);for(let f of cam.files)dt.items.add(f);if(dt.files.length>4){alert('Max 4');return}input.files=dt.files;handleFiles(input.files)})})
    </script>"""
    return BASE_CSS+html

@app.route('/product/add', methods=['POST'])
def product_add():
    phone=request.form.get('phone');files=request.files.getlist('photos')
    if len(files)==0 or len(files)>4: return f"Need 1-4 photos, got {len(files)}",400
    os.makedirs('static/uploads',exist_ok=True);compressed=[]
    for i,f in enumerate(files[:4]):
        buf=compress_to_80kb(f);fname=f"{int(dt_class.utcnow().timestamp())}_{i}_{phone[-4:]}.jpg"
        with open(os.path.join('static/uploads',fname),'wb') as out: out.write(buf.read() if hasattr(buf,'read') else buf.getvalue())
        compressed.append(fname)
    new_prod={'id':len(products_list)+100,'name':request.form.get('name'),'price':int(request.form.get('price') or 0),'desc':request.form.get('desc',''),'seller_phone':phone,'photos':compressed,'cover':compressed[0],'status':'pending','views':0,'leads':0,'leads_list':[],'location':{'lat':request.form.get('lat',''),'lng':request.form.get('lng','')},'created_at':dt_class.utcnow()}
    products_list.append(new_prod)
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();c.execute('INSERT INTO products (name,price,photo,details,category,seller_phone,status) VALUES (?,?,?,?,?,?,?)',(new_prod['name'],new_prod['price'],'static/uploads/'+compressed[0],new_prod['desc'],'fashion',phone,'approved'));conn.commit();conn.close()
    return redirect(f'/seller/dashboard?phone={phone}&msg=uploaded')

@app.route('/boost/cancel', methods=['POST'])
def boost_cancel_route():
    pid=int(request.form.get('product_id'));phone=request.form.get('phone');cancel_boost(pid);return redirect(f'/seller/dashboard?phone={phone}&msg=cancelled')
@app.route('/boost/buy', methods=['POST'])
def boost_buy_route():
    pid=int(request.form.get('product_id'));phone=request.form.get('phone');btype=request.form.get('boost_type');settings=get_admin_settings();add_boost(pid,btype,settings[f'{btype}_boost']);return redirect(f'/seller/dashboard?phone={phone}&msg=boosted')
@app.route('/seller/upgrade', methods=['POST'])
def seller_upgrade():
    phone=request.form.get('phone');seller=next((s for s in sellers_list if s.phone==phone),None)
    if seller: seller.plan=request.form.get('plan');seller.charge_payer=request.form.get('charge_payer');seller.yearly_expiry=dt_class.utcnow()+timedelta(days=365) if seller.plan=="yearly" else seller.yearly_expiry
    return redirect(f'/seller/dashboard?phone={phone}&msg=plan_updated')

@app.route('/leads')
def leads_page():
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();leads=c.execute('SELECT * FROM leads ORDER BY id DESC').fetchall();orders=c.execute('SELECT * FROM orders ORDER BY id DESC').fetchall();conn.close()
    html=BASE_CSS+'<div class="top"><b>Leads Dashboard</b></div><div style="padding:12px">'
    for o in orders: html+=f'<div class="lead-card"><b>Order #{o[0]}</b> - {o[2]} - {o[3]} UGX<br>Buyer: {o[4]} -> Seller: {o[5]} <a href="/track/{o[0]}">Track</a></div>'
    for l in leads: html+=f'<div class="lead-card">Phone {l[1]} viewed product {l[2]} at {l[4]}</div>'
    html+='</div>';return html
@app.route('/wallet')
def wallet_page():
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();wallets=c.execute('SELECT * FROM wallets').fetchall();total=c.execute("SELECT balance FROM wallets WHERE phone='TIBIPAY_EARNINGS'").fetchone();conn.close();total=total[0] if total else 0
    html=BASE_CSS+f'<div class="top"><b>TibiPay Earnings</b></div><div class="wallet"><h1>UGX {int(total)}</h1></div><div style="padding:12px">'
    for w in wallets: html+=f'<div class="lead-card">{w[0]} : {w[1]} UGX</div>'
    html+='</div>';return html
@app.route('/orders')
def orders_page():
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();orders=c.execute('SELECT * FROM orders ORDER BY id DESC').fetchall();conn.close()
    html=get_header()+BASE_CSS+'<div style="padding:12px"><h3>Orders Inbox</h3>'
    for o in orders: html+=f'<div class="lead-card">Order #{o[0]} - {o[2]} - {o[4]}->{o[5]} - {o[3]} UGX <a href="/track/{o[0]}" style="background:#ff8a00;color:#fff;padding:4px 8px;border-radius:10px;text-decoration:none">Track</a></div>'
    html+='</div>';return html
@app.route('/chat/<int:pid>')
def chat_page(pid):
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();prod=c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone();chats=c.execute('SELECT * FROM chats').fetchall() if prod else [];conn.close();pname=prod[1] if prod else ''
    html=BASE_CSS+f'<div class="top"><b>Chat - {pname}</b><a href="/shop" style="color:#fff">Back</a></div><div style="padding:12px;padding-bottom:120px">'
    for ch in chats: html+=f'<div style="background:#fff;padding:8px;border-radius:8px;margin:6px 0"><b>{ch[1]}</b>: {ch[3]} <small>{ch[4]}</small></div>'
    html+=f'</div><form method="post" action="/send_chat/{pid}" class="chat-bar"><input name="buyer_phone" placeholder="Your phone" required style="width:30%;padding:10px;border:1px solid #ddd;border-radius:12px"><input name="message" placeholder="Type..." required style="flex:1;padding:10px;border:1px solid #ddd;border-radius:12px"><button class="btn btn-black" style="width:auto">Send</button></form>';return html
@app.route('/send_chat/<int:pid>', methods=['POST'])
def send_chat(pid):
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();prod=c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone();seller=prod[6] if prod else 'unknown';c.execute('INSERT INTO chats (buyer_phone,seller_phone,message,time) VALUES (?,?,?,?)',(request.form['buyer_phone'],seller,request.form['message'],dt_class.now().isoformat()));conn.commit();conn.close();return redirect('/chat/'+str(pid))

# ===== DELIVERY TRACKING - FIXED =====
@app.route('/save_location', methods=['POST'])
def save_location():
    phone=request.form.get('phone','').strip();loc=request.form.get('location','').strip();order_id=request.form.get('order_id','').strip()
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();c.execute('UPDATE orders SET seller_location=? WHERE id=?',(loc,order_id));conn.commit();conn.close()
    try:
        with open(ORDERS_FILE,'r') as f: orders=json.load(f)
        for o in orders:
            if str(o.get('id'))==str(order_id): o['seller_location']=loc;o['seller_phone']=phone
        with open(ORDERS_FILE,'w') as f: json.dump(orders,f,indent=2)
    except: pass
    return {"status":"ok","location":loc}

@app.route('/update_delivery', methods=['POST'])
def update_delivery():
    order_id=request.form.get('order_id','').strip();status=request.form.get('status','').strip()
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();c.execute('UPDATE orders SET delivery_status=? WHERE id=?',(status,order_id))
    if status=='Delivered': c.execute('UPDATE orders SET paid_out=1 WHERE id=?',(order_id,))
    conn.commit();conn.close()
    try:
        with open(ORDERS_FILE,'r') as f: orders=json.load(f)
        for o in orders:
            if str(o.get('id'))==str(order_id): o['delivery_status']=status
        with open(ORDERS_FILE,'w') as f: json.dump(orders,f,indent=2)
    except: pass
    return redirect(f"/track/{order_id}")

@app.route('/track/<order_id>')
def track_page(order_id):
    conn=sqlite3.connect('tibishop.db');c=conn.cursor();row=c.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone();conn.close()
    if not row:
        try:
            with open(ORDERS_FILE,'r') as f: orders=json.load(f)
            order=next((o for o in orders if str(o.get('id'))==str(order_id)),None)
        except: order=None
        if not order: return get_header()+f"<div style='padding:20px'>❌ Order {order_id} not found <a href='/orders'>Orders</a></div>"
        status=order.get('delivery_status','Packed');loc=order.get('seller_location','Kampala');phone=order.get('seller_phone','')
    else:
        status=row[9] or 'Packed';loc=row[10] or row[11] or 'Kampala';phone=row[5]
    width='33%' if status=='Packed' else '66%' if status=='On Boda' else '100%'
    map_link=f"https://www.google.com/maps?q={loc}" if ',' in str(loc) else f"https://www.google.com/maps/search/{loc}"
    return get_header()+f"""
    <div style="font-family:sans-serif;padding:20px;max-width:500px;margin:auto;background:#fff;border-radius:16px;margin-top:12px">
      <h2>🚚 Track Order {order_id}</h2><p>📍 {loc} <a href="{map_link}" target="_blank" style="color:#ff8a00">🗺️ View Map</a></p>
      <p>Packed → On Boda → Delivered</p>
      <div style="height:10px;background:#eee;border-radius:10px;overflow:hidden;margin:12px 0"><div style="height:100%;background:#ff8a00;width:{width};"></div></div>
      <p><b>Status: {status}</b></p><p>Rider: {phone} <a href="tel:{phone}">📞 Call</a></p>
      <div style="margin-top:20px;display:flex;gap:8px;flex-wrap:wrap">
        <form method="POST" action="/update_delivery"><input type="hidden" name="order_id" value="{order_id}"><input type="hidden" name="status" value="Packed"><button style="padding:8px 12px;border-radius:8px;border:1px solid #ddd">📦 Packed</button></form>
        <form method="POST" action="/update_delivery"><input type="hidden" name="order_id" value="{order_id}"><input type="hidden" name="status" value="On Boda"><button style="padding:8px 12px;border-radius:8px;background:#ff8a00;color:#fff;border:none">🛵 On Boda</button></form>
        <form method="POST" action="/update_delivery"><input type="hidden" name="order_id" value="{order_id}"><input type="hidden" name="status" value="Delivered"><button style="padding:8px 12px;border-radius:8px;background:#111;color:#fff;border:none">✅ Delivered</button></form>
      </div><br><a href="/seller/location/{order_id}" style="display:block;text-align:center;padding:12px;background:#eee;border-radius:10px;text-decoration:none">📡 Share My Real GPS</a><br><a href="/shop">Back to Shop</a></div>"""

@app.route('/seller/location/<order_id>')
def seller_location_page(order_id):
    return get_header()+f"""
    <div style='padding:20px;text-align:center;background:#fff;margin:12px;border-radius:16px'><h2>📍 Sharing location for {order_id}</h2><p id='i'>Getting GPS...</p><p id='s'></p></div>
    <script>
    navigator.geolocation.getCurrentPosition(function(p){{
      var s=p.coords.latitude.toFixed(6)+', '+p.coords.longitude.toFixed(6);
      document.getElementById('s').innerHTML='<a href=https://www.google.com/maps?q='+p.coords.latitude+','+p.coords.longitude+' target=_blank>View Map</a>';
      var f=new FormData();f.append('location',s);f.append('order_id','{order_id}');f.append('phone',localStorage.getItem('tibi_phone')||'unknown');
      fetch('/save_location',{{method:'POST',body:f}}).then(r=>r.json()).then(d=>{{document.getElementById('i').innerText='✅ Saved: '+s;setTimeout(()=>location.href='/track/{order_id}',1000)}})
    }},function(e){{document.getElementById('i').innerText='❌ Failed: '+e.message}},{{enableHighAccuracy:true,timeout:15000}});
    </script></body></html>"""

@app.route('/welcome')
def welcome():
    return get_header()+"""
    <style>.card{width:100%;max-width:380px;background:#f7f7f8;border-radius:24px;padding:20px;text-align:center;margin:20px auto}.btn{width:100%;padding:16px;border-radius:16px;border:none;font-weight:700;font-size:16px;cursor:pointer;margin:8px 0}.btn-buy{background:#111;color:#fff}.btn-sell{background:#ff8a00;color:#fff}.input{width:100%;padding:14px;border-radius:12px;border:1px solid #ddd;margin:8px 0}.small{font-size:12px;color:#666}.logo{width:80px;height:80px;background:#111;border-radius:20px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:32px;margin:0 auto 16px}</style>
    <div style="display:flex;flex-direction:column;align-items:center;padding:20px"><div class="logo">T</div><h2>Welcome to TibiShop 🇺🇬</h2><p class="small">Buy & Sell • Any SIM • Buyer 0% fee</p>
    <div class="card" id="step1"><h3>What do you want to do?</h3><button class="btn btn-buy" onclick="choose('buyer')">🛒 I want to Buy</button><button class="btn btn-sell" onclick="choose('seller')">💼 I want to Sell</button></div>
    <div class="card" id="step2" style="display:none"><h3 id="title">Enter phone</h3><input id="phone" class="input" placeholder="07XXXXXXXX"><input id="shopname" class="input" placeholder="Shop name (sellers)" style="display:none"><button class="btn btn-buy" onclick="save()">Continue →</button><button class="btn" style="background:#eee" onclick="back()">Back</button></div></div>
    <script>let role='';function choose(r){role=r;document.getElementById('step1').style.display='none';document.getElementById('step2').style.display='block';if(r=='seller')document.getElementById('shopname').style.display='block';}function back(){document.getElementById('step2').style.display='none';document.getElementById('step1').style.display='block';}function save(){let phone=document.getElementById('phone').value;if(phone.length<10){alert('Enter phone');return;}localStorage.setItem('tibi_phone',phone);localStorage.setItem('tibi_role',role);location.href=role=='buyer'?'/shop?phone='+phone:'/seller/dashboard?phone='+phone;}</script>"""

if __name__=='__main__':
    print('TibiShop v4 FIXED - profile, login, terms agree/disagree, orange nav, location buyer+seller, tracking')
    app.run()