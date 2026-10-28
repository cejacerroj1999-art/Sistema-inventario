"""Acceso propio: bcrypt, sesiones opacas y cookie persistente; sin Google."""
import re
import datetime as dt
import bcrypt
import streamlit as st
from streamlit_cookies_controller import CookieController


def hash_password(password):
    raw = password.encode('utf-8')
    if len(password) < 10 or len(raw) > 72:
        raise ValueError('La contraseña debe tener al menos 10 caracteres y como máximo 72 bytes UTF-8.')
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12, prefix=b'2a')).decode('ascii')


def valid_login(value):
    return bool(re.fullmatch(r'[a-z0-9][a-z0-9_.-]{2,39}', value))


def authenticate(client):
    """Consultar siempre la sesión real en DB; no confiar en un rol de una cookie."""
    name = st.secrets.get('SESSION_COOKIE_NAME','inventario_sesion')
    secure = bool(st.secrets.get('COOKIE_SECURE',True))
    # El lector nativo restaura la cookie; el componente sólo la escribe o elimina.
    # Inicializar el caché evita valores None mientras el componente carga.
    if st.session_state.get('inventario_cookies') is None:
        request_token = st.context.cookies.get(name)
        st.session_state['inventario_cookies'] = {name:request_token} if request_token else {}
    cookies = CookieController(key='inventario_cookies')
    token = st.session_state.get('_session_token')
    if not token and not st.session_state.get('_signed_out'):
        # Leer del request de Streamlit evita depender del render asíncrono del componente.
        token = st.context.cookies.get(name)
    actor = None
    if token:
        actor = client.rpc('validar_sesion_local', {'p_token':token}).execute().data
        if actor:
            st.session_state['_session_token'] = token
        else:
            st.session_state.pop('_session_token',None)
            st.session_state['_signed_out'] = True
    if actor:
        st.sidebar.write(f"{actor['usuario']} · {actor['rol']}")
        if not st.sidebar.button('Cerrar sesión',key='logout_local'):
            return actor
        # Revocar primero en DB: incluso una copia de la cookie queda inválida.
        client.rpc('cerrar_sesion_local',{'p_token':token}).execute()
        if cookies.get(name) is not None:
            cookies.remove(name,secure=secure,same_site='strict')
        else:
            # El componente puede seguir cargando; set con max_age=0 también elimina.
            cookies.set(name,'',max_age=0,secure=secure,same_site='strict')
        for key in list(st.session_state):
            if key.startswith(('op:','cart:')) or key=='_session_token':
                del st.session_state[key]
        st.session_state['_signed_out'] = True
        st.success('Sesión cerrada.')
    st.subheader('Iniciar sesión')
    with st.form('login_local',clear_on_submit=True):
        username = st.text_input('Usuario',max_chars=40)
        password = st.text_input('Contraseña',type='password')
        submitted = st.form_submit_button('Ingresar',type='primary')
    if submitted:
        result = client.rpc('iniciar_sesion_local',{'p_login':username.strip().lower(),'p_password':password}).execute().data
        if not result:
            st.error('No se pudo iniciar sesión. Revisa tus credenciales o consulta al administrador. Tras cinco fallos, espera 15 minutos.')
            return None
        token = result['token']
        cookies.set(name,token,max_age=30*24*3600,
                    expires=dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=30),
                    secure=secure,same_site='strict')
        st.session_state['_session_token'] = token
        st.session_state['_signed_out'] = False
        # No rerun inmediato: permitir que el navegador reciba la escritura de cookie.
        st.success('Sesión iniciada.')
        st.button('Entrar al inventario',on_click=lambda: None)
        return None
    return None
