"""
Test suite for StudentAssign.
Covers: unit tests (model logic), integration tests (routes + DB),
and functional/system tests (end-to-end user flows).
Run with: pytest -v
"""
import io
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from models import db, User, Course, Enrollment, Assignment, Submission


@pytest.fixture
def app():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        }
    )
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def make_users(app):
    with app.app_context():
        instructor = User(name="Dr. Osei", email="i@test.com", role="instructor")
        instructor.set_password("Password1")
        student = User(name="Kojo", email="s@test.com", role="student")
        student.set_password("Password1")
        db.session.add_all([instructor, student])
        db.session.commit()
        return instructor.id, student.id


def login(client, email, password):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=True)


# ---------------- UNIT TESTS ----------------

class TestUserModel:
    def test_password_hashing(self, app):
        with app.app_context():
            u = User(name="A", email="a@test.com", role="student")
            u.set_password("secret123")
            assert u.password_hash != "secret123"
            assert u.check_password("secret123") is True
            assert u.check_password("wrong") is False

    def test_is_instructor(self, app):
        with app.app_context():
            u = User(name="A", email="a@test.com", role="instructor")
            assert u.is_instructor() is True
            u2 = User(name="B", email="b@test.com", role="student")
            assert u2.is_instructor() is False


class TestModelRelationships:
    def test_course_assignment_cascade_delete(self, app):
        with app.app_context():
            i = User(name="I", email="i2@test.com", role="instructor")
            i.set_password("x")
            db.session.add(i)
            db.session.commit()
            c = Course(code="C1", title="T", instructor_id=i.id)
            db.session.add(c)
            db.session.commit()
            a = Assignment(course_id=c.id, title="A1", due_date=datetime.utcnow())
            db.session.add(a)
            db.session.commit()
            assert Assignment.query.count() == 1
            db.session.delete(c)
            db.session.commit()
            assert Assignment.query.count() == 0  # cascade delete works

    def test_unique_enrollment_constraint(self, app):
        with app.app_context():
            i = User(name="I", email="i3@test.com", role="instructor")
            i.set_password("x")
            s = User(name="S", email="s3@test.com", role="student")
            s.set_password("x")
            db.session.add_all([i, s])
            db.session.commit()
            c = Course(code="C2", title="T2", instructor_id=i.id)
            db.session.add(c)
            db.session.commit()
            db.session.add(Enrollment(student_id=s.id, course_id=c.id))
            db.session.commit()
            db.session.add(Enrollment(student_id=s.id, course_id=c.id))
            with pytest.raises(Exception):
                db.session.commit()


# ---------------- INTEGRATION TESTS ----------------

class TestAuthRoutes:
    def test_register_and_login(self, client):
        resp = client.post(
            "/register",
            data={"name": "New User", "email": "new@test.com", "password": "Password1", "role": "student"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        resp = login(client, "new@test.com", "Password1")
        assert b"Dashboard" in resp.data or resp.status_code == 200

    def test_duplicate_email_rejected(self, client):
        client.post("/register", data={"name": "A", "email": "dup@test.com", "password": "Password1", "role": "student"})
        resp = client.post(
            "/register",
            data={"name": "B", "email": "dup@test.com", "password": "Password1", "role": "student"},
        )
        assert b"already exists" in resp.data

    def test_login_wrong_password(self, client):
        client.post("/register", data={"name": "A", "email": "wp@test.com", "password": "Password1", "role": "student"})
        resp = client.post("/login", data={"email": "wp@test.com", "password": "wrong"})
        assert b"Invalid email or password" in resp.data

    def test_short_password_rejected(self, client):
        resp = client.post(
            "/register", data={"name": "A", "email": "short@test.com", "password": "123", "role": "student"}
        )
        assert b"at least 6 characters" in resp.data

    def test_dashboard_requires_login(self, client):
        resp = client.get("/dashboard", follow_redirects=True)
        assert b"Log in" in resp.data


class TestRoleBasedAccess:
    def test_student_cannot_create_course(self, app, client):
        make_users(app)
        login(client, "s@test.com", "Password1")
        resp = client.get("/courses/new")
        assert resp.status_code == 403

    def test_instructor_can_create_course(self, app, client):
        make_users(app)
        login(client, "i@test.com", "Password1")
        resp = client.post(
            "/courses/new", data={"code": "CS101", "title": "Intro", "description": ""}, follow_redirects=True
        )
        assert resp.status_code == 200
        with app.app_context():
            assert Course.query.filter_by(code="CS101").count() == 1

    def test_student_cannot_grade(self, app, client):
        instructor_id, student_id = make_users(app)
        with app.app_context():
            c = Course(code="C1", title="T", instructor_id=instructor_id)
            db.session.add(c)
            db.session.commit()
            a = Assignment(course_id=c.id, title="A1", due_date=datetime.utcnow() + timedelta(days=1))
            db.session.add(a)
            db.session.commit()
            db.session.add(Enrollment(student_id=student_id, course_id=c.id))
            db.session.commit()
            sub = Submission(assignment_id=a.id, student_id=student_id, content_text="ans")
            db.session.add(sub)
            db.session.commit()
            sub_id = sub.id

        login(client, "s@test.com", "Password1")
        resp = client.post(f"/submissions/{sub_id}/grade", data={"score": "90", "feedback": "x"})
        assert resp.status_code == 403


class TestAssignmentSubmissionFlow:
    def test_full_submission_and_grading_flow(self, app, client):
        instructor_id, student_id = make_users(app)
        with app.app_context():
            c = Course(code="C1", title="T", instructor_id=instructor_id)
            db.session.add(c)
            db.session.commit()
            a = Assignment(
                course_id=c.id, title="Essay", due_date=datetime.utcnow() + timedelta(days=2), max_score=100
            )
            db.session.add(a)
            db.session.commit()
            db.session.add(Enrollment(student_id=student_id, course_id=c.id))
            db.session.commit()
            assignment_id = a.id

        # Student submits
        login(client, "s@test.com", "Password1")
        resp = client.post(
            f"/assignments/{assignment_id}/submit",
            data={"content_text": "My essay text"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        with app.app_context():
            sub = Submission.query.filter_by(assignment_id=assignment_id, student_id=student_id).first()
            assert sub is not None
            assert sub.is_late is False
            sub_id = sub.id
        client.get("/logout")

        # Instructor grades
        login(client, "i@test.com", "Password1")
        resp = client.post(
            f"/submissions/{sub_id}/grade", data={"score": "77", "feedback": "Nice work"}, follow_redirects=True
        )
        assert resp.status_code == 200
        with app.app_context():
            sub = db.session.get(Submission, sub_id)
            assert sub.score == 77
            assert sub.feedback == "Nice work"

    def test_late_submission_flagged(self, app, client):
        instructor_id, student_id = make_users(app)
        with app.app_context():
            c = Course(code="C1", title="T", instructor_id=instructor_id)
            db.session.add(c)
            db.session.commit()
            a = Assignment(
                course_id=c.id, title="Late Essay", due_date=datetime.utcnow() - timedelta(days=1), max_score=100
            )
            db.session.add(a)
            db.session.commit()
            db.session.add(Enrollment(student_id=student_id, course_id=c.id))
            db.session.commit()
            assignment_id = a.id

        login(client, "s@test.com", "Password1")
        client.post(f"/assignments/{assignment_id}/submit", data={"content_text": "Late work"})
        with app.app_context():
            sub = Submission.query.filter_by(assignment_id=assignment_id, student_id=student_id).first()
            assert sub.is_late is True

    def test_score_out_of_range_rejected(self, app, client):
        instructor_id, student_id = make_users(app)
        with app.app_context():
            c = Course(code="C1", title="T", instructor_id=instructor_id)
            db.session.add(c)
            db.session.commit()
            a = Assignment(course_id=c.id, title="A", due_date=datetime.utcnow() + timedelta(days=1), max_score=50)
            db.session.add(a)
            db.session.commit()
            db.session.add(Enrollment(student_id=student_id, course_id=c.id))
            db.session.commit()
            sub = Submission(assignment_id=a.id, student_id=student_id, content_text="x")
            db.session.add(sub)
            db.session.commit()
            sub_id, aid = sub.id, a.id

        login(client, "i@test.com", "Password1")
        resp = client.post(f"/submissions/{sub_id}/grade", data={"score": "999", "feedback": ""}, follow_redirects=True)
        assert b"must be between" in resp.data
        with app.app_context():
            assert db.session.get(Submission, sub_id).score is None

    def test_unenrolled_student_cannot_submit(self, app, client):
        instructor_id, student_id = make_users(app)
        with app.app_context():
            c = Course(code="C1", title="T", instructor_id=instructor_id)
            db.session.add(c)
            db.session.commit()
            a = Assignment(course_id=c.id, title="A", due_date=datetime.utcnow() + timedelta(days=1))
            db.session.add(a)
            db.session.commit()
            aid = a.id
        login(client, "s@test.com", "Password1")  # not enrolled
        resp = client.post(f"/assignments/{aid}/submit", data={"content_text": "x"})
        assert resp.status_code == 403


class TestEnrollment:
    def test_student_can_enroll(self, app, client):
        instructor_id, student_id = make_users(app)
        with app.app_context():
            c = Course(code="C1", title="T", instructor_id=instructor_id)
            db.session.add(c)
            db.session.commit()
            cid = c.id
        login(client, "s@test.com", "Password1")
        client.post(f"/courses/{cid}/enroll", follow_redirects=True)
        with app.app_context():
            assert Enrollment.query.filter_by(student_id=student_id, course_id=cid).count() == 1

    def test_double_enroll_does_not_duplicate(self, app, client):
        instructor_id, student_id = make_users(app)
        with app.app_context():
            c = Course(code="C1", title="T", instructor_id=instructor_id)
            db.session.add(c)
            db.session.commit()
            cid = c.id
        login(client, "s@test.com", "Password1")
        client.post(f"/courses/{cid}/enroll")
        client.post(f"/courses/{cid}/enroll")
        with app.app_context():
            assert Enrollment.query.filter_by(student_id=student_id, course_id=cid).count() == 1
