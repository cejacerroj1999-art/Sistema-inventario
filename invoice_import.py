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
    result = Invoice()
    normalized = norm(text)

    # Número o folio de factura
    number = re.search(
        r'(?:folio|factura(?:\s+electronica)?'
        r'(?:\s+n[°ºo.]?)?|n[°ºo.]?)'
        r'\s*[:#.-]?\s*(\d+)',
        normalized
    )

    if number:
        result.number = number.group(1)

    # Fecha de emisión
    date = re.search(
        r'(?:fecha(?:\s+de)?(?:\s+emision)?)'
        r'\s*[:.]?\s*'
        r'(\d{4}-\d{2}-\d{2}|'
        r'\d{1,2}[/-]\d{1,2}[/-]\d{4})',
        normalized
    )

    if date:
        value = date.group(1)

        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            result.date = value
        else:
            day, month, year = re.split('[/-]', value)
            result.date = (
                f'{year}-{int(month):02}-{int(day):02}'
            )

    # RUT del proveedor
    rut = re.search(
        r'\b\d{1,2}[.]?\d{3}[.]?\d{3}\s*-\s*[0-9kK]\b',
        text
    )

    if rut:
        result.provider_rut = rut.group(0)

    return result

def table_lines(table):
    """Extraer productos de tablas con encabezados reconocibles."""
    header = None
    output = []

    for raw in table:
        if not raw:
            continue

        cells = [
            str(x or '').replace('\n', ' ').strip()
            for x in raw
        ]
        labels = [norm(x) for x in cells]

        if header is None:
            indexes = {}

            for i, label in enumerate(labels):
                if (
                    'descripcion' in label
                    or 'producto' in label
                    or label == 'detalle'
                ):
                    indexes['name'] = i

                elif (
                    'cantidad' in label
                    or label in ('cant', 'cant.', 'qty')
                ):
                    indexes['qty'] = i

                elif (
                    'subtotal' in label
                    or label in ('total', 'monto', 'importe')
                ):
                    indexes['amount'] = i

                elif (
                    'unitario' in label
                    or 'precio' in label
                    or 'costo' in label
                    or 'valor unit' in label
                ):
                    indexes['cost'] = i

                elif (
                    'barras' in label
                    or label in ('ean', 'gtin')
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
            if not name:
                continue

            if norm(name).startswith((
                'subtotal', 'total', 'iva',
                'neto', 'descuento'
            )):
                continue

            qty = money(cells[header['qty']])

            if qty <= 0:
                continue

            if 'cost' in header and cells[header['cost']]:
                cost = money(cells[header['cost']])
            elif 'amount' in header:
                cost = money(cells[header['amount']]) / qty
            else:
                continue

            barcode = (
                cells[header['barcode']]
                if 'barcode' in header
                else ''
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



def pdf_product_lines(page):
    """Lee filas con columnas por coordenadas; soporta precio, unitario e impuestos."""
    words = page.extract_words(x_tolerance=2, y_tolerance=3)
    rows = []
    for w in sorted(words, key=lambda x: (x['top'], x['x0'])):
        cy = (w['top'] + w['bottom']) / 2
        match = next((r for r in rows if abs(r['y'] - cy) <= 3), None)
        if match is None:
            match = {'y': cy, 'words': []}
            rows.append(match)
        match['words'].append(w)
    for r in rows:
        r['words'].sort(key=lambda w: w['x0'])

    header = None
    header_index = None
    for i, row in enumerate(rows):
        found = {}
        for w in row['words']:
            t = norm(w['text']).strip(' .:%')
            if t in ('codigo', 'cod'):
                found['code'] = w['x0']
            elif 'descripcion' in t or t == 'producto':
                found['name'] = w['x0']
            elif t in ('cantidad', 'cant', 'qty'):
                found['qty'] = w['x0']
            elif t in ('precio', 'unitario', 'costo'):
                found['cost'] = w['x0']
            elif t in ('und', 'unidad', 'u/m'):
                found['unit'] = w['x0']
            elif t.startswith(('impto', 'impuesto')):
                found['tax'] = w['x0']
            elif t.startswith(('desc', 'descuento')) and t != 'descripcion':
                found['discount'] = w['x0']
            elif t in ('valor', 'subtotal', 'sub-total', 'importe'):
                found['amount'] = w['x0']
        if {'name', 'qty', 'cost'} <= found.keys():
            header, header_index = found, i
            break
    if header is None:
        return []

    qty_start = header['qty'] - 17
    following_qty = [x for k,x in header.items() if x > header['qty'] and k != 'amount']
    qty_end = min(following_qty) - 8 if following_qty else header['cost'] - 10
    cost_start = header['cost'] - 16
    following_cost = [x for k,x in header.items() if x > header['cost']]
    cost_end = min(following_cost) - 7 if following_cost else page.width
    amount_start = header.get('amount', page.width + 1) - 18
    output = []
    pending = ''
    for row in rows[header_index+1:]:
        ws = row['words']
        line = norm(' '.join(w['text'] for w in ws))
        if re.match(r'^(?:documento referencia|timbre electronico|subtotal|total neto|monto neto|observaciones|descto\.|neto afecto)\b', line):
            break
        qty_words = [w['text'] for w in ws if qty_start <= w['x0'] < qty_end]
        cost_words = [w['text'] for w in ws if cost_start <= w['x0'] < cost_end]
        desc_words = [w['text'] for w in ws if w['x0'] < qty_start]
        amount_words = [w['text'] for w in ws if w['x0'] >= amount_start]
        if not qty_words or not cost_words:
            if desc_words and not any(w['text'].lower() in ('codigo','descripcion') for w in ws):
                pending += ' ' + ' '.join(desc_words)
            continue
        try:
            qty = money(''.join(qty_words))
            cost = money(cost_words[0])  # El primer valor es el precio; otros pueden ser impuestos/descuentos
            if qty <= 0 or qty != qty.to_integral_value() or cost <= 0:
                continue
            if amount_words:
                try:
                    amount = money(''.join(amount_words))
                    if abs(cost * qty - amount) > Decimal('1.01'):
                        cost = amount / qty
                except ValueError:
                    pass
        except ValueError:
            continue
        if not desc_words:
            continue
        code = desc_words[0] if 'code' in header else ''
        name = ' '.join(desc_words[1:] if code else desc_words).strip()
        if pending.strip():
            name = (pending.strip() + ' ' + name).strip()
            pending = ''
        if not name:
            continue
        output.append(dict(nombre=name, cantidad=int(qty), costo_unitario=float(cost),
                           codigo_de_barras=''))
    return output


def _ocr(image):
    import pytesseract
    try:
        return pytesseract.image_to_string(image,lang='spa',timeout=45)
    except (pytesseract.TesseractNotFoundError,pytesseract.TesseractError,RuntimeError) as exc:
        raise ValueError('No fue posible ejecutar OCR. Verifica packages.txt y la instalación de tesseract-ocr-spa en Streamlit.') from exc



def read_invoice(data, filename):
    """Lee PDF (todas las páginas), XML o imagen. Revisa duplicados de copias."""
    if len(data) > 15 * 1024 * 1024:
        raise ValueError('El archivo supera 15 MB')
    if filename.lower().endswith('.xml'):
        return read_xml(data)
    texts, lines, warnings = [], [], []
    if data.startswith(b'%PDF-'):
        import pdfplumber
        with pdfplumber.open(BytesIO(data)) as pdf:
            if not pdf.pages:
                raise ValueError('El PDF no contiene páginas')
            signatures = set()
            for n, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ''
                if len(text.strip()) < 30:
                    pixels = page.width * page.height * (150 / 72) ** 2
                    if pixels > 30_000_000:
                        raise ValueError('La página es demasiado grande para OCR')
                    text = _ocr(page.to_image(resolution=150).original)
                texts.append(text)
                candidates = pdf_product_lines(page)
                if not candidates:
                    for table in page.extract_tables():
                        candidates.extend(table_lines(table))
                if not candidates:
                    candidates = text_lines(text)
                # No deduplicar productos dentro de la misma página: podrían ser líneas legítimas.
                signature = tuple((norm(x['nombre']), str(x['cantidad']),
                                   round(float(x['costo_unitario']), 2)) for x in candidates)
                if signature and signature in signatures:
                    warnings.append(f'Página {n}: copia de detalle ya procesado; no se duplicaron unidades.')
                    continue
                if signature:
                    signatures.add(signature)
                lines.extend(candidates)
                if not candidates:
                    warnings.append(f'Página {n}: no se detectaron productos; revisar manualmente.')
    else:
        from PIL import Image, ImageOps
        with Image.open(BytesIO(data)) as original:
            if original.width * original.height > 30_000_000:
                raise ValueError('La imagen supera 30 megapíxeles')
            image = ImageOps.exif_transpose(original).convert('RGB')
            text = _ocr(image)
            texts.append(text)
            lines = text_lines(text)
    result = metadata('\n'.join(texts))
    result.lines = lines
    result.warnings.extend(warnings)
    if not lines:
        result.warnings.append('No se reconocieron productos; ingrésalos manualmente antes de guardar.')
    result.warnings.append('Revisa cantidades y costos con la factura antes de registrar.')
    return result
