"""Autenticação (R9) e perfis com permissões diferentes (R16).

Usuários vêm do .env (AUTH_USERS="admin:<senha>:admin,operador:<senha>:operador"), nunca do código.
Perfis:
    admin     vê tudo, envia comandos, altera a regra e as configurações
    operador  só visualiza (as rotas de comando e de configuração devolvem 403)
O token é assinado com HMAC-SHA256 (AUTH_SECRET) e expira em AUTH_TTL_H horas; sobrevive a reinícios do backend.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

ROLES = ("admin", "operador")


@dataclass(frozen=True)
class User:
    username: str
    role: str

    @property
    def can_command(self) -> bool:
        return self.role == "admin"


class AuthError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def parse_users(spec: str) -> dict[str, tuple[str, str]]:
    """'nome:senha:perfil,...' -> {nome: (senha, perfil)}. Senha vazia ou perfil inválido = erro de configuração."""
    users: dict[str, tuple[str, str]] = {}
    for item in filter(None, (x.strip() for x in (spec or "").split(","))):
        parts = item.split(":")
        if len(parts) != 3 or not parts[0] or not parts[1] or parts[2] not in ROLES:
            raise ValueError("AUTH_USERS deve ser 'nome:senha:perfil,...' com perfil admin ou operador")
        users[parts[0]] = (parts[1], parts[2])
    return users


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Auth:
    def __init__(self, users_spec: str, secret: str | None, ttl_hours: float = 12) -> None:
        self.users = parse_users(users_spec)
        # Sem AUTH_SECRET os tokens valem só até o próximo reinício (segredo aleatório em memória).
        self.secret = (secret or secrets.token_hex(32)).encode()
        self.ttl = int(ttl_hours * 3600)

    @property
    def enabled(self) -> bool:
        return bool(self.users)

    def login(self, username: str, password: str) -> tuple[str, User]:
        entry = self.users.get(username)
        # compare_digest mesmo para usuário inexistente: não revela quais nomes existem pelo tempo de resposta
        ok = hmac.compare_digest((entry[0] if entry else secrets.token_hex(8)).encode(), (password or "").encode())
        if not entry or not ok:
            raise AuthError(401, "usuário ou senha inválidos")
        user = User(username, entry[1])
        return self.issue(user), user

    def issue(self, user: User) -> str:
        body = _b64(json.dumps({"u": user.username, "r": user.role, "exp": int(time.time()) + self.ttl}).encode())
        sig = _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())
        return f"{body}.{sig}"

    def verify(self, token: str | None) -> User:
        if not token or "." not in token:
            raise AuthError(401, "faça login para continuar")
        body, sig = token.rsplit(".", 1)
        good = _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(good, sig):
            raise AuthError(401, "sessão inválida")
        try:
            data = json.loads(_unb64(body))
        except Exception:
            raise AuthError(401, "sessão inválida")
        if data.get("exp", 0) < time.time():
            raise AuthError(401, "sessão expirada, faça login de novo")
        if data.get("u") not in self.users or self.users[data["u"]][1] != data.get("r"):
            raise AuthError(401, "usuário removido ou perfil alterado")
        return User(data["u"], data["r"])
