"""Lectura local de DTE XML, PDF con texto/tablas y OCR de imágenes. Sin API externa."""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from io import BytesIO
import re
import unicodedata
from defusedxml import ElementTree


@dataclass
class Invoice:
    number: str = ''
    date: str = ''
    provider_rut: str = ''
    provider_name: str = ''
    lines: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def norm(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(value).lower())
                   if not unicodedata.combining(c))


def rut_key(value):
    return re.sub(r'[^0-9K]','',str(value).upper())


def money(value, xml=False):
    text=str(value or '').strip().replace('$','').replace(' ','')
    if not xml:
        if ',' in text:
            text=text.replace('.','').replace(',','.')
        elif '.' in text and all(len(x)==3 for x in text.split('.')[1:]):
            text=text.replace('.','')
    try:
        n=Decimal(text)
    except InvalidOperation as exc:
        raise ValueError('Número no reconocido en el documento') from exc
    if not n.is_finite() or n<0:
        raise ValueError('Número fuera de rango')
    return n


def _text(node, tag, default=''):
    match=node.find('.//{*}'+tag)
    return match.text.strip() if match is not None and match.text else default


def read_xml(data):
    root=ElementTree.fromstring(data)
    if root.tag.split('}')[-1] not in ('DTE','EnvioDTE','EnvioBOLETA','Documento'):
        raise ValueError('El XML no es un DTE chileno compatible')
    docs=[root] if root.tag.split('}')[-1]=='Documento' else root.findall('.//{*}Documento')
    if len(docs)!=1:
        raise ValueError('Sube un XML con exactamente un documento, no un envío con varios DTE')
    doc=docs[0]
    if _text(doc,'TipoDTE') not in ('33','34'):
        raise ValueError('Sólo se admiten facturas DTE 33 o 34 para entradas de inventario')
    result=Invoice(number=_text(doc,'Folio'),date=_text(doc,'FchEmis'),
                   provider_rut=_text(doc,'RUTEmisor'),provider_name=_text(doc,'RznSoc'))
    for row in doc.findall('./{*}Detalle'):
        qty=money(_text(row,'QtyItem','1'),xml=True)
        if qty<=0:
            raise ValueError('Cantidad no positiva en un detalle XML')
        amount=_text(row,'MontoItem')
        cost=money(amount,xml=True)/qty if amount else money(_text(row,'PrcItem'),xml=True)
        barcode=''
        for code in row.findall('./{*}CdgItem'):
            if _text(code,'TpoCodigo').upper() in ('EAN','EAN13','EAN-13','GTIN','UPC'):
                barcode=_text(code,'VlrCodigo')
        name=_text(row,'NmbItem')
        if not name:
            raise ValueError('Una línea del XML no tiene nombre')
        result.lines.append(dict(nombre=name,cantidad=float(qty),costo_unitario=float(cost),codigo_de_barras=barcode))
    if _text(doc,'MntBruto')=='1':
        result.warnings.append('El XML declara montos brutos. Verifica la misma base de costo que usas en el inventario.')
    if not result.lines:
        raise ValueError('El XML no contiene líneas de productos')
    return result


def metadata(text):
    result=Invoice()
    normalized=norm(text)
    number=re.search(r'(?:folio|n[°ºo.]\s*[:.]?)\s*([0-9]+)',normalized)
    if number: result.number=number.group(1)
    date=re.search(r'(?:fecha(?:\s+de)?(?:\s+emision)?\s*[:.]?\s*)(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{4})',normalized)
    if date:
        value=date.group(1)
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',value): result.date=value
        else:
            day,month,year=re.split('[/-]',value)
            result.date=f'{year}-{int(month):02}-{int(day):02}'
    rut=re.search(r'\b\d{1,2}[.]?\d{3}[.]?\d{3}\s*-\s*[0-9kK]\b',text)
    if rut: result.provider_rut=rut.group(0)
    return result



def table_lines(table):
    """Extrae productos de tablas con encabezados reconocibles."""
    header = None
    output = []

    for raw in table:
        cells = [
            str(x or '').replace('\n', ' ').strip()
            for x in raw
        ]
        labels = [norm(x).strip() for x in cells]

        if header is None:
            indexes = {}

            for i, label in enumerate(labels):
                if (
                    'descripcion' in label
                    or label in ('producto', 'detalle', 'articulo')
                ):
                    indexes['name'] = i

                elif 'cantidad' in label or label in (
                    'cant', 'cant.', 'qty'
                ):
                    indexes['qty'] = i

                elif label in ('subtotal', 'importe', 'monto', 'total'):
                    indexes['amount'] = i

                elif (
                    'unitario' in label
                    or 'precio' in label
                    or 'costo' in label
                    or 'valor unit' in label
                ):
                    indexes['cost'] = i

                elif 'barras' in label or label in (
                    'ean', 'ean13', 'gtin'
                ):
                    indexes['barcode'] = i

            if (
                {'name', 'qty'} <= indexes.keys()
                and ('cost' in indexes or 'amount' in indexes)
            ):
                header = indexes

            continue

        try:
            name = cells[header['name']]

            if not name or norm(name).startswith((
                'subtotal', 'total', 'iva',
                'neto', 'descuento'
            )):
                continue

            qty = money(cells[header['qty']])
            if qty <= 0:
                continue

            # Priorizar el precio unitario explícito.
            if 'cost' in header and cells[header['cost']]:
                cost = money(cells[header['cost']])
            elif 'amount' in header:
                cost = money(cells[header['amount']]) / qty
            else:
                continue

            barcode = (
                cells[header['barcode']]
                if 'barcode' in header else ''
            )

            output.append({
                'nombre': name,
                'cantidad': float(qty),
                'costo_unitario': float(cost),
                'codigo_de_barras': barcode
            })

        except (ValueError, IndexError, KeyError):
            continue

    return output



def text_lines(text):
    """Respaldo para filas: cantidad descripción unitario total, o descripción cantidad unitario total."""
    output=[]; active=False
    number=r'[0-9]+(?:[.,][0-9]+)*'
    patterns=[re.compile(rf'^({number})\s+(.+?)\s+\$?({number})\s+\$?({number})$'),
              re.compile(rf'^(.+?)\s+({number})\s+\$?({number})\s+\$?({number})$')]
    for raw in text.splitlines():
        line=raw.strip(); normalized=norm(line)
        if ('cant' in normalized and ('descripcion' in normalized or 'producto' in normalized)
                and ('precio' in normalized or 'unit' in normalized or 'total' in normalized)):
            active=True; continue
        if not active: continue
        if re.match(r'^(?:total|subtotal|neto|iva|monto|observaciones)\b',normalized): break
        for i,pattern in enumerate(patterns):
            match=pattern.fullmatch(line)
            if not match: continue
            a,b,unit,total=match.groups()
            qty,name=(a,b) if i==0 else (b,a)
            try:
                q,u,t=money(qty),money(unit),money(total)
                if q<=0 or abs(q*u-t)>max(Decimal('2'),t*Decimal('.005')): continue
                output.append(dict(nombre=name,cantidad=float(q),costo_unitario=float(t/q),codigo_de_barras=''))
                break
            except ValueError: pass
    return output


def _ocr(image):
    import pytesseract
    try:
        return pytesseract.image_to_string(image,lang='spa',timeout=45)
    except (pytesseract.TesseractNotFoundError,pytesseract.TesseractError,RuntimeError) as exc:
        raise ValueError('No fue posible ejecutar OCR. Verifica packages.txt y la instalación de tesseract-ocr-spa en Streamlit.') from exc


def read_invoice(data, filename):
    if len(data)>15*1024*1024:
        raise ValueError('El archivo supera 15 MB')
    if filename.lower().endswith('.xml'):
        return read_xml(data)
    texts = []
    lines = []
    diagnostico = []
    if data.startswith(b'%PDF-'):
        import pdfplumber
        with pdfplumber.open(BytesIO(data)) as pdf:
            if len(pdf.pages)>10:
                raise ValueError('Máximo 10 páginas por factura')
            seen_pages = set()
            
            for page in pdf.pages:
                text = page.extract_text() or ''
            
                if len(text.strip()) < 30:
                    if page.width * page.height * (150/72)**2 > 30_000_000:
                        raise ValueError(
                            'Una página del PDF es demasiado grande para OCR'
                        )
                    text = _ocr(page.to_image(resolution=150).original)
            
                # Detectar páginas con texto idéntico
                page_signature = ' '.join(norm(text).split())
            
                if page_signature and page_signature in seen_pages:
                    continue
            
                if page_signature:
                    seen_pages.add(page_signature)
                texts.append(text)

                found = []
                tables = page.extract_tables()
                
                # Diagnóstico estructural sin mostrar contenido
                for numero_tabla, tabla in enumerate(tables, start=1):
                    cantidad_filas = len(tabla)
                    columnas_por_fila = [
                        len(fila) if fila else 0
                        for fila in tabla
                    ]
                
                    print(
                        f"[ESTRUCTURA PDF] "
                        f"Pagina {page.page_number} | "
                        f"Tabla {numero_tabla} | "
                        f"Filas: {cantidad_filas} | "
                        f"Columnas por fila: {columnas_por_fila}"
                    )

                print(
                    f"[DIAGNOSTICO PDF] "
                    f"Pagina: {len(texts)} | "
                    f"Caracteres extraidos: {len(text)} | "
                    f"Tablas detectadas: {len(tables)}"
                )
                
                for table in tables:
                    found.extend(table_lines(table))
                
                print(
                    f"[DIAGNOSTICO PDF] "
                    f"Productos desde tablas: {len(found)}"
                )
                
                fallback = text_lines(text) if not found else []
                
                print(
                    f"[DIAGNOSTICO PDF] "
                    f"Productos desde texto: {len(fallback)}"
                )
                
                lines.extend(found or fallback)
                diagnostico.append({
                    "pagina": len(texts),
                    "caracteres": len(text),
                    "tablas": len(tables),
                    "productos_tabla": len(found),
                    "productos_texto": len(fallback)
                })
                # Guardar el texto de la página
#                texts.append(text)
            
                # Extraer los productos
 #               found = []
  #              for table in page.extract_tables():
   #                 found.extend(table_lines(table))
            
    #            lines.extend(found or text_lines(text))
                

            
    else:
        from PIL import Image,ImageOps
        with Image.open(BytesIO(data)) as original:
            if original.width*original.height>30_000_000:
                raise ValueError('La imagen supera 30 megapíxeles')
            image=ImageOps.exif_transpose(original).convert('RGB')
            texts.append(_ocr(image))
        lines=text_lines(texts[0])
    result=metadata('\n'.join(texts));result.lines=lines
    result.warnings.append('Lectura automática: confirma emisor, folio, fecha, cantidades y costos. El OCR puede omitir o confundir líneas.')
    if not lines:
        resumen = "; ".join(
            f"Página {d['pagina']}: "
            f"{d['caracteres']} caracteres, "
            f"{d['tablas']} tablas, "
            f"{d['productos_tabla']} productos desde tablas, "
            f"{d['productos_texto']} productos desde texto"
            for d in diagnostico
        )
        
        # Solo para revisión local: no imprime contenido
        for numero_tabla, tabla in enumerate(tables, start=1):
            if tabla:
                st.write(
                    f"Página {page.page_number} - "
                    f"Tabla {numero_tabla}"
                )
                st.write(
                    f"Cantidad de filas: {len(tabla)}"
                )
                st.write(
                    f"Columnas de la primera fila: "
                    f"{len(tabla[0]) if tabla[0] else 0}"
                )

        raise ValueError(
            "No se identificó una tabla de productos compatible. "
            "Diagnóstico: " + (resumen or "sin datos")
        )
#    if not lines:
 #       raise ValueError('No se identificó una tabla de productos compatible. Prueba el XML DTE o un PDF más claro. Necesitamos una factura de ejemplo para adaptar este formato; no se inventarán productos.')
  #  return result
