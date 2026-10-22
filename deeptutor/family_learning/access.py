"""Optional local-only learner boundary shared by HTTP and WebSocket auth."""
def learner_route_allowed(*, local_only, auth_enabled, role, path, websocket=False):
    if not local_only:
        return True
    if not auth_enabled:
        return False
    if role == 'admin':
        return True
    if websocket:
        return False
    return path in {'/api/auth/me', '/api/auth/status', '/api/auth/logout'} or path == '/api/family-learning' or path.startswith('/api/family-learning/')
