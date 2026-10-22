"""Local-only lesson authority. No model calls, networking, or code execution.

Actor identity MUST come from an authenticated server session, never a request
body. This module is not an HTTP authentication layer or a Python sandbox.
"""
from dataclasses import dataclass
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid


@dataclass(frozen=True)
class Actor:
    id: str
    role: str


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def validate(course):
    if not isinstance(course, dict) or set(course) != {'title', 'subject', 'objectives', 'lessons'}:
        raise ValueError('Course needs title, subject, objectives and lessons')
    for key in ('title', 'subject'):
        if not isinstance(course[key], str) or not 1 <= len(course[key]) <= 200:
            raise ValueError('Invalid course title or subject')
    if not isinstance(course['objectives'], list) or not 1 <= len(course['objectives']) <= 20:
        raise ValueError('Provide one to twenty objectives')
    if any(not isinstance(item, str) or not 1 <= len(item) <= 500 for item in course['objectives']):
        raise ValueError('Invalid objective')
    if not isinstance(course['lessons'], list) or not 1 <= len(course['lessons']) <= 100:
        raise ValueError('Provide one to one hundred lessons')
    ids = set()
    for lesson in course['lessons']:
        required = {'id', 'title', 'explanation', 'question', 'kind', 'hints', 'success'}
        if not isinstance(lesson, dict) or not required <= lesson.keys():
            raise ValueError('Incomplete lesson')
        if lesson.keys() - (required | {'answer', 'choices', 'rubric'}):
            raise ValueError('Unsupported lesson field')
        if not isinstance(lesson['id'], str) or not re.fullmatch(r'[a-z0-9-]{1,64}', lesson['id']) or lesson['id'] in ids:
            raise ValueError('Lesson IDs must be unique slugs')
        ids.add(lesson['id'])
        for key in ('title', 'explanation', 'question', 'success'):
            if not isinstance(lesson[key], str) or not 1 <= len(lesson[key]) <= 20000:
                raise ValueError('Invalid lesson text')
        if not isinstance(lesson['hints'], list) or len(lesson['hints']) > 10 or any(not isinstance(hint, str) or not 1 <= len(hint) <= 2000 for hint in lesson['hints']):
            raise ValueError('Invalid prepared hints')
        kind = lesson['kind']
        if kind == 'choice':
            choices = lesson.get('choices')
            if not isinstance(choices, list) or not 2 <= len(choices) <= 8 or any(not isinstance(c, str) or not 1 <= len(c) <= 1000 for c in choices):
                raise ValueError('Invalid choices')
            if type(lesson.get('answer')) is not int or not 0 <= lesson['answer'] < len(choices):
                raise ValueError('Invalid choice answer')
        elif kind == 'number':
            if not isinstance(lesson.get('answer'), str) or not decimal(lesson['answer']).is_finite():
                raise ValueError('Number answers must be finite decimal strings')
        elif kind == 'writing':
            if 'answer' in lesson or not isinstance(lesson.get('rubric'), list) or not 1 <= len(lesson['rubric']) <= 20:
                raise ValueError('Writing needs a parent rubric, not an automatic answer')
            if any(not isinstance(item, str) or not 1 <= len(item) <= 1000 for item in lesson['rubric']):
                raise ValueError('Invalid rubric')
        else:
            raise ValueError('Unsupported exercise; Python execution is not enabled yet')
    if len(encoded(course).encode()) > 1_000_000:
        raise ValueError('Course too large')


def decimal(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 100:
        raise ValueError('Enter a number')
    try:
        result = Decimal(value.strip())
    except InvalidOperation as exc:
        raise ValueError('Enter a number') from exc
    if not result.is_finite():
        raise ValueError('Enter a finite number')
    return result


class Lessons:
    def __init__(self, directory):
        root = Path(directory)
        if root.is_symlink():
            raise ValueError('Private storage cannot be a link')
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
            raise ValueError('Lesson storage must be private and parent owned')
        self.path = root / 'lessons.sqlite3'
        if self.path.is_symlink():
            raise ValueError('Database cannot be a link')
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(descriptor)
        if self.path.stat().st_uid != os.getuid() or self.path.stat().st_mode & 0o077:
            raise ValueError('Database must be private and parent owned')
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS courses(id TEXT PRIMARY KEY, owner TEXT, content TEXT);
                CREATE TABLE IF NOT EXISTS assignments(course TEXT, learner TEXT, active INTEGER,
                    PRIMARY KEY(course, learner));
                CREATE TABLE IF NOT EXISTS work(course TEXT, learner TEXT, lesson TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'new',
                    draft TEXT NOT NULL DEFAULT '', feedback TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(course, learner, lesson));
                CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, actor TEXT, fingerprint TEXT, result TEXT);
                CREATE TABLE IF NOT EXISTS submissions(id TEXT PRIMARY KEY, course TEXT,
                    learner TEXT, lesson TEXT, writing TEXT, decision TEXT, feedback TEXT);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def publish(self, actor, course):
        if actor.role != 'parent':
            raise PermissionError('Only parents publish lessons')
        validate(course)
        content = encoded(course)
        key = hashlib.sha256((actor.id + '\0' + content).encode()).hexdigest()
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO courses VALUES(?,?,?)', (key, actor.id, content))
        return key

    def owned(self, db, actor, course):
        row = db.execute('SELECT * FROM courses WHERE id=?', (course,)).fetchone()
        if actor.role != 'parent' or row is None or row['owner'] != actor.id:
            raise PermissionError('Course unavailable')
        return row

    def assign(self, actor, course, learner, active=True):
        if not isinstance(learner, str) or not 1 <= len(learner) <= 128 or type(active) is not bool:
            raise ValueError('Invalid assignment')
        with self.db() as db:
            self.owned(db, actor, course)
            db.execute('INSERT INTO assignments VALUES(?,?,?) ON CONFLICT(course,learner) DO UPDATE SET active=excluded.active', (course, learner, int(active)))

    def current(self, db, actor, course, lesson_id=None):
        row = db.execute('SELECT c.* FROM courses c JOIN assignments a ON c.id=a.course WHERE c.id=? AND a.learner=? AND a.active=1', (course, actor.id)).fetchone()
        if actor.role != 'learner' or row is None:
            raise PermissionError('Lesson is not assigned')
        course_data = json.loads(row['content'])
        states = {r['lesson']: dict(r) for r in db.execute('SELECT * FROM work WHERE course=? AND learner=?', (course, actor.id))}
        unlocked = True
        public = []
        selected = None
        for item in course_data['lessons']:
            state = states.get(item['id'], {'state': 'new', 'attempts': 0, 'draft': '', 'feedback': ''})
            visible = {key: value for key, value in item.items() if key not in {'answer', 'hints', 'success'}}
            visible.update({'unlocked': unlocked, 'state': state['state'], 'attempts': state['attempts'], 'draft': state['draft'], 'feedback': state['feedback']})
            if not unlocked:
                visible = {'id': item['id'], 'title': item['title'], 'unlocked': False}
            public.append(visible)
            if item['id'] == lesson_id:
                if not unlocked:
                    raise PermissionError('Finish the earlier lesson first')
                selected = item
            unlocked = unlocked and state['state'] == 'passed'
        if lesson_id is not None and selected is None:
            raise PermissionError('Unknown lesson')
        return course_data, public, selected

    def view(self, actor, course):
        with self.db() as db:
            data, lessons, _ = self.current(db, actor, course)
            return {**data, 'lessons': lessons}

    def respond(self, actor, course, lesson_id, answer, request_id):
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9]{32}', request_id):
            raise ValueError('A unique request ID is required')
        if not isinstance(answer, str) or len(answer) > 20000:
            raise ValueError('Answer must be text, at most 20000 characters')
        fingerprint = encoded([course, lesson_id, answer])
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            _, _, item = self.current(db, actor, course, lesson_id)
            prior = db.execute('SELECT * FROM events WHERE id=?', (request_id,)).fetchone()
            if prior:
                if prior['actor'] != actor.id or prior['fingerprint'] != fingerprint:
                    raise ValueError('Request ID already used')
                return json.loads(prior['result'])
            db.execute('INSERT OR IGNORE INTO work(course,learner,lesson) VALUES(?,?,?)', (course, actor.id, lesson_id))
            work = db.execute('SELECT * FROM work WHERE course=? AND learner=? AND lesson=?', (course, actor.id, lesson_id)).fetchone()
            if work['state'] in {'passed', 'review'}:
                raise ValueError('Lesson is complete or awaiting parent review')
            attempts = work['attempts'] + 1
            if item['kind'] == 'writing':
                if not answer.strip():
                    raise ValueError('Write something before submitting')
                submission = uuid.uuid4().hex
                db.execute('INSERT INTO submissions VALUES(?,?,?,?,?,?,?)', (submission, course, actor.id, lesson_id, answer, 'pending', ''))
                result = {'state': 'review', 'feedback': 'Sent to your parent for review.', 'submission': submission}
            else:
                try:
                    correct = decimal(answer) == decimal(item['answer']) if item['kind'] == 'number' else answer == str(item['answer'])
                except ValueError:
                    correct = False
                hints = item['hints'] or ['Try again, or ask your parent for help.']
                result = {'state': 'passed' if correct else 'retry', 'feedback': item['success'] if correct else hints[min(attempts - 1, len(hints) - 1)]}
            db.execute('UPDATE work SET attempts=?,state=?,draft=?,feedback=? WHERE course=? AND learner=? AND lesson=?', (attempts, result['state'], answer, result['feedback'], course, actor.id, lesson_id))
            db.execute('INSERT INTO events VALUES(?,?,?,?)', (request_id, actor.id, fingerprint, encoded(result)))
            return result

    def save_draft(self, actor, course, lesson, text):
        if not isinstance(text, str) or len(text) > 20000:
            raise ValueError('Draft too long')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            _, _, item = self.current(db, actor, course, lesson)
            if item['kind'] != 'writing':
                raise ValueError('Only writing exercises have drafts')
            old = db.execute('SELECT state FROM work WHERE course=? AND learner=? AND lesson=?', (course, actor.id, lesson)).fetchone()
            if old and old['state'] in {'passed', 'review'}:
                raise ValueError('Wait for parent review before revising')
            db.execute("INSERT INTO work(course,learner,lesson,draft) VALUES(?,?,?,?) ON CONFLICT(course,learner,lesson) DO UPDATE SET draft=excluded.draft", (course, actor.id, lesson, text))

    def submissions(self, actor, course):
        with self.db() as db:
            self.owned(db, actor, course)
            return [dict(row) for row in db.execute('SELECT * FROM submissions WHERE course=?', (course,))]

    def review(self, actor, submission, approve, feedback):
        if type(approve) is not bool or not isinstance(feedback, str) or not feedback.strip() or len(feedback) > 10000:
            raise ValueError('Provide a decision and helpful feedback')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM submissions WHERE id=?', (submission,)).fetchone()
            if row is None:
                raise PermissionError('Submission unavailable')
            self.owned(db, actor, row['course'])
            if row['decision'] != 'pending':
                raise ValueError('Submission already reviewed')
            state = 'passed' if approve else 'revise'
            db.execute('UPDATE submissions SET decision=?,feedback=? WHERE id=?', (state, feedback, submission))
            db.execute('UPDATE work SET state=?,feedback=? WHERE course=? AND learner=? AND lesson=?', (state, feedback, row['course'], row['learner'], row['lesson']))
