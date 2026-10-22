#!/usr/bin/env python3
"""Narrow, parent-owned OpenAI relay with pre-request weekly reservations.

The real API key stays outside DeepTutor. Child traffic is disabled unless
the parent has verified privacy readiness. No arbitrary upstream URLs, hosted
tools, images, audio, multiple completions, higher service tiers or models.
"""
from datetime import date, datetime
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import ipaddress
import selectors
import socket
import stat
import threading
import time
from zoneinfo import ZoneInfo

from weekly_budget import Ledger, BudgetExceeded, MODEL

MAX_BODY = 131072
MAX_LINE = 262144
PRICING_REVIEW_BY = date(2026, 11, 20)
TUTOR_POLICY = (
    'Tutor a nine-year-old with short, age-appropriate explanations. Teach one '
    'small step at a time and ask one practice question. Do not request names, '
    'addresses, photos, secrets or other identifying information. Do not provide '
    'sexual or fetish content, graphic violence, dangerous instructions, or '
    'ways to evade parental controls. Refuse inappropriate requests briefly '
    'without shaming and suggest speaking with a trusted parent. Normal '
    'age-appropriate health education is allowed. Do not suggest external '
    'websites. Follow the assigned lesson; topic approval is managed separately.'
)


def private_text(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Credentials must be private parent-owned files')
        value = source.read(4097).strip()
    if not value or len(value) > 4096 or any(c.isspace() for c in value):
        raise ValueError('Invalid private credential file')
    return value


def prepare(payload):
    if not isinstance(payload, dict) or payload.get('model') != MODEL:
        raise ValueError('Only GPT-6 Luna is enabled for this allowance')
    messages = payload.get('messages')
    if not isinstance(messages, list) or not 1 <= len(messages) <= 64:
        raise ValueError('Start a shorter tutoring conversation')
    for message in messages:
        if not isinstance(message, dict) or message.get('role') not in {'system', 'developer', 'user', 'assistant', 'tool'}:
            raise ValueError('Invalid tutoring message')
        if message.get('content') is not None and not isinstance(message['content'], str):
            raise ValueError('This allowance currently supports text only')
        if set(message) - {'role', 'content', 'name', 'tool_calls', 'tool_call_id'}:
            raise ValueError('Unsupported message field')
        if message.get('role') == 'user' and message.get('name'):
            raise ValueError('Personal user names are not sent to the provider')
    tools = payload.get('tools') or []
    if not isinstance(tools, list) or len(tools) > 32:
        raise ValueError('Too many function definitions')
    if any(not isinstance(tool, dict) or tool.get('type') != 'function' for tool in tools):
        raise ValueError('Hosted paid tools are disabled')
    wire = {'model': MODEL, 'messages': [{'role': 'developer', 'content': TUTOR_POLICY}, *messages],
            'max_completion_tokens': 1024, 'reasoning_effort': 'none',
            'n': 1, 'store': False, 'service_tier': 'default',
            'stream': payload.get('stream') is True}
    if tools:
        wire['tools'] = tools
        wire['tool_choice'] = 'auto'
    if wire['stream']:
        wire['stream_options'] = {'include_usage': True}
    raw = json.dumps(wire, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
    if len(raw) > MAX_BODY:
        raise ValueError('Conversation is too long; start a new lesson session')
    # Text-only byte upper bound plus ample message/template framing overhead.
    # Context stays well below long-context pricing; max_completion_tokens
    # includes reasoning tokens. Discounts are deliberately not assumed.
    return wire, raw, len(raw) + 4096


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    config_root = Path.home() / '.config/family-tutor'
    ledger = None
    tunnel_slots = threading.BoundedSemaphore(8)

    def log_message(self, *args):
        pass  # Never log prompts, credentials or provider error bodies.

    def reply(self, status, data):
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def authorized(self):
        return self.client_address[0] == '172.30.60.2' and hmac.compare_digest(
            self.headers.get('Authorization', ''),
            'Bearer ' + private_text(self.config_root / 'gateway-token'))

    def do_GET(self):
        try:
            if not self.authorized():
                return self.reply(403, {'error': {'message': 'Not an enrolled tutoring client'}})
            if self.path == '/v1/models':
                return self.reply(200, {'object': 'list', 'data': [{'id': MODEL, 'object': 'model', 'owned_by': 'openai'}]})
            if self.path == '/family/budget':
                return self.reply(200, self.ledger.status())
            self.reply(404, {'error': {'message': 'Endpoint disabled'}})
        except (OSError, ValueError):
            self.reply(503, {'error': {'message': 'Parent API configuration is not ready'}})

    def do_CONNECT(self):
        """TLS passthrough for parent Codex sign-in only; no general egress.

        Provider credentials remain end-to-end encrypted. OpenAI API traffic
        is deliberately NOT a tunnel destination: it must use the budget path.
        """
        if self.client_address[0] != '172.30.60.2' or self.path not in {
            'auth.openai.com:443', 'chatgpt.com:443'
        }:
            return self.reply(403, {'error': {'message': 'Destination is not enabled'}})
        if not self.tunnel_slots.acquire(blocking=False):
            return self.reply(503, {'error': {'message': 'Parent connection is busy'}})
        remote = None
        sent = False
        try:
            host = self.path.rsplit(':', 1)[0]
            for family, socktype, proto, _, address in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
                if not ipaddress.ip_address(address[0]).is_global:
                    continue
                candidate = socket.socket(family, socktype, proto)
                candidate.settimeout(10)
                try:
                    candidate.connect(address)
                    remote = candidate
                    break
                except OSError:
                    candidate.close()
            if remote is None:
                raise OSError('No public provider address available')
            self.send_response(200, 'Connection Established')
            self.end_headers()
            sent = True
            self.connection.settimeout(120)
            remote.settimeout(120)
            deadline = time.monotonic() + 120
            with selectors.DefaultSelector() as selector:
                selector.register(self.connection, selectors.EVENT_READ, remote)
                selector.register(remote, selectors.EVENT_READ, self.connection)
                while time.monotonic() < deadline:
                    for key, _ in selector.select(timeout=1):
                        chunk = key.fileobj.recv(65536)
                        if not chunk:
                            return
                        key.data.sendall(chunk)
                        deadline = time.monotonic() + 120
        except OSError:
            if not sent:
                self.reply(502, {'error': {'message': 'Parent sign-in provider is unreachable'}})
        finally:
            if remote:
                remote.close()
            self.tunnel_slots.release()
            self.close_connection = True

    def do_POST(self):
        upstream = None
        headers_sent = False
        try:
            if not self.authorized() or self.path != '/v1/chat/completions':
                return self.reply(403, {'error': {'message': 'Endpoint or client disabled'}})
            # Never auto-enable merely because a key or billing credit exists.
            if not (self.config_root / 'child-api-ready').is_file():
                return self.reply(403, {'error': {'message': 'Child API tutoring awaits parent privacy and content-control verification'}})
            if datetime.now(ZoneInfo('America/New_York')).date() > PRICING_REVIEW_BY:
                return self.reply(503, {'error': {'message': 'Parent must review current model pricing before tutoring resumes'}})
            if self.headers.get('Transfer-Encoding'):
                raise ValueError('Chunked request uploads are disabled')
            length = int(self.headers.get('Content-Length', '0'))
            if not 1 <= length <= MAX_BODY:
                raise ValueError('Invalid request length')
            self.connection.settimeout(120)
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError('Incomplete request')
            wire, raw, bound = prepare(json.loads(body))
            api_key = private_text(self.config_root / 'openai-api-key')
            key = self.ledger.reserve(bound, wire['max_completion_tokens'])
            upstream = http.client.HTTPSConnection('api.openai.com', timeout=120)
            upstream.request('POST', '/v1/chat/completions', raw,
                             {'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'})
            response = upstream.getresponse()
            if response.status != 200:
                # Ambiguous failures keep the conservative reservation.
                return self.reply(response.status, {'error': {'message': f'OpenAI request failed (HTTP {response.status}); ask your parent'}})
            if not wire['stream']:
                result = response.read(4 * 1024 * 1024 + 1)
                if len(result) > 4 * 1024 * 1024:
                    raise ValueError('Oversized provider response')
                parsed = json.loads(result)
                self.ledger.reconcile(key, parsed.get('usage'))
                return self.reply(200, parsed)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()
            headers_sent = True
            usage = None
            done = False
            while line := response.readline(MAX_LINE + 1):
                if len(line) > MAX_LINE:
                    raise ValueError('Oversized provider event')
                if line.startswith(b'data: '):
                    event = line[6:].strip()
                    if event == b'[DONE]':
                        done = True
                    else:
                        parsed = json.loads(event)
                        if parsed.get('usage') is not None:
                            usage = parsed['usage']
                self.wfile.write(line)
                self.wfile.flush()
            if done:
                self.ledger.reconcile(key, usage)
        except BudgetExceeded as exc:
            if not headers_sent:
                self.reply(429, {'error': {'message': str(exc), 'code': 'family_weekly_budget_exceeded'}})
        except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException):
            if not headers_sent:
                self.reply(503, {'error': {'message': 'Tutoring request could not complete; unused allowance remains conservatively reserved'}})
        finally:
            if upstream:
                upstream.close()
            self.close_connection = True


if __name__ == '__main__':
    os.umask(0o077)
    Handler.ledger = Ledger(Path.home() / '.local/state/family-tutor/budget')
    ThreadingHTTPServer(('172.30.60.1', 11435), Handler).serve_forever()
