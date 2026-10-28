"""Ingreso de facturas: manual o archivo; productos resueltos dentro del mismo flujo."""
import datetime as dt
import hashlib
from uuid import uuid4
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from domain import candidates, normalize
from invoice_import import read_invoice, rut_key
from invoice_domain import consolidate


def _line_editor(catalog, cart, scan, scope, source=None, source_index=None):
    if source:
        st.write(f"Producto leído: **{source['nombre']}**")
        term=source['nombre']
    else:
        term=st.text_input('Nombre o código del producto que ingresa',key=scope+':search')
    wanted_code=(source or {}).get('codigo_de_barras') or term
    exact=[p for p in catalog if normalize(p['nombre'])==normalize(term)
           or wanted_code and wanted_code==p.get('codigo_de_barras')]
    scores=candidates(term,catalog) if term else []
    suggested=[p for score,p in scores if score>=.5]
    ordered=exact+[p for p in suggested if p not in exact]+[p for p in catalog if p not in exact and p not in suggested]
    options=['elegir','nuevo']+[p['id'] for p in ordered]
    mapping={p['id']:p for p in catalog}
    default=options.index(exact[0]['id']) if len(exact)==1 else (1 if term and not suggested and not exact else 0)
    labels={'elegir':'Selecciona un producto o crea uno nuevo','nuevo':'Crear producto nuevo'}
    selected=st.selectbox('¿A qué producto corresponde?',options,index=default,
        format_func=lambda x:labels[x] if x in labels else f"{mapping[x]['nombre']} · {mapping[x]['codigo_de_barras'] or 'SIN CÓDIGO'}",
        key=scope+':match:'+hashlib.sha256(term.encode()).hexdigest()[:12])
    if selected=='elegir':
        if suggested: st.info('Hay nombres similares. Selecciona el existente sólo si es el mismo producto y presentación.')
        return
    scope+=':'+selected+':'+hashlib.sha256(term.encode()).hexdigest()[:12]
    new=selected=='nuevo';p={} if new else mapping[selected]
    if not new and not p['codigo_de_barras']:
        st.warning('Este producto existe, pero no tiene código de barras. Complétalo aquí.')
    scanned=scan(scope+':barcode') if new or not p.get('codigo_de_barras') else ''
    with st.form(scope+':form'):
        name=st.text_input('Nombre del producto',value=term if new else p['nombre'],disabled=not new)
        code=st.text_input('Código de barras',value=scanned or p.get('codigo_de_barras') or (source or {}).get('codigo_de_barras',''),disabled=bool(p.get('codigo_de_barras')))
        if new:
            kind=st.text_input('Tipo de producto',value='General')
            price=st.number_input('Precio de venta CLP',min_value=0.,value=0.)
            minimum=st.number_input('Umbral de bajo stock',min_value=0.,value=5.)
        else:
            kind=p['tipo'];price=p['precio_venta'];minimum=p['stock_minimo']
            st.caption(f"Tipo: {kind} · Precio de venta: ${float(price):,.0f} · Stock actual: {p['stock']}")
        quantity=st.number_input('Cantidad que ingresa',min_value=.001,value=float((source or {}).get('cantidad',1)),step=1.,format='%.3f')
        cost=st.number_input('Costo unitario de compra CLP',min_value=0.,value=float((source or {}).get('costo_unitario',p.get('valor_unitario',0))))
        submit=st.form_submit_button('Confirmar producto en la factura')
    if submit:
        if not name.strip() or not code.strip() or not kind.strip():
            st.warning('Completa nombre, código de barras y tipo de producto.')
            return
        if new and any(normalize(x['nombre'])==normalize(name) for x in catalog):
            st.warning('Ese nombre ya existe. Selecciona el producto existente en lugar de crear otro.')
            return
        if any(x.get('codigo_de_barras')==code.strip() and x['id']!=p.get('id') for x in catalog):
            st.warning('Ese código de barras pertenece a otro producto. Selecciona ese producto o corrige el código.')
            return
        prior=next((x for x in cart if x['nuevo'] and normalize(x['nombre'])==normalize(name) and x['codigo_de_barras']==code.strip()),None)
        product_id=(prior['producto_id'] if prior else st.session_state.setdefault(scope+':new_id:'+hashlib.sha256((normalize(name)+'|'+code.strip()).encode()).hexdigest(),str(uuid4()))) if new else selected
        line=dict(producto_id=product_id,nuevo=new,nombre=name.strip(),codigo_de_barras=code.strip(),tipo=kind,
                  precio_venta=float(price),stock_minimo=float(minimum),cantidad=quantity,costo_unitario=cost,source_index=source_index)
        if source_index is not None:
            cart[:]=[x for x in cart if x['source_index']!=source_index]
        cart.append(line)
        st.success('Producto agregado al borrador. Se guardará con la factura y el stock aumentará al autorizarla.')


def invoice_entry(actor, rows, products, github, mutate, scan):
    mode_label=st.radio('Cómo ingresar la factura',['Ingreso manual','Subir archivo'],horizontal=True,key='invoice:mode')
    mode='manual' if mode_label=='Ingreso manual' else 'archivo'
    revision_key='invoice:revision:'+mode
    revision=st.session_state.setdefault(revision_key,0)
    if st.button('Comenzar otra factura',key='invoice:new:'+mode):
        st.session_state[revision_key]=revision+1
        st.rerun()
    imported=None;uploaded=None;scope='invoice:'+mode+':'+str(revision)
    if mode=='archivo':
        uploaded=st.file_uploader('Sube la factura: XML DTE, PDF, PNG o JPEG',type=['xml','pdf','png','jpg','jpeg'],key='invoice:file:'+str(revision))
        if uploaded is None:
            st.info('Sube un archivo para leer los datos. Después revisarás la factura y vincularás sus productos.')
            return
        digest=hashlib.sha256(uploaded.getvalue()).hexdigest()
        scope+=':'+digest
        if st.button('Leer datos del archivo',key=scope+':read'):
            try:
                with st.spinner('Leyendo la factura…'):
                    st.session_state[scope+':imported']=read_invoice(uploaded.getvalue(),uploaded.name)
            except Exception as exc:
                # Sólo ValueError del lector contiene mensajes controlados. No mostrar XML, OCR o rutas internos.
                st.error(str(exc) if isinstance(exc,ValueError) else 'No se pudo leer el archivo. Prueba un XML DTE o un PDF/imagen más claro.')
        imported=st.session_state.get(scope+':imported')
        if imported is None: return
        for warning in imported.warnings: st.warning(warning)
        st.caption('Los campos siguientes se completaron con la lectura. Corrige los que no se hayan reconocido; no vuelvas a transcribir todo el detalle.')
    catalog=products()
    providers=rows('proveedor')
    if not providers:
        st.warning('El administrador debe agregar el proveedor antes de guardar la factura.')
        return
    by_provider={p['id']:p for p in providers}
    default_provider=next((p['id'] for p in providers if imported and rut_key(p['rut'])==rut_key(imported.provider_rut)),None)
    options=['']+list(by_provider)
    if imported and imported.provider_rut and default_provider is None:
        st.warning(f'El emisor leído ({imported.provider_rut}) no coincide con un proveedor registrado. Revisa y selecciona el proveedor correcto.')
    number=st.text_input('Folio de la factura',value=imported.number if imported else '',key=scope+':number')
    try: date_default=dt.date.fromisoformat(imported.date) if imported and imported.date else dt.datetime.now(ZoneInfo('America/Santiago')).date()
    except ValueError: date_default=dt.datetime.now(ZoneInfo('America/Santiago')).date()
    if imported and not imported.date: st.warning('No se reconoció la fecha. Confírmala antes de guardar.')
    date=st.date_input('Fecha de la factura',value=date_default,key=scope+':date')
    provider_id=st.selectbox('Proveedor',options,index=options.index(default_provider) if default_provider else 0,
        format_func=lambda x:'Seleccionar proveedor' if not x else f"{by_provider[x]['nombre']} · {by_provider[x]['rut']}",key=scope+':provider')
    cart=st.session_state.setdefault('cart:'+scope,[])
    st.subheader('Productos de la factura')
    if imported:
        st.dataframe(pd.DataFrame(imported.lines),hide_index=True)
        done={x['source_index'] for x in cart}
        index=st.selectbox('Línea a revisar',list(range(len(imported.lines))),
            format_func=lambda i:f"{'✓ ' if i in done else ''}{i+1}. {imported.lines[i]['nombre']}",key=scope+':line')
        _line_editor(catalog,cart,scan,scope+':resolve:'+str(index),imported.lines[index],index)
    else:
        _line_editor(catalog,cart,scan,scope+':manual_line')
    st.subheader('Detalle confirmado')
    st.dataframe(pd.DataFrame(cart),hide_index=True)
    if cart:
        remove=st.selectbox('Línea para quitar del borrador',list(range(len(cart))),format_func=lambda i:f"{i+1}. {cart[i]['nombre']}",key=scope+':remove')
        if st.button('Quitar línea seleccionada',key=scope+':remove_button'):
            cart.pop(remove);st.rerun()
    checked=st.checkbox('Revisé el proveedor, folio, fecha y todas las líneas de esta factura',key=scope+':confirmed')
    if st.button('Guardar factura pendiente',type='primary',key=scope+':save'):
        if not number.strip() or not provider_id or not checked:
            st.warning('Completa folio y proveedor y confirma la revisión.');return
        if imported and {x['source_index'] for x in cart}!=set(range(len(imported.lines))):
            st.warning('Debes confirmar cada línea leída antes de guardar.');return
        try: detail=consolidate(cart)
        except ValueError as exc: st.warning(str(exc));return
        payload=dict(tipo='factura',modo_ingreso=mode,numero=number.strip(),fecha=date.isoformat(),proveedor_id=provider_id,detalle=detail)
        if uploaded: payload.update(github().upload(uploaded,'factura'))
        result=mutate('factura',payload,scope)
        st.success(f"Factura guardada: {result['id']}. Autorízala en Documentos para incorporar el stock.")
