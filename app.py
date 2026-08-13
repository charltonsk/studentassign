import os
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, redirect, url_for, flash, request, abort
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from werkzeug.utils import secure_filename

from models import db, User, Course, Enrollment, Assignment, Submission

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"pdf", "txt", "doc", "docx", "zip", "py", "java", "c", "cpp"}
MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB


def create_app(test_config=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    db_url = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'studentassign.db')}"
    )
    # Render/Heroku-style URLs use the legacy "postgres://" scheme;
    # SQLAlchemy 2.x requires "postgresql://".
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

    if test_config:
        app.config.update(test_config)

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    db.init_app(app)

    # Create tables on startup if they don't exist yet. This makes table
    # creation happen synchronously before the app can serve any request,
    # rather than relying on a separate deploy hook whose timing relative
    # to the app starting to accept traffic is not guaranteed by every
    # hosting platform (observed race condition on first deploy).
    # create_all() only creates missing tables — it never drops or
    # overwrites existing data, so this is safe to run on every startup.
    with app.app_context():
        db.create_all()

    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    def instructor_required(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated or not current_user.is_instructor():
                abort(403)
            return f(*args, **kwargs)

        return wrapper

    def student_required(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated or current_user.is_instructor():
                abort(403)
            return f(*args, **kwargs)

        return wrapper

    def allowed_file(filename):
        return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

    # ---------- AUTH ----------
    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        return render_template("index.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            role = request.form.get("role", "student")

            if not name or not email or not password:
                flash("All fields are required.", "error")
                return render_template("register.html")
            if role not in ("student", "instructor"):
                role = "student"
            if User.query.filter_by(email=email).first():
                flash("An account with that email already exists.", "error")
                return render_template("register.html")
            if len(password) < 6:
                flash("Password must be at least 6 characters.", "error")
                return render_template("register.html")

            user = User(name=name, email=email, role=role)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = User.query.filter_by(email=email).first()
            if user and user.check_password(password):
                login_user(user)
                return redirect(url_for("dashboard"))
            flash("Invalid email or password.", "error")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    # ---------- DASHBOARD ----------
    @app.route("/dashboard")
    @login_required
    def dashboard():
        if current_user.is_instructor():
            courses = Course.query.filter_by(instructor_id=current_user.id).all()
            pending_count = 0
            for c in courses:
                for a in c.assignments:
                    pending_count += Submission.query.filter_by(
                        assignment_id=a.id, score=None
                    ).count()
            return render_template(
                "dashboard_instructor.html", courses=courses, pending_count=pending_count
            )
        else:
            enrollments = Enrollment.query.filter_by(student_id=current_user.id).all()
            course_ids = [e.course_id for e in enrollments]
            upcoming = (
                Assignment.query.filter(Assignment.course_id.in_(course_ids))
                .order_by(Assignment.due_date.asc())
                .all()
                if course_ids
                else []
            )
            submitted_ids = {
                s.assignment_id
                for s in Submission.query.filter_by(student_id=current_user.id).all()
            }
            return render_template(
                "dashboard_student.html",
                enrollments=enrollments,
                upcoming=upcoming,
                submitted_ids=submitted_ids,
                now=datetime.utcnow(),
            )

    # ---------- COURSES ----------
    @app.route("/courses")
    @login_required
    def course_list():
        all_courses = Course.query.order_by(Course.code).all()
        my_ids = set()
        if not current_user.is_instructor():
            my_ids = {
                e.course_id
                for e in Enrollment.query.filter_by(student_id=current_user.id).all()
            }
        return render_template("course_list.html", courses=all_courses, my_ids=my_ids)

    @app.route("/courses/new", methods=["GET", "POST"])
    @login_required
    @instructor_required
    def course_new():
        if request.method == "POST":
            code = request.form.get("code", "").strip()
            title = request.form.get("title", "").strip()
            description = request.form.get("description", "").strip()
            if not code or not title:
                flash("Course code and title are required.", "error")
                return render_template("course_form.html")
            course = Course(
                code=code, title=title, description=description, instructor_id=current_user.id
            )
            db.session.add(course)
            db.session.commit()
            flash("Course created.", "success")
            return redirect(url_for("dashboard"))
        return render_template("course_form.html")

    @app.route("/courses/<int:course_id>")
    @login_required
    def course_detail(course_id):
        course = db.get_or_404(Course, course_id)
        is_enrolled = False
        if not current_user.is_instructor():
            is_enrolled = (
                Enrollment.query.filter_by(
                    student_id=current_user.id, course_id=course.id
                ).first()
                is not None
            )
        elif current_user.id != course.instructor_id:
            abort(403)
        return render_template("course_detail.html", course=course, is_enrolled=is_enrolled)

    @app.route("/courses/<int:course_id>/enroll", methods=["POST"])
    @login_required
    @student_required
    def course_enroll(course_id):
        course = db.get_or_404(Course, course_id)
        existing = Enrollment.query.filter_by(
            student_id=current_user.id, course_id=course.id
        ).first()
        if not existing:
            db.session.add(Enrollment(student_id=current_user.id, course_id=course.id))
            db.session.commit()
            flash(f"Enrolled in {course.code}.", "success")
        return redirect(url_for("course_detail", course_id=course.id))

    # ---------- ASSIGNMENTS ----------
    @app.route("/courses/<int:course_id>/assignments/new", methods=["GET", "POST"])
    @login_required
    @instructor_required
    def assignment_new(course_id):
        course = db.get_or_404(Course, course_id)
        if course.instructor_id != current_user.id:
            abort(403)
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            description = request.form.get("description", "").strip()
            due_date_str = request.form.get("due_date", "")
            max_score = request.form.get("max_score", 100)
            if not title or not due_date_str:
                flash("Title and due date are required.", "error")
                return render_template("assignment_form.html", course=course)
            try:
                due_date = datetime.strptime(due_date_str, "%Y-%m-%dT%H:%M")
            except ValueError:
                flash("Invalid due date format.", "error")
                return render_template("assignment_form.html", course=course)
            assignment = Assignment(
                course_id=course.id,
                title=title,
                description=description,
                due_date=due_date,
                max_score=int(max_score) if str(max_score).isdigit() else 100,
            )
            db.session.add(assignment)
            db.session.commit()
            flash("Assignment created.", "success")
            return redirect(url_for("course_detail", course_id=course.id))
        return render_template("assignment_form.html", course=course)

    @app.route("/assignments/<int:assignment_id>")
    @login_required
    def assignment_detail(assignment_id):
        assignment = db.get_or_404(Assignment, assignment_id)
        course = assignment.course
        my_submission = None
        if current_user.is_instructor():
            if course.instructor_id != current_user.id:
                abort(403)
            submissions = Submission.query.filter_by(assignment_id=assignment.id).all()
            return render_template(
                "assignment_detail_instructor.html",
                assignment=assignment,
                course=course,
                submissions=submissions,
            )
        else:
            enrolled = Enrollment.query.filter_by(
                student_id=current_user.id, course_id=course.id
            ).first()
            if not enrolled:
                abort(403)
            my_submission = Submission.query.filter_by(
                assignment_id=assignment.id, student_id=current_user.id
            ).first()
            return render_template(
                "assignment_detail_student.html",
                assignment=assignment,
                course=course,
                submission=my_submission,
                now=datetime.utcnow(),
            )

    @app.route("/assignments/<int:assignment_id>/submit", methods=["POST"])
    @login_required
    @student_required
    def submission_create(assignment_id):
        assignment = db.get_or_404(Assignment, assignment_id)
        enrolled = Enrollment.query.filter_by(
            student_id=current_user.id, course_id=assignment.course_id
        ).first()
        if not enrolled:
            abort(403)

        content_text = request.form.get("content_text", "").strip()
        file = request.files.get("file")
        filename = None

        if file and file.filename:
            if not allowed_file(file.filename):
                flash("File type not allowed.", "error")
                return redirect(url_for("assignment_detail", assignment_id=assignment.id))
            safe_name = secure_filename(file.filename)
            filename = f"{current_user.id}_{assignment.id}_{safe_name}"
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        if not content_text and not filename:
            flash("Provide text or a file to submit.", "error")
            return redirect(url_for("assignment_detail", assignment_id=assignment.id))

        existing = Submission.query.filter_by(
            assignment_id=assignment.id, student_id=current_user.id
        ).first()
        is_late = datetime.utcnow() > assignment.due_date

        if existing:
            existing.content_text = content_text
            existing.filename = filename or existing.filename
            existing.submitted_at = datetime.utcnow()
            existing.is_late = is_late
            existing.score = None
            existing.feedback = None
        else:
            db.session.add(
                Submission(
                    assignment_id=assignment.id,
                    student_id=current_user.id,
                    content_text=content_text,
                    filename=filename,
                    is_late=is_late,
                )
            )
        db.session.commit()
        flash("Submission received" + (" (late)" if is_late else "") + ".", "success")
        return redirect(url_for("assignment_detail", assignment_id=assignment.id))

    @app.route("/submissions/<int:submission_id>/grade", methods=["POST"])
    @login_required
    @instructor_required
    def submission_grade(submission_id):
        submission = db.get_or_404(Submission, submission_id)
        assignment = submission.assignment
        if assignment.course.instructor_id != current_user.id:
            abort(403)
        score = request.form.get("score", "")
        feedback = request.form.get("feedback", "").strip()
        try:
            score_val = int(score)
        except ValueError:
            flash("Score must be a number.", "error")
            return redirect(url_for("assignment_detail", assignment_id=assignment.id))
        if score_val < 0 or score_val > assignment.max_score:
            flash(f"Score must be between 0 and {assignment.max_score}.", "error")
            return redirect(url_for("assignment_detail", assignment_id=assignment.id))
        submission.score = score_val
        submission.feedback = feedback
        submission.graded_at = datetime.utcnow()
        db.session.commit()
        flash("Grade saved.", "success")
        return redirect(url_for("assignment_detail", assignment_id=assignment.id))

    @app.cli.command("init-db")
    def init_db_command():
        """Create database tables. Run once after first deploy: flask init-db"""
        db.create_all()
        print("Database tables created.")

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403, message="Forbidden"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="Not found"), 404

    return app


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5000)
