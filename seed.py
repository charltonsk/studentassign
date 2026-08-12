"""Seed the database with demo data for examiner testing."""
from datetime import datetime, timedelta
from app import create_app
from models import db, User, Course, Enrollment, Assignment

app = create_app()

with app.app_context():
    db.drop_all()
    db.create_all()

    instructor = User(name="Dr. Amara Osei", email="instructor@demo.com", role="instructor")
    instructor.set_password("Password1")

    student1 = User(name="Kojo Mensah", email="student1@demo.com", role="student")
    student1.set_password("Password1")

    student2 = User(name="Ama Boateng", email="student2@demo.com", role="student")
    student2.set_password("Password1")

    db.session.add_all([instructor, student1, student2])
    db.session.commit()

    course = Course(
        code="CS301",
        title="Advanced Software Engineering",
        description="Requirements, design, implementation and quality practices for real systems.",
        instructor_id=instructor.id,
    )
    db.session.add(course)
    db.session.commit()

    db.session.add_all([
        Enrollment(student_id=student1.id, course_id=course.id),
        Enrollment(student_id=student2.id, course_id=course.id),
    ])

    a1 = Assignment(
        course_id=course.id,
        title="Requirements Specification",
        description="Submit an SRS for your chosen project, including functional and non-functional requirements.",
        due_date=datetime.utcnow() + timedelta(days=5),
        max_score=100,
    )
    a2 = Assignment(
        course_id=course.id,
        title="System Design Document",
        description="Submit UML diagrams and an architecture overview for your project.",
        due_date=datetime.utcnow() - timedelta(days=1),  # already overdue, for demo
        max_score=50,
    )
    db.session.add_all([a1, a2])
    db.session.commit()

    print("Seeded database with:")
    print("  Instructor: instructor@demo.com / Password1")
    print("  Student 1 : student1@demo.com  / Password1")
    print("  Student 2 : student2@demo.com  / Password1")
