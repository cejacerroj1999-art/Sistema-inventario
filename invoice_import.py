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
    """
    Extrae productos según las columnas del PDF.
    Ignora impuestos y descuentos para identificar
    cantidad y precio unitario.
    """
    words = page.extract_words(
        x_tolerance=2,
        y_tolerance=3,
        keep_blank_chars=False
    )

    if not words:
        return []

    # Agrupar palabras por líneas visuales
    rows = []

    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        cy = (word["top"] + word["bottom"]) / 2

        row = next(
            (r for r in rows if abs(r["y"] - cy) <= 4),
            None
        )

        if row is None:
            row = {"y": cy, "words": []}
            rows.append(row)

        row["words"].append(word)

    rows.sort(key=lambda r: r["y"])

    for row in rows:
        row["words"].sort(key=lambda w: w["x0"])

    # Identificar encabezados
    header_index = None
    columns = {}

    for i, row in enumerate(rows):
        found = {}

        for word in row["words"]:
            label = norm(word["text"]).strip()

            if label in ("codigo", "cod", "cod."):
                found["code"] = word["x0"]

            elif "descripcion" in label:
                found["name"] = word["x0"]

            elif "cantidad" in label or label == "cant":
                found["qty"] = word["x0"]

            elif label in ("precio", "unitario"):
                found["cost"] = word["x0"]

            elif "impto" in label or "impuesto" in label:
                found["tax"] = word["x0"]

            elif "desc" in label:
                found["discount"] = word["x0"]

            elif label in ("valor", "subtotal", "total"):
                found["amount"] = word["x0"]

        if all(k in found for k in ("name", "qty", "cost")):
            columns = found
            header_index = i
            break

    if header_index is None:
        return []

    # Construir límites entre columnas
    ordered = sorted(columns.items(), key=lambda x: x[1])

    boundaries = [
        (ordered[i][1] + ordered[i + 1][1]) / 2
        for i in range(len(ordered) - 1)
    ]

    def get_column(word):
        center_x = (word["x0"] + word["x1"]) / 2

        for i, boundary in enumerate(boundaries):
            if center_x < boundary:
                return ordered[i][0]

        return ordered[-1][0]

    output = []

    for row in rows[header_index + 1:]:
        row_text = " ".join(w["text"] for w in row["words"])
        normalized = norm(row_text).strip()

        if normalized.startswith((
            "subtotal", "total neto",
            "monto total", "observaciones"
        )):
            break

        cells = {key: [] for key in columns}

        for word in row["words"]:
            key = get_column(word)
            cells[key].append(word["text"])

        values = {
            key: " ".join(parts).strip()
            for key, parts in cells.items()
        }

        name = values.get("name", "")
        qty_text = values.get("qty", "")
        cost_text = values.get("cost", "")
        code = values.get("code", "")

        # No usar tax ni discount como cantidad/precio
        if not name or not qty_text or not cost_text:
            if name or qty_text or cost_text:
                import logging
                logging.warning(
                    "Fila incompleta: nombre=%s, cantidad=%s, precio=%s",
                    bool(name),
                    bool(qty_text),
                    bool(cost_text)
                )
            continue

        try:
            qty = money(qty_text)
            cost = money(cost_text)

            if qty <= 0 or cost <= 0:
                continue

            full_name = (
                f"{code} {name}".strip()
                if code else name
            )

            output.append({
                "nombre": full_name,
                "cantidad": float(qty),
                "costo_unitario": float(cost),
                "codigo_de_barras": ""
            })

        except ValueError:
            import logging
            logging.warning(
                "Producto descartado por conversión numérica"
            )
            continue

    return output


#def pdf_product_lines(page):
    """
    Extrae productos desde la primera página del PDF,
    utilizando las posiciones reales de las columnas.
    """

 #   words = page.extract_words(
  #      x_tolerance=2,
   #     y_tolerance=3,
    #    keep_blank_chars=False
#    )

 #   if not words:
  #      return []

    # Agrupar palabras por línea visual
   # rows = []

    #for word in sorted(
     #   words,
      #  key=lambda w: (
       #     (w['top'] + w['bottom']) / 2,
        #    w['x0']
#        )
 #   ):
  #      center_y = (word['top'] + word['bottom']) / 2

   #     if (
    #        rows
     #       and abs(rows[-1]['y'] - center_y) <= 4
      #  ):
       #     rows[-1]['words'].append(word)
        #else:
         #   rows.append({
          #      'y': center_y,
           #     'words': [word]
            #})

#    for row in rows:
 #       row['words'].sort(key=lambda w: w['x0'])
#
    # Localizar encabezados de la tabla
 #   header_index = None
  #  columns = {}

   # for i, row in enumerate(rows):
    #    found = {}
#
 #       for word in row['words']:
  #          label = norm(word['text']).strip()
#
 #           if label in ('codigo', 'cod.'):
  #              found['code'] = word['x0']
#
 #           elif 'descripcion' in label:
  #              found['name'] = word['x0']
#
 #           elif 'cantidad' in label or label == 'cant':
  #              found['qty'] = word['x0']

#            elif (
 #               'precio' in label
  #              or 'unitario' in label
  #          ):
   #             found['cost'] = word['x0']
#
 #           elif (
  #              label in ('valor', 'subtotal', 'total')
   #         ):
    #            found['amount'] = word['x0']
#
 #       if all(
  #          key in found
   #         for key in ('name', 'qty', 'cost')
    #    ):
     #       header_index = i
      #      columns = found
       #     break
#
 #   if header_index is None:
  #      return []
#
 #   # Ordenar columnas por su posición horizontal
  #  ordered = sorted(
   #     columns.items(),
    #    key=lambda item: item[1]
    #)

    # Límites entre columnas
#    boundaries = []
#
 #   for i in range(len(ordered) - 1):
  #      midpoint = (
   #         ordered[i][1] + ordered[i + 1][1]
    #    ) / 2
     #   boundaries.append(midpoint)
#
 #   def column_for_word(word):
  #      x = (word['x0'] + word['x1']) / 2
#
 #       for i, boundary in enumerate(boundaries):
  #          if x < boundary:
   #             return ordered[i][0]
#
 #       return ordered[-1][0]
#
 #   output = []
#
 #   for row in rows[header_index + 1:]:

#        row_text = ' '.join(
 #           w['text'] for w in row['words']
  #      )
#
 #       normalized = norm(row_text).strip()
#
 #       if normalized.startswith((
  #          'subtotal',
   #         'total neto',
    #        'monto total',
     #       'observaciones'
      #  )):
       #     break
#
 #       cells = {
  #          key: []
   #         for key in columns
    #    }
#
 #       for word in row['words']:
  #          key = column_for_word(word)
   #         cells[key].append(word['text'])
#
 #       values = {
  #          key: ' '.join(parts).strip()
   #         for key, parts in cells.items()
    #    }
#
 #       name = values.get('name', '')
  #      qty_text = values.get('qty', '')
   #     cost_text = values.get('cost', '')
    #    code = values.get('code', '')

#        if not name or not qty_text or not cost_text:
 #           continue
#
 #       try:
  #          qty = money(qty_text)
   #         cost = money(cost_text)
#
 #           if qty <= 0:
  #              continue
#
 #           # Código del proveedor, separado de
  #          # la descripción cuando corresponda.
   #         full_name = (
    #            f'{code} {name}'.strip()
     #           if code else name
      #      )
#
 #           output.append({
  #              'nombre': full_name,
   #             'cantidad': float(qty),
    #            'costo_unitario': float(cost),
     #           'codigo_de_barras': ''
      #      })
#
 #       except ValueError:
  #          continue
#
 #   return output
#
def _ocr(image):
    import pytesseract
    try:
        return pytesseract.image_to_string(image,lang='spa',timeout=45)
    except (pytesseract.TesseractNotFoundError,pytesseract.TesseractError,RuntimeError) as exc:
        raise ValueError('No fue posible ejecutar OCR. Verifica packages.txt y la instalación de tesseract-ocr-spa en Streamlit.') from exc



def read_invoice(data, filename):
    """
    Lee la primera página de una factura PDF.
    Conserva soporte para XML DTE e imágenes.
    """

    if len(data) > 15 * 1024 * 1024:
        raise ValueError('El archivo supera 15 MB')

    # XML DTE
    if filename.lower().endswith('.xml'):
        return read_xml(data)

    texts = []
    lines = []

    # PDF
    if data.startswith(b'%PDF-'):
        import pdfplumber

        with pdfplumber.open(BytesIO(data)) as pdf:

            if not pdf.pages:
                raise ValueError(
                    'El PDF no contiene páginas'
                )

            # Procesar exclusivamente la primera página
            page = pdf.pages[0]

            text = page.extract_text() or ''

            # OCR si no hay texto suficiente
            if len(text.strip()) < 30:

                pixels = (
                    page.width * page.height
                    * (150 / 72) ** 2
                )

                if pixels > 30_000_000:
                    raise ValueError(
                        'La página es demasiado grande para OCR'
                    )

                text = _ocr(
                    page.to_image(resolution=150).original
                )

            texts.append(text)
            
            # Obtener candidatos de los tres métodos
#            positional = pdf_product_lines(page)
            
 #           from_tables = []
  #          for table in page.extract_tables():
   #             from_tables.extend(table_lines(table))
            
    #        from_text = text_lines(text)
            
            # Combinar sin duplicar productos idénticos
     #       lines = []
      #      seen = set()
            
       #     for item in positional + from_tables + from_text:
        #        key = (
         #           norm(item.get('nombre', '')).strip(),
          #          round(float(item.get('cantidad', 0)), 4)
           #     )
            
            #    if key not in seen:
             #       seen.add(key)
              #      lines.append(item)

            # Primero intentar extraer productos por posiciones
            lines = pdf_product_lines(page)
            
            # Si falla, intentar las tablas tradicionales
            if not lines:
                for table in page.extract_tables():
                    lines.extend(table_lines(table))
            
            # Último intento: lectura del texto
            if not lines:
                lines = text_lines(text)
            # Intentar obtener productos desde tablas
#            found = []

 #           for table in page.extract_tables():
  #              found.extend(table_lines(table))

            # Usar extracción de texto como alternativa
   #         lines = found or text_lines(text)

    # IMÁGENES
    else:
        from PIL import Image, ImageOps

        with Image.open(BytesIO(data)) as original:

            if original.width * original.height > 30_000_000:
                raise ValueError(
                    'La imagen supera 30 megapíxeles'
                )

            image = ImageOps.exif_transpose(
                original
            ).convert('RGB')

            text = _ocr(image)
            texts.append(text)

            lines = text_lines(text)

    # Extraer metadatos
    result = metadata('\n'.join(texts))

    result.lines = lines

    result.warnings.append(
        'Se procesó únicamente la primera página '
        'del PDF. Verifica los datos antes de guardar.'
    )

    # Permitir completar manualmente los productos
    if not lines:
        result.warnings.append(
            'No se reconocieron automáticamente los productos. '
            'Debes ingresarlos manualmente antes de guardar.'
        )

    return result
