
import os
import re
from datetime import datetime
from pathlib import Path

from flask import Flask, request, redirect, url_for, render_template_string, flash, Response
from werkzeug.utils import secure_filename
import psycopg
from psycopg.rows import dict_row
from psycopg.errors import UniqueViolation

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = BASE_DIR / "wedding.db"

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
AUDIO_EXTENSIONS = {"mp3", "wav", "ogg", "m4a"}


# -----------------------------
# DATABASE — PostgreSQL
# -----------------------------
def get_db():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured in Render.")
    return psycopg.connect(url, row_factory=dict_row)

def init_db():
    con=get_db()
    with con:
        with con.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS invitations (
              id BIGSERIAL PRIMARY KEY, slug TEXT UNIQUE NOT NULL,
              bride TEXT NOT NULL, groom TEXT NOT NULL, wedding_date TEXT NOT NULL,
              wedding_time TEXT, venue TEXT, address TEXT, map_url TEXT, message TEXT,
              photo TEXT, event1_name TEXT, event1_date TEXT, event1_time TEXT,
              event2_name TEXT, event2_date TEXT, event2_time TEXT, created_at TEXT NOT NULL,
              music TEXT, gallery TEXT, theme TEXT DEFAULT 'rose', story TEXT,
              event3_name TEXT, event3_date TEXT, event3_time TEXT)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS rsvps (
              id BIGSERIAL PRIMARY KEY,
              invitation_id BIGINT NOT NULL REFERENCES invitations(id) ON DELETE CASCADE,
              guest_name TEXT NOT NULL, attendance TEXT NOT NULL, guest_count INTEGER DEFAULT 1,
              message TEXT, created_at TEXT NOT NULL)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS wishes (
              id BIGSERIAL PRIMARY KEY,
              invitation_id BIGINT NOT NULL REFERENCES invitations(id) ON DELETE CASCADE,
              guest_name TEXT NOT NULL, wish TEXT NOT NULL, created_at TEXT NOT NULL)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS media (
              filename TEXT PRIMARY KEY, content_type TEXT NOT NULL,
              data BYTEA NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
    con.close()

# -----------------------------
# HELPERS
# -----------------------------
def slugify(value):
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "wedding"


def allowed_file(filename, allowed):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed


def save_uploaded_file(file_obj, slug, prefix, allowed):
    if not file_obj or not file_obj.filename or not allowed_file(file_obj.filename, allowed):
        return None
    ext=secure_filename(file_obj.filename).rsplit(".",1)[1].lower()
    filename=f"{slug}-{prefix}-{int(datetime.now().timestamp()*1000)}.{ext}"
    data=file_obj.read()
    con=get_db()
    with con:
        con.execute("""INSERT INTO media(filename,content_type,data)
                       VALUES (%s,%s,%s)
                       ON CONFLICT(filename) DO UPDATE
                       SET content_type=EXCLUDED.content_type,data=EXCLUDED.data""",
                    (filename,file_obj.mimetype or "application/octet-stream",data))
    con.close()
    return filename


def pretty_date(value):
    if not value:
        return ""
    try:
        d = datetime.strptime(value, "%Y-%m-%d")
        return d.strftime("%A, %d %B %Y")
    except Exception:
        return value


def pretty_time(value):
    if not value:
        return ""
    try:
        t = datetime.strptime(value, "%H:%M")
        return t.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return value


app.jinja_env.filters["pretty_date"] = pretty_date
app.jinja_env.filters["pretty_time"] = pretty_time


# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def home():
    return render_template_string(HOME_HTML)


@app.route("/create", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        bride = request.form.get("bride", "").strip()
        groom = request.form.get("groom", "").strip()
        wedding_date = request.form.get("wedding_date", "").strip()

        if not bride or not groom or not wedding_date:
            flash("Bride, groom and wedding date are required.")
            return redirect(url_for("create"))

        slug = slugify(request.form.get("slug", "") or f"{groom}-{bride}")

        photo = save_uploaded_file(
            request.files.get("photo"), slug, "cover", IMAGE_EXTENSIONS
        )

        music = save_uploaded_file(
            request.files.get("music"), slug, "music", AUDIO_EXTENSIONS
        )

        gallery_files = []
        for i, f in enumerate(request.files.getlist("gallery")):
            saved = save_uploaded_file(f, slug, f"gallery-{i}", IMAGE_EXTENSIONS)
            if saved:
                gallery_files.append(saved)

        con = get_db()

        try:
            con.execute("""
                INSERT INTO invitations (
                    slug, bride, groom, wedding_date, wedding_time,
                    venue, address, map_url, message, photo,
                    music, gallery, theme, story,
                    event1_name, event1_date, event1_time,
                    event2_name, event2_date, event2_time,
                    event3_name, event3_date, event3_time,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                slug,
                bride,
                groom,
                wedding_date,
                request.form.get("wedding_time", ""),
                request.form.get("venue", ""),
                request.form.get("address", ""),
                request.form.get("map_url", ""),
                request.form.get("message", ""),
                photo,
                music,
                ",".join(gallery_files),
                request.form.get("theme", "rose"),
                request.form.get("story", ""),
                request.form.get("event1_name", ""),
                request.form.get("event1_date", ""),
                request.form.get("event1_time", ""),
                request.form.get("event2_name", ""),
                request.form.get("event2_date", ""),
                request.form.get("event2_time", ""),
                request.form.get("event3_name", ""),
                request.form.get("event3_date", ""),
                request.form.get("event3_time", ""),
                datetime.now().isoformat(timespec="seconds")
            ))

            con.commit()

        except UniqueViolation:
            con.close()
            flash("That custom invitation link already exists. Choose another.")
            return redirect(url_for("create"))

        con.close()

        return redirect(url_for("invite", slug=slug))

    return render_template_string(CREATE_HTML)


@app.route("/media/<path:filename>")
def media(filename):
    con=get_db()
    row=con.execute("SELECT content_type,data FROM media WHERE filename = %s",(filename,)).fetchone()
    con.close()
    if not row:
        return "Media not found",404
    return Response(bytes(row["data"]),mimetype=row["content_type"])

@app.route("/invite/<slug>")
def invite(slug):
    con = get_db()

    invitation = con.execute(
        "SELECT * FROM invitations WHERE slug = %s",
        (slug,)
    ).fetchone()

    if not invitation and slug == "imam-muskan":
        # Permanent invitation fallback. This survives Render restarts because
        # the event information is stored in source code, not only in SQLite.
        con.execute("""
            INSERT INTO invitations (
                slug, bride, groom, wedding_date, wedding_time,
                venue, address, message, theme, story,
                event1_name, event1_date, event1_time,
                created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO NOTHING
        """, (
            "imam-muskan",
            "A. Muskan",
            "M. Imam Hussain",
            "2026-10-02",
            "11:00",
            "GSS Function Hall",
            "Banaganapalli",
            "Bismillahir Rahmanir Raheem. With the grace and blessings of Allah (SWT), together with our families, we joyfully invite you to celebrate our Nikah and share in the happiness of this blessed occasion.",
            "islamicgreen",
            "Alhamdulillah, by the beautiful decree of Allah, two hearts begin a blessed journey together.",
            "Reception",
            "2026-10-03",
            "13:00",
            datetime.now().isoformat(timespec="seconds")
        ))
        con.commit()
        invitation = con.execute(
            "SELECT * FROM invitations WHERE slug = %s",
            (slug,)
        ).fetchone()

    if not invitation:
        con.close()
        return "Invitation not found", 404

    wishes = con.execute("""
        SELECT * FROM wishes
        WHERE invitation_id = %s
        ORDER BY id DESC
        LIMIT 12
    """, (invitation["id"],)).fetchall()

    con.close()

    gallery = [
        x for x in (invitation["gallery"] or "").split(",")
        if x
    ]

    return render_template_string(
        INVITE_HTML,
        invitation=invitation,
        wishes=wishes,
        gallery=gallery
    )


@app.route("/invite/<slug>/rsvp", methods=["POST"])
def rsvp(slug):
    con = get_db()

    invitation = con.execute(
        "SELECT * FROM invitations WHERE slug = %s",
        (slug,)
    ).fetchone()

    if not invitation:
        con.close()
        return "Invitation not found", 404

    guest_name = request.form.get("guest_name", "").strip()
    attendance = request.form.get("attendance", "Yes")
    message = request.form.get("message", "").strip()

    try:
        guest_count = max(
            1,
            min(20, int(request.form.get("guest_count", 1)))
        )
    except Exception:
        guest_count = 1

    if guest_name:
        con.execute("""
            INSERT INTO rsvps (
                invitation_id,
                guest_name,
                attendance,
                guest_count,
                message,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            invitation["id"],
            guest_name,
            attendance,
            guest_count,
            message,
            datetime.now().isoformat(timespec="seconds")
        ))

        con.commit()

    con.close()

    return redirect(url_for("thank_you", slug=slug))


@app.route("/invite/<slug>/wish", methods=["POST"])
def wish(slug):
    con = get_db()

    invitation = con.execute(
        "SELECT * FROM invitations WHERE slug = %s",
        (slug,)
    ).fetchone()

    if not invitation:
        con.close()
        return "Invitation not found", 404

    guest_name = request.form.get("guest_name", "").strip()
    wish_text = request.form.get("wish", "").strip()

    if guest_name and wish_text:
        con.execute("""
            INSERT INTO wishes (
                invitation_id,
                guest_name,
                wish,
                created_at
            )
            VALUES (%s, %s, %s, %s)
        """, (
            invitation["id"],
            guest_name,
            wish_text,
            datetime.now().isoformat(timespec="seconds")
        ))

        con.commit()

    con.close()

    return redirect(url_for("invite", slug=slug) + "#wishes")


@app.route("/invite/<slug>/thank-you")
def thank_you(slug):
    return render_template_string(
        THANK_YOU_HTML,
        slug=slug
    )


@app.route("/admin/<slug>")
def admin(slug):
    key = request.args.get("key", "")
    admin_key = os.getenv("ADMIN_KEY", "1234")

    if key != admin_key:
        return "Unauthorized. Use ?key=YOUR_ADMIN_KEY", 401

    con = get_db()

    invitation = con.execute(
        "SELECT * FROM invitations WHERE slug = %s",
        (slug,)
    ).fetchone()

    if not invitation:
        con.close()
        return "Invitation not found", 404

    responses = con.execute("""
        SELECT * FROM rsvps
        WHERE invitation_id = %s
        ORDER BY id DESC
    """, (invitation["id"],)).fetchall()

    wishes = con.execute("""
        SELECT * FROM wishes
        WHERE invitation_id = %s
        ORDER BY id DESC
    """, (invitation["id"],)).fetchall()

    con.close()

    total_yes = sum(
        1 for r in responses
        if r["attendance"] == "Yes"
    )

    total_guests = sum(
        r["guest_count"]
        for r in responses
        if r["attendance"] == "Yes"
    )

    return render_template_string(
        ADMIN_HTML,
        invitation=invitation,
        responses=responses,
        wishes=wishes,
        total_yes=total_yes,
        total_guests=total_guests
    )


# -----------------------------
# HOME PAGE
# -----------------------------
HOME_HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Wedding Invitation Maker</title>

<style>
*{box-sizing:border-box}

body{
margin:0;
font-family:Arial,sans-serif;
background:#fff8f4;
color:#402c2d;
}

.hero{
min-height:100vh;
display:grid;
place-items:center;
padding:30px;
background:
radial-gradient(circle at top,#ffe9e6,#fffaf7 55%,#f7ded8);
}

.card{
max-width:820px;
text-align:center;
background:#ffffffdd;
padding:60px 35px;
border-radius:32px;
box-shadow:0 20px 70px #6f3e4730;
}

h1{
font-family:Georgia,serif;
font-size:52px;
color:#8f4b5b;
margin:10px 0;
}

p{
font-size:18px;
line-height:1.7;
}

.btn{
display:inline-block;
margin-top:24px;
padding:15px 28px;
border-radius:30px;
background:#8f4b5b;
color:#fff;
text-decoration:none;
font-weight:bold;
}
</style>
</head>

<body>
<section class="hero">
<div class="card">
<div style="font-size:60px">💍</div>
<h1>Wedding Invitation Maker</h1>
<p>
Create an elegant Islamic wedding invitation with curtain opening,
music, event details, gallery, RSVP and sharing.
</p>
<a class="btn" href="/create">Create Invitation</a>
</div>
</section>
</body>
</html>
"""


# -----------------------------
# CREATE PAGE
# -----------------------------
CREATE_HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Create Wedding Invitation</title>

<style>
*{box-sizing:border-box}

body{
margin:0;
background:#f8efeb;
font-family:Arial,sans-serif;
color:#3e3130;
}

.wrap{
max-width:1000px;
margin:30px auto;
background:white;
border-radius:28px;
padding:38px;
box-shadow:0 18px 55px #0001;
}

h1{
font-family:Georgia,serif;
color:#8f4b5b;
text-align:center;
font-size:40px;
}

.grid{
display:grid;
grid-template-columns:1fr 1fr;
gap:18px;
}

.full{grid-column:1/-1}

.sectiontitle{
grid-column:1/-1;
margin-top:15px;
color:#8f4b5b;
font-family:Georgia,serif;
font-size:24px;
border-bottom:1px solid #ead9d4;
padding-bottom:8px;
}

label{
display:block;
font-weight:700;
margin-bottom:7px;
}

input,
textarea,
select{
width:100%;
padding:13px;
border:1px solid #dfd0ca;
border-radius:12px;
font-size:15px;
background:white;
}

textarea{min-height:105px}

.btn{
border:0;
background:#8f4b5b;
color:#fff;
padding:15px 28px;
border-radius:30px;
font-size:17px;
cursor:pointer;
}

.note{
background:#fff3df;
padding:13px;
border-radius:12px;
margin-bottom:20px;
}

.flash{
background:#ffe3e3;
padding:11px;
border-radius:10px;
margin:10px 0;
}

@media(max-width:680px){
.grid{grid-template-columns:1fr}
.full,.sectiontitle{grid-column:1}
.wrap{
margin:0;
border-radius:0;
padding:22px;
}
}
</style>
</head>

<body>
<div class="wrap">

<h1>Create Your Wedding Invitation</h1>

<p class="note">
Use a short custom link such as <b>imam-muskan</b>.
</p>

{% with messages = get_flashed_messages() %}
{% for m in messages %}
<div class="flash">{{m}}</div>
{% endfor %}
{% endwith %}

<form method="post" enctype="multipart/form-data">

<div class="grid">

<div class="sectiontitle">Couple</div>

<div>
<label>Groom name *</label>
<input name="groom" required>
</div>

<div>
<label>Bride name *</label>
<input name="bride" required>
</div>

<div>
<label>Custom link</label>
<input name="slug" placeholder="imam-muskan">
</div>

<div>
<label>Theme</label>
<select name="theme">
<option value="rose">🌹 Rose Blush</option>
<option value="gold">✨ Royal Gold</option>
<option value="emerald">💚 Emerald</option>
<option value="royalblue">💙 Royal Blue</option>
<option value="lavender">💜 Lavender</option>
<option value="peach">🌸 Peach</option>
<option value="maroon">❤️ Maroon & Gold</option>
<option value="ivory">🤍 Ivory & Gold</option>
<option value="islamicgreen">🌙 Islamic Green & Gold</option>
<option value="navygold">🌙 Navy Blue & Gold</option>
</select>
</div>

<div class="full">
<label>Couple photo</label>
<input
type="file"
name="photo"
accept=".jpg,.jpeg,.png,.webp">
</div>


<div class="sectiontitle">Main Wedding</div>

<div>
<label>Wedding date *</label>
<input type="date" name="wedding_date" required>
</div>

<div>
<label>Wedding time</label>
<input type="time" name="wedding_time">
</div>

<div>
<label>Venue</label>
<input name="venue">
</div>

<div>
<label>Address</label>
<input name="address">
</div>

<div class="full">
<label>Google Maps link</label>
<input
name="map_url"
placeholder="https://maps.google.com/...">
</div>


<div class="sectiontitle">Invitation Text</div>

<div class="full">
<label>Invitation message</label>
<textarea
name="message"
placeholder="Bismillahir Rahmanir Raheem..."></textarea>
</div>

<div class="full">
<label>Our Story</label>
<textarea
name="story"
placeholder="Alhamdulillah, by the beautiful decree of Allah..."></textarea>
</div>


<div class="sectiontitle">Additional Events</div>

<div>
<label>Event 1</label>
<input name="event1_name" placeholder="Nikah / Mehendi">
</div>

<div>
<label>Event 1 Date</label>
<input type="date" name="event1_date">
</div>

<div>
<label>Event 1 Time</label>
<input type="time" name="event1_time">
</div>

<div></div>


<div>
<label>Event 2</label>
<input name="event2_name" placeholder="Reception / Walima">
</div>

<div>
<label>Event 2 Date</label>
<input type="date" name="event2_date">
</div>

<div>
<label>Event 2 Time</label>
<input type="time" name="event2_time">
</div>

<div></div>


<div>
<label>Event 3</label>
<input name="event3_name" placeholder="Family dinner">
</div>

<div>
<label>Event 3 Date</label>
<input type="date" name="event3_date">
</div>

<div>
<label>Event 3 Time</label>
<input type="time" name="event3_time">
</div>

<div></div>


<div class="sectiontitle">Media</div>

<div class="full">
<label>Background music</label>
<input
type="file"
name="music"
accept=".mp3,.wav,.ogg,.m4a">
</div>

<div class="full">
<label>Gallery photos</label>
<input
type="file"
name="gallery"
multiple
accept=".jpg,.jpeg,.png,.webp">
</div>


<div class="full" style="text-align:center;margin-top:20px">
<button class="btn" type="submit">
Create Wedding Invitation
</button>
</div>

</div>
</form>

</div>
</body>
</html>
"""


# -----------------------------
# INVITATION PAGE
# -----------------------------
INVITE_HTML = r"""
<!DOCTYPE html>
<html>
<head>

<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">

<title>
{{ invitation['groom'] }} & {{ invitation['bride'] }}
</title>

<style>

*{
box-sizing:border-box;
}

html{
scroll-behavior:smooth;
}

body{
margin:0;
font-family:Georgia,serif;
overflow-x:hidden;
color:#4d3434;
}


/* ---------------- THEMES ---------------- */

body.rose{
--accent:#914c5d;
--soft:#f8e8e3;
--deep:#693740;
--bg:#fffaf7;
}

body.gold{
--accent:#9b752d;
--soft:#f5ecd6;
--deep:#624817;
--bg:#fffdf7;
}

body.emerald{
--accent:#35695d;
--soft:#e4f1ed;
--deep:#214a41;
--bg:#f8fdfb;
}

body.royalblue{
--accent:#315b8a;
--soft:#e7eff8;
--deep:#183858;
--bg:#f8fbff;
}

body.lavender{
--accent:#80649b;
--soft:#eee6f5;
--deep:#513b68;
--bg:#fcf9ff;
}

body.peach{
--accent:#b96e5b;
--soft:#fae5dc;
--deep:#794337;
--bg:#fff9f5;
}

body.maroon{
--accent:#8b2635;
--soft:#f6e6df;
--deep:#56131f;
--bg:#fffaf5;
}

body.ivory{
--accent:#a27c38;
--soft:#f4eedf;
--deep:#675022;
--bg:#fffdf7;
}

body.islamicgreen{
--accent:#b28a3e;
--soft:#e8f1e8;
--deep:#164b37;
--bg:#f8fcf8;
}

body.navygold{
--accent:#c19a4b;
--soft:#e8ebf1;
--deep:#172642;
--bg:#f8f9fc;
}

body{
background:var(--bg);
}


/* =========================================================
   CURTAIN / PARDA OPENING SCREEN
   ========================================================= */

.curtain-screen{
position:fixed;
inset:0;
z-index:9999;
overflow:hidden;
background:#f8eadc;
transition:
opacity .8s ease,
visibility .8s ease;
}

.curtain-screen.hide{
opacity:0;
visibility:hidden;
pointer-events:none;
}


/* glowing stage behind curtain */

.curtain-stage{
position:absolute;
inset:0;
background:
radial-gradient(
circle at center,
#fffaf2 0%,
#f4dcc6 48%,
#c6937b 100%
);
}


/* top floral strip */

.curtain-floral-top{
position:absolute;
top:0;
left:0;
right:0;
height:110px;
z-index:7;
display:flex;
justify-content:space-around;
align-items:flex-start;
font-size:70px;
padding-top:8px;
filter:
drop-shadow(0 5px 10px rgba(0,0,0,.15));
pointer-events:none;
}


/* hanging lights */

.bulb{
position:absolute;
z-index:6;
font-size:42px;
filter:
drop-shadow(0 0 18px #f5bf64);
animation:
lightGlow 1.6s ease-in-out infinite alternate;
}

.bulb.b1{
left:12%;
top:12%;
}

.bulb.b2{
right:12%;
top:12%;
}

.bulb.b3{
left:25%;
top:20%;
font-size:30px;
}

.bulb.b4{
right:25%;
top:20%;
font-size:30px;
}

@keyframes lightGlow{
from{
opacity:.72;
transform:scale(.96);
}
to{
opacity:1;
transform:scale(1.05);
}
}


/* Curtain panels */

.curtain{
position:absolute;
top:0;
bottom:0;
width:51%;
z-index:5;

background:
linear-gradient(
90deg,
#e6cbb5 0%,
#fff6e9 13%,
#d7b59c 27%,
#fff8ee 43%,
#d6b39b 60%,
#fff5e9 77%,
#cfaa92 100%
);

box-shadow:
inset 0 0 40px rgba(95,49,32,.25),
0 0 40px rgba(0,0,0,.18);

transition:
transform 1.8s cubic-bezier(.67,.02,.22,1);
will-change:transform;
}

.curtain-left{
left:0;
transform-origin:left center;
border-right:
1px solid rgba(135,88,61,.3);
}

.curtain-right{
right:0;
transform-origin:right center;
border-left:
1px solid rgba(135,88,61,.3);
}


/* fabric folds */

.curtain::after{
content:"";
position:absolute;
inset:0;

background:
repeating-linear-gradient(
90deg,
rgba(255,255,255,.22) 0 30px,
rgba(90,48,30,.10) 30px 65px
);

mix-blend-mode:soft-light;
}


/* tie backs */

.tie{
position:absolute;
top:66%;
height:35px;
width:95px;
z-index:7;

background:
linear-gradient(
90deg,
#7c2538,
#b06370,
#7c2538
);

box-shadow:
0 4px 10px rgba(0,0,0,.25);
}

.tie-left{
left:0;
border-radius:0 20px 20px 0;
}

.tie-right{
right:0;
border-radius:20px 0 0 20px;
}


/* opening text */

.curtain-center{
position:absolute;
inset:0;
z-index:10;
display:flex;
align-items:center;
justify-content:center;
text-align:center;
padding:20px;

transition:
opacity .45s ease,
transform .45s ease;
}

.curtain-content{
max-width:650px;
padding:35px;
text-shadow:
0 2px 12px rgba(255,255,255,.85);
}

.curtain-bismillah{
font-size:52px;
color:#741b36;
margin-bottom:8px;
}

.curtain-small{
font:
12px Arial,sans-serif;
letter-spacing:5px;
text-transform:uppercase;
color:#7d5547;
}

.curtain-title{
font-size:44px;
font-weight:normal;
color:#741b36;
margin:16px 0 10px;
}

.curtain-names{
font-size:31px;
color:#7b3149;
margin:12px 0 8px;
}

.curtain-button{
margin-top:24px;

border:
1px solid #9d6a56;

background:
rgba(116,27,54,.94);

color:#fff;

padding:
14px 34px;

border-radius:
32px;

font-family:
Georgia,serif;

font-size:
18px;

cursor:pointer;

box-shadow:
0 10px 30px rgba(90,35,50,.28);

animation:
tapPulse 1.8s infinite;
}

.curtain-note{
font:
12px Arial,sans-serif;
margin-top:10px;
color:#7b5246;
}

@keyframes tapPulse{
0%,100%{
transform:scale(1);
}
50%{
transform:scale(1.05);
}
}


/* curtain open state */

.curtain-screen.opening .curtain-left{
transform:
translateX(-102%);
}

.curtain-screen.opening .curtain-right{
transform:
translateX(102%);
}

.curtain-screen.opening .curtain-center{
opacity:0;
transform:scale(1.04);
pointer-events:none;
}


/* petals while opening */

.curtain-petal{
position:absolute;
z-index:9;
top:-50px;
font-size:22px;
opacity:.7;
animation:
curtainFall linear infinite;
pointer-events:none;
}

@keyframes curtainFall{
to{
transform:
translateY(115vh)
rotate(360deg);
}
}


/* =========================================================
   MAIN HERO
   ========================================================= */

.hero{
min-height:100vh;
position:relative;

display:grid;
place-items:center;

text-align:center;

padding:
70px 20px;

overflow:hidden;

background:
radial-gradient(
circle at 50% 22%,
rgba(255,255,255,.99),
rgba(255,249,244,.94) 48%,
var(--soft) 100%
);
}


/* gold decorative frame */

.hero-frame{
position:absolute;
inset:18px;

border:
2px solid rgba(178,138,62,.40);

border-radius:
30px;

pointer-events:none;
}


/* floral decoration */

.hero-flower{
position:absolute;
font-size:100px;
opacity:.28;

filter:
drop-shadow(
0 4px 6px rgba(0,0,0,.08)
);
}

.hero-flower.tl{
top:-16px;
left:-10px;
}

.hero-flower.tr{
top:-16px;
right:-10px;
transform:scaleX(-1);
}

.hero-flower.bl{
bottom:-20px;
left:-10px;
}

.hero-flower.br{
bottom:-20px;
right:-10px;
transform:scaleX(-1);
}


/* decorative lanterns */

.hero-lantern{
position:absolute;
top:12%;

font-size:
56px;

opacity:.85;

filter:
drop-shadow(
0 0 14px #e6b96388
);
}

.hero-lantern.left{
left:6%;
}

.hero-lantern.right{
right:6%;
}


.hero-inner{
position:relative;
z-index:3;

width:100%;
max-width:900px;

padding:
28px 25px;
}


.bismillah-main{
font-size:42px;
color:var(--accent);
margin-bottom:8px;
}


.overline{
letter-spacing:6px;
text-transform:uppercase;
font:13px Arial,sans-serif;
margin-bottom:18px;
}


.cover{
width:220px;
height:220px;

object-fit:cover;

border-radius:50%;

border:
8px solid #fff;

box-shadow:
0 18px 45px rgba(0,0,0,.15);
}


.names{
font-size:64px;
font-weight:normal;

color:var(--accent);

margin:
25px 0 10px;
}


.amp{
font-size:32px;
}


.date{
font-size:22px;
line-height:1.8;
}


.btn{
display:inline-block;

border:0;

text-decoration:none;

background:
var(--accent);

color:#fff;

padding:
13px 22px;

border-radius:
28px;

font:
15px Arial,sans-serif;

margin:6px;

cursor:pointer;
}


.btn.secondary{
background:#fff;
color:var(--accent);

border:
1px solid var(--accent);
}


/* sections */

.section{
padding:
80px 20px;

text-align:center;
}

.section.soft{
background:
var(--soft);
}

.section h2{
font-size:
40px;

color:
var(--accent);

font-weight:
normal;

margin-top:0;
}

.lead{
max-width:
800px;

margin:auto;

font-size:
20px;

line-height:
1.8;
}


/* events */

.events{
display:flex;
flex-wrap:wrap;
justify-content:center;
gap:20px;

margin-top:
30px;
}

.event{
width:
290px;

background:
#fff;

border-radius:
22px;

padding:
28px;

box-shadow:
0 10px 35px rgba(0,0,0,.06);
}

.event h3{
font-size:
24px;

color:
var(--accent);
}


/* countdown */

.countdown{
display:flex;
justify-content:center;
gap:12px;
flex-wrap:wrap;
}

.count{
background:
#fff;

min-width:
100px;

padding:
20px;

border-radius:
18px;

box-shadow:
0 9px 30px rgba(0,0,0,.05);

font-family:
Arial,sans-serif;
}

.count b{
font-size:
30px;

color:
var(--accent);
}


/* gallery */

.gallery{
max-width:
1000px;

margin:auto;

display:grid;

grid-template-columns:
repeat(3,1fr);

gap:
12px;
}

.gallery img{
width:
100%;

height:
260px;

object-fit:
cover;

border-radius:
18px;

transition:
.25s;
}

.gallery img:hover{
transform:
scale(1.02);
}


/* forms */

.formbox{
max-width:
650px;

margin:auto;

background:
#fff;

padding:
30px;

border-radius:
24px;

box-shadow:
0 12px 38px rgba(0,0,0,.06);
}

input,
select,
textarea{
width:
100%;

padding:
13px;

margin:
7px 0;

border:
1px solid #dbcac4;

border-radius:
11px;

font-size:
15px;
}

textarea{
min-height:
90px;
}


/* wishes */

.wishes{
max-width:
900px;

margin:
25px auto 0;

display:grid;

grid-template-columns:
repeat(2,1fr);

gap:
15px;
}

.wish{
background:
#fff;

padding:
20px;

border-radius:
18px;

text-align:left;

box-shadow:
0 8px 25px rgba(0,0,0,.05);
}

.wish b{
color:
var(--accent);
}


/* floating buttons */

.floatbar{
position:fixed;
right:16px;
bottom:16px;
z-index:30;

display:flex;
flex-direction:column;
gap:10px;
}

.fab{
width:
52px;

height:
52px;

border:
0;

border-radius:
50%;

background:
var(--accent);

color:#fff;

font-size:
21px;

box-shadow:
0 10px 28px rgba(0,0,0,.2);

cursor:pointer;
}


/* footer */

.footer{
background:
var(--deep);

color:#fff;

text-align:center;

padding:
50px 20px;
}


/* mobile */

@media(max-width:700px){

.curtain-bismillah{
font-size:
38px;
}

.curtain-title{
font-size:
34px;
}

.curtain-names{
font-size:
25px;
}

.curtain-floral-top{
font-size:
46px;
height:
80px;
}

.names{
font-size:
43px;
}

.cover{
width:
180px;

height:
180px;
}

.gallery{
grid-template-columns:
1fr 1fr;
}

.gallery img{
height:
180px;
}

.wishes{
grid-template-columns:
1fr;
}

.section{
padding:
58px 16px;
}

.bismillah-main{
font-size:
32px;
}

.hero-lantern{
font-size:
38px;
}

.hero-flower{
font-size:
75px;
}

}

</style>
</head>


<body class="{{ invitation['theme'] or 'rose' }}">


<!-- ======================================================
     CURTAIN / PARDA OPENING
     ====================================================== -->

<div
id="curtainScreen"
class="curtain-screen"
onclick="openCurtain()"
>

<div class="curtain-stage"></div>


<div class="curtain-floral-top">
<span>🌹</span>
<span>🌸</span>
<span>🌹</span>
<span>🌸</span>
<span>🌹</span>
</div>


<div class="bulb b1">🏮</div>
<div class="bulb b2">🏮</div>
<div class="bulb b3">💡</div>
<div class="bulb b4">💡</div>


<div class="curtain curtain-left"></div>
<div class="curtain curtain-right"></div>


<div class="tie tie-left"></div>
<div class="tie tie-right"></div>


<!-- petals -->

<span
class="curtain-petal"
style="left:10%;animation-duration:8s">
🌹
</span>

<span
class="curtain-petal"
style="left:28%;animation-duration:11s;animation-delay:2s">
🌸
</span>

<span
class="curtain-petal"
style="left:48%;animation-duration:9s;animation-delay:1s">
🌹
</span>

<span
class="curtain-petal"
style="left:70%;animation-duration:12s;animation-delay:3s">
🌸
</span>

<span
class="curtain-petal"
style="left:88%;animation-duration:10s;animation-delay:4s">
🌹
</span>


<div class="curtain-center">

<div class="curtain-content">

<div class="curtain-bismillah">
﷽
</div>

<div class="curtain-small">
A Blessed Beginning
</div>

<h1 class="curtain-title">
You're Invited
</h1>

<p>
To celebrate the Nikah of
</p>

<div class="curtain-names">

{{ invitation['groom'] }}

&nbsp;&amp;&nbsp;

{{ invitation['bride'] }}

</div>


<button
type="button"
class="curtain-button"
>

Tap to Open

</button>


<div class="curtain-note">
Tap anywhere on the parda
</div>

</div>
</div>

</div>



<!-- ======================================================
     MUSIC
     ====================================================== -->

{% if invitation['music'] %}

<audio
id="bgmusic"
loop
>

<source
src="{{ url_for('media', filename=invitation['music']) }}">

</audio>

{% endif %}



<!-- ======================================================
     MAIN INVITATION
     ====================================================== -->

<section class="hero">

<div class="hero-frame"></div>


<div class="hero-flower tl">
🌹
</div>

<div class="hero-flower tr">
🌹
</div>

<div class="hero-flower bl">
🌸
</div>

<div class="hero-flower br">
🌸
</div>


<div class="hero-lantern left">
🏮
</div>

<div class="hero-lantern right">
🏮
</div>


<div class="hero-inner">


<div class="bismillah-main">
﷽
</div>


<div class="overline">

Together with our families

</div>


{% if invitation['photo'] %}

<img
class="cover"
src="{{ url_for('media', filename=invitation['photo']) }}"
alt="Wedding photo"
>

{% endif %}


<h1 class="names">

{{ invitation['groom'] }}

<span class="amp">
&amp;
</span>

{{ invitation['bride'] }}

</h1>


<p>

joyfully invite you to celebrate their wedding

</p>


<div class="date">

<strong>

{{ invitation['wedding_date'] | pretty_date }}

</strong>

<br>

{% if invitation['wedding_time'] %}

{{ invitation['wedding_time'] | pretty_time }}

{% endif %}

</div>


<a
class="btn"
href="#details"
>

View Invitation

</a>


<button
class="btn secondary"
onclick="shareInvitation()"
>

Share Invitation

</button>


</div>
</section>



<!-- ======================================================
     INVITATION MESSAGE
     ====================================================== -->

<section
class="section"
id="details"
>

<h2>

You're Invited

</h2>


<p class="lead">

{{ invitation['message']
or
"Bismillahir Rahmanir Raheem. With the grace and blessings of Allah (SWT), together with our families, we joyfully invite you to celebrate our Nikah and share in the happiness of this blessed occasion. Your presence, duas and blessings will make our special day even more meaningful." }}

</p>

</section>



<!-- ======================================================
     STORY
     ====================================================== -->

{% if invitation['story'] %}

<section class="section soft">

<h2>

Our Story

</h2>


<p class="lead">

{{ invitation['story'] }}

</p>

</section>

{% endif %}



<!-- ======================================================
     EVENTS
     ====================================================== -->

<section class="section">

<h2>

Wedding Events

</h2>


<div class="events">


<div class="event">

<div style="font-size:42px">

💍

</div>

<h3>

Wedding

</h3>


<p>

<b>

{{ invitation['wedding_date'] | pretty_date }}

</b>

</p>


{% if invitation['wedding_time'] %}

<p>

{{ invitation['wedding_time'] | pretty_time }}

</p>

{% endif %}


{% if invitation['venue'] %}

<p>

{{ invitation['venue'] }}

</p>

{% endif %}


{% if invitation['address'] %}

<p>

{{ invitation['address'] }}

</p>

{% endif %}


{% if invitation['map_url'] %}

<a
class="btn"
href="{{ invitation['map_url'] }}"
target="_blank"
>

Get Directions

</a>

{% endif %}

</div>



{% for n in [1,2,3] %}

{% set name =
invitation['event' ~ n ~ '_name']
%}

{% set date =
invitation['event' ~ n ~ '_date']
%}

{% set time =
invitation['event' ~ n ~ '_time']
%}


{% if name %}

<div class="event">

<div style="font-size:42px">

✨

</div>


<h3>

{{ name }}

</h3>


{% if date %}

<p>

<b>

{{ date | pretty_date }}

</b>

</p>

{% endif %}


{% if time %}

<p>

{{ time | pretty_time }}

</p>

{% endif %}


</div>

{% endif %}

{% endfor %}


</div>

</section>



<!-- ======================================================
     COUNTDOWN
     ====================================================== -->

<section class="section soft">

<h2>

Counting Down

</h2>


<div class="countdown">


<div class="count">

<b id="days">

0

</b>

<br>

<small>

Days

</small>

</div>


<div class="count">

<b id="hours">

0

</b>

<br>

<small>

Hours

</small>

</div>


<div class="count">

<b id="minutes">

0

</b>

<br>

<small>

Minutes

</small>

</div>


<div class="count">

<b id="seconds">

0

</b>

<br>

<small>

Seconds

</small>

</div>


</div>

</section>



<!-- ======================================================
     GALLERY
     ====================================================== -->

{% if gallery %}

<section class="section">

<h2>

Our Gallery

</h2>


<div class="gallery">

{% for img in gallery %}

<img
src="{{ url_for('media', filename=img) }}"
loading="lazy"
alt="Wedding gallery"
>

{% endfor %}

</div>

</section>

{% endif %}



<!-- ======================================================
     RSVP
     ====================================================== -->

<section class="section soft">

<h2>

RSVP

</h2>


<div class="formbox">

<form
method="post"
action="{{ url_for('rsvp', slug=invitation['slug']) }}"
>


<input
name="guest_name"
placeholder="Your name"
required
>


<select name="attendance">

<option value="Yes">

Joyfully attending

</option>

<option value="No">

Unable to attend

</option>

</select>


<input
type="number"
name="guest_count"
min="1"
max="20"
value="1"
>


<textarea
name="message"
placeholder="Optional message"
></textarea>


<button
type="submit"
class="btn"
>

Send RSVP

</button>


</form>

</div>

</section>



<!-- ======================================================
     WISHES
     ====================================================== -->

<section
class="section"
id="wishes"
>

<h2>

Wedding Wishes

</h2>


<div class="formbox">

<form
method="post"
action="{{ url_for('wish', slug=invitation['slug']) }}"
>


<input
name="guest_name"
placeholder="Your name"
required
>


<textarea
name="wish"
placeholder="Write your blessings or wishes..."
required
></textarea>


<button
type="submit"
class="btn"
>

Send Wishes

</button>


</form>

</div>



{% if wishes %}

<div class="wishes">

{% for w in wishes %}

<div class="wish">

<b>

{{ w['guest_name'] }}

</b>

<p>

{{ w['wish'] }}

</p>

</div>

{% endfor %}

</div>

{% endif %}


</section>



<!-- ======================================================
     FOOTER
     ====================================================== -->

<footer class="footer">

<h2 style="font-size:34px">

{{ invitation['groom'] }}

&amp;

{{ invitation['bride'] }}

</h2>


<p>

May Allah bless this union with love, mercy,
happiness and Barakah. Ameen.

</p>


<button
class="btn"
onclick="shareInvitation()"
>

Share on WhatsApp

</button>

</footer>



<!-- ======================================================
     FLOAT BUTTONS
     ====================================================== -->

<div class="floatbar">

{% if invitation['music'] %}

<button
class="fab"
onclick="toggleMusic()"
title="Music"
>

♫

</button>

{% endif %}


<button
class="fab"
onclick="shareInvitation()"
title="Share"
>

↗

</button>

</div>



<!-- ======================================================
     JAVASCRIPT
     ====================================================== -->

<script>


let curtainOpened = false;

let musicPlaying = false;



function openCurtain(){

    if(curtainOpened){
        return;
    }

    curtainOpened = true;


    const screen =
    document.getElementById(
        "curtainScreen"
    );


    screen.classList.add(
        "opening"
    );


    const audio =
    document.getElementById(
        "bgmusic"
    );


    if(audio){

        audio.volume = 0.45;


        audio.play()

        .then(
            ()=>musicPlaying=true
        )

        .catch(
            ()=>{}
        );

    }


    setTimeout(
        ()=>{

            screen.classList.add(
                "hide"
            );

        },
        1800
    );

}



function toggleMusic(){

    const audio =
    document.getElementById(
        "bgmusic"
    );


    if(!audio){
        return;
    }


    if(audio.paused){

        audio.play();

        musicPlaying = true;

    }

    else{

        audio.pause();

        musicPlaying = false;

    }

}



function shareInvitation(){

    const message =

    "You're invited to the wedding of " +

    "{{ invitation['groom'] }}" +

    " & " +

    "{{ invitation['bride'] }}" +

    " 💍❤️\n" +

    "{{ invitation['wedding_date'] | pretty_date }}" +

    "\n";


    if(navigator.share){

        navigator.share({

            title:
            "Wedding Invitation",

            text:
            message,

            url:
            window.location.href

        })

        .catch(()=>{});

    }

    else{

        const whatsapp =

        "https://wa.me/?text=" +

        encodeURIComponent(
            message +
            window.location.href
        );


        window.open(
            whatsapp,
            "_blank"
        );

    }

}



const target =

new Date(

"{{ invitation['wedding_date'] }}T{{ invitation['wedding_time'] or '00:00' }}:00"

).getTime();



function updateCountdown(){

    let difference =

    target -
    Date.now();


    if(difference < 0){

        difference = 0;

    }


    document.getElementById(
        "days"
    ).textContent =

    Math.floor(
        difference /
        86400000
    );


    document.getElementById(
        "hours"
    ).textContent =

    Math.floor(
        (difference % 86400000) /
        3600000
    );


    document.getElementById(
        "minutes"
    ).textContent =

    Math.floor(
        (difference % 3600000) /
        60000
    );


    document.getElementById(
        "seconds"
    ).textContent =

    Math.floor(
        (difference % 60000) /
        1000
    );

}


updateCountdown();


setInterval(
    updateCountdown,
    1000
);


</script>


</body>
</html>
"""


# -----------------------------
# THANK YOU PAGE
# -----------------------------
THANK_YOU_HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">

<style>
body{
margin:0;
height:100vh;
display:grid;
place-items:center;
background:#fff4ef;
font-family:Georgia,serif;
color:#8f4b5b;
text-align:center;
}

.card{
background:white;
padding:50px;
border-radius:25px;
box-shadow:0 14px 45px #0001;
}

.btn{
display:inline-block;
background:#8f4b5b;
color:white;
padding:13px 22px;
border-radius:28px;
text-decoration:none;
}
</style>

</head>

<body>

<div class="card">

<div style="font-size:65px">

💐

</div>

<h1>

Thank You!

</h1>

<p>

Your RSVP has been received.

</p>

<a
class="btn"
href="/invite/{{slug}}"
>

Back to Invitation

</a>

</div>

</body>
</html>
"""


# -----------------------------
# ADMIN PAGE
# -----------------------------
ADMIN_HTML = r"""
<!DOCTYPE html>
<html>
<head>

<meta name="viewport" content="width=device-width,initial-scale=1">

<title>

Wedding Admin

</title>

<style>

body{
font-family:Arial,sans-serif;
background:#f5f1ef;
margin:0;
padding:25px;
color:#333;
}

.wrap{
max-width:1100px;
margin:auto;
}

.top{
display:grid;
grid-template-columns:
repeat(3,1fr);
gap:15px;
margin-bottom:20px;
}

.stat,
.card{
background:white;
border-radius:20px;
padding:24px;
box-shadow:0 8px 28px #0001;
}

.stat b{
font-size:34px;
color:#8f4b5b;
}

.card{
margin-bottom:20px;
}

table{
width:100%;
border-collapse:collapse;
}

th,
td{
padding:11px;
border-bottom:1px solid #eee;
text-align:left;
}

th{
background:#8f4b5b;
color:#fff;
}

@media(max-width:700px){

.top{
grid-template-columns:1fr;
}

table{
font-size:12px;
}

}

</style>
</head>

<body>

<div class="wrap">


<h1>

{{ invitation['groom'] }}

&amp;

{{ invitation['bride'] }}

— Admin

</h1>


<div class="top">


<div class="stat">

<small>

RSVP responses

</small>

<br>

<b>

{{ responses|length }}

</b>

</div>


<div class="stat">

<small>

Attending responses

</small>

<br>

<b>

{{ total_yes }}

</b>

</div>


<div class="stat">

<small>

Total attending guests

</small>

<br>

<b>

{{ total_guests }}

</b>

</div>


</div>



<div class="card">

<h2>

RSVP Responses

</h2>


<table>

<tr>

<th>Name</th>

<th>Status</th>

<th>Guests</th>

<th>Message</th>

</tr>


{% for r in responses %}

<tr>

<td>

{{r['guest_name']}}

</td>

<td>

{{r['attendance']}}

</td>

<td>

{{r['guest_count']}}

</td>

<td>

{{r['message']}}

</td>

</tr>

{% else %}

<tr>

<td colspan="4">

No RSVP responses yet.

</td>

</tr>

{% endfor %}

</table>

</div>



<div class="card">

<h2>

Wedding Wishes

</h2>


<table>

<tr>

<th>Name</th>

<th>Wish</th>

</tr>


{% for w in wishes %}

<tr>

<td>

{{w['guest_name']}}

</td>

<td>

{{w['wish']}}

</td>

</tr>

{% else %}

<tr>

<td colspan="2">

No wishes yet.

</td>

</tr>

{% endfor %}

</table>

</div>


</div>

</body>
</html>
"""


# -----------------------------
# START DATABASE / APP
# -----------------------------
init_db()


if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=True
    )
