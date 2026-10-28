"""Ejecutar con: streamlit run app.py. Ver README antes de configurar."""
import copy
import datetime as dt
import logging
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from supabase import create_client
from PIL import Image
import zxingcpp

from domain import candidates
from github_files import GitHubFiles

st.set_page_config(page_title='Inventario', page_icon='📦', layout='wide')
st.title('Inventario')

# Cada sesión tiene su propio cliente; nunca cachear clientes con estado de usuario.
if not st.user.is_logged_in:
    st.info('Inicia sesión con la cuenta habilitada por el administrador.')
    if st.button('Iniciar sesión'):
        st.login()
    st.stop()
if not st.user.get('email_verified', False):
    st.error('Se requiere un correo verificado por Google.')
    if st.button('Cerrar sesión'):
        st.logout()
    st.stop()


def db():
    if '_db' not in st.session_state:
        st.session_state['_db'] = create_client(st.secrets['SUPABASE_URL'], st.secrets['SUPABASE_SERVICE_KEY'])
    return st.session_state['_db']


def rows(table):
    # Supabase limita por defecto cada respuesta. Paginar para no truncar inventario.
    output, start = [], 0
    order = 'historial_id' if table == 'validaciones' else 'id'
    while True:
        batch = db().table(table).select('*').order(order).range(start, start + 499).execute().data
        output.extend(batch)
        if len(batch) < 500:
            return output
        start += 500


def github():
    return GitHubFiles(st.secrets['GITHUB_TOKEN'], st.secrets['GITHUB_REPO'], st.secrets['GITHUB_BRANCH'])


def mutate(action, payload, slot):
    """Conservar el UUID si hay timeout; un reintento idéntico no aplica dos veces."""
    key = f'op:{slot}'
    state = st.session_state.get(key)
    if not state or state['payload'] != payload:
        state = {'id': str(uuid4()), 'payload': copy.deepcopy(payload)}
        st.session_state[key] = state
    result = db().rpc('operar', {'p_actor': actor['id'], 'p_operacion': state['id'],
                                'p_accion': action, 'p_datos': payload}).execute().data
    # Mantener id hasta que cambie el formulario: protege doble clic y respuesta tardía.
    st.success('Operación guardada.')
    return result


def scan(key):
    if st.checkbox('Usar cámara del celular', key=f'cam:{key}'):
        shot = st.camera_input('Fotografiar el código con buena luz', key=f'photo:{key}')
        if shot:
            codes = zxingcpp.read_barcodes(Image.open(shot))
            if codes:
                code = st.selectbox('Código detectado', [c.text for c in codes], key=f'detected:{key}')
                st.code(code)
                return code
            st.warning('No se pudo leer el código. Acerque la cámara o ingréselo manualmente.')
    return ''


def products():
    return rows('inventario')


def product_choice(items, label='Producto', key='product'):
    if not items:
        st.info('No hay productos. Administrador o bodeguero debe crear el catálogo.')
        return None
    mapped = {p['id']: p for p in items}
    chosen = st.selectbox(label, list(mapped), format_func=lambda x:
        f"{mapped[x]['nombre']} · {mapped[x]['codigo_de_barras'] or 'sin código'} · stock {mapped[x]['stock']}", key=key)
    return mapped[chosen]


def inventory(low=False):
    data = products()
    if low:
        data = [p for p in data if float(p['stock']) <= float(p['stock_minimo'])]
    st.subheader('Bajo stock' if low else 'Inventario')
    a, b = st.columns(2)
    a.metric('Productos distintos', len(data))
    b.metric('Unidades disponibles', f"{sum(float(p['stock']) for p in data):,.3f}")
    # Todos pueden consultar bajo stock; vendedor ve sólo información operativa.
    if actor['rol'] == 'vendedor':
        data = [{k: p[k] for k in ('id','codigo_de_barras','nombre','tipo','stock','precio_venta','stock_minimo')} for p in data]
    if not data:
        st.info('Sin productos para mostrar.')
        return
    frame = pd.DataFrame(data)
    term = st.text_input('Buscar nombre, código, stock o precio').casefold().strip()
    if term:
        cols = ['nombre','codigo_de_barras','stock','precio_venta']
        frame = frame[frame[cols].astype(str).apply(lambda c: c.str.casefold().str.contains(term, regex=False)).any(axis=1)]
    types = st.multiselect('Tipo de producto', sorted(frame.tipo.unique()))
    if types:
        frame = frame[frame.tipo.isin(types)]
    order = st.selectbox('Ordenar por', ['nombre','stock','tipo','precio_venta'])
    descending = st.checkbox('Descendente')
    st.dataframe(frame.sort_values(order, ascending=not descending), hide_index=True, use_container_width=True)


def catalog():
    st.subheader('Productos')
    data = products()
    search = st.text_input('Nombre que aparece en la factura')
    if search:
        for score, p in candidates(search, data):
            if score >= .5:
                st.write(f"Coincidencia {score:.0%}: {p['nombre']} — {p['codigo_de_barras'] or 'falta código'}")
        st.caption('Selecciona el producto existente si es el mismo; verifica formato, tamaño y unidad.')
    editing = st.radio('Acción', ['Crear producto','Modificar existente'], horizontal=True)
    p = product_choice(data, key='editprod') if editing == 'Modificar existente' else None
    if editing == 'Modificar existente' and not p:
        return
    scanned = scan('catalog')
    p = p or {}
    with st.form('catalog'):
        name = st.text_input('Nombre', value=p.get('nombre', search))
        barcode = st.text_input('Código de barras (texto; conserva ceros iniciales)', value=scanned or p.get('codigo_de_barras') or '')
        kind = st.text_input('Tipo de producto', value=p.get('tipo','General'))
        price = st.number_input('Precio de venta CLP', min_value=0., value=float(p.get('precio_venta',0)))
        minimum = st.number_input('Umbral de bajo stock', min_value=0., value=float(p.get('stock_minimo',5)))
        if st.form_submit_button('Guardar producto'):
            if not name.strip() or not kind.strip():
                st.warning('Completa nombre y tipo.')
            else:
                mutate('producto', dict(id=p.get('id',''), version=p.get('version',0), nombre=name,
                       codigo_de_barras=barcode, tipo=kind, precio_venta=price, stock_minimo=minimum), 'producto')
    st.subheader('Ajustar stock físico')
    p = product_choice(data, key='adjustprod')
    if p:
        with st.form('adjust'):
            value = st.number_input('Stock contado', min_value=0., value=float(p['stock']), step=1.)
            reason = st.text_input('Motivo obligatorio')
            if st.form_submit_button('Registrar ajuste'):
                mutate('ajuste', dict(producto_id=p['id'], version=p['version'], stock=value, motivo=reason), 'ajuste')
        st.caption('El ajuste conserva el costo promedio. Para el stock inicial con costo, registra una factura de apertura.')


def document_entry():
    available = ['factura'] if actor['rol']=='bodeguero' else ['boleta','manual'] if actor['rol']=='vendedor' else ['factura','boleta','manual']
    kind = st.selectbox('Tipo de ingreso', available)
    st.caption('Guardar crea un pendiente. Autorizar en Documentos aplica el stock una sola vez.')
    number = st.text_input('Folio de factura/boleta (para manual: referencia única)')
    date = st.date_input('Fecha del documento', value=dt.datetime.now(ZoneInfo('America/Santiago')).date())
    provider_id = None
    if kind == 'factura':
        providers = rows('proveedor')
        if not providers:
            st.warning('El administrador debe agregar un proveedor.')
            return
        mapping = {p['id']: p for p in providers}
        provider_id = st.selectbox('Proveedor', list(mapping), format_func=lambda x: f"{mapping[x]['nombre']} · {mapping[x]['rut']}")
    uploaded = st.file_uploader('Factura o boleta PDF/PNG/JPEG', type=['pdf','png','jpg','jpeg']) if kind!='manual' else None
    scanned = scan('sale')
    term = st.text_input('Buscar producto por nombre o código', value=scanned)
    all_products = products()
    filtered = [p for p in all_products if term.casefold() in p['nombre'].casefold() or term in (p['codigo_de_barras'] or '')]
    if term and not filtered:
        st.warning('No existe una coincidencia exacta en la búsqueda. Revisa estas sugerencias o solicita crear el producto.')
        for score, p in candidates(term, all_products):
            if score>=.5:
                st.write(f"{p['nombre']} ({score:.0%})")
    p = product_choice(filtered, key='lineproduct')
    cart_key = 'cart:' + kind
    cart = st.session_state.setdefault(cart_key, [])
    if p:
        with st.form('line'):
            quantity = st.number_input('Cantidad', min_value=.001, value=1., step=1., format='%.3f')
            cost = st.number_input('Costo unitario de compra CLP', min_value=0., value=float(p['valor_unitario']), disabled=kind!='factura')
            if st.form_submit_button('Agregar producto al detalle'):
                if kind=='factura' and not p['codigo_de_barras']:
                    st.warning('Completa el código de barras en Productos.')
                elif any(x['producto_id']==p['id'] for x in cart):
                    st.warning('Producto ya agregado. Vacía el detalle para corregir cantidades.')
                else:
                    cart.append(dict(producto_id=p['id'], nombre=p['nombre'], cantidad=quantity,
                                     costo_unitario=cost, precio_venta=p['precio_venta']))
    st.dataframe(pd.DataFrame(cart), hide_index=True)
    if st.button('Vaciar detalle'):
        st.session_state[cart_key] = []
        st.rerun()
    if st.button('Guardar pendiente', type='primary'):
        if not number.strip() or not cart or (kind!='manual' and uploaded is None):
            st.warning('Falta folio, detalle o archivo.')
            return
        payload = dict(tipo=kind, numero=number.strip(), fecha=date.isoformat(), proveedor_id=provider_id, detalle=cart)
        if uploaded:
            payload.update(github().upload(uploaded, kind))
        result = mutate('documento', payload, 'doc:'+kind)
        st.info(f"Documento {result['id']}. Revísalo y autorízalo en Documentos. Vacía el detalle antes de otra venta.")


def documents():
    docs = rows('documentos')
    allowed = ['factura'] if actor['rol']=='bodeguero' else ['boleta','manual'] if actor['rol']=='vendedor' else ['factura','boleta','manual']
    docs = [d for d in docs if d['tipo'] in allowed]
    st.dataframe(pd.DataFrame(docs), hide_index=True)
    if not docs:
        return
    mapping = {d['id']: d for d in docs}
    key = st.selectbox('Revisar documento', list(mapping), format_func=lambda x:
        f"{mapping[x]['tipo']} {mapping[x]['numero']} · {mapping[x]['fecha']} · {mapping[x]['estado']}")
    d = mapping[key]
    detail = db().table('documento_detalle').select('*,productos(nombre,codigo_de_barras)').eq('documento_id', key).execute().data
    st.dataframe(pd.json_normalize(detail), hide_index=True)
    if d['archivo_path'] and st.button('Preparar descarga'):
        content = github().download(d['archivo_path'],d['archivo_sha'])
        st.download_button('Descargar archivo', content, file_name=d['archivo_path'].split('/')[-1])
    confirmed = st.checkbox('Revisé productos, cantidades y costos del documento')
    if d['estado']=='pendiente' and st.button('Autorizar y aplicar stock', disabled=not confirmed):
        mutate('aprobar', dict(id=key), 'approve:'+key)
        st.rerun()


def providers():
    st.subheader('Proveedores')
    st.dataframe(pd.DataFrame(rows('proveedor')), hide_index=True)
    if actor['rol']!='administrador':
        return
    with st.form('provider'):
        rut = st.text_input('RUT (formato único, ejemplo 76123456-7)')
        name = st.text_input('Nombre proveedor')
        email = st.text_input('Email proveedor')
        phone = st.text_input('Teléfono')
        if st.form_submit_button('Agregar proveedor'):
            if rut.strip() and name.strip():
                mutate('proveedor', dict(rut=rut.strip().upper(), nombre=name.strip(), email=email, numero=phone), 'provider')
            else:
                st.warning('RUT y nombre obligatorios.')


def users():
    data = rows('usuarios')
    st.dataframe(pd.DataFrame(data), hide_index=True)
    mapping = {p['id']: p for p in data}
    chosen = st.selectbox('Usuario', ['nuevo']+list(mapping), format_func=lambda x:'Nuevo usuario' if x=='nuevo' else mapping[x]['usuario'])
    p = mapping.get(chosen,{})
    with st.form('user'):
        name = st.text_input('Nombre de usuario', value=p.get('usuario',''))
        email = st.text_input('Correo Google autorizado', value=p.get('email',''))
        roles = ['administrador','bodeguero','vendedor']
        role = st.selectbox('Rol', roles, index=roles.index(p.get('rol','vendedor')))
        active = st.checkbox('Activo', value=p.get('activo',True))
        if st.form_submit_button('Guardar usuario'):
            if name.strip() and '@' in email:
                mutate('usuario',dict(id=p.get('id',''),usuario=name,email=email,rol=role,activo=active),'user')
            else:
                st.warning('Completa nombre y correo válido.')


def history():
    data = rows('historial')
    approved = {v['historial_id'] for v in rows('validaciones')}
    people = {u['id']:u['usuario'] for u in rows('usuarios')}
    for h in data:
        h['usuario'] = people.get(h['usuario_id'], h['usuario_id'])
        h['validado'] = h['id'] in approved
    pending = st.checkbox('Sólo sin validar')
    filtered = [h for h in data if not pending or not h['validado']]
    st.dataframe(pd.json_normalize(filtered), hide_index=True)
    choices = [h['id'] for h in filtered if h['tipo']!='validacion' and not h['validado']]
    if choices:
        selected = st.selectbox('Movimiento a validar', choices)
        if st.button('Validar movimiento'):
            mutate('validar',dict(id=selected),'validate:'+str(selected))
            st.rerun()
    st.caption('Validar deja constancia de revisión administrativa. El stock ya se aplicó al autorizar el documento.')


# Marco de navegación permanece visible también cuando falla una página.
try:
    found = db().table('usuarios').select('*').eq('email',st.user.email.lower()).eq('activo',True).execute().data
    if not found:
        st.error('Tu cuenta no está habilitada. Contacta al administrador.')
        if st.button('Cerrar sesión'):
            st.logout()
        st.stop()
    actor = found[0]
    role = actor['rol']
    st.sidebar.write(f"{actor['usuario']} · {role}")
    if st.sidebar.button('Cerrar sesión'):
        st.session_state.clear()
        st.logout()
    pages = {'Inicio':lambda: st.info('Selecciona una sección en el menú.'), 'Bajo stock':lambda: inventory(True)}
    if role in ('administrador','bodeguero'):
        pages.update({'Inventario':inventory,'Productos y ajustes':catalog,'Proveedores':providers})
    pages.update({'Registrar documento o venta':document_entry,'Documentos':documents})
    if role=='administrador':
        pages.update({'Usuarios':users,'Historial y validaciones':history})
    st.session_state.setdefault('page','Inicio')
    st.session_state.setdefault('previous','Inicio')
    if st.session_state['page'] not in pages:
        st.session_state['page']='Inicio'
    if st.sidebar.button('← Volver a la página anterior'):
        old = st.session_state['page']
        st.session_state['page'] = st.session_state['previous'] if st.session_state['previous'] in pages else 'Inicio'
        st.session_state['previous'] = old
    def changed():
        st.session_state['previous'] = st.session_state['page']
        st.session_state['page'] = st.session_state['menu']
    # Sin recrear la clave se conserva la selección entre reruns y botón Volver.
    st.session_state['menu'] = st.session_state['page']
    st.sidebar.selectbox('Sección', list(pages), key='menu', on_change=changed)
    if st.sidebar.button('Recargar datos'):
        st.rerun()
    pages[st.session_state['page']]()
except Exception:
    reference = uuid4().hex[:10]
    logging.exception('Error inventario referencia=%s',reference)
    st.error(f'No se pudo completar la operación. Referencia: {reference}. Puedes reintentar o volver desde el menú.')
    st.caption('Un documento pendiente no cambia existencias. Las autorizaciones fallidas revierten toda su transacción.')
