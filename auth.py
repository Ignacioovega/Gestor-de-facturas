import hashlib
import json
import secrets
from pathlib import Path

import streamlit as st

USERS_PATH = Path(__file__).parent / "data" / "users.json"
OLD_AUTH_PATH = Path(__file__).parent / "data" / "auth.json"
DEFAULT_PASSWORD = "cambiar123"
ROLES = ["admin", "editor", "lector"]


def _hash(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode()).hexdigest()


def _save(users: dict):
    USERS_PATH.write_text(json.dumps(users, indent=2))


def _load_or_create() -> dict:
    USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if USERS_PATH.exists():
        return json.loads(USERS_PATH.read_text())

    if OLD_AUTH_PATH.exists():
        old = json.loads(OLD_AUTH_PATH.read_text())
        users = {
            "admin": {
                "salt": old["salt"],
                "hash": old["hash"],
                "role": "admin",
                "is_default": old.get("is_default", False),
            }
        }
        OLD_AUTH_PATH.unlink()
    else:
        salt = secrets.token_hex(16)
        users = {
            "admin": {
                "salt": salt,
                "hash": _hash(DEFAULT_PASSWORD, salt),
                "role": "admin",
                "is_default": True,
            }
        }

    _save(users)
    return users


def check_password(username: str, password: str) -> bool:
    users = _load_or_create()
    user = users.get(username)
    if not user:
        return False
    return _hash(password, user["salt"]) == user["hash"]


def get_role(username: str) -> str | None:
    user = _load_or_create().get(username)
    return user["role"] if user else None


def is_default_password(username: str) -> bool:
    return _load_or_create().get(username, {}).get("is_default", False)


def set_password(username: str, new_password: str):
    users = _load_or_create()
    salt = secrets.token_hex(16)
    users[username]["salt"] = salt
    users[username]["hash"] = _hash(new_password, salt)
    users[username]["is_default"] = False
    _save(users)


def list_users() -> dict:
    return _load_or_create()


def add_user(username: str, password: str, role: str):
    users = _load_or_create()
    username = username.strip()
    if not username:
        raise ValueError("El nombre de usuario no puede estar vacío.")
    if username in users:
        raise ValueError("Ese usuario ya existe.")
    salt = secrets.token_hex(16)
    users[username] = {
        "salt": salt,
        "hash": _hash(password, salt),
        "role": role,
        "is_default": False,
    }
    _save(users)


def delete_user(username: str):
    users = _load_or_create()
    if username not in users:
        return
    admins = [u for u, d in users.items() if d["role"] == "admin"]
    if users[username]["role"] == "admin" and len(admins) <= 1:
        raise ValueError("No se puede eliminar al único administrador.")
    del users[username]
    _save(users)


def require_login():
    if st.session_state.get("authenticated"):
        return

    st.title("🔒 Gestor de Facturas")
    st.write("Ingresá tus credenciales para acceder.")

    if is_default_password("admin"):
        st.caption(
            f"Primer ingreso: usuario **admin**, contraseña **{DEFAULT_PASSWORD}** "
            "(cambiala después de entrar)."
        )

    username = st.text_input("Usuario")
    password = st.text_input("Contraseña", type="password")
    if st.button("Entrar"):
        if check_password(username, password):
            st.session_state["authenticated"] = True
            st.session_state["username"] = username
            st.session_state["role"] = get_role(username)
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos.")

    st.stop()


def render_account_controls():
    with st.sidebar:
        st.subheader("Cuenta")
        st.caption(f"Conectado como **{st.session_state.get('username')}** ({st.session_state.get('role')})")

        if st.button("Cerrar sesión"):
            for key in ("authenticated", "username", "role"):
                st.session_state.pop(key, None)
            st.rerun()

        with st.expander("Cambiar mi contraseña"):
            actual = st.text_input("Contraseña actual", type="password", key="pw_actual")
            nueva = st.text_input("Nueva contraseña", type="password", key="pw_nueva")
            nueva2 = st.text_input("Repetir nueva contraseña", type="password", key="pw_nueva2")
            if st.button("Actualizar contraseña"):
                username = st.session_state["username"]
                if not check_password(username, actual):
                    st.error("La contraseña actual no es correcta.")
                elif len(nueva) < 6:
                    st.error("La nueva contraseña debe tener al menos 6 caracteres.")
                elif nueva != nueva2:
                    st.error("Las contraseñas nuevas no coinciden.")
                else:
                    set_password(username, nueva)
                    st.success("Contraseña actualizada.")

        if st.session_state.get("role") == "admin":
            with st.expander("Gestionar usuarios"):
                users = list_users()
                st.table([{"usuario": u, "rol": d["role"]} for u, d in users.items()])

                st.markdown("**Agregar usuario**")
                nuevo_user = st.text_input("Usuario nuevo", key="nuevo_user")
                nuevo_pass = st.text_input("Contraseña", type="password", key="nuevo_pass")
                nuevo_rol = st.selectbox("Rol", ROLES, key="nuevo_rol")
                if st.button("Crear usuario"):
                    if not nuevo_user or not nuevo_pass:
                        st.error("Completá usuario y contraseña.")
                    elif len(nuevo_pass) < 6:
                        st.error("La contraseña debe tener al menos 6 caracteres.")
                    else:
                        try:
                            add_user(nuevo_user, nuevo_pass, nuevo_rol)
                            st.success(f"Usuario {nuevo_user} creado.")
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))

                st.markdown("**Eliminar usuario**")
                borrables = [u for u in users if u != st.session_state.get("username")]
                if borrables:
                    elegido = st.selectbox("Usuario a eliminar", borrables, key="elegido_borrar")
                    if st.button("Eliminar usuario", type="primary"):
                        try:
                            delete_user(elegido)
                            st.success("Usuario eliminado.")
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
                else:
                    st.caption("No hay otros usuarios para eliminar.")
